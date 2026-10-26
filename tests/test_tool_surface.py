"""The nine tools (GitLab #48, stage 2a): each `(tool, action)` / `(what, view)` row dispatches to its old handler
with the same arguments, a malformed call is refused naming the shape, and a merged family's reply is the old
reply byte for byte. The old names stay registered beside the nine until #52.
"""
import json
import os
import unittest
from unittest import mock

import anyio

from harness import gate as G
from harness import mcp_server as m
from harness.surface import dispatch as D
from harness.surface import forward as F
from harness.surface import listing as L
from harness.surface import retirement as R
from harness.surface import survey
from harness.surface import vocabulary as V


def sample_args(old: str) -> dict:
    """The old handler's required arguments with placeholder values (by type), under their OLD names."""
    sch = D.schema(old)
    out = {}
    for name in sch.get("required") or []:
        p = (sch.get("properties") or {}).get(name) or {}
        t = p.get("type") or next((x.get("type") for x in p.get("anyOf", []) if x.get("type") != "null"), "string")
        out[name] = {"integer": 7, "number": 7, "boolean": True, "array": [1], "object": {}}.get(t, f"X_{name}")
    return out


def new_args(row: R.Row, old_args: dict) -> dict:
    return {row.renames.get(k, k): v for k, v in old_args.items()}


class EveryRowDispatchesTests(unittest.TestCase):
    """Every old name of the retirement map is reached from its new call with its own arguments."""

    def test_every_old_name_is_reached(self):
        names = {t.name for t in survey.tools()}
        reached, skipped = set(), set()
        for old, row in R.RETIRED.items():
            self.assertIn(old, names)
            fixed = dict(row.fixed)
            if row.tool in ("answer", "question"):
                skipped.add(old)      # answers and questions dispatch on the live gate: AnswerTests, ThroughTheServerTests
                continue
            if any(isinstance(v, R.FromArg) for v in fixed.values()):
                fixed = {k: ("bully_gold" if isinstance(v, R.FromArg) else v) for k, v in fixed.items()}
                args = new_args(row, {k: v for k, v in sample_args(old).items() if k != "action"})
            else:
                args = new_args(row, sample_args(old))
            if old == "turn_digest":
                args["detail"] = "digest"
            if old == "purchase_cost":
                args["item"] = "UNIT_X"
            target = D.resolve(row.tool, fixed, args)
            if isinstance(target, D.Composite):
                self.assertIn(old, {c.tool for c in target.parts.values()}, old)
                reached.add(old)
                continue
            self.assertIsInstance(target, D.Call, (old, target))
            candidates = D.INDEX[row.key]
            if target.tool == old:
                reached.add(old)
            else:
                # a shared row whose default is another old name: the arguments did not say (players, known_world, the
                # governor trio without its field, a great-work swap, the production chooser's default)
                self.assertIn(target.tool, candidates, (old, target))
                self.assertIn(old, {"players", "known_world", "set_avoid_growth", "set_auto_specialists",
                                    "swap_great_works", "set_swappable_great_work", "unlock_policy_branch"}, (old, target))
        self.assertEqual(skipped, {n for n, r in R.RETIRED.items() if r.tool in ("answer", "question")})
        # 145 old names: 10 questions and 13 answers dispatch on the gate, 7 share a row whose default is another name
        self.assertGreaterEqual(len(reached), 145 - 10 - 13 - 7)
        # the shared rows are reached when the arguments say which
        self.assertEqual(D.resolve("order", {"to": "city", "action": "governor"}, {"id": 1, "avoid": True}).tool, "set_avoid_growth")
        self.assertEqual(D.resolve("order", {"to": "city", "action": "governor"}, {"id": 1, "automatic": True}).tool, "set_auto_specialists")
        self.assertEqual(D.resolve("order", {"to": "city", "action": "great_work"}, {"their_work_id": 3}).tool, "swap_great_works")
        self.assertEqual(D.resolve("order", {"to": "empire", "action": "policy"}, {"policy": "POLICY_BRANCH_HONOR"}),
                         D.Call("unlock_policy_branch", {"branch": "POLICY_BRANCH_HONOR"}))
        self.assertEqual(D.resolve("order", {"to": "empire", "action": "policy"}, {"policy": "POLICY_LIBERTY"}).tool, "choose_policy")

    def test_the_arguments_are_renamed_back_and_a_single_id_becomes_the_list_the_old_handler_takes(self):
        self.assertEqual(D.resolve("order", {"to": "city", "action": "produce"}, {"id": 3, "item": "UNIT_X"}),
                         D.Call("set_production", {"city_id": 3, "item": "UNIT_X"}))
        self.assertEqual(D.resolve("inspect", {"what": "units", "view": "actions"}, {"id": 7}),
                         D.Call("todo_actions", {"unit_ids": [7]}))
        self.assertEqual(D.resolve("inspect", {"what": "units", "view": "actions"}, {"id": [7, 8], "detail": "summary"}),
                         D.Call("todo_actions", {"unit_ids": [7, 8], "detail": "summary"}))
        self.assertEqual(D.resolve("inspect", {"what": "unit", "view": "tactical"}, {"id": 5, "radius": 2}),
                         D.Call("tactical_view", {"unit_id": 5, "radius": 2}))
        self.assertEqual(D.resolve("session", {"action": "seat"}, {"seat": 1}), D.Call("set_seat", {"player_id": 1}))
        self.assertEqual(D.resolve("reference", {"book": "playbook"}, {"section": "start"}), D.Call("how_to_play", {"topic": "start"}))
        self.assertEqual(D.resolve("turn", {"action": "briefing"}, {"detail": "digest"}), D.Call("turn_digest", {}))
        self.assertEqual(D.resolve("turn", {"action": "status"}, {}), D.Call("turn_status", {}))
        self.assertEqual(D.resolve("order", {"to": "city_state", "action": "make_peace"}, {"id": 20}),
                         D.Call("city_state_action", {"player_id": 20, "action": "make_peace"}))
        full = D.resolve("inspect", {"what": "city_state", "view": "full"}, {"id": 20})
        self.assertEqual({k: c.tool for k, c in full.parts.items()}, D.CITY_STATE_FULL)
        self.assertEqual(full.parts["bonuses"].args, {"minor_id": 20})

    def test_the_vocabulary_and_the_index_agree(self):
        for (head, tail), names in D.INDEX.items():
            tool, _, what = head.partition(":")
            if tool == "inspect":
                self.assertIn(tail, V.VIEWS[what], (head, tail))
            elif tool == "order":
                self.assertTrue(tail in V.ACTIONS[what] or tail.startswith("<"), (head, tail))
            for n in names:
                self.assertEqual(R.RETIRED[n].key, (head, tail))


