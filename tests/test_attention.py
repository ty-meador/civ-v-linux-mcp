"""Where a call's attention was (harness/attention.py, harness/hexgrid.py): the plots a reply described, the plots
the arguments named, the ids named, and how the ledger row carries them (docs/VISUALIZATION.md)."""
from __future__ import annotations

import json
import unittest

from harness import attention as A
from harness import call_ledger as L
from harness import hexgrid


class HexGridTests(unittest.TestCase):
    def test_distance_odd_r(self):
        # odd rows sit half a hex east: (0,0)'s neighbours are (1,0), (-1,0), (0,1), (-1,1), (0,-1), (-1,-1)
        for nx, ny in ((1, 0), (-1, 0), (0, 1), (-1, 1), (0, -1), (-1, -1)):
            self.assertEqual(hexgrid.distance(0, 0, nx, ny), 1, (nx, ny))
        self.assertEqual(hexgrid.distance(0, 0, 1, 1), 2)      # NE-E, two steps from an even row
        for nx, ny in ((2, 1), (0, 1), (1, 2), (2, 2), (1, 0), (2, 0)):
            self.assertEqual(hexgrid.distance(1, 1, nx, ny), 1, (nx, ny))   # from an odd row

    def test_wrap(self):
        self.assertEqual(hexgrid.distance(0, 3, 7, 3, width=8), 1)
        self.assertEqual(hexgrid.distance(0, 3, 7, 3), 7)

    def test_disk_sizes(self):
        self.assertEqual(len(hexgrid.disk(5, 5, 0)), 1)
        self.assertEqual(len(hexgrid.disk(5, 5, 1)), 7)
        self.assertEqual(len(hexgrid.disk(5, 5, 2)), 19)
        self.assertEqual(len(hexgrid.disk(5, 4, 3)), 37)
        self.assertEqual(hexgrid.disk(5, 5, 2)[0], [5, 5])
        self.assertEqual(len({tuple(p) for p in hexgrid.disk(5, 5, 2)}), 19)


