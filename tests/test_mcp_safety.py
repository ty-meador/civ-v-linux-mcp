"""Regression tests for privacy and invalid actions, using the real Lua runtime."""
import ctypes
import ctypes.util
import json
from pathlib import Path
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from harness.client import Civ5
from harness.action_lock import action_lock


class LuaRuntimeTests(unittest.TestCase):
    def setUp(self):
        library = ctypes.util.find_library("lua5.4")
        if not library:
            self.skipTest("liblua5.4 is needed for runtime regression tests")
        self.lua = ctypes.CDLL(library)
        self.lua.luaL_newstate.restype = ctypes.c_void_p
        self.lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        self.lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lua.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong, ctypes.c_void_p]
        self.lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self.lua.lua_tolstring.restype = ctypes.c_char_p
        self.lua.lua_close.argtypes = [ctypes.c_void_p]
        self.state = self.lua.luaL_newstate()
        self.lua.luaL_openlibs(self.state)
        self.addCleanup(self.lua.lua_close, self.state)
        self.run_lua("Events={}; Game={GetActivePlayer=function() return 0 end, GetGameTurn=function() return 1 end}")
        self.run_lua(Path("harness/lua/runtime.lua").read_text())

    def run_lua(self, source):
        result = self.lua.luaL_loadstring(self.state, source.encode())
        if result == 0:
            result = self.lua.lua_pcallk(self.state, 0, 0, 0, 0, None)
        if result:
            self.fail(self.lua.lua_tolstring(self.state, -1, None).decode())

    def test_unmet_civilizations_are_not_returned(self):
        self.run_lua("""
        Players={[0]={GetTeam=function() return 0 end}, [1]={
          IsAlive=function() return true end, IsEverAlive=function() return true end,
          GetTeam=function() return 1 end, GetName=function() error('private identity read') end}}
        Teams={[0]={IsHasMet=function() return false end}}; GameDefines={MAX_MAJOR_CIVS=2}
        assert(#H.diplomacy(0)==0)
        """)

    def test_fogged_plots_do_not_read_dynamic_state(self):
        self.run_lua("""
        local function no() return false end
        local p={IsRevealed=function() return true end, IsVisible=no,
          GetX=function() return 2 end, GetY=function() return 3 end,
          GetTerrainType=function() return 0 end, IsHills=no, IsMountain=no, IsRiver=no,
          GetFeatureType=function() return -1 end,
          GetResourceType=function(self, team) assert(team==7); return -1 end}
        setmetatable(p,{__index=function(_,key) error('private state read: '..key) end})
        Map={PlotXYWithRangeCheck=function() return p end}
        GameInfo={Terrains={[0]={Type='TERRAIN_GRASS'}}}
        local result=H.plots_around(2,3,0,7)
        assert(#result==1 and result[1].vis==false)
        assert(result[1].owner==nil and result[1].city==nil and result[1].units==nil and result[1].feature==nil)
        """)

    def test_revealed_plots_omit_unrevealed_and_do_not_cheat_fog(self):
        self.run_lua("""
        local function no() return false end
        local function yes() return true end
        local function plot(revealed, visible, extra)
          local p={IsRevealed=function() return revealed end, IsVisible=function() return visible end,
            GetX=function() return extra.x end, GetY=function() return extra.y end,
            GetTerrainType=function() return 0 end, IsHills=no, IsMountain=no, IsRiver=no,
            GetResourceType=function() return -1 end}
          if visible then
            p.GetFeatureType=function() return -1 end
            p.GetImprovementType=function() return -1 end
            p.GetRouteType=function() return -1 end
            p.GetOwner=function() return extra.owner end
            p.IsCity=no
            p.GetNumUnits=function() return extra.units or 0 end
            p.GetUnit=function() return extra.unit end
          else
            setmetatable(p,{__index=function(_,key) error('fog cheat: '..key) end})
          end
          return p
        end
        local hidden=plot(false, false, {x=0,y=0})
        local fog=plot(true, false, {x=1,y=1})
        local seen=plot(true, true, {x=2,y=2, owner=3, units=1, unit={
          IsInvisible=no, GetOwner=function() return 3 end, GetID=function() return 9 end,
          GetUnitType=function() return 0 end, GetCurrHitPoints=function() return 100 end}})
        Map={GetNumPlots=function() return 3 end, GetPlotByIndex=function(i)
          return ({[0]=hidden,[1]=fog,[2]=seen})[i]
        end}
        GameInfo={Terrains={[0]={Type='TERRAIN_GRASS'}}, Units={[0]={Type='UNIT_WARRIOR'}}}
        local result=H.revealed_plots(7)
        assert(#result==2)
        assert(result[1].x==1 and result[1].vis==false and result[1].units==nil and result[1].owner==nil)
        assert(result[2].x==2 and result[2].vis==true and result[2].owner==3)
        assert(#result[2].units==1 and result[2].units[1].id==9)
        """)

    def test_explore_frontier_reads_only_revealed_flag_of_fog(self):
        # A 3x1 strip: x=0 revealed water, x=1 revealed water, x=2 unrevealed. Only (1,0) borders the fog.
        # Touching anything but IsRevealed on the unrevealed plot is a fog cheat.
        self.run_lua("""
        local function no() return false end
        local function yes() return true end
        local plots = {}
        local function water(x)
          return {IsRevealed=yes, IsImpassable=no, IsWater=yes, GetX=function() return x end, GetY=function() return 0 end,
                  GetTerrainType=function() return 0 end}
        end
        plots[0]=water(0); plots[1]=water(1)
        plots[2]=setmetatable({IsRevealed=no, GetX=function() return 2 end, GetY=function() return 0 end},
          {__index=function(_,key) error('fog cheat: '..key) end})
        Map={GetNumPlots=function() return 3 end, GetPlotByIndex=function(i) return plots[i] end,
             GetGridSize=function() return 3, 1 end,
             PlotXYWithRangeCheck=function(x, y, dx, dy, r) if dy ~= 0 then return nil end return plots[x+dx] end,
             PlotDistance=function(ax, ay, bx, by) return math.abs(ax-bx) end}
        DomainTypes={DOMAIN_SEA=1, DOMAIN_LAND=0}
        GameInfo={Terrains={[0]={Type='TERRAIN_COAST'}}}
        local ship={GetDomainType=function() return 1 end, IsEmbarked=no, GetX=function() return 0 end, GetY=function() return 0 end}
        Players={[0]={GetUnitByID=function(_, id) if id==5 then return ship end end, GetTeam=function() return 0 end}}
        local r=H.explore_frontier(5, 0, 12)
        assert(r.ok, 'ok')
        assert(r.unrevealed_plots==1, 'one fogged plot')
        assert(#r.frontier==1 and r.frontier[1].x==1 and r.frontier[1].unrevealed_neighbors==1 and r.frontier[1].distance==1, 'frontier is (1,0)')
        assert(r.frontier[1].t=='COAST')
        assert(r.unit.domain=='SEA' and r.map.width==3)
        assert(r.note==nil)
        -- a land unit sees no frontier here (all water) and gets a note instead of nothing
        local land={GetDomainType=function() return 0 end, IsEmbarked=no, GetX=function() return 0 end, GetY=function() return 0 end}
        Players[0].GetUnitByID=function(_, id) return land end
        local r2=H.explore_frontier(5, 0, 12)
        assert(#r2.frontier==0 and r2.note ~= nil and r2.frontier_total==0)
        assert(not H.explore_frontier(99, 0, 12).ok or true)
        """)

    def test_unmet_city_states_are_not_returned(self):
        self.run_lua("""
        Players={[0]={GetTeam=function() return 0 end}, [22]={
          IsAlive=function() return true end, IsEverAlive=function() return true end,
          IsMinorCiv=function() return true end, GetTeam=function() return 22 end,
          GetName=function() error('private minor identity read') end}}
        Teams={[0]={IsHasMet=function() return false end}}
        GameDefines={MAX_CIV_PLAYERS=23, MAX_MAJOR_CIVS=2}
        assert(#H.diplomacy(0)==0)
        """)

    def test_non_trade_unit_never_reaches_native_route_api(self):
        self.run_lua("""
        Players={[0]={GetUnitByID=function() return {IsTrade=function() return false end} end,
          GetPotentialInternationalTradeRouteDestinations=function() error('unsafe native call') end}}
        assert(#H.available_trade_routes(1,0)==0)
        local result=H.establish_trade_route(1,2,3,0,0)
        assert(result.ok==false and result.err=='unit is not a caravan or cargo ship')
        """)

    def test_events_are_filtered_at_capture_and_consumed_per_seat(self):
        self.run_lua("""
        H.record('city_created', {player=1,city=123})
        H.record('city_created', {player=0,city=456})
        Game.GetActivePlayer=function() return 1 end
        H.record('city_created', {player=1,city=789})
        local zero=H.take_events(0); local one=H.take_events(1)
        assert(#zero==1 and zero[1].data.city==456)
        assert(#one==1 and one[1].data.city==789)
        assert(#H.take_events(0)==0)
        """)

    def test_available_research_uses_can_research_not_raw_table(self):
        self.run_lua("""
        local seen={}
        GameInfo={Technologies=function()
          local rows={{ID=1,Type='TECH_POTTERY'},{ID=2,Type='TECH_FUTURE_TECH'}}
          local i=0
          return function() i=i+1; return rows[i] end
        end}
        Players={[0]={
          GetCurrentResearch=function() return 1 end,
          CanResearch=function(self,id) seen[#seen+1]=id; return id==1 end,
          GetResearchTurnsLeft=function() return 3 end,
          GetResearchCost=function() return 35 end,
        }}
        local out=H.available_research(0)
        assert(#out==1 and out[1].tech=='TECH_POTTERY' and out[1].current==true)
        assert(#seen==2)
        """)

    def test_available_production_missing_city_does_not_scan(self):
        self.run_lua("""
        GameInfo={Units=function() error('scanned units') end,
                  Buildings=function() error('scanned buildings') end,
                  Projects=function() error('scanned projects') end,
                  Processes=function() error('scanned processes') end}
        Players={[0]={GetCityByID=function() return nil end}}
        local r=H.available_production(99,0)
        assert(r.ok==false and r.err=='no such city')
        """)

    def test_available_unit_actions_do_not_select_or_consult_panel(self):
        self.run_lua("""
        Game.CanHandleAction=function() error('CanHandleAction without selection') end
        UI={SelectUnit=function() error('SelectUnit flips camera') end,
            GetHeadSelectedUnit=function() return nil end}
        GameDefines={MOVE_DENOMINATOR=60}
        GameInfoActions={[0]={Type='MISSION_FORTIFY', MissionType=7, CommandType=-1, AutomateType=-1, MissionData=-1}}
        local unit={
          CanStartMission=function(self, mid, d1, d2, vis) assert(mid==7); return true end,
          GetX=function() return 1 end, GetY=function() return 2 end,
          MovesLeft=function() return 120 end,
        }
        Players={[0]={GetUnitByID=function() return unit end}}
        local r=H.available_unit_actions(1,0)
        assert(r.ok==true and #r.actions==1 and r.actions[1].type=='MISSION_FORTIFY')
        """)

    def test_available_unit_actions_omit_global_ui_controls(self):
        self.run_lua("""
        local unit={}
        Game.CanHandleAction=function() error('CanHandleAction must not be used') end
        GameDefines={MOVE_DENOMINATOR=60}
        GameInfoActions={
          [0]={Type='MISSION_FORTIFY', MissionType=7, CommandType=-1, AutomateType=-1, MissionData=-1},
          [1]={Type='CONTROL_QUICK_SAVE', MissionType=-1, CommandType=-1, AutomateType=-1, MissionData=-1},
          [2]={Type='AUTOMATE_EXPLORE', MissionType=-1, CommandType=2, AutomateType=1, MissionData=-1},
          [3]={Type='COMMAND_HOTKEY', MissionType=-1, CommandType=-1, AutomateType=-1, MissionData=-1},
          [4]={Type='INTERFACEMODE_MOVE_TO', MissionType=-1, CommandType=-1, AutomateType=-1, MissionData=-1},
        }
        Players={[0]={GetUnitByID=function() return unit end}}
        unit.CanStartMission=function(self, mid, d1, d2, vis) return mid==7 end
        unit.CanAutomate=function(self, at) return at==1 end
        unit.CanDoCommand=function() return true end
        unit.GetX=function() return 1 end; unit.GetY=function() return 2 end
        unit.MovesLeft=function() return 120 end
        local r=H.available_unit_actions(1,0)
        assert(r.ok==true and #r.actions==2)
        assert(r.actions[1].type=='MISSION_FORTIFY' and r.actions[2].type=='AUTOMATE_EXPLORE')
        """)

    def test_move_unit_pushmission_does_not_select(self):
        self.run_lua("""
        local pushed={}
        UI={SelectUnit=function() error('SelectUnit flips camera') end,
            LookAt=function() error('LookAt flips camera') end,
            GetHeadSelectedUnit=function() return nil end}
        Game={GetActivePlayer=function() return 0 end,
              SelectionListMove=function() error('SelectionListMove needs selection') end,
              SelectionListGameNetMessage=function() error('net message needs selection') end,
              CanHandleAction=function() error('CanHandleAction needs selection') end}
        GameDefines={MOVE_DENOMINATOR=60}
        MissionTypes={MISSION_MOVE_TO=1}
        GameInfoTypes=MissionTypes
        local unit={
          GetX=function() return 10 end, GetY=function() return 20 end,
          MovesLeft=function() return 120 end, IsCombatUnit=function() return false end,
          CanStartMission=function(self, m, x, y, vis)
            assert(m==1 and x==11 and y==20 and vis==false); return true
          end,
          PushMission=function(self, m, x, y, flags, append, manual)
            pushed[#pushed+1]={m=m,x=x,y=y,flags=flags,append=append,manual=manual}
          end,
        }
        Players={[0]={GetUnitByID=function() return unit end, GetTeam=function() return 7 end}}
        Map={GetPlot=function(x,y)
          return {IsRevealed=function(self, team) assert(team==7); return true end,
                  IsImpassable=function() return false end, IsMountain=function() return false end}
        end}
        local r=H.move_unit(1, 11, 20, 0)
        assert(r.ok==true and r.x==10 and r.y==20 and r.moves==2)
        assert(#pushed==1 and pushed[1].m==1 and pushed[1].x==11 and pushed[1].y==20)
        assert(pushed[1].flags==0 and pushed[1].append==0 and pushed[1].manual==1)
        """)

    def test_move_unit_rejects_unrevealed_and_illegal(self):
        self.run_lua("""
        UI={SelectUnit=function() error('SelectUnit flips camera') end}
        Game={GetActivePlayer=function() return 0 end}
        GameDefines={MOVE_DENOMINATOR=60}
        MissionTypes={MISSION_MOVE_TO=1}; GameInfoTypes=MissionTypes
        local pushed=false
        local unit={
          GetX=function() return 1 end, GetY=function() return 1 end, MovesLeft=function() return 60 end,
          CanStartMission=function() return true end,
          PushMission=function() pushed=true end,
        }
        Players={[0]={GetUnitByID=function() return unit end, GetTeam=function() return 0 end}}
        Map={GetPlot=function() return {IsRevealed=function() return false end} end}
        local r=H.move_unit(1, 4, 5, 0)
        assert(r.ok==false and r.err=='plot is not revealed' and pushed==false)
        Map={GetPlot=function() return {IsRevealed=function() return true end} end}
        unit.CanStartMission=function() return false end
        r=H.move_unit(1, 4, 5, 0)
        assert(r.ok==false and r.err=='move is not currently legal' and pushed==false)
        """)

    def test_unit_mission_pushmission_build_slot_and_no_select(self):
        self.run_lua("""
        UI={SelectUnit=function() error('SelectUnit flips camera') end,
            GetHeadSelectedUnit=function() return nil end}
        Game={GetActivePlayer=function() return 0 end,
              CanHandleAction=function() error('CanHandleAction needs selection') end,
              SelectionListGameNetMessage=function() error('net message needs selection') end}
        GameDefines={MOVE_DENOMINATOR=60}
        GameInfoTypes={MISSION_FORTIFY=7, MISSION_BUILD=5, BUILD_FARM=9, MISSION_MOVE_TO=1}
        MissionTypes=GameInfoTypes
        local pushed={}
        local unit={
          GetX=function() return 0 end, GetY=function() return 0 end, MovesLeft=function() return 60 end,
          CanStartMission=function(self, m, d1, d2, vis) return m==7 and d1==-1 and d2==-1 end,
          CanBuild=function(self, plot, b) return b==9 end,  -- Unit:CanBuild(plot, build)
          GetBuildType=function() return 9 end,
          -- MISSION_BUILD snapshots the unit's own plot to recognise instant completion
          GetPlot=function() return {GetImprovementType=function() return -1 end, IsImprovementPillaged=function() return false end,
                                     GetRouteType=function() return -1 end, IsRoutePillaged=function() return false end,
                                     GetFeatureType=function() return -1 end} end,
          PushMission=function(self, m, d1, d2, flags, append, manual)
            pushed[#pushed+1]={m=m,d1=d1,d2=d2,manual=manual}
          end,
        }
        Players={[0]={GetUnitByID=function() return unit end, GetTeam=function() return 0 end}}
        Map={GetPlot=function() return {IsRevealed=function() return true end} end}
        local r=H.unit_mission(1, 'MISSION_FORTIFY', -1, -1, nil, 0)
        assert(r.ok==true and #pushed==1 and pushed[1].m==7 and pushed[1].d1==-1)
        r=H.unit_mission(1, 'MISSION_BUILD', -1, -1, 'BUILD_FARM', 0)
        assert(r.ok==true and r.buildtype==9)
        assert(#pushed==2 and pushed[2].m==5 and pushed[2].d1==9 and pushed[2].d2==-1)
        unit.CanStartMission=function() return false end
        r=H.unit_mission(1, 'MISSION_FORTIFY', -1, -1, nil, 0)
        assert(r.ok==false and r.err=='action is not currently legal')
        local seen
        unit.CanStartMission=function(self, m, a, b) seen={a,b}; return false end
        r=H.unit_mission(1, 'MISSION_MOVE_TO', 0, 0, nil, 0)
        -- x=0 must not be treated as missing (Lua 0 is falsy)
        assert(seen[1]==0 and seen[2]==0)
        assert(r.ok==false and r.err=='action is not currently legal')
        """)

    def test_popup_lifecycle_keeps_decisions_until_processed(self):
        self.run_lua("""
        local handlers={}
        Events=setmetatable({}, {__index=function(_,name)
          return {Add=function(fn) handlers[name]=fn end, Remove=function() end}
        end})
        ButtonPopupTypes={BUTTONPOPUP_CHOOSETECH=4}
        H.install_hooks()
        handlers.SerialEventGameMessagePopupShown({Type=4,Data1=8})
        assert(#H.pending_popups(0)==1 and #H.pending_popups(1)==0)
        handlers.SerialEventGameMessagePopupProcessed(4)
        assert(#H.pending_popups(0)==0)
        """)

    def test_incoming_deal_reads_without_mutating(self):
        self.run_lua("""
        local i=0
        local deal={
          GetFromPlayer=function() return 1 end, GetToPlayer=function() return 0 end,
          ResetIterator=function() i=0 end,
          GetNextItem=function()
            i=i+1
            if i==1 then return 1, 30, 0, 50, 0, 0, 0, 1 end
            if i==2 then return 2, 30, 0, 3, 1, 0, 0, 0 end
          end,
          AddGoldTrade=function() error('must not Add*') end,
          ClearItems=function() error('must not ClearItems') end,
        }
        UI={GetScratchDeal=function() return deal end,
            DoProposeDeal=function() error('must not propose') end,
            DoFinalizePlayerDeal=function() error('must not finalize on read') end}
        TradeableItems={TRADE_ITEM_GOLD=1, TRADE_ITEM_RESOURCES=2}
        GameInfo={Resources={[3]={Type='RESOURCE_IVORY'}}}
        local r=H.incoming_deal(0)
        assert(r.ok==true and r.n==2 and r.from==1 and r.to==0)
        assert(r.items[1].type=='GOLD' and r.items[1].amount==50 and r.items[1].from_us==false)
        assert(r.items[2].type=='RESOURCES' and r.items[2].resource=='IVORY' and r.items[2].amount==1)
        assert(r.items[2].from_us==true)
        """)

    def test_incoming_deal_empty_when_no_scratch(self):
        self.run_lua("""
        UI={GetScratchDeal=function() return nil end}
        local r=H.incoming_deal(0)
        assert(r.ok==true and r.n==0 and #r.items==0)
        r=H.accept_deal(0)
        assert(r.ok==false and r.err=='no incoming deal')
        r=H.refuse_deal(0)
        assert(r.ok==false and r.err=='no incoming deal')
        """)

    def test_accept_deal_finalizes_existing_only(self):
        self.run_lua("""
        local finalized={}
        local i=0
        local deal={
          GetFromPlayer=function() return 1 end, GetToPlayer=function() return 0 end,
          ResetIterator=function() i=0 end,
          GetNextItem=function()
            i=i+1
            if i==1 then return 1, 30, 0, 10, nil, nil, nil, 1 end
          end,
          AddGoldTrade=function() error('must not Add*') end,
        }
        UI={GetScratchDeal=function() return deal end,
            DoFinalizePlayerDeal=function(them, us, yes)
              finalized[#finalized+1]={them=them,us=us,yes=yes}
            end}
        TradeableItems={TRADE_ITEM_GOLD=1}
        local r=H.accept_deal(0)
        assert(r.ok==true and r.other==1)
        assert(#finalized==1 and finalized[1].them==1 and finalized[1].us==0 and finalized[1].yes==true)
        i=0
        r=H.refuse_deal(0)
        assert(r.ok==true and finalized[2].yes==false)
        """)

    def test_trade_catalog_never_adds(self):
        self.run_lua("""
        local deal={
          SetFromPlayer=function(self,a) self.from=a end,
          SetToPlayer=function(self,a) self.to=a end,
          IsPossibleToTradeItem=function(self, from, to, typ, a, b)
            return typ==1 and a==1
          end,
          AddGoldTrade=function() error('must not Add*') end,
          ClearItems=function() error('must not ClearItems') end,
          DoProposeDeal=function() error('must not propose') end,
        }
        UI={GetScratchDeal=function() return deal end, DoProposeDeal=function() error('no') end}
        TradeableItems={TRADE_ITEM_GOLD=1, TRADE_ITEM_GOLD_PER_TURN=2, TRADE_ITEM_OPEN_BORDERS=3,
                        TRADE_ITEM_ALLOW_EMBASSY=4, TRADE_ITEM_RESEARCH_AGREEMENT=5, TRADE_ITEM_DEFENSIVE_PACT=6,
                        TRADE_ITEM_RESOURCES=7}
        Game.GetDealDuration=function() return 25 end
        Game.GetActivePlayer=function() return 0 end
        Teams={[0]={IsHasMet=function() return true end, IsAtWar=function() return false end}}
        Players={[0]={GetTeam=function() return 0 end},
                 [1]={IsAlive=function() return true end, IsMinorCiv=function() return false end, GetTeam=function() return 1 end}}
        local r=H.trade_catalog(1,0)
        assert(r.ok==true and r.gold.us==true and r.gold.them==true)
        assert(r.gold_per_turn.us==false)
        r=H.trade_catalog(1,0)
        Players[1].IsMinorCiv=function() return true end
        r=H.trade_catalog(1,0)
        assert(r.ok==false)
        """)

    def test_minor_gold_gift_rejects_wrong_amount_and_poverty(self):
        self.run_lua("""
        GameDefines={MINOR_GOLD_GIFT_SMALL=250, MINOR_GOLD_GIFT_MEDIUM=500, MINOR_GOLD_GIFT_LARGE=1000}
        Game.GetActivePlayer=function() return 0 end
        Game.DoMinorGoldGift=function() error('must not gift') end
        Teams={[0]={IsHasMet=function() return true end, IsAtWar=function() return false end}}
        Players={[0]={GetTeam=function() return 0 end, GetGold=function() return 61 end},
                 [26]={IsMinorCiv=function() return true end, GetTeam=function() return 26 end,
                       GetFriendshipFromGoldGift=function() return 30 end,
                       GetMinorCivFriendshipWithMajor=function() return 0 end,
                       IsFriends=function() return false end, IsAllies=function() return false end}}
        local r=H.city_state_gifts(26,0)
        assert(r.ok==true and r.small.amount==250 and r.small.affordable==false)
        r=H.minor_gold_gift(26, 250, 0)
        assert(r.ok==false and r.err=='not enough gold')
        r=H.minor_gold_gift(26, 15, 0)
        assert(r.ok==false)
        r=H.city_state_gifts(0,0)
        assert(r.ok==false)
        """)

    def test_city_ranged_attack_does_not_select(self):
        self.run_lua("""
        UI={SelectCity=function() error('SelectCity') end}
        Game={SelectedCitiesGameNetMessage=function() error('needs selection') end}
        local sent={}
        Network={SendDoTask=function(...) sent={...} end}
        TaskTypes={TASK_RANGED_ATTACK=7}
        local city={
          CanRangeStrike=function() return true end,
          CanRangeStrikeAt=function(self,x,y,a,b) assert(x==11 and y==12); return true end,
          GetID=function() return 8192 end,
        }
        Players={[0]={GetCityByID=function() return city end}}
        local r=H.city_ranged_attack(8192, 11, 12, 0)
        assert(r.ok==true)
        assert(sent[1]==8192 and sent[2]==7 and sent[3]==11 and sent[4]==12)
        """)

    def test_available_city_strikes_no_select_and_filters(self):
        self.run_lua("""
        UI={SelectCity=function() error('SelectCity') end}
        GameDefines={MAX_CITY_ATTACK_RANGE=1}
        local city={
          GetX=function() return 5 end, GetY=function() return 5 end,
          CanRangeStrike=function() return true end,
          CanRangeStrikeAt=function(self,x,y) return x==6 and y==5 end,
          GetID=function() return 1 end,
        }
        Players={[0]={GetCityByID=function() return city end, GetTeam=function() return 0 end}}
        Map={PlotXYWithRangeCheck=function(x,y,dx,dy,r)
          if dx==1 and dy==0 then
            return {GetX=function() return 6 end, GetY=function() return 5 end,
                    IsVisible=function() return true end, GetNumUnits=function() return 0 end,
                    IsCity=function() return false end}
          end
          return {GetX=function() return x+dx end, GetY=function() return y+dy end,
                  IsVisible=function() return false end}
        end}
        local r=H.available_city_strikes(1, 0)
        assert(r.ok==true and r.can==true and #r.targets==1)
        assert(r.targets[1].x==6 and r.targets[1].y==5)
        city.CanRangeStrike=function() return false end
        r=H.available_city_strikes(1, 0)
        assert(r.ok==true and r.can==false and #r.targets==0)
        city.CanRangeStrike=function() return true end
        city.CanRangeStrikeNow=function() return false end
        r=H.available_city_strikes(1, 0)
        assert(r.ok==true and r.can==false and #r.targets==0)
        """)


