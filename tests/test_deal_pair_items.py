"""propose_deal places a symmetric item's pair once: tradelogic.lua's pocket handler for a research agreement,
defensive pact or trade agreement puts a row from EACH side on the table in one press (live t196: Venice's
research agreement with England, asked as one item per side, held two pairs and cost 468 gold instead of 234)."""
import unittest
from unittest import mock

from harness.game import Game


def game(table_items):
    g = Game.__new__(Game)
    g.seat = 0
    g._trade_state = "DiploTrade"
    g.c = mock.Mock()
    g.c.exec = mock.Mock()
    g.incoming_deal = lambda pid=None: {"ok": True, "items": list(table_items)}
    return g


class DealPairItemTests(unittest.TestCase):
    def test_a_research_agreement_asked_from_both_sides_presses_the_pocket_once(self):
        with mock.patch("harness.game_parts.deals.time.sleep"):
            g = game([{"type": "RESEARCH_AGREEMENT", "from_us": True}, {"type": "RESEARCH_AGREEMENT", "from_us": False}])
            r = g._add_deal_items(2, [{"type": "RESEARCH_AGREEMENT", "from_us": True},
                                      {"type": "RESEARCH_AGREEMENT", "from_us": False}], 0)
        codes = [c.args[1] for c in g.c.exec.call_args_list]
        self.assertEqual(codes, ["PocketResearchAgreementHandler(1)"])
        self.assertNotEqual(r.get("ok"), False, r)

    def test_a_defensive_pact_once_but_open_borders_per_side(self):
        with mock.patch("harness.game_parts.deals.time.sleep"):
            g = game([{"type": "DEFENSIVE_PACT", "from_us": True}, {"type": "DEFENSIVE_PACT", "from_us": False},
                      {"type": "OPEN_BORDERS", "from_us": True}, {"type": "OPEN_BORDERS", "from_us": False}])
            r = g._add_deal_items(2, [{"type": "DEFENSIVE_PACT", "from_us": False}, {"type": "OPEN_BORDERS", "from_us": True},
                                      {"type": "DEFENSIVE_PACT", "from_us": True}, {"type": "OPEN_BORDERS", "from_us": False}], 0)
        codes = [c.args[1] for c in g.c.exec.call_args_list]
        self.assertEqual(codes, ["PocketDefensivePactHandler(0)", "PocketOpenBordersHandler(1)", "PocketOpenBordersHandler(0)"])
        self.assertNotEqual(r.get("ok"), False, r)


if __name__ == "__main__":
    unittest.main()
