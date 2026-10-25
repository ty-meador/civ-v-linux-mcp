"""The Notification Log holds what the panel has already dropped.

`notifications()` returns only undismissed entries -- what the panel is currently showing -- so a
notification read once and dismissed had nowhere to be read again, even though the gamecore still
held it (live t233: 3 live, 99 held). The stock log lists them all, newest first, dismissed ones
included; that is the entire point of the screen.
"""
import unittest

import test_mcp_safety as support

WORLD = """
local rows = {}
for i = 0, 4 do
  rows[i] = { turn = 100 + i, summary = 'S' .. i, text = 'Text ' .. i, dismissed = i < 3 }
end
Players = { [0] = {
  GetNumNotifications = function() return 5 end,
  GetNotificationTurn = function(_, i) return rows[i].turn end,
  GetNotificationSummaryStr = function(_, i) return rows[i].summary end,
  GetNotificationStr = function(_, i) return rows[i].text end,
  GetNotificationDismissed = function(_, i) return rows[i].dismissed end,
} }
"""


class NotificationLogTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_newest_first_and_dismissed_included(self):
        self.run_lua("""
        local r = H.notification_log(0)
        assert(r.ok and r.held == 5 and r.shown == 5)
        assert(r.notifications[1].turn == 104 and r.notifications[5].turn == 100, 'newest first')
        assert(r.notifications[1].dismissed == false and r.notifications[5].dismissed == true)
        assert(r.notifications[1].text == 'Text 4' and r.notifications[1].summary == 'S4')
        """)

    def test_dismissed_can_be_filtered_out_and_counted(self):
        self.run_lua("""
        local r = H.notification_log(0, 40, false)
        assert(r.shown == 2 and r.dismissed_skipped == 3, r.shown .. '/' .. tostring(r.dismissed_skipped))
        for _, e in ipairs(r.notifications) do assert(e.dismissed == false) end
        """)

    def test_the_limit_takes_the_newest(self):
        self.run_lua("""
        local r = H.notification_log(0, 2)
        assert(r.shown == 2 and r.held == 5)
        assert(r.notifications[1].turn == 104 and r.notifications[2].turn == 103)
        """)

    def test_a_summary_equal_to_the_text_is_not_repeated(self):
        self.run_lua("""
        Players[0].GetNotificationSummaryStr = function(_, i) return 'Text ' .. i end
        local r = H.notification_log(0, 1)
        assert(r.notifications[1].summary == nil and r.notifications[1].text == 'Text 4')
        """)

    def test_a_great_person_notice_names_the_person_and_whether_it_is_still_mine(self):
        """Live Assyria t238: two "Great Person born" notices, no new Great Person in units(): both were spent the
        same turn. The hook's row carries the unit type in d1 (148 UNIT_MUSICIAN, 4 UNIT_SCIENTIST) and the
        engine's GetNotificationIndex(i) is that row's id, so the log can say who was born and that it is gone."""
        self.run_lua("""
        NotificationTypes = { NOTIFICATION_GREAT_PERSON_ACTIVE_PLAYER = -2083717098, NOTIFICATION_CITY_GROWTH = 7 }
        GameInfo = { Units = { [148] = { Type = 'UNIT_MUSICIAN' }, [4] = { Type = 'UNIT_SCIENTIST' } } }
        local scientist = { GetUnitType = function() return 4 end, IsDelayedDeath = function() return false end,
                            GetGameTurnCreated = function() return 103 end, GetID = function() return 777 end,  -- born on notice 3's turn
                            GetX = function() return 19 end, GetY = function() return 29 end }
        local units = { scientist }
        local p = Players[0]
        p.Units = function() local i = 0; return function() i = i + 1; return units[i] end end
        p.GetUnitByID = function(_, id) for _, u in ipairs(units) do if u:GetID() == id then return u end end end
        p.GetNotificationIndex = function(_, i) return 860 + i end
        -- notice 4 (id 864): a Musician the hook located as unit 555, spent since; notice 3 (id 863): a Scientist still here;
        -- notice 2 (id 862): a Musician row recorded by an older runtime, no type read at hook time.
        H.events = {
          { kind = 'notification', data = { id = 864, ntype = -2083717098, d1 = 148, d2 = -1, player = 0, unit = 'MUSICIAN', unit_id = 555, x = 1, y = 1 } },
          { kind = 'notification', data = { id = 863, ntype = -2083717098, d1 = 4, d2 = -1, player = 0 } },
          { kind = 'notification', data = { id = 862, ntype = -2083717098, d1 = 148, d2 = -1, player = 0 } },
          { kind = 'notification', data = { id = 861, ntype = 7, d1 = 8192, player = 0, x = 3, y = 4, city_id = 8192 } },
          { kind = 'notification', data = { id = 863, ntype = -2083717098, d1 = 4, player = 1 } },  -- another seat's: never joined
        }
        local r = H.notification_log(0)
        local by_i = {}; for _, e in ipairs(r.notifications) do by_i[e.i] = e end
        local spent, here, old, grown, none = by_i[4], by_i[3], by_i[2], by_i[1], by_i[0]
        assert(spent.unit == 'MUSICIAN' and spent.unit_gone == true and spent.of_type_now == 0 and spent.unit_id == 555 and spent.x == 1, 'born as 555 at (1,1), gone now: ' .. H.json(spent))
        assert(here.unit == 'SCIENTIST' and here.unit_id == 777 and here.x == 19 and here.y == 29 and here.unit_gone == nil, H.json(here))
        assert(old.unit == 'MUSICIAN' and old.of_type_now == 0 and old.unit_gone == nil, H.json(old))
        assert(grown.city_id == 8192 and grown.x == 3 and grown.unit == nil, H.json(grown))
        assert(none.unit == nil and none.unit_id == nil, H.json(none))
        """)

    def test_the_hook_attaches_the_great_person_born_this_turn(self):
        self.run_lua("""
        NotificationTypes = { NOTIFICATION_GREAT_PERSON_ACTIVE_PLAYER = -2083717098 }
        GameInfo = { Units = { [4] = { Type = 'UNIT_SCIENTIST' } } }
        Game.GetGameTurn = function() return 238 end
        local function sci(id, created) return { GetUnitType = function() return 4 end, IsDelayedDeath = function() return false end,
          GetGameTurnCreated = function() return created end, GetID = function() return id end,
          GetX = function() return id end, GetY = function() return 2 end } end
        local units = { sci(10, 200), sci(12, 238), sci(11, 238) }
        Players[0].Units = function() local i = 0; return function() i = i + 1; return units[i] end end
        local d = { player = 0, ntype = -2083717098, d1 = 4, d2 = -1, summary = 'Great Person born',
                    text = 'A Great Person has been born in your civilization!' }
        H.locate_notification(d)
        assert(d.unit == 'SCIENTIST' and d.unit_id == 12 and d.x == 12 and d.y == 2, 'the newest one born this turn: ' .. H.json(d))
        local gone = { player = 0, ntype = -2083717098, d1 = 4, d2 = -1 }
        units = { sci(10, 200) }
        H.locate_notification(gone)
        assert(gone.unit == 'SCIENTIST' and gone.unit_id == nil and gone.of_type_now == 1, H.json(gone))
        local other = { player = 0, ntype = 5, d1 = 4 }
        H.locate_notification(other)
        assert(other.unit == nil, 'another type is not a great person')
        """)

    def test_a_player_without_the_list_is_refused_not_crashed(self):
        self.run_lua("""
        Players[0] = {}
        local r = H.notification_log(0)
        assert(r.ok == false and r.err:find('notification'), r.err)
        """)


if __name__ == "__main__":
    unittest.main()