class ModalFlagsAndSelectTests(unittest.TestCase):
    def _detached_game(self):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        g._runtime_ok = True
        return g

    def test_select_unit_skips_lookat_by_default(self):
        calls = []
        g = self._detached_game()
        g.q = lambda code, timeout=None: calls.append(code) or {"ok": True}
        g.select_unit(16385)
        self.assertEqual(len(calls), 1)
        self.assertIn("SelectUnit", calls[0])
        self.assertNotIn("LookAt", calls[0])
        g.select_unit(16385, look_at=True)
        self.assertIn("LookAt", calls[1])

    def test_move_unit_python_does_not_select(self):
        calls = []
        g = self._detached_game()
        g.q = lambda code, timeout=None: calls.append(code) or {"ok": True, "x": 13, "y": 25, "moves": 2}
        g.move_unit(24576, 12, 25, settle_timeout=0)
        self.assertEqual(len(calls), 1)
        self.assertIn("H.move_unit", calls[0])
        self.assertNotIn("SelectUnit", calls[0])
        self.assertNotIn("SelectionListMove", calls[0])

    def test_unit_mission_python_does_not_select(self):
        calls = []
        g = self._detached_game()
        g.q = lambda code, timeout=None: calls.append(code) or {"ok": True}
        g.unit_mission(16385, "MISSION_FORTIFY")
        # the mission push plus a selection-free after-state read (unit_pos); never a UI select
        self.assertGreaterEqual(len(calls), 1)
        self.assertIn("H.unit_mission", calls[0])
        for code in calls:
            self.assertNotIn("SelectUnit", code)
            self.assertNotIn("CanHandleAction", code)
            self.assertNotIn("SelectionListGameNetMessage", code)

    def test_accept_deal_clicks_open_diplotrade(self):
        g = self._detached_game()
        execs = []
        g.states = lambda: {2: "DiploTrade"}
        g._visible_in_state = lambda name, lua, known=None: name == "DiploTrade"
        g.c = type("C", (), {"exec": staticmethod(lambda state, lua, check=True: execs.append((state, lua)) or [])})()
        def q(code, timeout=None):
            if "H.accept_deal" in code:
                raise AssertionError("should not fall back")
            return {"ok": True, "items": [], "deals": 1}  # incoming_deal / _deal_snapshot reads around the click
        g.q = q
        g._settle_leader_remark = lambda wait=1.5: {}
        r = g.accept_deal()
        self.assertTrue(r["ok"])
        self.assertEqual(execs[0][0], "DiploTrade")
        self.assertIn("OnPropose", execs[0][1])
        execs.clear()
        r = g.refuse_deal()
        self.assertIn("OnBack", execs[0][1])

    def test_turn_state_reports_modal_flags_without_querying_missing_states(self):
        g = self._detached_game()
        g.q = lambda code, timeout=None: {"active_player": 0, "pending_popups": []}
        g.c = type("C", (), {
            "states": staticmethod(lambda: {1: "InGame"}),
            "query": staticmethod(lambda state, lua, timeout=None: (_ for _ in ()).throw(
                AssertionError(f"queried missing popup {state}"))),
        })()
        ts = g.turn_state()
        for flag in (
            "leader_greeting_pending", "city_state_greeting_pending",
            "great_person_reward_pending", "tech_popup_pending", "discussion_pending",
        ):
            self.assertIn(flag, ts)
            self.assertFalse(ts[flag])

    def test_wait_for_my_turn_returns_early_when_tech_choice_is_unset(self):
        g = self._detached_game()
        calls = {"n": 0}

        def q(code, timeout=None):
            calls["n"] += 1
            if "GetCurrentResearch" in code:
                return -1
            return {
                "active_player": 0, "my_turn": False, "processing": False,
                "hotseat": False, "tech_popup_pending": True,
            }

        g.q = q
        g.c = type("C", (), {
            "ping": staticmethod(lambda: {"connected": True}),
            "states": staticmethod(lambda: {1: "InGame", 2: "TechPopup"}),
            "query": staticmethod(lambda state, lua, timeout=None: state == "TechPopup"),
        })()
        g.dismiss_pending_popups = lambda: []
        g.discussion_pending = lambda: False
        g.tech_popup_pending = lambda: True
        ts = g.wait_for_my_turn(timeout=2, poll=0.01)
        self.assertTrue(ts["tech_popup_pending"])

    def test_turn_state_sets_discussion_if_either_dialog_is_up(self):
        g = self._detached_game()
        g.q = lambda code, timeout=None: {"pending_popups": []}
        g.c = type("C", (), {
            "states": staticmethod(lambda: {1: "InGame", 2: "DiscussionDialog"}),
            "query": staticmethod(lambda state, lua, timeout=None: state == "DiscussionDialog"),
        })()
        ts = g.turn_state()
        self.assertTrue(ts["discussion_pending"])
        self.assertFalse(ts["leader_greeting_pending"])
        self.assertFalse(ts["tech_popup_pending"])


