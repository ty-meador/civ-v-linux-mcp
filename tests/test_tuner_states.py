"""TunerClient.refresh_states over a socket pair: the LSQ reply is the handshake frame, not whatever frame
arrives first, and an empty list in a game that had states is asked again before it is believed.

Live 2026-09-27 (Codex, t58): one finish_turn failed with "no Lua state named 'InGame'; have []" in a game
that had 48 states before and after.
"""
import socket
import unittest

from harness.tuner import HEADER, TAG_COMMAND, TAG_HANDSHAKE, TAG_OUTPUT, TunerClient, TunerError


def frame(tag: int, payload: str) -> bytes:
    data = payload.encode() + b"\x00"
    return HEADER.pack(len(data), tag) + data


STATES = "1\x00Main State\x005\x00InGame\x00"


class RefreshStatesTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.b.settimeout(1.0)
        self.c = TunerClient(sock=self.a, timeout=1.0)

    def tearDown(self):
        self.a.close()
        self.b.close()

    def requests(self) -> list[str]:
        out = []
        buf = b""
        self.b.settimeout(0.2)
        try:
            while True:
                chunk = self.b.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        while len(buf) >= HEADER.size:
            ln, _tag = HEADER.unpack_from(buf)
            out.append(buf[HEADER.size:HEADER.size + ln].rstrip(b"\x00").decode())
            buf = buf[HEADER.size + ln:]
        return out

    def test_a_late_output_frame_before_the_reply_is_not_the_list(self):
        self.b.sendall(frame(TAG_OUTPUT, "O\x00InGame: late print") + frame(TAG_HANDSHAKE, STATES))
        st = self.c.refresh_states()
        self.assertEqual(st, {1: "Main State", 5: "InGame"})
        self.assertEqual(self.c.find_state("InGame", refresh=False), 5)

    def answer_each_request(self, replies: list[bytes]) -> list[str]:
        """Reply to the client's requests one at a time (the game answers an LSQ only when asked)."""
        seen: list[str] = []

        def run():
            buf = b""
            for reply in replies:
                while True:
                    if len(buf) >= HEADER.size:
                        ln, _tag = HEADER.unpack_from(buf)
                        if len(buf) >= HEADER.size + ln:
                            seen.append(buf[HEADER.size:HEADER.size + ln].rstrip(b"\x00").decode())
                            buf = buf[HEADER.size + ln:]
                            break
                    chunk = self.b.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                self.b.sendall(reply)

        import threading
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.addCleanup(t.join, 2.0)
        return seen

    def test_an_empty_list_after_a_full_one_is_asked_again(self):
        self.c.states = {1: "Main State", 5: "InGame"}
        seen = self.answer_each_request([frame(TAG_HANDSHAKE, ""), frame(TAG_HANDSHAKE, STATES)])
        st = self.c.refresh_states()
        self.assertEqual(st, {1: "Main State", 5: "InGame"})
        self.assertEqual(seen, ["LSQ:", "LSQ:"], "asked twice, no more")

    def test_two_empty_answers_are_believed(self):
        self.c.states = {5: "InGame"}
        seen = self.answer_each_request([frame(TAG_HANDSHAKE, ""), frame(TAG_HANDSHAKE, "")])
        self.assertEqual(self.c.refresh_states(), {})
        self.assertEqual(seen, ["LSQ:", "LSQ:"])

    def test_an_empty_list_from_the_start_is_an_answer(self):
        # the front end is still loading: the connect loop in tunerd retries this one itself
        self.b.sendall(frame(TAG_HANDSHAKE, ""))
        self.assertEqual(self.c.refresh_states(), {})
        self.assertEqual(self.requests(), ["LSQ:"])

    def test_a_command_ack_is_skipped_too(self):
        self.b.sendall(frame(TAG_COMMAND, "") + frame(TAG_HANDSHAKE, STATES))
        self.assertEqual(self.c.refresh_states(), {1: "Main State", 5: "InGame"})


