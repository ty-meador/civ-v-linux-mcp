"""What the fresh Grok session at Assyria t238 met (docs/measurements/2026-10-27-assyria-t238-grok-session.md):
notes from a later timeline marked, inspect refusals that say where the ids come from, playbook aliases, and
#49's per-client schema variants after the Grok and Claude Code measurements."""
import os
import tempfile
import unittest
from unittest import mock

from harness import guide
from harness.notes import Notebook
from harness.surface import dispatch as D
from harness.surface import listing as L


class LaterTimelineNotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        self.env.start()
        self.nb = Notebook("pangaea-Assur", seat=0)
        self.nb.remember("t98: Rationalism opened", turn=98)
        self.nb.remember("t247: gifted Ur", turn=247)
        self.nb.remember("t257: the free Great Scientist bulbed", turn=257)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_a_note_from_a_later_turn_is_marked_when_the_turn_on_screen_is_earlier(self):
        out = self.nb.hand_off_section("all", 8, turn=238)
        marked = [n["turn"] for n in out["notes"] if n.get("later_timeline")]
        self.assertEqual(marked, [247, 257])
        self.assertNotIn("later_timeline", out["notes"][0])
        self.assertIn("2 of these notes were written on turns later than turn 238", out["notes_later_timeline"])
        self.assertIn("a save was loaded", out["notes_later_timeline"])

    def test_nothing_is_marked_when_the_notes_are_the_past_or_no_turn_is_given(self):
        self.assertNotIn("notes_later_timeline", Notebook("pangaea-Assur", 0).hand_off_section("all", 8, turn=260))
        out = Notebook("pangaea-Assur", 0).hand_off_section("all", 8)
        self.assertNotIn("notes_later_timeline", out)
        self.assertFalse(any("later_timeline" in n for n in out["notes"]))

    def test_the_mark_is_not_written_into_the_notebook(self):
        self.nb.hand_off_section("all", 8, turn=100)
        self.assertFalse(any("later_timeline" in n for n in self.nb.recall()["notes"]))


class InspectRefusalHintTests(unittest.TestCase):
    def test_a_plural_miss_names_the_object_and_where_its_ids_come_from(self):
        r = D.pick(("inspect:city_states", "default"), {})
        self.assertIsInstance(r, D.Refusal)
        reply = r.reply()
        self.assertEqual(reply["err"], "inspect has no object 'city_states'")
        self.assertIn("inspect(what='city_state', id=<id>, view=<full / summary>)", reply["hint"])
        self.assertIn("`minor: true` rows of inspect(what='civs')", reply["hint"])
        self.assertIn("city_state", reply["choices"])

    def test_an_object_that_takes_an_id_says_so_when_only_the_view_is_wrong(self):
        reply = D.pick(("inspect:city_state", "default"), {}).reply()
        self.assertEqual(reply["err"], "inspect:city_state has no 'default'")
        self.assertEqual(reply["choices"], ["full", "summary"])
        self.assertTrue(reply["hint"].startswith("`id` is needed too; city-state ids"))
        for what, where in (("unit", "units"), ("city", "cities"), ("civ", "civs")):
            self.assertIn(f"inspect(what='{where}')", D.pick((f"inspect:{what}", "nope"), {}).reply()["hint"])

    def test_other_refusals_carry_no_hint(self):
        self.assertNotIn("hint", D.pick(("inspect:league", "nope"), {}).reply())
        self.assertNotIn("hint", D.pick(("inspect:weather", "default"), {}).reply())
        self.assertNotIn("hint", D.pick(("order:units", "move"), {}).reply())


class PlaybookAliasTests(unittest.TestCase):
    def test_city_states_and_deals_are_the_diplomacy_section(self):
        diplomacy = guide.how_to_play("diplomacy")
        for alias in ("city_state", "city_states", "deals", "trade", "league"):
            self.assertEqual(guide.how_to_play(alias), diplomacy, alias)
        self.assertEqual(guide.how_to_play("blocking"), guide.how_to_play("blockers"))
        self.assertIn("`minor: true` rows", diplomacy)
        self.assertIn("`votable` rows", diplomacy)

    def test_an_unknown_topic_is_still_unknown(self):
        self.assertTrue(guide.how_to_play("weather").startswith("unknown topic 'weather'"))


class SchemaVariantPerClientTests(unittest.TestCase):
    def test_the_measured_clients(self):
        self.assertEqual(L.variant_for("claude-code/2.1.311", env={}), L.FLAT)
        self.assertEqual(L.variant_for("codex-mcp-client", env={}), L.FLAT)
        self.assertEqual(L.variant_for("grok-shell-civ5/1.0.70", env={}), L.ONEOF)
        self.assertEqual(L.variant_for("SomethingNew/0.1", env={}), L.ONEOF)
        self.assertEqual(L.variant_for("claude-code", env={L.ENV: "oneof"}), L.ONEOF)


if __name__ == "__main__":
    unittest.main()
