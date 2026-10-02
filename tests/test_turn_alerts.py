"""turn_status.alerts (#39): low happiness, an unhappy tier, strategic deficits -- on the status, not only on
overview -- and the quiet-turn wake rule behind them (a drop wakes, a steady low total does not).

Lua half: H.status_alerts against a mocked player (test_happiness_screen checks the tier agrees with
happiness_breakdown on its full fixture); Python half: Game's baseline bookkeeping and finish_turn.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game
from test_finish_turn import QUIET, ScriptedGame, status


WORLD = r"""
local function iter(rows)
  local i = 0
  return function() i = i + 1; return rows[i] end
end
GameInfo = GameInfo or {}
GameInfo.Resources = function() return iter({
  { ID = 1, Type = "RESOURCE_IRON", ResourceClassType = "RESOURCECLASS_RUSH", TechReveal = "TECH_BRONZE_WORKING" },
  { ID = 2, Type = "RESOURCE_HORSE", ResourceClassType = "RESOURCECLASS_RUSH", TechReveal = "TECH_ANIMAL_HUSBANDRY" },
  { ID = 3, Type = "RESOURCE_COAL", ResourceClassType = "RESOURCECLASS_MODERN", TechReveal = "TECH_SCIENTIFIC_THEORY" },
  { ID = 4, Type = "RESOURCE_SILK", ResourceClassType = "RESOURCECLASS_LUXURY" },
  { ID = 5, Type = "RESOURCE_HIDDEN_ARTIFACTS", ResourceClassType = "RESOURCECLASS_MODERN" },
}) end
GameInfoTypes = { TECH_BRONZE_WORKING = 10, TECH_ANIMAL_HUSBANDRY = 11, TECH_SCIENTIFIC_THEORY = 12 }
local known = { [10] = true, [11] = true }   -- Coal is not revealed yet
Teams = { [0] = { GetTeamTechs = function() return { HasTech = function(_, id) return known[id] == true end } end } }

World = { happiness = 1, tier = nil,
          available = { [1] = -2, [2] = 3, [3] = -5, [4] = 1 }, total = { [1] = 2, [2] = 4, [3] = 0, [4] = 1 },
          used = { [1] = 4, [2] = 1, [3] = 5, [4] = 0 } }
