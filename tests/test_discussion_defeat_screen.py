"""The leader screen must name its leader, including the one whose civ we just ended.

Live t190, taking Cusco -- the Inca's last city -- opened the defeat screen on top of the capture
popup. `discussion()` read "Pachacuti the Pious of The Inca" off it and reported `player: -1`: the
title-to-id sweep only considered players `IsAlive()`, and by then he was not one. An id that never
resolves is the same failure as the captured-city row that resolved to the wrong city -- the caller
cannot act on the screen it is looking at.
"""
import unittest

from harness.game import Game


class _FakeClient:
    def __init__(self, lines):
        self.lines = lines
        self.asked = []

    def exec(self, state, lua, timeout=None, check=True):
        self.asked.append(state)
        return self.lines


def _game(lines, visible="DiscussionDialog"):
    g = Game.__new__(Game)
    g.c = _FakeClient(lines)
    g.states = lambda: {7: "DiscussionDialog"}
    g._visible_in_state = lambda state, lua, states=None: state == visible
    g._pid = lambda pid=None: 0
    g.relationship = lambda other, pid=None: {"ok": True, "other": other}
    return g


class DefeatScreenTest(unittest.TestCase):
    def test_a_living_leader_resolves_and_carries_a_relationship(self):
        g = _game(["3\tPachacuti the Pious of The Inca\tNeutral\tfalse\ttrue",
                   "You have been a worthy rival.",
                   "1\tfalse\tVery well."])

        d = g.discussion()

        self.assertEqual(d["player"], 3)
        self.assertNotIn("player_eliminated", d)
        self.assertEqual(d["relationship"]["other"], 3)
        self.assertEqual(d["buttons"], [{"id": 1, "disabled": False, "text": "Very well."}])

    def test_a_defeated_leader_is_still_named(self):
        g = _game(["2\tPachacuti the Pious of The Inca\tDestroyed\tfalse\tfalse",
                   "You have destroyed my civilization."])

        d = g.discussion()

        self.assertEqual(d["player"], 2, "the defeat screen's leader must resolve to an id")
        self.assertTrue(d["player_eliminated"])
        self.assertEqual(d["leader"], "Pachacuti the Pious of The Inca")

    def test_a_defeated_leader_is_not_asked_for_a_relationship(self):
        """There is no relationship left to read with a civ that no longer exists."""
        g = _game(["2\tPachacuti the Pious of The Inca\tDestroyed\tfalse\tfalse", ""])

        d = g.discussion()

        self.assertNotIn("relationship", d)

    def test_an_unmatched_title_still_reports_minus_one(self):
        g = _game(["-1\tSomeone We Have Never Met\tNeutral\tfalse\tfalse", ""])

        d = g.discussion()

        self.assertEqual(d["player"], -1)
        self.assertNotIn("player_eliminated", d, "-1 is not an elimination, it is a failed match")

    def test_an_older_runtime_without_the_alive_column_still_parses(self):
        g = _game(["3\tPachacuti the Pious of The Inca\tNeutral\ttrue", "Hello."])

        d = g.discussion()

        self.assertEqual(d["player"], 3)
        self.assertTrue(d["can_go_back"])
        self.assertNotIn("player_eliminated", d)


if __name__ == "__main__":
    unittest.main()
