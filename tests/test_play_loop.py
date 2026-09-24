"""scripts/play_loop.py against a fake Game: the turn counter, the Worker cap, and idle Workers.

Live t253 (2026-09-24) the loop ended a turn, looked at the counter half a second later while the
AIs were still moving, backed off into the next wait, and came back on t254 with no memory of
t253: neither logged nor counted, so --max-turns 8 would have played nine. The same run showed
UNIT_WORKER at the head of the production fallback breeding a spare Worker in Goshute every few
turns, each one spawning on the Worker already in the city.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("play_loop", ROOT / "scripts" / "play_loop.py")
play_loop = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(play_loop)


class FakeGame:
    """Enough of harness.game.Game for the loop's happy path. Like the real one, end_turn returns
    before the counter moves (the AIs are still playing) and wait_for_my_turn blocks until the
    next turn is on the table -- so the counter is only ever seen to advance from inside a wait."""

    def __init__(self, first_turn: int = 250, units=None, cities=None):
        self.turn = first_turn
        self._turn_pending = False
        self.end_turn_calls = 0
        self.orders: list[tuple] = []
        self._units = units or []
        self._cities = cities or []

    def wait_for_my_turn(self, timeout=None):
        if self._turn_pending:
            self.turn += 1
            self._turn_pending = False
        return {"turn": self.turn, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "game_over": False}

    def turn_state(self):
        # what the old loop polled half a second after end_turn: still the old turn
        return {"turn": self.turn}

    def end_turn(self):
        self.end_turn_calls += 1
        self._turn_pending = True
        return {"ok": True}

    def cities(self, seat):
        return self._cities

    def units(self, seat):
        return self._units

    def set_production(self, city_id, order, item, seat):
        self.orders.append((city_id, order, item))
        return {"ok": True}

    def unit_mission(self, unit_id, mission, pid=None, **kw):
        self.orders.append((unit_id, mission))
        return {"ok": True, "automated": mission.startswith("AUTOMATE_")}


def _run(argv, game):
    with mock.patch.object(play_loop, "Game", return_value=game), \
            mock.patch.object(play_loop.time, "sleep"), \
            mock.patch.object(sys, "argv", ["play_loop", *argv]):
        return play_loop.main()


class TurnCountTest(unittest.TestCase):
    def test_counts_every_turn_the_engine_advances_during_the_wait(self):
        g = FakeGame(first_turn=253)
        with mock.patch.object(play_loop, "log") as log:
            rc = _run(["--max-turns", "3"], g)
        self.assertEqual(rc, 0)
        self.assertEqual(g.end_turn_calls, 3)
        self.assertEqual(g.turn, 256)
        ended = [c.args[0] for c in log.call_args_list if c.args[0].startswith("ended turn")]
        self.assertEqual(ended, ["ended turn 253 (played 1 this session)",
                                 "ended turn 254 (played 2 this session)",
                                 "ended turn 255 (played 3 this session)"])

    def test_a_turn_that_did_not_end_is_not_counted_twice(self):
        g = FakeGame(first_turn=40)
        real_wait = g.wait_for_my_turn
        calls = {"n": 0}

        def wait(timeout=None):
            calls["n"] += 1
            if calls["n"] == 2:
                # end_turn was accepted but the engine kept the turn (a blocker appeared)
                g._turn_pending = False
                return {"turn": 40, "blocking_name": "ENDTURN_BLOCKING_UNITS", "game_over": False}
            return real_wait(timeout)

        g.wait_for_my_turn = wait
        with mock.patch.object(play_loop, "log") as log:
            rc = _run(["--max-turns", "2"], g)
        self.assertEqual(rc, 0)
        ended = [c.args[0] for c in log.call_args_list if c.args[0].startswith("ended turn")]
        self.assertEqual(ended, ["ended turn 40 (played 1 this session)",
                                 "ended turn 41 (played 2 this session)"])


class HotseatRotationTest(unittest.TestCase):
    """--seats 0 1: every seat is ours. The loop re-points the Game at the next seat before each
    wait, the engine's turn counter only moves once the last seat has ended the turn, and a turn is
    still counted exactly once (two-human hotseat, 2026-09-24)."""

    def test_two_seats_alternate_and_a_turn_counts_once_per_rotation(self):
        g = FakeGame(first_turn=214)
        seen: list[tuple[int, int]] = []   # (seat, turn) at every wait
        real_wait = g.wait_for_my_turn
        ends = {"n": 0}

        def wait(timeout=None):
            # the counter moves only after BOTH seats ended the turn
            if g._turn_pending and ends["n"] % 2 == 1:
                g._turn_pending = False
            ts = real_wait(timeout)
            seen.append((g.seat, ts["turn"]))
            return ts

        real_end = g.end_turn

        def end_turn():
            ends["n"] += 1
            return real_end()

        g.wait_for_my_turn = wait
        g.end_turn = end_turn
        with mock.patch.object(play_loop, "log") as log:
            rc = _run(["--seats", "0", "1", "--max-turns", "2"], g)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [(0, 214), (1, 214), (0, 215), (1, 215), (0, 216)])
        self.assertEqual(g.end_turn_calls, 4)
        ended = [c.args[0] for c in log.call_args_list if c.args[0].startswith("ended turn")]
        self.assertEqual(ended, ["ended turn 214 (played 1 this session)",
                                 "ended turn 215 (played 2 this session)"])


def _unit(uid, utype, **kw):
    u = {"id": uid, "type": utype, "moves": 2, "fortified": False, "automated": False, "mission": -1}
    u.update(kw)
    return u


class ProductionFallbackTest(unittest.TestCase):
    def test_no_more_workers_than_cities(self):
        cities = [{"id": 1, "name": "Goshute", "queue_len": 0}, {"id": 2, "name": "Te-Moak", "queue_len": 0}]
        g = FakeGame(units=[_unit(1, "WORKER"), _unit(2, "WORKER")], cities=cities)
        play_loop.ensure_production(g, 0)
        self.assertEqual([o[2] for o in g.orders], ["BUILDING_MONUMENT", "BUILDING_MONUMENT"])

    def test_a_worker_when_short(self):
        cities = [{"id": 1, "name": "Goshute", "queue_len": 0}]
        g = FakeGame(units=[], cities=cities)
        play_loop.ensure_production(g, 0)
        self.assertEqual([o[2] for o in g.orders], ["UNIT_WORKER"])


class IdleWorkerTest(unittest.TestCase):
    def test_idle_worker_is_automated_not_skipped(self):
        g = FakeGame(units=[_unit(7, "WORKER"), _unit(8, "MUSKETMAN")])
        play_loop.resolve_units_need_orders(g, 0)
        self.assertEqual(g.orders, [(7, "AUTOMATE_BUILD"), (8, "MISSION_SKIP")])

    def test_working_worker_is_left_alone(self):
        g = FakeGame(units=[_unit(7, "WORKER", build="BUILD_FARM")])
        play_loop.resolve_units_need_orders(g, 0)
        self.assertEqual(g.orders, [(7, "MISSION_SKIP")])

    def test_refused_automation_falls_back_to_skip(self):
        g = FakeGame(units=[_unit(7, "WORK_BOAT")])
        g.unit_mission = lambda uid, m, pid=None, **kw: (g.orders.append((uid, m)) or {"ok": False, "err": "nope"})
        play_loop.resolve_units_need_orders(g, 0)
        self.assertEqual(g.orders, [(7, "AUTOMATE_BUILD"), (7, "MISSION_SKIP")])


if __name__ == "__main__":
    unittest.main()
