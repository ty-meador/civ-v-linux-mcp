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

    def test_a_player_without_the_list_is_refused_not_crashed(self):
        self.run_lua("""
        Players[0] = {}
        local r = H.notification_log(0)
        assert(r.ok == false and r.err:find('notification'), r.err)
        """)


if __name__ == "__main__":
    unittest.main()
