"""front_end_screen names the visible front-end state by asking each candidate whether it is hidden; the
start-up splash (LegalScreen) is one of them, so a cold start is not reported as the "?" screen."""
import unittest

from harness.game import Game


class FakeClient:
    def __init__(self, visible):
        self.visible = visible

    def exec(self, sid, code, check=False):
        return ["true" if sid in self.visible else "false"]


def game_with(states, visible):
    g = Game.__new__(Game)
    g.states = lambda: states
    g.c = FakeClient(visible)
    return g


class FrontEndScreenTests(unittest.TestCase):
    def test_the_splash_is_named(self):
        g = game_with({1: "LegalScreen", 2: "MainMenu", 3: "JoiningRoom"}, visible={1})
        self.assertEqual(g.front_end_screen(), "LegalScreen")

    def test_a_visible_main_menu_wins_over_a_hidden_stale_state(self):
        g = game_with({1: "LegalScreen", 2: "MainMenu", 3: "JoiningRoom"}, visible={2})
        self.assertEqual(g.front_end_screen(), "MainMenu")

    def test_nothing_visible_is_a_question_mark(self):
        g = game_with({2: "MainMenu"}, visible=set())
        self.assertEqual(g.front_end_screen(), "?")
