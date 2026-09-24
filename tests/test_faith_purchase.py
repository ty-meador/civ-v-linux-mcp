"""The Religion Overview's automatic faith purchase pull-down (GitLab #11).

religionoverview.lua lists: nothing; save for a Great Prophet while a religion can still be founded
(or we founded one) and only before the Industrial era; every unit the capital could faith-buy
somewhere that passes DoesUnitPassFaithPurchaseCheck; every building it could faith-buy somewhere.
The selection callback is Network.SendFaithPurchase and offers nothing else.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
FaithPurchaseTypes = { NO_AUTOMATIC_FAITH_PURCHASE = 0, FAITH_PURCHASE_SAVE_PROPHET = 1, FAITH_PURCHASE_UNIT = 2, FAITH_PURCHASE_BUILDING = 3 }
ReligionTypes = { RELIGION_PANTHEON = 0 }
YieldTypes = { YIELD_FAITH = 5 }
ERA = 4; INDUSTRIAL = 5
FOUNDED = -1; STILL = 1
SEL_KIND, SEL_INDEX = 0, 0
local function rows(list) return setmetatable({}, { __call = function() local i = 0; return function() i = i + 1; return list[i] end end,
                                                    __index = function(_, k) for _, r in ipairs(list) do if r.ID == k or r.Type == k then return r end end end })
end
GameInfo = {
  Eras = { ERA_INDUSTRIAL = { ID = 5 } },
  Units = rows({ { ID = 10, Type = 'UNIT_MISSIONARY' }, { ID = 11, Type = 'UNIT_SCIENTIST' }, { ID = 12, Type = 'UNIT_WARRIOR' }, { ID = 13, Type = 'UNIT_ARTIST' } }),
  Buildings = rows({ { ID = 20, Type = 'BUILDING_MOSQUE' }, { ID = 21, Type = 'BUILDING_LIBRARY' } }),
}
Game = { GetNumReligionsStillToFound = function() return STILL end }
local capital = {
  GetUnitFaithPurchaseCost = function(_, id, include) assert(include == true); return ({ [10] = 200, [11] = 1500, [12] = 0, [13] = 1500 })[id] end,
  GetBuildingFaithPurchaseCost = function(_, id) return ({ [20] = 250, [21] = 0 })[id] end,
}
SENT = {}
Network = { SendFaithPurchase = function(pid, kind, index) SENT[#SENT + 1] = { pid, kind, index } end }
Players = { [0] = {
  GetFaithPurchaseType = function() return SEL_KIND end, GetFaithPurchaseIndex = function() return SEL_INDEX end,
  GetReligionCreatedByPlayer = function() return FOUNDED end, GetCurrentEra = function() return ERA end,
  GetCapitalCity = function() return capital end,
  IsCanPurchaseAnyCity = function(_, gold, faith, uid, bid, yield)
    assert(gold == false and faith == true and yield == 5)
    return uid ~= 13 and bid ~= 21          -- the artist is not buyable anywhere; the library never with faith
  end,
  DoesUnitPassFaithPurchaseCheck = function(_, uid) return uid ~= 11 end,   -- scientist blocked by the check
} }
"""


class FaithPurchaseMenuTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_menu_lists_what_the_pull_down_lists(self):
        self.run_lua("""
        local m = H.faith_auto_purchase(0)
        local kinds = {}
        for _, o in ipairs(m.options) do kinds[#kinds + 1] = o.kind .. ':' .. tostring(o.item) .. ':' .. tostring(o.faith) end
        local got = table.concat(kinds, ' ')
        assert(got == 'nothing:nil:nil save_prophet:nil:nil unit:UNIT_MISSIONARY:200 building:BUILDING_MOSQUE:250', got)
        assert(m.current.kind == 'nothing' and m.current.index == 0)
        """)

    def test_save_prophet_needs_a_foundable_religion_and_a_pre_industrial_era(self):
        self.run_lua("""
        local function has_prophet() for _, o in ipairs(H.faith_auto_purchase(0).options) do if o.kind == 'save_prophet' then return true end end return false end
        STILL = 0; FOUNDED = -1
        assert(not has_prophet(), 'no religion left to found and none founded')
        FOUNDED = 3
        assert(has_prophet(), 'we founded one')
        ERA = 5
        assert(not has_prophet(), 'Industrial era hides it')
        """)

    def test_current_selection_names_the_item(self):
        self.run_lua("""
        SEL_KIND, SEL_INDEX = 2, 10
        local m = H.faith_auto_purchase(0)
        assert(m.current.kind == 'unit' and m.current.index == 10 and m.current.item == 'UNIT_MISSIONARY')
        SEL_KIND, SEL_INDEX = 3, 20
        assert(H.faith_auto_purchase(0).current.item == 'BUILDING_MOSQUE')
        SEL_KIND, SEL_INDEX = 1, 0
        assert(H.faith_auto_purchase(0).current.kind == 'save_prophet')
        """)

    def test_set_sends_only_listed_entries(self):
        self.run_lua("""
        local r = H.set_faith_purchase('unit', 10, 0)
        assert(r.ok and r.selected.item == 'UNIT_MISSIONARY' and #SENT == 1 and SENT[1][2] == 2 and SENT[1][3] == 10, H.json(r))
        r = H.set_faith_purchase('save_prophet', 99, 0)
        assert(r.ok and SENT[2][2] == 1 and SENT[2][3] == 0, 'save_prophet ignores the index')
        r = H.set_faith_purchase('unit', 11, 0)
        assert(r.ok == false and #SENT == 2 and r.options[3] == 'unit:UNIT_MISSIONARY', H.json(r))
        r = H.set_faith_purchase('building', 21, 0)
        assert(r.ok == false and #SENT == 2)
        r = H.set_faith_purchase('bogus', 0, 0)
        assert(r.ok == false and #SENT == 2)
        r = H.set_faith_purchase('nothing', 0, 0)
        assert(r.ok and SENT[3][2] == 0)
        """)

    def test_religion_overview_carries_the_menu(self):
        self.run_lua("""
        GameInfo.Religions = setmetatable({}, { __call = function() return function() return nil end end })
        GameInfo.Beliefs = GameInfo.Religions
        Players[0].GetFaith = function() return 100 end
        Players[0].GetFaithPerTurn = function() return 3 end
        Players[0].Cities = function() return function() return nil end end
        Players[0].HasCreatedPantheon = function() return false end
        Players[0].HasCreatedReligion = function() return false end
        local ok, r = pcall(H.religion_overview, 0)
        if ok and type(r) == 'table' then
          assert(r.auto_purchase and r.auto_purchase.options[1].kind == 'nothing')
        end
        """)


if __name__ == "__main__":
    unittest.main()