class SeenTests(unittest.TestCase):
    def test_generic_walk_finds_nested_xy(self):
        reply = {"ok": True, "plots": [{"x": 1, "y": 2, "t": "G"}, {"x": 1, "y": 2}], "city": {"x": 3, "y": 4},
                 "deep": {"list": [{"inner": {"x": 5, "y": 6}}]}, "no": {"x": "a", "y": 2}, "b": {"x": True, "y": 1}}
        self.assertEqual(sorted(A.seen_plots("city_screen", {}, reply)), [[1, 2], [3, 4], [5, 6]])

    def test_refusals_and_non_dicts_see_nothing(self):
        self.assertEqual(A.seen_plots("units", {}, {"ok": False, "x": 1, "y": 1}), [])
        self.assertEqual(A.seen_plots("units", {}, "text"), [])
        self.assertEqual(A.seen_plots("units", {}, [{"x": 1, "y": 1}, {"x": 1, "y": 1}]), [[1, 1]])   # a bare list (live t266)

    def test_tactical_view_lights_the_disk_around_the_unit(self):
        reply = {"ok": True, "unit": {"id": 7, "x": 10, "y": 10}, "neighbors": [{"x": 11, "y": 10}],
                 "units": [{"x": 30, "y": 30}]}
        seen = A.seen_plots("tactical_view", {"unit_id": 7}, reply)
        self.assertEqual(len(seen), 19 + 1)                      # radius-2 disk plus the far unit it listed
        self.assertEqual(seen[0], [10, 10])
        self.assertIn([30, 30], seen)
        r3 = A.seen_plots("tactical_view", {"unit_id": 7, "radius": 3}, reply)
        self.assertEqual(len(r3), 37 + 1)

    def test_map_window_uses_its_arguments(self):
        seen = A.seen_plots("map_window", {"x": 4, "y": 4, "radius": 1}, {"ok": True, "plots": []})
        self.assertEqual(len(seen), 7)
        self.assertEqual(seen[0], [4, 4])

    def test_disk_is_not_wrapped_or_clipped(self):
        seen = A.seen_plots("map_window", {"x": 0, "y": 0, "radius": 1}, {"ok": True})
        self.assertIn([-1, 0], seen)
        self.assertIn([0, -1], seen)

    def test_revealed_map_reads_the_vis_grid_by_window(self):
        reply = {"ok": True, "w": 8, "h": 4, "window": {"x0": 2, "y0": 1, "x1": 4, "y1": 2},
                 "layers": {"vis": ["# ~", "  #"], "terrain": ["G P", "  C"]}}
        seen = A.seen_plots("revealed_map", {}, reply)
        # rows[0] is y = y1 = 2: x = 2 ('#'), x = 4 ('~'); rows[1] is y = 1: x = 4
        self.assertEqual(sorted(seen), [[2, 2], [4, 1], [4, 2]])

    def test_revealed_map_without_vis_uses_first_grid(self):
        reply = {"ok": True, "window": {"x0": 0, "y0": 0, "x1": 1, "y1": 0}, "layers": {"terrain": ["G "]}}
        self.assertEqual(A.seen_plots("revealed_map", {}, reply), [[0, 0]])

    def test_seen_is_capped_and_counted(self):
        reply = {"ok": True, "plots": [{"x": i % 200, "y": i // 200} for i in range(A.SEEN_MAX + 50)]}
        f = A.fields("known_world", "read", {}, reply, True, "")
        self.assertEqual(len(f["seen"]), A.SEEN_MAX)
        self.assertEqual(f["seen_more"], 50)


class IntentTests(unittest.TestCase):
    def test_xy_and_dest(self):
        self.assertEqual(A.intent_plots("move_unit", {"unit_id": 1, "x": 3, "y": 4}), [[3, 4]])
        self.assertEqual(A.intent_plots("establish_trade_route", {"unit_id": 1, "dest_x": 3, "dest_y": 4}), [[3, 4]])

    def test_order_steps_and_compare_plots(self):
        steps = {"unit_id": 1, "steps": [{"move": {"x": 1, "y": 1}}, {"build": "FARM", "x": 2, "y": 2}, "fortify"]}
        self.assertEqual(sorted(A.intent_plots("give_order", steps)), [[1, 1], [2, 2]])
        self.assertEqual(A.intent_plots("compare", {"kind": "builds", "plots": [[1, 2], [3, 4], "x"]}), [[1, 2], [3, 4]])

    def test_batches_recurse(self):
        args = {"actions": [{"tool": "move_unit", "args": {"unit_id": 1, "x": 1, "y": 1}},
                            {"tool": "set_production", "args": {"city_id": 9, "item": "BUILDING_MONUMENT"}},
                            {"tool": "move_unit", "args": {"unit_id": 2, "x": 1, "y": 1}}]}
        self.assertEqual(A.intent_plots("do", args), [[1, 1]])
        self.assertEqual(A.refs(args), {"unit_id": [1, 2], "city_id": [9]})

    def test_refs(self):
        self.assertEqual(A.refs({"unit_id": 5, "city_ids": [1, 2, 2], "unit_ids": [5, 6], "radius": 2}),
                         {"unit_id": [5, 6], "city_id": [1, 2]})
        self.assertEqual(A.refs(None), {})
        self.assertEqual(A.refs({"unit_id": "x"}), {})


class FieldsTests(unittest.TestCase):
    def test_scope(self):
        self.assertEqual(A.scope("tactical_view", "read"), "focus")
        self.assertEqual(A.scope("revealed_map", "read"), "broad")
        self.assertEqual(A.scope("move_unit", "write"), "act")
        self.assertEqual(A.scope("finish_turn", "wait"), "wait")
        for t in A.FOCUS_TOOLS:
            self.assertIn(t, L.READ_TOOLS, f"{t} is a focus tool but not a read")

    def test_excerpt_only_for_writes_and_refusals(self):
        self.assertIsNone(A.excerpt("read", True, "x" * 50))
        self.assertEqual(A.excerpt("read", False, "  refused  "), "refused")
        self.assertEqual(len(A.excerpt("write", True, "y" * 1000)), A.EXCERPT_CHARS)

    def test_args_compact_and_capped(self):
        self.assertIsNone(A.compact_args({}))
        self.assertEqual(A.compact_args({"a": 1, "b": "é"}), '{"a":1,"b":"é"}')
        self.assertEqual(len(A.compact_args({"text": "z" * 5000})), A.ARGS_CHARS)

    def test_row_carries_attention_when_given_args(self):
        reply = json.dumps({"ok": True, "unit": {"x": 2, "y": 2}, "turn": 12})
        r = L.row("tactical_view", 1, reply, 0.4, 3, now=1.0, args={"unit_id": 44, "radius": 1})
        self.assertEqual((r["scope"], r["turn"], r["refs"]), ("focus", 12, {"unit_id": [44]}))
        self.assertEqual(len(r["seen"]), 7)
        self.assertEqual(r["args"], '{"unit_id":44,"radius":1}')
        self.assertNotIn("excerpt", r)
        self.assertNotIn("intent", r)
        w = L.row("move_unit", 1, json.dumps({"ok": True, "moved": True}), 0.4, 3, args={"unit_id": 44, "x": 3, "y": 3})
        self.assertEqual((w["scope"], w["intent"], w["excerpt"]), ("act", [[3, 3]], '{"ok": true, "moved": true}'))

    def test_row_without_args_is_unchanged(self):
        r = L.row("tactical_view", 1, json.dumps({"ok": True, "unit": {"x": 2, "y": 2}}), 0.4, 3)
        for k in ("scope", "seen", "args", "refs", "intent", "excerpt"):
            self.assertNotIn(k, r)

    def test_refused_write_keeps_intent_and_excerpt(self):
        r = L.row("move_unit", 0, json.dumps({"ok": False, "err": "no such unit"}), 0.1, 1,
                  args={"unit_id": 1, "x": 5, "y": 5})
        self.assertEqual((r["ok"], r["intent"], r["seen"] if "seen" in r else None), (False, [[5, 5]], None))
        self.assertIn("no such unit", r["excerpt"])
