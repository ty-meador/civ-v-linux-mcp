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
        assert(#result==1 and result[1].owner==nil and result[1].city==nil and result[1].units==nil)
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
