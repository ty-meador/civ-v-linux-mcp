"""The notebook: per-game notes that outlive a session, keyed so two games never share one."""
import json
import os
import tempfile
import unittest
from unittest import mock

from harness.notes import Notebook, notes_dir, safe_key


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_remember_recall_forget_roundtrip(self):
        nb = Notebook("Pocatello-continents", seat=0)
        r = nb.remember("Tradition then Rationalism", turn=12, tag="plan")
        self.assertTrue(r["ok"])
        self.assertEqual(r["note"]["id"], 1)
        nb.remember("Askia denounced me", turn=140, tag="threat")
        got = nb.recall()
        self.assertEqual([n["text"] for n in got["notes"]], ["Tradition then Rationalism", "Askia denounced me"])
        self.assertEqual([n["turn"] for n in got["notes"]], [12, 140])
        self.assertEqual(nb.recall(tag="threat")["count"], 1)
        self.assertTrue(nb.forget(1)["ok"])
        self.assertEqual(nb.recall()["count"], 1)
        bad = nb.forget(99)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["ids"], [2])

    def test_notes_survive_a_new_notebook_object_and_stay_per_game_and_seat(self):
        Notebook("gameA", 0).remember("a0", turn=1)
        Notebook("gameA", 1).remember("a1", turn=1)
        Notebook("gameB", 0).remember("b0", turn=1)
        self.assertEqual([n["text"] for n in Notebook("gameA", 0).recall()["notes"]], ["a0"])
        self.assertEqual([n["text"] for n in Notebook("gameA", 1).recall()["notes"]], ["a1"])
        self.assertEqual([n["text"] for n in Notebook("gameB", 0).recall()["notes"]], ["b0"])
        files = sorted(os.listdir(self.tmp.name))
        self.assertEqual(files, ["gameA-seat0.json", "gameA-seat1.json", "gameB-seat0.json"])

    def test_replace_keeps_one_living_plan(self):
        nb = Notebook("g", 0)
        first = nb.remember("plan v1", turn=1, tag="plan")["note"]["id"]
        r = nb.remember("plan v2", turn=30, replace_id=first)
        self.assertTrue(r["replaced"])
        notes = nb.recall()["notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["text"], notes[0]["turn"], notes[0]["tag"]), ("plan v2", 30, "plan"))
        self.assertFalse(nb.remember("x", turn=1, replace_id=42)["ok"])

    def test_empty_and_oversized_notes_are_refused_and_the_book_is_bounded(self):
        nb = Notebook("g", 0)
        self.assertFalse(nb.remember("   ", turn=1)["ok"])
        self.assertFalse(nb.remember("x" * 5000, turn=1)["ok"])
        for i in range(205):
            nb.remember(f"n{i}", turn=i)
        got = nb.recall(limit=500)
        self.assertEqual(got["count"], 200)
        self.assertEqual(got["notes"][0]["text"], "n5")
        self.assertEqual(nb.latest(3), got["notes"][-3:])

    def test_corrupt_file_is_treated_as_empty(self):
        nb = Notebook("g", 0)
        nb.path.parent.mkdir(parents=True, exist_ok=True)
        nb.path.write_text("{not json")
        self.assertEqual(nb.recall()["count"], 0)
        nb.remember("fresh", turn=3)
        self.assertEqual(json.loads(nb.path.read_text())["notes"][0]["text"], "fresh")

    def test_keys_are_filesystem_safe_and_dir_follows_xdg(self):
        self.assertEqual(safe_key("Assets\\Maps/continents.lua game/1"), "Assets_Maps_continents.lua_game_1")
        with mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": "", "XDG_DATA_HOME": "/x/data"}):
            self.assertEqual(str(notes_dir()), "/x/data/civ5-harness/notes")


if __name__ == "__main__":
    unittest.main()
