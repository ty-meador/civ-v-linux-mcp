"""plain_text and bare icons: a [ICON_*] with no word after it keeps its name, spaced from its neighbours.

Live t175 (Mongolia, overview.public_opinion.tooltip): the hover draws one ideology icon per unit of pressure
straight after the civ's name -- "Portugal[ICON_IDEOLOGY_ORDER][ICON_IDEOLOGY_ORDER], Russia" -- and read
"PortugalIdeology OrderIdeology Order, Russia".
"""
import unittest

from harness.game_parts.support import plain_text


class BareIconSpacing(unittest.TestCase):
    def test_icons_glued_to_a_name_are_spaced(self):
        s = "For Order:\nPortugal[ICON_IDEOLOGY_ORDER][ICON_IDEOLOGY_ORDER], Russia"
        self.assertEqual(plain_text(s), "For Order:\nPortugal Ideology Order Ideology Order, Russia")

    def test_an_icon_before_its_word_still_vanishes(self):
        self.assertEqual(plain_text("+3 [ICON_GOLD] Gold"), "+3 Gold")
        self.assertEqual(plain_text("[ICON_CULTURE] Culture: 5"), "Culture: 5")

    def test_a_bare_icon_at_the_end_keeps_its_name(self):
        self.assertEqual(plain_text("Yields 2 [ICON_PRODUCTION]"), "Yields 2 Production")
        self.assertEqual(plain_text("2 [ICON_GOLD]."), "2 Gold.")

    def test_no_markup_leaves_the_text_alone(self):
        self.assertEqual(plain_text("a, b (c)"), "a, b (c)")


if __name__ == "__main__":
    unittest.main()
