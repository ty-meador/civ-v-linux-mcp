"""A move refused as unrevealed says when the target read with x and y swapped is a revealed plot.

GitLab #150 F4 (hotseat Spain t4, Grok): the ruins stood at x=26, y=30; the order went to x=30, y=26, an
unrevealed plot, and the refusal blamed the fog. The swap is the likelier mistake, so the refusal names it.
"""
import unittest

import test_mcp_safety as support


class SwappedAxesHintTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    WORLD = """
    UI={SelectUnit=function() error('SelectUnit flips camera') end}
    Game={GetActivePlayer=function() return 0 end}
    GameDefines={MOVE_DENOMINATOR=60}
    MissionTypes={MISSION_MOVE_TO=1}; GameInfoTypes=MissionTypes
    local unit={ GetX=function() return 1 end, GetY=function() return 1 end, MovesLeft=function() return 60 end,
                 CanStartMission=function() return true end, PushMission=function() end }
    Players={[0]={GetUnitByID=function() return unit end, GetTeam=function() return 0 end}}
    REVEALED = {}
    Map={GetPlot=function(x, y) return {GetX=function() return x end, GetY=function() return y end,
                                        IsRevealed=function() return REVEALED[x..','..y] == true end,
                                        IsWater=function() return false end, IsImpassable=function() return false end} end,
         PlotDistance=function(x1, y1, x2, y2) return math.max(math.abs(x1-x2), math.abs(y1-y2)) end}
    """

    def test_the_swapped_plot_is_named_when_it_is_revealed(self):
        self.run_lua(self.WORLD + """
        REVEALED['26,30'] = true
        local r = H.move_unit(1, 30, 26, 0)
        assert(r.ok == false and r.err == 'plot is not revealed', tostring(r.err))
        assert(r.swapped and r.swapped.x == 26 and r.swapped.y == 30, 'swapped plot missing')
        assert(r.hint:find('x=26, y=30 IS revealed', 1, true), r.hint)
        """)

    def test_no_swap_row_when_the_swapped_plot_is_fog_too_or_the_same_plot(self):
        self.run_lua(self.WORLD + """
        local r = H.move_unit(1, 30, 26, 0)
        assert(r.ok == false and r.swapped == nil, 'no revealed swap, no row')
        assert(not r.hint:find('swapped', 1, true), r.hint)
        REVEALED['7,7'] = false
        r = H.move_unit(1, 7, 7, 0)
        assert(r.ok == false and r.swapped == nil, 'x == y is not a swap')
        """)
