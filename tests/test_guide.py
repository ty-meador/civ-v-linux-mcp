"""how_to_play: the playbook and the long reply references by topic (harness/guide.py), and the size caps that
make it necessary -- a client shows a tool description or the server instructions only up to about 2000
characters (Claude Code, measured 2026-09-27), so every docstring and the instructions stay under that and
point at how_to_play for the rest."""
import ast
import re
import unittest
from pathlib import Path
from unittest import mock

from harness import guide
from harness import mcp_server as m

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "harness" / "mcp_server.py").read_text()
CLIENT_CUT = 2000


def tool_docstrings() -> dict[str, str]:
    out = {}
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.FunctionDef) and any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in node.decorator_list):
            out[node.name] = ast.get_docstring(node) or ""
    return out


class SizeCapTests(unittest.TestCase):
    def test_every_tool_description_fits_the_client_cut(self):
        over = {name: len(doc) for name, doc in tool_docstrings().items() if len(doc) >= CLIENT_CUT}
        self.assertEqual(over, {}, "move the tail into docs/TOOL_REPLIES.md and point at how_to_play")

    def test_every_tool_has_a_description(self):
        self.assertEqual([n for n, d in tool_docstrings().items() if not d], [])

    def test_instructions_fit_the_client_cut_and_point_at_the_guide(self):
        instr = m.mcp.instructions if hasattr(m.mcp, "instructions") else m.mcp._mcp_server.instructions
        self.assertLess(len(instr), CLIENT_CUT)
        self.assertIn("how_to_play", instr)
        self.assertIn("finish_turn", instr[:600])
        self.assertIn("gate", instr[:600])


class GuideTests(unittest.TestCase):
    def test_index_lists_every_topic_and_starts_with_the_introduction(self):
        text = guide.how_to_play("")
        for topic in guide.PLAYBOOK_TOPICS:
            self.assertIn(f"`{topic}`", text)
        for tool in guide.reply_topics():
            self.assertIn(f"`{tool}`", text)
        self.assertIn("Read `gate` first", text)
        self.assertNotIn("## The turn loop", text)

    def test_playbook_topics_are_whole_sections(self):
        for topic, (heading, _) in guide.PLAYBOOK_TOPICS.items():
            body = guide.how_to_play(topic)
            self.assertIsNotNone(body, topic)
            if heading:
                self.assertTrue(body.startswith(heading), topic)
            self.assertGreater(len(body), 200, topic)
        # a ## topic keeps its ### parts; the ### part is its own topic too
        self.assertIn("### Letting quiet turns pass", guide.how_to_play("turn_loop"))
        self.assertTrue(guide.how_to_play("quiet_turns").startswith("### Letting quiet turns pass"))
        self.assertNotIn("## Many orders", guide.how_to_play("turn_loop"))

    def test_all_is_the_whole_playbook(self):
        self.assertEqual(guide.how_to_play("all"), (ROOT / "docs" / "PLAYBOOK.md").read_text())

    def test_reply_references_exist_for_the_shortened_tools(self):
        docs = tool_docstrings()
        for tool in guide.reply_topics():
            self.assertIn(tool, docs, "a reply reference for something that is not a tool")
            self.assertIn(f'how_to_play("{tool}")', docs[tool], f"{tool}'s description must point at its reference")
            body = guide.how_to_play(tool)
            self.assertTrue(body.startswith(f"## {tool}"))
            self.assertGreater(len(body), len(docs[tool]) // 2)

    def test_unknown_topic_lists_the_topics(self):
        text = guide.how_to_play("nope")
        self.assertIn("unknown topic", text)
        self.assertIn("turn_loop", text)
        self.assertIn("finish_turn", text)

    def test_the_tool_needs_no_game(self):
        with mock.patch.object(m, "game", side_effect=AssertionError("no game may be touched")):
            self.assertIn("Read `gate` first", m.how_to_play())
            self.assertTrue(m.how_to_play("blockers").startswith("## What `blocking_name` means"))

    def test_the_tool_is_a_read_for_the_ledger(self):
        from harness import call_ledger
        self.assertEqual(call_ledger.kind("how_to_play"), "read")

    def test_missing_docs_say_so(self):
        with mock.patch.object(guide, "PLAYBOOK", Path("/nonexistent/PLAYBOOK.md")):
            self.assertIn("not installed", guide.how_to_play("all"))
            self.assertIn("is docs/ installed", guide.how_to_play("turn_loop"))


class TopicsMatchThePlaybookTests(unittest.TestCase):
    def test_every_second_level_heading_is_a_topic(self):
        text = (ROOT / "docs" / "PLAYBOOK.md").read_text()
        headings = re.findall(r"^(##+ .+)$", text, re.M)
        prefixes = [h for h, _ in guide.PLAYBOOK_TOPICS.values() if h]
        for h in headings:
            self.assertTrue(any(h.startswith(p) for p in prefixes), f"playbook heading without a topic: {h}")