class RefusalTests(unittest.TestCase):
    def test_a_malformed_order_is_refused_naming_the_shape_with_an_example(self):
        r = D.resolve("order", {"to": "city", "action": "produce"}, {"id": 3})
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("needs item", r.err)
        self.assertEqual(r.example, {"tool": "order", "args": {"to": "city", "action": "produce", "id": 1, "args": {"item": "<item>"}}})
        self.assertTrue(r.accepts.startswith("set_production("))
        r = D.resolve("order", {"to": "unit", "action": "move"}, {"id": 3, "x": 1, "y": 2, "speed": 9})
        self.assertIn("does not take speed", r.err)
        r = D.resolve("order", {"to": "unit", "action": "fly"}, {"id": 1})
        self.assertEqual(r.choices, sorted(V.ACTIONS["unit"]))
        r = D.resolve("inspect", {"what": "nothing"}, {})
        self.assertIn("league", r.choices)
        self.assertEqual(len(r.choices), len(set(r.choices)))
        reply = r.reply()
        self.assertEqual((reply["ok"], "choices" in reply), (False, True))

    def test_an_ambiguous_shared_row_is_refused_with_every_shape(self):
        r = D.resolve("order", {"to": "city", "action": "governor"}, {"id": 1})
        self.assertIsInstance(r, D.Refusal)
        self.assertEqual(len(r.accepts), 3)

    def test_an_example_for_every_old_name_is_a_row_of_the_new_tool(self):
        for old, row in R.RETIRED.items():
            ex = F.example(old)
            self.assertEqual(ex["tool"], row.tool, old)
            self.assertIsInstance(ex["args"], dict)


