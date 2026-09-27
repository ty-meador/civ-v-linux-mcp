"""TunerClient.refresh_states over a socket pair: the LSQ reply is the handshake frame, not whatever frame
arrives first, and an empty list in a game that had states is asked again before it is believed.

Live 2026-09-27 (Codex, t58): one finish_turn failed with "no Lua state named 'InGame'; have []" in a game
that had 48 states before and after.
"""
import socket
import unittest

from harness.tuner import HEADER, TAG_COMMAND, TAG_HANDSHAKE, TAG_OUTPUT, TunerClient


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


if __name__ == "__main__":
    unittest.main()
