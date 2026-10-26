"""Stage 0 of milestone 2.0.0 "The tool surface" (GitLab #44): the measurements reproduce the baseline.

harness/surface/ holds the vocabulary of the nine tools, the retirement map from each old name, the
measurements and the affordance audit; scripts/tool_survey.py writes them to docs/measurements/tool_survey.md.
The baseline here is the one counted by hand on #44 at 7c30a8f: 145 tools, 35 zero-argument reads, the eight
shapes. A tool added or removed fails these on purpose: a new feature is a new view or action, never a new tool.
"""
import re
import unittest
from pathlib import Path
from unittest import mock

from harness import mcp_server as m
from harness.surface import audit, retirement, survey, vocabulary

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {"reference": (2, 0), "turn": (11, 4), "batch": (2, 0), "notebook": (11, 0), "units": (24, 7),
            "cities": (22, 3), "policies": (21, 7), "diplomacy": (36, 10), "trade": (13, 4), "front_end": (3, 0),
            "total": (145, 35)}
SHAPE_COUNTS = (16, 13, 6, 4, 9, 6, 14, 10)
REPLACES = {"turn": 8, "inspect": 46, "order": 48, "question": 10, "answer": 13, "notebook": 11, "batch": 2,
            "session": 5, "reference": 2}   # #59 counts known_world under inspect; #50's table sends it to turn


class RetirementMapTests(unittest.TestCase):
    def setUp(self):
        self.names = [t.name for t in survey.tools()]

    def test_every_name_maps_to_exactly_one_row_and_none_is_left_over(self):
        self.assertEqual(retirement.check(self.names), {"unmapped": [], "stale": [], "off_vocabulary": []})
        self.assertEqual(len(retirement.RETIRED), 145)

    def test_rows_speak_the_vocabulary_and_render_the_renamed_string(self):
        self.assertEqual(retirement.RETIRED["map_window"].render(), 'inspect(what="map", view="window")')
        self.assertEqual(retirement.RETIRED["set_production"].render(), 'order(to="city", action="produce")')
        self.assertEqual(retirement.RETIRED["choose_goody_hut"].render(), "answer(choice=<goody>)")
        self.assertEqual(retirement.RETIRED["city_state_action"].key, ("order:city_state", "<action>"))
        self.assertEqual(retirement.RETIRED["league_status"].key, ("inspect:league", vocabulary.DEFAULT))
        self.assertEqual(retirement.RETIRED["move_unit"].renames, {"unit_id": "id"})

    def test_a_row_off_the_vocabulary_is_reported(self):
        bad = retirement.Row("order", {"to": "unit", "action": "teleport"})
        with mock.patch.dict(retirement.RETIRED, {"teleport_unit": bad}):
            self.assertEqual(retirement.vocabulary_errors(), ["teleport_unit: order(to='unit') has no action 'teleport'"])

    def test_the_vocabulary_is_the_nine_tools_of_59(self):
        self.assertEqual(vocabulary.TOOLS, ("turn", "inspect", "order", "question", "answer", "notebook", "batch",
                                            "session", "reference"))
        self.assertEqual(len(vocabulary.VIEWS["screen"]), 11)
        self.assertEqual(len(vocabulary.ACTIONS["city"]), 11)