class AnswerTests(unittest.TestCase):
    FREE = {"turn": 24, "active_player": 0, "my_turn": True, "processing": False, "paused": False, "hotseat": False,
            "pending_popups": [], "todo": {"units": [], "research_unset": False}, "blocking_name": "ENDTURN_BLOCKING_UNITS"}

    def gate(self, **ts):
        return G.compute_gate({**self.FREE, **ts}, 0)

    def test_a_fixed_word_needs_no_gate(self):
        self.assertEqual(D.resolve("answer", {"choice": "accept"}, {}, None), D.Call("accept_deal", {}))
        self.assertEqual(D.resolve("answer", {"choice": "leave"}, {}, None), D.Call("dismiss_discussion", {}))
        self.assertEqual(D.resolve("answer", {"choice": "accept_friendship"}, {"player_id": 2}, None),
                         D.Call("accept_friendship", {"player_id": 2}))

    def test_every_popup_the_gate_knows_takes_its_choice(self):
        want = {"BUTTONPOPUP_CHOOSETECH": ("set_research", "tech"), "BUTTONPOPUP_CHOOSEPRODUCTION": ("set_production", "item"),
                "BUTTONPOPUP_CHOOSEPOLICY": ("choose_policy", "policy"), "BUTTONPOPUP_CHOOSE_IDEOLOGY": ("choose_ideology", "branch"),
                "BUTTONPOPUP_CHOOSEUNITPROMOTION": ("choose_promotion", "promotion"), "BUTTONPOPUP_FOUND_PANTHEON": ("found_pantheon", "belief"),
                "BUTTONPOPUP_FOUND_RELIGION": ("found_religion", "religion"), "BUTTONPOPUP_ENHANCE_RELIGION": ("enhance_religion", "religion"),
                "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD": ("choose_goody_hut", "goody"), "BUTTONPOPUP_CITY_CAPTURED": ("choose_city_capture", "choice"),
                "BUTTONPOPUP_CHOOSE_FAITH_GREAT_PERSON": ("choose_faith_great_person", "unit"),
                "BUTTONPOPUP_CHOOSE_ARCHAEOLOGY": ("choose_archaeology", "choice"), "BUTTONPOPUP_CHOOSE_MAYA_BONUS": ("choose_maya_bonus", "unit")}
        extra = {"set_production": {"id": 3}, "choose_promotion": {"id": 5}, "found_religion": {"beliefs": ["B1", "B2"], "city_x": 1, "city_y": 2},
                 "enhance_religion": {"belief4": "B4", "belief5": "B5", "city_x": 1, "city_y": 2}, "choose_archaeology": {"x": 4, "y": 9}}
        for popup in G.POPUP_RESOLUTIONS:
            if popup == "BUTTONPOPUP_TECH_TREE":
                continue
            old, arg = want[popup]
            choice = 2 if arg == "choice" and old == "choose_archaeology" else "CHOICE_X"
            r = D.resolve("answer", {"choice": choice}, extra.get(old, {}), self.gate(pending_popups=[{"name": popup}]))
            self.assertIsInstance(r, D.Call, (popup, r))
            self.assertEqual(r.tool, old, popup)
            self.assertEqual(r.args[arg], choice, popup)
            self.assertFalse(set(D.required(old)) - set(r.args), (popup, r))
        r = D.resolve("answer", {"choice": "POLICY_BRANCH_HONOR"}, {}, self.gate(pending_popups=[{"name": "BUTTONPOPUP_CHOOSEPOLICY"}]))
        self.assertEqual(r, D.Call("unlock_policy_branch", {"branch": "POLICY_BRANCH_HONOR"}))
        r = D.resolve("answer", {"choice": 1}, {}, G.popup_gate({"name": "BUTTONPOPUP_RETURN_CIVILIAN"}))
        self.assertEqual(r, D.Call("answer_popup", {"button": 1}))

    def test_a_leader_screen_and_the_tech_chooser(self):
        self.assertEqual(D.resolve("answer", {"choice": 2}, {}, self.gate(discussion_pending=True)),
                         D.Call("respond_discussion", {"button_id": 2}))
        r = D.resolve("answer", {"choice": "yes"}, {}, self.gate(discussion_pending=True))
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("respond_discussion", r.choices)
        self.assertEqual(D.resolve("answer", {"choice": "x"}, {}, self.gate(leader_greeting_pending=True)), D.Call("dismiss_discussion", {}))
        self.assertEqual(D.resolve("answer", {"choice": "TECH_MINING"}, {},
                                   self.gate(tech_popup_pending=True, todo={"research_unset": True})), D.Call("set_research", {"tech": "TECH_MINING"}))
        r = D.resolve("answer", {"choice": "TECH_MINING"}, {}, None)
        self.assertIn("nothing is asked", r.err)
        r = D.resolve("answer", {"choice": 1}, {}, self.gate(paused=True))
        self.assertIn("paused", r.err)