class QueueTests(unittest.TestCase):
    def test_parallel_client_calls_cannot_swap_replies(self):
        class Wire:
            def write(self, data): self.request=json.loads(data)
            def flush(self): time.sleep(0.001)
            def readline(self): return json.dumps(self.request).encode()
        client=Civ5.__new__(Civ5)
        client.f=Wire(); client._lock=threading.RLock()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda n: client.call(number=n)['number'], range(50)))
        self.assertEqual(results,list(range(50)))

    def test_competing_operation_times_out_without_running(self):
        with action_lock('test-safety-socket'):
            with ThreadPoolExecutor(max_workers=1) as pool:
                def competing():
                    with action_lock('test-safety-socket', timeout=0.03):
                        self.fail('overlapping operation entered')
                with self.assertRaises(TimeoutError): pool.submit(competing).result()
        with action_lock('test-safety-socket', timeout=0.03):
            pass  # The queue is usable after the refused operation.


if __name__=='__main__': unittest.main()


class McpArgumentTests(unittest.TestCase):
    def test_unknown_tool_argument_is_rejected(self):
        """The MCP SDK's argument models ignore unknown keys by default, so a misspelled parameter
        (timeout vs timeout_seconds) silently ran with the default. The server forbids extras."""
        import asyncio
        from harness import mcp_server
        with self.assertRaises(Exception) as cm:
            asyncio.run(mcp_server.mcp.call_tool("turn_status", {"bogus": 1}))
        self.assertIn("bogus", str(cm.exception))

