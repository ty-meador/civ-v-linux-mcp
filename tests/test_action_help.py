"""The sentence under a unit-action button (unitpanel.lua TipHandler).

Most buttons print `action.Help` from GameInfoActions. A handful print a computed line instead --
upgrade names the unit and the price, scrap names the gold, a golden age names its length, paradrop
names its range -- and `MISSION_ALERT` swaps in a different sentence entirely for a unit that can
never fortify. Without them the enum is the whole story, which is how BUILD_CITADEL read live at
t221 as "+1 production, -1 food" and said nothing about claiming territory.

v216 splits the two: `H.action_help` keeps only the computed lines (they differ per unit, so they ride
on the action row); `H.action_static_help` gives the standing sentence, printed once per action in
reference("actions") instead of on every row of every unit every turn.
"""
import unittest

import test_mcp_safety as support

WORLD = """
GameDefines = { MOVE_DENOMINATOR = 60 }
Locale = { ConvertTextKey = function(k, ...)
  -- The engine resolves TXT_KEYs passed as arguments too (live t221: "Upgrade the unit to a
  -- Crossbowman"), so the mock does the same before substituting.
  local args = {}
  for i, v in ipairs({...}) do
    args[i] = (type(v) == 'string' and v:sub(1, 8) == 'TXT_KEY_')
      and v:gsub('^TXT_KEY_UNIT_', ''):sub(1, 1) .. v:gsub('^TXT_KEY_UNIT_', ''):sub(2):lower() or v
  end
  if k == 'TXT_KEY_UPGRADE_HELP' then
    return 'Upgrade the unit to a ' .. tostring(args[1]) .. '. This requires ' .. tostring(args[2]) .. ' Gold.'
  elseif k == 'TXT_KEY_SCRAP_HELP' then
    return 'Performing this action within your territory will provide ' .. tostring(args[1]) .. ' Gold.'
  elseif k == 'TXT_KEY_MISSION_START_GOLDENAGE_HELP' then
    return 'Start a Golden Age lasting ' .. tostring(args[1]) .. ' turns.'
  elseif k == 'TXT_KEY_INTERFACEMODE_PARADROP_HELP_WITH_RANGE' then
    return 'Paradrop up to ' .. tostring(args[1]) .. ' tiles away.'
  elseif k == 'TXT_KEY_MISSION_ALERT_NO_FORTIFY_HELP' then
    return 'This unit cannot fortify; it will sleep instead.'
  elseif k == 'TXT_KEY_MISSION_DISCOVER_TECH_HELP' then
    return 'Discover a new technology.'
  elseif k:sub(1, 8) == 'TXT_KEY_' then
    return k:sub(9):lower():gsub('_', ' ')
  end
  return k                              -- the engine hands back anything it cannot resolve
end }
GameInfo = { Units = {[7] = {Description = 'TXT_KEY_UNIT_CROSSBOWMAN'}} }

unit = {
  GetUpgradeUnitType = function() return 7 end,
  UpgradePrice = function(_, t) assert(t == 7); return 100 end,
  GetScrapGold = function() return 18 end,
  GetGoldenAgeTurns = function() return 10 end,
  GetDropRange = function() return 5 end,
  IsEverFortifyable = function() return fortifyable end,
}
fortifyable = true
"""


class ActionHelpTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_plain_buttons_carry_no_help_on_the_row_but_the_reference_has_it(self):
        self.run_lua("""
        assert(H.action_help(unit, 'BUILD_CITADEL', 'TXT_KEY_BUILD_CITADEL_HELP') == nil,
               'static text stays off the row (v216)')
        local h = H.action_static_help('BUILD_CITADEL', 'TXT_KEY_BUILD_CITADEL_HELP')
        assert(h == 'build citadel help', h)
        """)

    def test_the_none_sentinel_is_not_a_tooltip(self):
        """GameInfoActions spells "no help" as the string "NONE", and ConvertTextKey echoes it back."""
        self.run_lua("""
        for _, raw in ipairs({'NONE', 'None', ''}) do
          assert(H.action_static_help('MISSION_SWAP_UNITS', raw) == nil, raw)
        end
        assert(H.action_static_help('MISSION_SWAP_UNITS', nil) == nil)
        assert(H.action_static_help('MISSION_SWAP_UNITS', 'not a text key') == nil,
               'an unresolvable key is not help text')
        """)

    def test_upgrade_names_the_unit_and_the_price(self):
        self.run_lua("""
        local h = H.action_help(unit, 'COMMAND_UPGRADE', 'TXT_KEY_IGNORED')
        assert(h:find('Crossbowman') and h:find('100 Gold'), h)
        """)

    def test_scrap_names_the_gold(self):
        self.run_lua("""
        assert(H.action_help(unit, 'COMMAND_DELETE', nil):find('18 Gold'))
        """)

    def test_golden_age_and_paradrop_carry_their_numbers(self):
        self.run_lua("""
        assert(H.action_help(unit, 'MISSION_GOLDEN_AGE', 'TXT_KEY_IGNORED'):find('10 turns'))
        assert(H.action_help(unit, 'INTERFACEMODE_PARADROP', nil):find('5 tiles'))
        """)

    def test_alert_says_sleep_when_the_unit_cannot_fortify(self):
        self.run_lua("""
        fortifyable = false
        assert(H.action_help(unit, 'MISSION_ALERT', 'TXT_KEY_MISSION_ALERT_HELP'):find('cannot fortify'))
        fortifyable = true
        assert(H.action_help(unit, 'MISSION_ALERT', 'TXT_KEY_MISSION_ALERT_HELP') == nil,
               'a unit that can fortify gets the standing sentence, which is in the reference')
        assert(H.action_static_help('MISSION_ALERT', 'TXT_KEY_MISSION_ALERT_HELP') == 'mission alert help')
        """)

    def test_great_person_missions_use_the_panel_key_not_the_action_row(self):
        self.run_lua("""
        assert(H.action_help(unit, 'MISSION_DISCOVER', 'TXT_KEY_WRONG') == nil, 'static: reference only')
        assert(H.action_static_help('MISSION_DISCOVER', 'TXT_KEY_WRONG') == 'Discover a new technology.')
        """)

    def test_a_missing_getter_costs_only_its_own_line(self):
        """A unit without GetScrapGold must not blow up the whole action list."""
        self.run_lua("""
        local bare = {}
        assert(H.action_help(bare, 'COMMAND_DELETE', nil):find('0 Gold'))
        assert(H.action_help(bare, 'COMMAND_UPGRADE', 'TXT_KEY_FALLBACK_HELP') == nil,
               'no upgrade target: nothing computed, and the standing sentence is in the reference')
        assert(H.action_static_help('COMMAND_UPGRADE', 'TXT_KEY_FALLBACK_HELP') == 'fallback help')
        """)


if __name__ == "__main__":
    unittest.main()
