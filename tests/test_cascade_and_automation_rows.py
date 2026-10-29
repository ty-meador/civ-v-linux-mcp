"""An alliance cascade is one row (GitLab #82); automation that ended is a digest line (GitLab #77)."""
import unittest

import test_mcp_safety as support
from harness.game_parts.events import group_alliance_cascade


def note(turn, seq, text):
    return {"kind": "notification", "turn": turn, "seq": seq, "audience": 0, "data": {"summary": text, "text": text}}


class AllianceCascadeTests(unittest.TestCase):
    def test_ten_notices_become_one_row_with_the_delegate_count(self):
        events = [note(251, 1, "No longer Ally of Ormus!"), note(251, 2, "Siam now Ally of Ormus!"),
                  note(251, 3, "No longer Ally of Monaco!"), note(251, 4, "Siam now Ally of Monaco!"),
                  note(251, 5, "Ormus has declared war on The Zulus!"), note(251, 6, "Monaco has declared war on The Zulus!"),
                  note(251, 7, "You have discovered Trapping!")]
        out = group_alliance_cascade(events)
        kinds = [e["kind"] for e in out]
        self.assertEqual(kinds.count("city_state_allies"), 1)
        self.assertEqual(kinds.count("notification"), 1, "the unrelated notice stays")
        row = next(e for e in out if e["kind"] == "city_state_allies")["data"]
        self.assertEqual(row["lost"], ["Ormus", "Monaco"])
        self.assertEqual(row["others_gained"], {"Siam": ["Ormus", "Monaco"]})
        self.assertEqual(row["delegates_change"], -4)
        self.assertEqual(len(row["wars_declared"]), 2)
        self.assertIn("lost 2 city-state allies (Ormus, Monaco)", row["summary"])
        self.assertIn("-4 World Congress delegates", row["summary"])

    def test_a_single_notice_is_left_alone(self):
        events = [note(240, 1, "Now Ally of Belgrade!"), note(240, 2, "You have discovered Trapping!")]
        self.assertEqual(group_alliance_cascade(events), events)


class AutomationEndedLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_worker_that_left_automation_is_a_row(self):
        self.run_lua("""
        GameInfo = GameInfo or {}
        GameInfo.Units = { [4] = { Type = 'UNIT_WORKER' } }
        AUTO = { [106504] = true, [507929] = true }
        local function mk(id)
          return { GetID = function() return id end, GetUnitType = function() return 4 end, GetX = function() return 12 end,
                   GetY = function() return 26 end, IsAutomated = function() return AUTO[id] end, IsDelayedDeath = function() return false end }
        end
        local units = { mk(106504), mk(507929) }
        Players = { [0] = { Units = function() local i = 0; return function() i = i + 1; return units[i] end end } }
        RECORDED = {}
        H.record = function(kind, data, audience) RECORDED[#RECORDED + 1] = { kind = kind, data = data } end
        H.note_units(0)
        assert(H.roster[0][106504].automated == true)
        AUTO[106504] = false
        H.automation_compare(0)
        assert(#RECORDED == 1 and RECORDED[1].kind == 'automation_ended' and RECORDED[1].data.unit == 106504, H.json(RECORDED))
        assert(RECORDED[1].data.reason:find('nothing left to build', 1, true), RECORDED[1].data.reason)
        H.note_units(0)
        H.automation_compare(0)
        assert(#RECORDED == 1, 'reported once')
        """)


if __name__ == "__main__":
    unittest.main()
