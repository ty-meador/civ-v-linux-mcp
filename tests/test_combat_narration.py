"""turn_digest combat provenance: `Game._narrate_combat` (pure Python; the Lua side fills attacker/defender)."""
import unittest
from types import SimpleNamespace

from harness.game import Game


def narrate(events, route_starts=()):
    return Game._narrate_combat(SimpleNamespace(seat=0, q=lambda code: list(route_starts)), events)


class CombatNarrationTests(unittest.TestCase):
    def test_barbarian_attack_names_both_sides(self):
        ev = {"kind": "combat", "data": {
            "att_player": 63, "att_unit": 122881, "att_dmg": 12, "def_player": 0, "def_unit": 8193, "def_dmg": 38,
            "attacker": {"owner": "Barbarians", "unit": "WARRIOR", "x": 13, "y": 8, "hp": 88},
            "defender": {"owner": "you", "unit": "SCOUT", "x": 12, "y": 8, "hp": 62}}}
        s = narrate([ev])[0]["data"]["summary"]
        self.assertIn("Barbarians WARRIOR (13,8) attacked your SCOUT (12,8)", s)
        self.assertIn("defender -38 hp, 62 left", s)

    def test_unseen_attacker_is_not_described(self):
        ev = {"kind": "combat", "data": {"att_player": 3, "att_dmg": 0, "def_player": 0, "def_unit": 5, "def_dmg": 20,
                                         "attacker": {"owner": "Unknown", "ranged": True},
                                         "defender": {"owner": "you", "unit": "WORKER", "x": 1, "y": 2, "hp": 80}}}
        s = narrate([ev])[0]["data"]["summary"]
        self.assertIn("Unknown unit (not visible) shot your WORKER", s)

    def test_hp_fallback_dropped_when_combat_explains_it(self):
        combat = {"kind": "combat", "data": {"def_unit": 5, "def_dmg": 20, "att_dmg": 0,
                                             "attacker": {"owner": "Barbarians"}, "defender": {"owner": "you", "killed": True}}}
        hurt = {"kind": "unit_lost", "data": {"unit_id": 5, "unit": "WORKER", "x": 1, "y": 2, "hp_before": 100}}
        other = {"kind": "unit_hurt", "data": {"unit_id": 9, "unit": "SCOUT", "x": 4, "y": 4, "hp_before": 100, "hp": 70}}
        out = narrate([combat, hurt, other])
        self.assertEqual([e["kind"] for e in out], ["combat", "unit_hurt"])
        self.assertIn("lost 30 hp", out[1]["data"]["summary"])
        self.assertIn("killed", out[0]["data"]["summary"])

    def test_own_turn_disappearance_is_spent_not_destroyed(self):
        gone = lambda u: {"kind": "unit_destroyed", "data": {"player": 0, "unit": u}}
        out = narrate([gone(1), {"kind": "turn_end", "data": {}}, gone(2), {"kind": "turn_start", "data": {}}, gone(3)])
        self.assertEqual([e["kind"] for e in out], ["unit_spent", "turn_end", "unit_destroyed", "turn_start", "unit_spent"])

    def test_a_batch_without_markers_continues_where_the_last_one_stopped(self):
        """Live England t224: the finish_turn read cut short by a war-declaration screen began after the previous
        batch's turn_end and held the Pikeman's death by Rocket Artillery; with no marker of its own it was read as
        my turn and the row said "gone during your own turn with no combat". The other players' round carries
        over; and a unit with a damage row of its own was in a fight whatever the marker says."""
        g = SimpleNamespace(seat=0, q=lambda code: [])
        gone = lambda u: {"kind": "unit_destroyed", "data": {"player": 0, "unit": u}}
        first = Game._narrate_combat(g, [gone(1), {"kind": "turn_end", "data": {}}])
        self.assertEqual([e["kind"] for e in first], ["unit_spent", "turn_end"])
        second = Game._narrate_combat(g, [gone(2)])
        self.assertEqual(second[0]["kind"], "unit_destroyed", "after a turn_end the next batch is the AI round")
        third = Game._narrate_combat(g, [{"kind": "turn_start", "data": {}}, gone(3)])
        self.assertEqual(third[1]["kind"], "unit_spent")
        hit = {"kind": "damage", "data": {"unit_id": 4, "dmg": 100, "side": {"owner": "you", "unit": "PIKEMAN"}}}
        fourth = Game._narrate_combat(g, [hit, gone(4)])
        self.assertEqual(fourth[1]["kind"], "unit_destroyed", "a damage row of its own: killed, not spent")
        self.assertEqual(Game._narrate_combat(SimpleNamespace(seat=0, q=lambda code: []), [gone(5)])[0]["kind"],
                         "unit_spent", "a fresh game starts inside my turn")

    def test_a_besieged_citys_hostiles_are_listed_once_per_digest(self):
        """Live England t226: six bomber hits and a rocket strike on London each carried the same eighteen-unit
        hostiles list. The first alert per city keeps it; the rest point at that row."""
        ring = [{"unit": "INFANTRY", "x": 59, "y": 40, "owner": "The Ottomans", "hp": 74, "distance": 1}]
        hit = lambda seq, city="London": {"kind": "alert", "seq": seq, "data": {"text": f"Your City of {city} was bombarded",
                                                                                  "city": city, "hostiles": list(ring)}}
        class G(SimpleNamespace):
            _narrate_combat = Game._narrate_combat
        out = Game._refine_events(G(seat=0, q=lambda code: []),
                                  [hit(100), hit(101), {"kind": "alert", "seq": 102, "data": {"text": "plain"}}, hit(103, "York"), hit(104)])
        self.assertEqual(out[0]["data"]["hostiles"], ring)
        self.assertNotIn("hostiles", out[1]["data"])
        self.assertEqual(out[1]["data"]["hostiles_as_in"], 100)
        self.assertNotIn("hostiles_as_in", out[2]["data"])
        self.assertEqual(out[3]["data"]["hostiles"], ring, "another city keeps its own first list")
        self.assertEqual(out[4]["data"]["hostiles_as_in"], 100)

    def test_caravan_leaving_on_a_route_is_not_spent(self):
        out = narrate([{"kind": "unit_destroyed", "data": {"player": 0, "unit": 901136}}],
                      route_starts=[{"unit_id": 901136, "unit": "CARAVAN", "to": "Ur"}])
        self.assertEqual(out[0]["kind"], "trade_route_started")
        self.assertIn("trade route to Ur", out[0]["data"]["summary"])

    def test_a_route_start_explains_a_disappearance_on_its_own_turn_only(self):
        # live t224 (Mongolia): unit ids are recycled -- the Foreign Legion upgraded that turn carried the id of a
        # caravan whose route to Guangzhou had started turns earlier, and the digest called the upgrade a departure.
        gone = {"kind": "unit_destroyed", "turn": 224, "data": {"player": 0, "unit": 720907, "unit_type": "FRENCH_FOREIGNLEGION"}}
        old = [{"unit_id": 720907, "unit": "CARAVAN", "to": "Guangzhou", "turn": 190}]
        self.assertEqual(narrate([dict(gone, data=dict(gone["data"]))], route_starts=old)[0]["kind"], "unit_spent")
        now = [{"unit_id": 720907, "unit": "CARAVAN", "to": "Guangzhou", "turn": 224}]
        out = narrate([dict(gone, data=dict(gone["data"]))], route_starts=old + now)
        self.assertEqual(out[0]["kind"], "trade_route_started")
        self.assertIn("Guangzhou", out[0]["data"]["summary"])

    def test_lost_and_spent_for_one_unit_keep_one_row(self):
        out = narrate([{"kind": "turn_start", "data": {}},
                       {"kind": "unit_lost", "data": {"unit_id": 843783, "unit": "CARAVAN", "x": 23, "y": 22, "hp_before": 100}},
                       {"kind": "unit_destroyed", "data": {"player": 0, "unit": 843783}}])
        self.assertEqual([e["kind"] for e in out], ["turn_start", "unit_lost"])
        self.assertIn("trade route ended", out[1]["data"]["summary"])


if __name__ == "__main__":
    unittest.main()


def test_civ_eliminated_gets_summary():
    from harness.game import Game
    g = Game.__new__(Game)
    ev = {"kind": "civ_eliminated", "turn": 444, "seq": 1, "audience": 0,
          "data": {"player": 2, "civ": "America", "leader": "Washington"}}
    g.q = lambda body: [ev] if "take_events" in body else []
    g._pid = lambda pid=None: 0
    g.seat = 0
    out = g.turn_digest()
    rows = [e for e in out.get("events", []) if e.get("kind") == "civ_eliminated"]
    assert rows and "America" in rows[0]["data"]["summary"]