class SurveyTests(unittest.TestCase):
    def test_the_catalog_by_module_is_the_baseline_of_44(self):
        got = {r["module"]: (r["tools"], r["zero_argument_reads"]) for r in survey.by_module()}
        self.assertEqual(got, BASELINE)
        self.assertEqual([r["module"] for r in survey.by_module()][:-1], list(BASELINE)[:-1])  # listing order

    def test_the_eight_shapes_are_the_baseline_and_disjoint(self):
        rows = survey.shapes()
        self.assertEqual(tuple(r["count"] for r in rows[:-1]), SHAPE_COUNTS)
        names = [n for r in rows for n in r["names"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sorted(names), sorted(t.name for t in survey.tools()))
        self.assertEqual(rows[-1]["count"], 145 - sum(SHAPE_COUNTS))

    def test_what_each_new_tool_replaces(self):
        self.assertEqual({r["tool"]: r["replaces"] for r in survey.by_new_tool()}, REPLACES)
        self.assertEqual(sum(REPLACES.values()), 145)

    def test_the_listing_sizes_are_the_wire_shape(self):
        full, compact = survey.listing_sizes()
        self.assertEqual((full["listing"], full["tools"]), ("full", 145))
        self.assertEqual((compact["listing"], compact["tools"]), ("compact", len(m.CORE_TOOLS)))
        self.assertGreater(full["bytes"], compact["bytes"] * 2)
        self.assertEqual(full["approx_tokens"], full["bytes"] // survey.BYTES_PER_TOKEN)
        self.assertLess(survey.longest_description()["chars"], survey.DESCRIPTION_CLIP)
        self.assertIn('"inputSchema"', survey.wire_listing({"turn_status"}))

    def test_every_mapping_row_names_a_catalog_tool(self):
        rows = survey.mapping()
        self.assertEqual(len(rows), 145)
        self.assertFalse([r["old"] for r in rows if r["key"] == "(unmapped)"])


class AuditTests(unittest.TestCase):
    """The seam as it stands before stage 1: the briefing's todo rows name tools in prose and the gate's rows are
    bare names. Stage 1 (#45-#47) turns these assertions around."""

    @classmethod
    def setUpClass(cls):
        cls.names = {t.name for t in survey.tools()}
        cls.sites = audit.scan(cls.names)

    def test_the_briefing_todo_rows_are_the_prose_seam(self):
        todo = [s for s in self.sites if s.file == "harness/briefing.py" and s.key == "tool"]
        self.assertGreaterEqual(len(todo), 9)
        self.assertEqual({s.kind for s in todo}, {"prose"})
        self.assertIn("available_production + set_production", [s.text for s in todo])

    def test_the_gate_rows_are_bare_names(self):
        gate = [s for s in self.sites if s.file == "harness/gate.py" and s.key in ("clear_with", "read_first")]
        self.assertGreaterEqual(len(gate), 30)
        self.assertEqual({s.kind for s in gate} - {"dynamic"}, {"name"})

    def test_a_row_literal_counts_once_as_rows(self):
        rows = [s for s in self.sites if s.kind == "rows"]
        self.assertTrue(any(s.file == "harness/orders.py" for s in rows))
        lines = {(s.file, s.line) for s in rows}
        self.assertFalse([s for s in self.sites if s.kind == "name" and (s.file, s.line) in lines])

    def test_classify(self):
        import ast
        names = {"move_unit", "units"}
        def node(src):
            return ast.parse(src, mode="eval").body
        self.assertEqual(audit.classify("tool", node("'move_unit'"), names), ("name", "move_unit"))
        self.assertEqual(audit.classify("also", node("['move_unit', 'units']"), names)[0], "names")
        self.assertEqual(audit.classify("hint", node("'look at units first'"), names)[0], "prose")
        self.assertEqual(audit.classify("hint", node("'still not my turn'"), names)[0], "text")
        self.assertEqual(audit.classify("hint", node("f'{n} units left'"), names)[0], "prose")
        self.assertEqual(audit.classify("tool", node("name"), names)[0], "dynamic")

    def test_the_affordance_replies_are_listed_and_hand_back_names_today(self):
        rows = audit.replies(survey.tools())
        listed = {r["reply"] for r in rows}
        for name in ("briefing", "todo_actions", "available_production", "available_research", "goody_hut_options",
                     "discussion", "incoming_deal", "city_state_actions", "trade_catalog", "available_spy_cities"):
            self.assertIn(name, listed)
        carries = {r["reply"]: r["carries"] for r in rows}
        # todo_actions already hands back one row: the "read the rest" continuation when its list is cut
        self.assertEqual({n for n, c in carries.items() if c == "rows"}, {"todo_actions"})


class MeasurementDocTests(unittest.TestCase):
    """docs/measurements/tool_survey.md is the script's output; its catalog table must be the live one."""

    def test_the_checked_in_tables_match(self):
        text = (ROOT / "docs" / "measurements" / "tool_survey.md").read_text()
        self.assertIn("scripts/tool_survey.py --write", text)
        self.assertIn("The mapping check passed", text)
        for r in survey.by_module():
            self.assertRegex(text, rf"\| {r['module']} \| {r['tools']} \| {r['zero_argument_reads']} \|")
        for r in survey.shapes():
            self.assertIn(f"| {r['shape']} | {r['count']} |", text)
        self.assertEqual(len(re.findall(r"^\| `\w+` \| \w+ \| ", text, re.M)), 145)


if __name__ == "__main__":
    unittest.main()