class CachedStateIdTests(RefreshStatesTests):
    """execute/query by name use the cached state list (one LSQ per connection, not one per command) and
    recover from a stale id or a lost helper with exactly one refresh or reinstall."""

    ACK = frame(TAG_COMMAND, "")

    def out(self, text: str) -> bytes:
        return frame(TAG_OUTPUT, "O\x00InGame: " + text)

    def test_two_commands_by_name_fetch_the_list_once(self):
        seen = self.answer_each_request([frame(TAG_HANDSHAKE, STATES), self.out("a") + self.ACK, self.out("b") + self.ACK])
        self.assertEqual(self.c.execute("InGame", "print('a')").output, ["a"])
        self.assertEqual(self.c.execute("InGame", "print('b')").output, ["b"])
        self.assertEqual(seen, ["LSQ:", "CMD:5:print('a')", "CMD:5:print('b')"])

    def test_a_stale_id_is_refreshed_and_the_command_sent_again_once(self):
        self.c.states = {1: "Main State", 5: "InGame"}
        new = "1\x00Main State\x009\x00InGame\x00"
        seen = self.answer_each_request([frame(TAG_COMMAND, "ERR:Invalid Lua State"), frame(TAG_HANDSHAKE, new),
                                         self.out("ok") + self.ACK])
        self.assertEqual(self.c.execute("InGame", "print('ok')").output, ["ok"])
        self.assertEqual(seen, ["CMD:5:print('ok')", "LSQ:", "CMD:9:print('ok')"])
        self.assertEqual(self.c.states, {1: "Main State", 9: "InGame"})

    def test_a_stale_int_id_is_the_callers_error(self):
        self.c.states = {5: "InGame"}
        self.answer_each_request([frame(TAG_COMMAND, "ERR:Invalid Lua State")])
        from harness.tuner import LuaError
        with self.assertRaises(LuaError):
            self.c.execute(7, "print(1)")

    def test_the_helper_is_installed_once_per_state(self):
        self.c.states = {5: "InGame"}
        seen = self.answer_each_request([self.ACK, self.out("@@HJ@@1") + self.ACK, self.out("@@HJ@@2") + self.ACK])
        self.assertEqual(self.c.query("InGame", "return 1"), 1)
        self.assertEqual(self.c.query("InGame", "return 2"), 2)
        self.assertEqual(len(seen), 3)
        self.assertIn("__hjson", seen[0])
        self.assertTrue(seen[1].startswith("CMD:5:local __f") and seen[2].startswith("CMD:5:local __f"))

    def test_a_lost_helper_is_reinstalled_and_the_query_run_again(self):
        self.c.states = {5: "InGame"}
        self.c._helpers_in.add(5)
        seen = self.answer_each_request([frame(TAG_COMMAND, "ERR:attempt to call global '__hjson' (a nil value)"),
                                         self.ACK, self.out("@@HJ@@3") + self.ACK])
        self.assertEqual(self.c.query("InGame", "return 3"), 3)
        self.assertEqual(len(seen), 3)
        self.assertIn("__hjson", seen[1])

    def test_a_new_connection_forgets_the_helpers(self):
        self.c._helpers_in.add(5)
        import socket as s
        srv = s.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        try:
            self.c.host, self.c.port = srv.getsockname()
            self.c.connect()
            self.assertEqual(self.c._helpers_in, set())
        finally:
            srv.close()
            self.c.close()


if __name__ == "__main__":
    unittest.main()


class TimeoutResyncTests(RefreshStatesTests):
    """A command that timed out is still finished by the game: its print lines and ack arrive later. The next
    command reads past them first, so every reply stays its own command's (not one behind, where a query would
    answer the previous question's JSON); an ack that never comes gives the connection up instead."""

    ACK = frame(TAG_COMMAND, "")

    def out(self, text: str) -> bytes:
        return frame(TAG_OUTPUT, "O\x00InGame: " + text)

    def timed_out(self, lua: str) -> None:
        """A command the game does not answer in time (nothing is read from the game side yet)."""
        self.c.states = {1: "Main State", 5: "InGame"}
        with self.assertRaises(TunerError):
            self.c.execute(5, lua, timeout=0.2)
        self.assertEqual(self.c._owed_acks, 1)

    def test_a_late_reply_is_read_past_before_the_next_command(self):
        self.timed_out("print('a')")
        # The game gets to the old command late and answers it; only then is the next one sent.
        seen = self.answer_each_request([self.out("a") + self.ACK, self.out("b") + self.ACK])
        self.assertEqual(self.c.execute(5, "print('b')").output, ["b"], "its own output, not the old one")
        self.assertEqual(seen, ["CMD:5:print('a')", "CMD:5:print('b')"])
        self.assertEqual(self.c._owed_acks, 0)

    def test_an_idle_drain_takes_the_late_ack(self):
        self.timed_out("print('a')")
        self.b.sendall(self.out("a") + self.ACK)
        self.assertEqual([m.tag for m in self.c.drain(0.1)], [TAG_OUTPUT, TAG_COMMAND])
        self.assertEqual(self.c._owed_acks, 0, "the pump between requests put the stream in step")
        seen = self.answer_each_request([b"", self.out("c") + self.ACK])   # the old request was answered above
        self.assertEqual(self.c.execute(5, "print('c')").output, ["c"])
        self.assertEqual(seen, ["CMD:5:print('a')", "CMD:5:print('c')"])

    def test_an_ack_that_never_comes_gives_the_connection_up(self):
        self.c.RESYNC_GRACE = 0.2
        self.timed_out("print('a')")
        with self.assertRaises(ConnectionError):
            self.c.execute(5, "print('b')")
        self.assertEqual(self.requests(), ["CMD:5:print('a')"], "the second command was never sent on a stream out of step")

    def test_the_state_list_waits_for_the_late_ack_too(self):
        self.timed_out("print('a')")
        self.answer_each_request([self.out("a") + self.ACK, frame(TAG_HANDSHAKE, STATES)])
        self.assertEqual(self.c.refresh_states(), {1: "Main State", 5: "InGame"})
        self.assertEqual(self.c._owed_acks, 0)