Players = { [0] = {
  GetTeam = function() return 0 end,
  GetExcessHappiness = function() return World.happiness end,
  IsEmpireUnhappy = function() return World.tier ~= nil end,
  IsEmpireVeryUnhappy = function() return World.tier == "very_unhappy" or World.tier == "super_unhappy" end,
  IsEmpireSuperUnhappy = function() return World.tier == "super_unhappy" end,
  GetNumResourceAvailable = function(_, id) return World.available[id] or 0 end,
  GetNumResourceTotal = function(_, id) return World.total[id] or 0 end,
  GetNumResourceUsed = function(_, id) return World.used[id] or 0 end,
  GetResourceImport = function() return 0 end,
  GetResourceExport = function() return 0 end,
} }
"""


class StatusAlertsLuaTests(support.LuaRuntimeTests):
    def test_low_happiness_and_revealed_deficits_are_alerts(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
local alerts, happiness, tier = H.status_alerts(0)
assert(happiness == 1 and tier == nil, "bare total and tier come back with the list")
assert(#alerts == 2, "happiness row + one deficit, got " .. #alerts)
assert(alerts[1].kind == "happiness" and alerts[1].happiness == 1 and alerts[1].unhappy == nil)
local d = alerts[2]
assert(d.kind == "strategic_deficit" and d.resource == "IRON", "the revealed deficit is Iron")
assert(d.available == -2 and d.deficit == 2 and d.total == 2 and d.used == 4, H.json(d))
-- Coal is in deficit too, but the tech that reveals it is not known: unknown stays unknown, as on the top bar.
for _, a in ipairs(alerts) do assert(a.resource ~= "COAL", "unrevealed strategic must not leak") end
-- The figures are the ones overview prints.
local strat = H.strategic_resources(0)
assert(strat.IRON.available == d.available and strat.IRON.used == d.used, "matches overview's row")
assert(strat.COAL == nil and strat.HORSE.available == 3)
""")

    def test_happy_empire_with_surplus_has_no_alerts(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
World.happiness = 3
World.available[1] = 1
local alerts = H.status_alerts(0)
assert(#alerts == 0, "happiness 3, no deficit: nothing, got " .. H.json(alerts))
assert(H.json(alerts) == "[]", "an empty list is a JSON array, not an object")
World.happiness = 2
assert(#H.status_alerts(0) == 1, "2 is the threshold")
""")

    def test_unhappy_tier_is_an_alert_even_when_the_total_reads_high(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
World.happiness = 5   -- not what the game does, but the tier must be its own trigger
World.available[1] = 0
World.tier = "very_unhappy"
local alerts, happiness, tier = H.status_alerts(0)
assert(tier == "very_unhappy" and #alerts == 1 and alerts[1].unhappy == "very_unhappy", H.json(alerts))
assert(H.unhappy_tier(Players[0]) == "very_unhappy")
World.tier = "super_unhappy"
assert(H.unhappy_tier(Players[0]) == "super_unhappy")
World.tier = "unhappy"
assert(H.unhappy_tier(Players[0]) == "unhappy")
World.tier = nil
assert(H.unhappy_tier(Players[0]) == nil)
""")

    def test_a_partial_player_yields_no_deficit_rows(self):
        self.run_lua("Players = { [0] = { GetExcessHappiness = function() return 1 end } }")
        self.run_lua(r"""
local alerts, happiness = H.status_alerts(0)
assert(happiness == 1 and #alerts == 1 and alerts[1].kind == "happiness", H.json(alerts))
""")

    def test_over_the_unit_supply_cap_is_an_alert_with_the_penalty(self):
        # v254: toppanel.lua shows its unit-supply string only while the production penalty is nonzero.
        self.run_lua(WORLD)
        self.run_lua(r"""
World.happiness = 9
World.available[1] = 1
local P = Players[0]
World.supply = { cap = 14, units = 17, over = 3, mod = -30 }
P.GetNumUnitsSupplied = function() return World.supply.cap end
P.GetNumUnits = function() return World.supply.units end
P.GetNumUnitsOutOfSupply = function() return World.supply.over end
P.GetUnitProductionMaintenanceMod = function() return World.supply.mod end
P.GetNumUnitsSuppliedByHandicap = function() return 5 end
P.GetNumUnitsSuppliedByCities = function() return 2 end
P.GetNumUnitsSuppliedByPopulation = function() return 7 end
local alerts = H.status_alerts(0)
assert(#alerts == 1, "one supply row, got " .. H.json(alerts))
local a = alerts[1]
assert(a.kind == "unit_supply" and a.deficit == 3 and a.cap == 14 and a.used == 17 and a.production_penalty == -30, H.json(a))
-- Venice t153: 15 units of 14 supplied, but the engine's own deficit (military units only) is 0 and the top
-- bar shows nothing: no row, as on screen. overview.unit_supply still reads remaining -1.
World.supply = { cap = 14, units = 15, over = 0, mod = 0 }
assert(#H.status_alerts(0) == 0, "no engine deficit, no row: " .. H.json(H.status_alerts(0)))
assert(H.unit_supply(0).remaining == -1)
""")


def alert_status(turn, happiness, unhappy=None, deficits=None, supply=None, **extra):
    alerts = []
    if unhappy or happiness <= 2:
        alerts.append({"kind": "happiness", "happiness": happiness, "unhappy": unhappy})
    for name, avail in (deficits or {}).items():
        alerts.append({"kind": "strategic_deficit", "resource": name, "available": avail, "deficit": -avail})
    if supply:
        alerts.append({"kind": "unit_supply", "deficit": supply, "cap": 14, "used": 14 + supply,
                       "production_penalty": -10 * supply})
    return status(turn, alerts=alerts, happiness=happiness, unhappy=unhappy, **extra)


class AlertWakeTests(unittest.TestCase):
    def run_quiet(self, first, turns, n=5):
        g = ScriptedGame([(ts, QUIET) for ts in turns], first_status=first)
        return g, g.finish_turn(skip_quiet_turns=n)

    def test_alerts_never_block_and_never_fill_todo(self):
        ts = alert_status(4, 1, deficits={"IRON": -2})
        self.assertEqual(ts["blocking_name"], "NO_ENDTURN_BLOCKING_TYPE")
        self.assertFalse(any(ts["todo"].values()))
        g = ScriptedGame([])
        # No baseline: the alert is on the status but it is not a wake reason.
        self.assertEqual(g._wake_reasons(ts, QUIET), [])
        self.assertEqual(len(ts["alerts"]), 2)

    def test_steady_low_happiness_does_not_wake(self):
        g, r = self.run_quiet(alert_status(1, 1), [alert_status(t, 1) for t in range(2, 6)], n=3)
        self.assertEqual(r["turns_skipped"], 3)
        self.assertEqual(r["woke_because"], ["quiet_turn_budget_used"])
        self.assertEqual(r["status"]["alerts"][0]["happiness"], 1, "the alert stays on every status")

    def test_a_drop_wakes(self):
        g, r = self.run_quiet(alert_status(1, 3), [alert_status(2, 3), alert_status(3, 1), alert_status(4, 1)])
        self.assertEqual(r["turn"], 3)
        self.assertEqual(r["turns_skipped"], 1)
        self.assertEqual(r["woke_because"], ["happiness_drop:3->1"])

    def test_a_drop_from_five_to_four_wakes_without_any_alert(self):
        g, r = self.run_quiet(alert_status(1, 5), [alert_status(2, 4)])
        self.assertEqual(r["woke_because"], ["happiness_drop:5->4"])
        self.assertEqual(r["status"]["alerts"], [])

    def test_a_new_or_deeper_tier_wakes_and_an_easing_one_does_not(self):
        g, r = self.run_quiet(alert_status(1, 1), [alert_status(2, -1, "unhappy"), alert_status(3, -1, "unhappy")])
        self.assertEqual(r["turn"], 2)
        self.assertEqual(r["woke_because"], ["happiness_drop:1->-1", "unhappy:unhappy"])
        g, r = self.run_quiet(alert_status(1, -1, "unhappy"), [alert_status(2, -1, "unhappy"), alert_status(3, -1, "very_unhappy")])
        self.assertEqual((r["turn"], r["woke_because"]), (3, ["unhappy:very_unhappy"]))
        g, r = self.run_quiet(alert_status(1, -1, "very_unhappy"), [alert_status(2, -1, "unhappy"), alert_status(3, -1, None)], n=1)
        self.assertEqual(r["woke_because"], ["quiet_turn_budget_used"], "easing is not news")

    def test_a_new_or_deeper_deficit_wakes_and_a_steady_one_does_not(self):
        g, r = self.run_quiet(alert_status(1, 5), [alert_status(2, 5, deficits={"IRON": -2}), alert_status(3, 5, deficits={"IRON": -2})])
        self.assertEqual((r["turn"], r["woke_because"]), (2, ["strategic_deficit:IRON:-2"]))
        g, r = self.run_quiet(alert_status(1, 5, deficits={"IRON": -2}),
                              [alert_status(2, 5, deficits={"IRON": -2}), alert_status(3, 5, deficits={"IRON": -4})])
        self.assertEqual((r["turn"], r["woke_because"]), (3, ["strategic_deficit:IRON:-4"]))

    def test_crossing_the_unit_supply_cap_wakes_and_a_steady_deficit_does_not(self):
        g, r = self.run_quiet(alert_status(1, 5), [alert_status(2, 5, supply=1), alert_status(3, 5, supply=1)])
        self.assertEqual((r["turn"], r["woke_because"]), (2, ["unit_supply:1"]))
        g, r = self.run_quiet(alert_status(1, 5, supply=1),
                              [alert_status(2, 5, supply=1), alert_status(3, 5, supply=3)])
        self.assertEqual((r["turn"], r["woke_because"]), (3, ["unit_supply:3"]))
        g, r = self.run_quiet(alert_status(1, 5, supply=3), [alert_status(2, 5, supply=1), alert_status(3, 5)], n=1)
        self.assertEqual(r["woke_because"], ["quiet_turn_budget_used"], "easing is not news")

    def test_first_status_of_a_process_has_no_baseline(self):
        g = ScriptedGame([])
        self.assertEqual(g._alert_wake_reasons(alert_status(7, -3, "unhappy", {"IRON": -1})), [])
        g._note_happiness(alert_status(7, -3, "unhappy", {"IRON": -1}))
        self.assertEqual(g._alert_wake_reasons(alert_status(7, -3, "unhappy", {"IRON": -1})), [], "same turn, still none")
        self.assertEqual(g._alert_wake_reasons(alert_status(8, -3, "unhappy", {"IRON": -1})), [],
                         "the next turn is compared with turn 7 only once that turn has been noted")
        g._note_happiness(alert_status(8, -4, "unhappy", {"IRON": -1}))
        self.assertEqual(g._alert_wake_reasons(alert_status(8, -4, "unhappy", {"IRON": -1})), ["happiness_drop:-3->-4"])

    def test_last_value_seen_is_the_baseline_and_a_reload_clears_it(self):
        g = ScriptedGame([])
        g._note_happiness(alert_status(3, 6))
        g._note_happiness(alert_status(3, 2))    # bought a settler mid-turn: the last read at turn 3 is 2
        g._note_happiness(alert_status(4, 2))
        self.assertEqual(g._alert_wake_reasons(alert_status(4, 2)), [])
        g._note_happiness(alert_status(2, 9))    # an earlier save was loaded
        self.assertEqual(g._alert_wake_reasons(alert_status(2, 9)), [])
        g._note_happiness(alert_status(3, 1))
        self.assertEqual(g._alert_wake_reasons(alert_status(3, 1)), ["happiness_drop:9->1"])

    def test_statuses_without_a_total_are_ignored(self):
        g = ScriptedGame([])
        g._note_happiness(status(3))              # an older runtime: no happiness key
        g._note_happiness({"ingame": False})
        self.assertEqual(g._alert_wake_reasons(alert_status(4, 1)), [])
        self.assertEqual(g._alert_wake_reasons(status(4)), [])

    def test_wrapper_notes_only_this_seat(self):
        class Q(Game):
            def __init__(self):
                self.seat = 1
            def q(self, code, timeout=None):
                pid = int(code.split("H.turn_state(")[1].split(")")[0])
                return {**alert_status(5, 1 if pid == 1 else -9, None if pid == 1 else "super_unhappy"),
                        **{k: False for k in Game.MODAL_FLAGS}}
        g = Q()
        g.turn_state(pid=0)   # another seat's economy is read but never becomes our baseline
        self.assertNotIn(1, getattr(g, "_happiness_seen", {}))
        ts = g.turn_state()
        self.assertEqual(ts["alerts"][0]["happiness"], 1)
        self.assertEqual(g._happiness_seen[1][1], 1)


if __name__ == "__main__":
    unittest.main()