# --- through the server: the old reply byte for byte -----------------------------------------------------
class FakeGame:
    seat = 0
    settle_announcements = None

    def __init__(self, popups=None):
        self.calls = []
        self.popups = popups or []

    def has_state(self, name):
        return True

    def mode(self):
        return "single"

    def turn_state(self, pid=None):
        return {"turn": 9, "active_player": 0, "my_turn": True, "processing": False, "paused": False, "hotseat": False,
                "blocking_name": "ENDTURN_BLOCKING_UNITS", "todo": {"units": [{"id": 1, "type": "WARRIOR", "x": 1, "y": 1, "moves": 2}]},
                "pending_popups": list(self.popups)}

    def discussion_pending(self):
        return False

    def clear_hand_off(self, ts):
        return ts

    def _goody_popup_unit(self):
        return 7

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fn(*a, **kw):
            self.calls.append((name, a, kw))
            if name == "goody_hut_options":   # the real mixin attaches the answers (harness/affordances); the fake does the same
                from harness import affordances as A
                return A.answered({"ok": True, "unit_id": 7, "options": [{"goody": "GOODY_GOLD"}]}, A.goody_hut_answers)
            if name == "league_status":
                return {"ok": True, "host": "me", "resolutions": [{"id": 1}]}
            return {"ok": True, "called": name}
        return fn


class ThroughTheServerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-surface.sock", "CIV5_SEAT": "0"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def run_tools(self, calls, client_name: str = "test-client"):
        """Run the calls through a client session; a call named `None` lists the tools instead (the listing
        lands in the outputs as {name: input_schema})."""
        outs = []

        async def go():
            from mcp import ClientSession
            from mcp.shared.memory import create_client_server_memory_streams
            from mcp.types import Implementation
            async with create_client_server_memory_streams() as (cs, ss):
                async with anyio.create_task_group() as tg:
                    srv = m.mcp._lowlevel_server

                    async def run_server():
                        await srv.run(ss[0], ss[1], srv.create_initialization_options())
                    tg.start_soon(run_server)
                    async with ClientSession(cs[0], cs[1], client_info=Implementation(name=client_name, version="0")) as s:
                        await s.initialize()
                        for name, args in calls:
                            if name is None:
                                r = await s.list_tools()
                                outs.append({t.name: getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) for t in r.tools})
                                continue
                            res = await s.call_tool(name, args)
                            outs.append(res.content[0].text)
                    tg.cancel_scope.cancel()
        anyio.run(go)
        return outs

    def test_the_nine_are_registered_beside_the_old_catalog(self):
        self.assertEqual([t.name for t in survey.new_tools()], ["reference", *[t for t in V.TOOLS if t != "reference"]])
        self.assertEqual(len(survey.tools()), 145)

    def test_a_merged_family_answers_byte_for_byte(self):
        old, new, old2, new2, old3, new3 = self.run_tools([
            ("league_status", {}), ("inspect", {"what": "league"}),
            ("units", {}), ("inspect", {"what": "units"}),
            ("turn_status", {}), ("turn", {"action": "status"})])
        self.assertEqual(old, new)
        self.assertEqual(old2, new2)
        self.assertEqual(json.loads(old3)["turn"], json.loads(new3)["turn"])
        self.assertEqual(sorted(json.loads(old3)), sorted(json.loads(new3)))

    def test_an_order_runs_the_old_handler_with_the_old_arguments(self):
        out, = self.run_tools([("order", {"to": "unit", "action": "move", "id": 1, "args": {"x": 2, "y": 3}})])
        self.assertTrue(json.loads(out)["ok"], out)
        self.assertIn(("move_unit", (1, 2, 3)), [(c[0], c[1][:3]) for c in self.fake.calls])
        out, = self.run_tools([("order", {"to": "unit", "action": "move", "id": 1})])
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assertIn("needs x, y", r["err"])
        self.assertEqual(r["example"]["tool"], "order")

    def test_the_other_tools_route(self):
        outs = self.run_tools([("notebook", {"action": "recall"}), ("recall", {}),
                               ("reference", {"book": "playbook"}), ("how_to_play", {}),
                               ("session", {"action": "save"}),
                               ("batch", {"actions": [{"tool": "order", "args": {"to": "unit", "action": "move", "id": 1, "args": {"x": 1, "y": 1}}},
                                                      {"tool": "move_unit", "args": {"unit_id": 1, "x": 2, "y": 2}}]})])
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[2], outs[3])
        self.assertIn("quick_save", [c[0] for c in self.fake.calls])
        batch = json.loads(outs[5])
        self.assertEqual((batch["ok"], batch["done"]), (True, 2))
        self.assertEqual([c[1][:3] for c in self.fake.calls if c[0] == "move_unit"], [(1, 1, 1), (1, 2, 2)])
        out, = self.run_tools([("batch", {"actions": [{"tool": "turn", "args": {"action": "finish"}}]})])
        self.assertFalse(json.loads(out)["ok"])

    def test_question_and_answer_follow_the_gate(self):
        self.fake.popups = [{"name": "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD"}]
        out, = self.run_tools([("question", {})])
        r = json.loads(out)
        self.assertEqual(r["gate"]["popup"], "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD")
        self.assertEqual(r["answers"], [{"tool": "choose_goody_hut", "args": {"goody": "GOODY_GOLD"}}])
        out, = self.run_tools([("answer", {"choice": "GOODY_GOLD"})])
        self.assertTrue(json.loads(out)["ok"], out)
        self.assertIn(("choose_goody_hut", "GOODY_GOLD"), [(c[0], c[1][0]) for c in self.fake.calls if c[1]])
        self.fake.popups = []
        out, = self.run_tools([("question", {})])
        r = json.loads(out)
        self.assertEqual((r["pending"], r["decisions"][0]["kind"]), (False, "unit_orders"))
        out, = self.run_tools([("answer", {"choice": "GOODY_GOLD"})])
        self.assertIn("nothing is asked", json.loads(out)["err"])

    def test_an_unlisted_old_name_or_alias_runs_with_renamed(self):
        out, described, batch = self.run_tools([("summary", {}),
                                                ("call", {"tool": "summary", "describe": True}),
                                                ("do", {"actions": [{"tool": "summary", "args": {}}]})])
        r = json.loads(out)
        self.assertEqual((r["ok"], r["renamed"]), (True, 'inspect(what="empire")'))   # the overview handler ran (its game method is `summary`)
        self.assertEqual(json.loads(described)["renamed"], 'inspect(what="empire")')
        self.assertEqual(json.loads(batch)["results"][0]["result"]["renamed"], 'inspect(what="empire")')
        # a listed old name answers as it always did, with no `renamed`
        out, = self.run_tools([("overview", {})])
        self.assertNotIn("renamed", json.loads(out))
        # a name hidden from the listing (--tools compact) is reached through the map: the old reply plus the key
        m.apply_toolset("compact")
        try:
            old, new = self.run_tools([("league_status", {}), ("inspect", {"what": "league"})])
        finally:
            m.apply_toolset("full")
        self.assertEqual(json.loads(old), {**json.loads(new), "renamed": 'inspect(what="league")'})
        self.assertNotIn("renamed", json.loads(new))

    def test_with_the_map_off_the_nine_still_answer_and_an_alias_is_unknown(self):
        with mock.patch.object(F, "old_name", lambda name: None):
            unknown, new = self.run_tools([("summary", {}), ("inspect", {"what": "league"})])
        self.assertIn("Unknown tool: summary", unknown)
        self.assertIn("overview", unknown)
        self.assertEqual(json.loads(new)["host"], "me")

    def test_the_listing_shows_order_as_oneof_or_flat_per_client(self):
        from harness.mcp_tools import surface as S
        listing, = self.run_tools([(None, {})], client_name="claude-code")
        self.assertEqual(L.variant_of(listing["order"]), L.ONEOF)
        self.assertEqual(len(listing["order"]["oneOf"]), len(V.ACTIONS))
        with mock.patch.object(L, "FLAT_CLIENTS", ("grok",)):
            listing, = self.run_tools([(None, {})], client_name="GrokClient/1")
        self.assertEqual(L.variant_of(listing["order"]), L.FLAT)
        self.assertEqual(S.order_schema_shown(), L.FLAT)
        with mock.patch.dict(os.environ, {L.ENV: "flat"}):
            listing, = self.run_tools([(None, {})], client_name="claude-code")
        self.assertEqual(L.variant_of(listing["order"]), L.FLAT)
        listing, out = self.run_tools([(None, {}), ("order", {"to": "unit", "action": "produce", "id": 1})], client_name="claude-code")
        self.assertEqual(L.variant_of(listing["order"]), L.ONEOF)     # the next listing settles it again
        r = json.loads(out)                                             # and the server refuses the malformed itself
        self.assertFalse(r["ok"])
        self.assertIn("order:unit has no 'produce'", r["err"])
        self.assertIn("move", r["choices"])


if __name__ == "__main__":
    unittest.main()
