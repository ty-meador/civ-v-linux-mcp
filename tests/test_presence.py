"""Status names the other MCP servers of this seat and a server running older code than main (GitLab #61)."""
import os
import subprocess
import time
import unittest
from unittest import mock

from harness import presence
from harness.mcp_tools import turn as T

SOCK = "/tmp/civ5-test-presence.sock"


class PresenceFileTests(unittest.TestCase):
    def setUp(self):
        presence.presence_path(SOCK, 0).unlink(missing_ok=True)
        self.other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(self.other.kill)

    def test_another_live_server_is_listed_and_a_dead_one_dropped(self):
        t0 = 1_000.0
        presence.touch(SOCK, 0, client="grok/1.0.70", pid=self.other.pid, now=t0, stamp=5.0)
        presence.touch(SOCK, 0, client="old", pid=2_000_000_000, now=t0, stamp=5.0)     # no such process
        rows = presence.touch(SOCK, 0, client="claude-code/2.1", now=t0 + 40, stamp=9.0)
        self.assertEqual(set(rows), {str(self.other.pid), str(os.getpid())}, "the dead pid's row is gone")
        other = presence.others(SOCK, 0, now=t0 + 100, disk_stamp=9.0)
        self.assertEqual(other, [{"pid": self.other.pid, "client": "grok/1.0.70", "attached_for_s": 100,
                                  "last_call_s": 100, "code_behind": True}])
        self.assertEqual(presence.others(SOCK, 0, pid=self.other.pid, now=t0 + 100, disk_stamp=9.0)[0]["pid"], os.getpid())

    def test_outdated_names_the_files_written_after_import(self):
        self.assertIsNone(presence.outdated(stamp_at_import=time.time() + 10), "nothing newer than the import")
        stale = presence.outdated(stamp_at_import=0.0)
        self.assertGreater(stale["files_changed"], 0)
        self.assertTrue(stale["newest"].endswith(".py"))
        self.assertIn("/mcp reconnect", stale["note"])

    def test_status_rows(self):
        presence.touch(SOCK, 0, client="grok/1.0.70", pid=self.other.pid, now=1_000.0, stamp=5.0)
        with mock.patch.object(presence, "outdated", return_value={"files_changed": 3, "newest": "x.py", "note": "n"}):
            ts = T._client_notes({"turn": 7}, 0, sock=SOCK, now=1_100.0)
        self.assertEqual(ts["other_clients"][0]["pid"], self.other.pid)
        self.assertIn("1 other MCP server(s) of seat 0", ts["other_clients_note"])
        self.assertEqual(ts["server_outdated"]["files_changed"], 3)
        self.other.kill(); self.other.wait()
        with mock.patch.object(presence, "outdated", return_value=None):
            quiet = T._client_notes({"turn": 7}, 0, sock=SOCK, now=1_100.0)
        self.assertEqual(quiet, {"turn": 7}, "nothing to say, nothing said")


if __name__ == "__main__":
    unittest.main()
