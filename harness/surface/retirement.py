"""The retirement map (GitLab #50): each of the 145 old tool names onto its row in the nine-tool surface.

Every old name stays callable forever -- agent prompts, Codex configs and transcript scripts in the wild
name them -- so the map is data the call wrapper will read (stage 2c): an unlisted old name runs its new
call and the reply carries `renamed`, the string `Row.render()` makes. Stage 0 (#44) uses the same table
for the check that every catalog name maps to exactly one row and none is left over, and for the shape
count of the baseline. An argument rename is per old name (`unit_id` -> `id`); an argument not renamed
keeps its name, and whether it nests under `args` is stage 2a's (#48) decision, not this table's.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from harness.surface import vocabulary as V


@dataclass(frozen=True)
class FromArg:
    """A fixed field of the new call taken from one of the old call's arguments:
    choose_goody_hut(goody) becomes answer(choice=<goody>)."""
    name: str


@dataclass(frozen=True)
class Row:
    tool: str
    fixed: dict = field(default_factory=dict)      # the new call's fixed fields: what / view / to / action / book / choice
    renames: dict = field(default_factory=dict)    # old argument name -> new argument name
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        """The `(tool, action)` / `(what, view)` label the measurements and, later, the ledger group by."""
        f = self.fixed
        if self.tool == "state":
            return (f"state:{f['what']}", f.get("view", V.DEFAULT))
        if self.tool == "order":
            return (f"order:{f['to']}", show(f["action"]))
        return (self.tool, show(f.get("action") or f.get("book") or f.get("choice") or ""))

    def fill(self, new_args: dict | None = None) -> dict:
        """The fixed fields with each FromArg filled from the argument it names (under the new name), or left as
        its `<name>` placeholder when the argument was not given."""
        a = new_args or {}
        return {k: (a.get(v.name, f"<{v.name}>") if isinstance(v, FromArg) else v) for k, v in self.fixed.items()}

    def render(self) -> str:
        """The `renamed` string of a reply: state(what="map", view="window")."""
        return f"{self.tool}({', '.join(f'{k}={show(v, quote=True)}' for k, v in self.fixed.items())})"


def show(v, quote: bool = False) -> str:
    """A fixed value as text: a FromArg as its `<name>` placeholder, anything else as is (or JSON-quoted)."""
    if isinstance(v, FromArg):
        return f"<{v.name}>"
    return json.dumps(v) if quote else str(v)


# --- row constructors: one per new tool, keyword arguments are the argument renames ---------------------
def state(what: str, view: str | None = None, note: str = "", **renames) -> Row:
    fixed = {"what": what, **({"view": view} if view else {})}
    return Row("state", fixed, renames, note)


def turn(action: str, note: str = "", **fixed) -> Row:
    return Row("turn", {"action": action, **fixed}, {}, note)


def order(to: str, action, note: str = "", **renames) -> Row:
    return Row("order", {"to": to, "action": action}, renames, note)


def answer(choice, note: str = "", **renames) -> Row:
    return Row("answer", {"choice": choice}, renames, note)


def question(note: str = "") -> Row:
    return Row("question", {}, {}, note)


def notebook(action: str, **renames) -> Row:
    return Row("notebook", {"action": action}, renames)


def session(action: str, **renames) -> Row:
    return Row("session", {"action": action}, renames)


def batch(note: str = "") -> Row:
    return Row("batch", {}, {}, note)


def reference(book: str, **renames) -> Row:
    return Row("reference", {"book": book}, renames)


#: A listed tool renamed since 2.0.0 -> its name now; the arguments did not change. `inspect` was the one verb
#: among nine nouns (Glama / TDQS naming 4/5, 2026-10-28): `state(what, id, view)` reads the same objects. The old
#: name answers like the 145 below, with `renamed` on the reply; `CIV5_RETIRED_NAMES=off` makes it unknown.
RENAMED_TOOLS: dict[str, str] = {"inspect": "state"}

#: old name -> its row, in the old catalog's module order (harness/mcp_tools/__init__.py MODULE_NAMES).
RETIRED: dict[str, Row] = {
    # reference
    "how_to_play": reference("playbook", topic="section"),
    "reference": reference("rules"),
    # turn
    "turn_status": turn("status"),
    "briefing": turn("briefing"),
    "set_seat": session("seat", player_id="seat"),
    "wait_for_my_turn": turn("wait"),
    "players": turn("status", note="`players` is a key of the status reply in hotseat games"),
    "overview": state("empire"),
    "notification_log": state("notifications"),
    "turn_digest": turn("briefing", detail="digest"),
    "quick_save": session("save"),
    "end_turn": turn("end"),
    "finish_turn": turn("finish"),
    # batch
    "do": batch(),
    "call": batch(note="`call(tool, args)` is one batch row; nothing is hidden once every tool is listed"),
    # notebook
    "remember": notebook("remember"),
    "recall": notebook("recall"),
    "forget": notebook("forget"),
    "assign": notebook("assign"),
    "assignments": notebook("assignments"),
    "amend_assignment": notebook("amend"),
    "close_assignment": notebook("close"),
    "give_order": notebook("give_order"),
    "orders": notebook("orders"),
    "resume_order": notebook("resume_order"),
    "cancel_order": notebook("cancel_order"),
    # units
    "unit_home_options": state("unit", "home", unit_id="id"),
    "units": state("units"),
    "maya_options": question(),
    "choose_maya_bonus": answer(FromArg("unit")),
    "archaeology_options": question(),
    "choose_archaeology": answer(FromArg("choice")),
    "unit_mission_targets": state("unit", "targets", unit_id="id"),
    "map_window": state("map", "window"),
    "explore_frontier": state("map", "frontier", unit_id="id"),
    "tactical_view": state("unit", "tactical", unit_id="id"),
    "known_world": turn("briefing", since="turn", note="retires to the briefing plus the parts it joined"),
    "map_index": state("map", "index"),
    "revealed_map": state("map", "grid"),
    "generic_popup": question(),
    "answer_popup": answer(FromArg("button")),
    "goody_hut_options": question(),
    "choose_goody_hut": answer(FromArg("goody")),
    "available_unit_actions": state("unit", "actions", unit_id="id"),
    "todo_actions": state("units", "actions", unit_ids="id"),
    "choose_promotion": order("unit", "promote", unit_id="id"),
    "upgrade_unit": order("unit", "upgrade", unit_id="id"),
    "disband_unit": order("unit", "disband", unit_id="id"),
    "move_unit": order("unit", "move", unit_id="id"),
    "unit_mission": order("unit", "mission", unit_id="id"),
    # cities
    "cities": state("cities"),
    "city_screen": state("city", "screen", city_id="id"),
    "great_person_progress": state("screen", "great_people"),
    "culture_works": state("screen", "culture_works"),
    "set_swappable_great_work": order("city", "great_work", note="offer / clear"),
    "swap_great_works": order("city", "great_work", note="swap"),
    "change_specialist": order("city", "specialist", city_id="id"),
    "set_auto_specialists": order("city", "governor", city_id="id"),
    "set_city_focus": order("city", "governor", city_id="id"),
    "set_avoid_growth": order("city", "governor", city_id="id"),
    "change_working_plot": order("city", "work_plot", city_id="id"),
    "buy_city_plot": order("city", "buy_plot", city_id="id"),
    "city_task": order("city", "status", city_id="id", note="annex / raze / unraze"),
    "sell_building": order("city", "sell_building", city_id="id"),
    "compare": state("compare"),
    "city_ranged_attack": order("city", "strike", city_id="id"),
    "available_city_strikes": state("city", "strikes", city_id="id"),
    "available_production": state("city", "production", city_id="id"),
    "set_production": order("city", "produce", city_id="id"),
    "remove_from_queue": order("city", "dequeue", "position is 1-based: 1 is the item being built now, 2 the one behind it "
                                                  "(state(what='city', id, view='production').queue lists them in order)", city_id="id"),
    "purchase_cost": state("city", "production", city_id="id", note="with `item` and `yield_type`"),
    "purchase_production": order("city", "purchase", city_id="id"),
    # policies
    "available_policies": state("options", "policies"),
    "choose_policy": order("empire", "policy"),
    "unlock_policy_branch": order("empire", "policy", branch="policy", note="a POLICY_BRANCH_* unlocks"),
    "choose_ideology": order("empire", "ideology"),
    "free_great_person_options": question(),
    "choose_free_great_person": answer(FromArg("unit")),
    "religion_overview": state("screen", "religion"),
    "set_faith_purchase": order("empire", "faith_purchase"),
    "change_ideology": order("empire", "switch_ideology"),
    "faith_great_person_options": question(),
    "choose_faith_great_person": answer(FromArg("unit")),
    "available_beliefs": state("options", "beliefs"),
    "add_reformation_belief": order("empire", "reformation"),
    "found_pantheon": order("empire", "pantheon"),
    "found_religion": order("empire", "religion"),
    "enhance_religion": order("empire", "enhance_religion"),
    "available_research": state("options", "research"),
    "tech_tree": state("screen", "tech_tree"),
    "steal_tech_options": question(),
    "steal_tech": answer(FromArg("tech")),
    "set_research": order("empire", "research"),
    # diplomacy
    "dismiss_discussion": answer("leave"),
    "discussion": question(),
    "respond_discussion": answer(FromArg("button_id")),
    "incoming_deal": question(),
    "current_deals": state("screen", "deals"),
    "accept_deal": answer("accept"),
    "refuse_deal": answer("refuse"),
    "trade_catalog": state("civ", "trade_catalog", player_id="id"),
    "city_state_gifts": state("city_state", "full", player_id="id"),
    "city_capture_options": question(),
    "choose_city_capture": answer(FromArg("choice")),
    "war_consequences": state("civ", "war", player_id="id"),
    "city_state_actions": state("city_state", "summary", player_id="id"),
    "city_state_action": order("city_state", FromArg("action"), player_id="id"),
    "gift_tile_improvement_options": state("city_state", "full", player_id="id"),
    "gift_tile_improvement": order("city_state", "gift_improvement", player_id="id"),
    "minor_gold_gift": order("city_state", "gift_gold", player_id="id"),
    "demographics": state("empire", "demographics"),
    "domination_progress": state("screen", "domination"),
    "wonder_overview": state("screen", "wonders"),
    "city_state_bonuses": state("city_state", "full", minor_id="id"),
    "gift_unit_options": state("city_state", "full", minor_id="id"),
    "gift_unit": order("city_state", "gift_unit", minor_id="id"),
    "diplomacy": state("civs"),
    "relationship": state("civ", "summary", player_id="id"),
    "declare_war": order("civ", "declare_war", player_id="id"),
    "make_peace": order("civ", "peace", player_id="id"),
    "denounce": order("civ", "denounce", player_id="id"),
    "spaceship_status": state("screen", "spaceship"),
    "culture_overview": state("screen", "culture"),
    "propose_friendship": order("civ", "friendship", player_id="id"),
    "accept_friendship": answer("accept_friendship", player_id="id"),
    "diplo_event": order("civ", "event", player_id="id"),
    "propose_deal": order("civ", "propose_deal", player_id="id"),
    "demand": order("civ", "demand", player_id="id"),
    "negotiate_deal": order("civ", "negotiate", player_id="id"),
    # trade
    "espionage_intrigue": state("screen", "intrigue"),
    "available_trade_routes": state("options", "trade_routes", unit_id="id"),
    "trade_routes": state("screen", "trade_routes"),
    "establish_trade_route": order("unit", "trade_route", unit_id="id"),
    "plunder_trade_route": order("unit", "plunder", unit_id="id"),
    "spies": state("spies"),
    "available_spy_cities": state("options", "spy_cities", agent_id="id"),
    "move_spy": order("spy", "move", agent_id="id"),
    "stage_coup": order("spy", "coup", agent_id="id"),
    "league_status": state("league"),
    "league_propose_enact": order("league", "propose"),
    "league_propose_repeal": order("league", "repeal"),
    "league_cast_votes": order("league", "vote"),
    # front_end
    "load_save": session("load"),
    "load_latest": session("load_latest"),
    "exit_to_main_menu": session("main_menu"),
}


def vocabulary_errors() -> list[str]:
    """Rows whose fixed words are not in `harness.surface.vocabulary`: empty when the table is consistent."""
    out = []
    for name, row in RETIRED.items():
        f = row.fixed
        if row.tool not in V.TOOLS:
            out.append(f"{name}: no tool {row.tool!r}")
        elif row.tool == "state":
            views = V.VIEWS.get(f["what"])
            if views is None:
                out.append(f"{name}: state has no object {f['what']!r}")
            elif f.get("view", V.DEFAULT) not in views:
                out.append(f"{name}: state({f['what']!r}) has no view {f.get('view')!r}")
        elif row.tool == "order":
            actions = V.ACTIONS.get(f["to"])
            want = V.SCREEN_BUTTON if isinstance(f["action"], FromArg) else f["action"]
            if actions is None:
                out.append(f"{name}: order has no target {f['to']!r}")
            elif want not in actions:
                out.append(f"{name}: order(to={f['to']!r}) has no action {want!r}")
        elif row.tool == "turn" and f["action"] not in V.TURN_ACTIONS:
            out.append(f"{name}: turn has no action {f['action']!r}")
        elif row.tool == "notebook" and f["action"] not in V.NOTEBOOK_ACTIONS:
            out.append(f"{name}: notebook has no action {f['action']!r}")
        elif row.tool == "session" and f["action"] not in V.SESSION_ACTIONS:
            out.append(f"{name}: session has no action {f['action']!r}")
        elif row.tool == "reference" and f["book"] not in V.BOOKS:
            out.append(f"{name}: reference has no book {f['book']!r}")
        elif row.tool == "answer" and not isinstance(f["choice"], FromArg) and f["choice"] not in V.ANSWER_CHOICES:
            out.append(f"{name}: answer has no choice {f['choice']!r}")
    return out


def check(names: Iterable[str]) -> dict[str, list[str]]:
    """The stage 0 check: every catalog name maps to exactly one row (a dict key is one row by construction),
    no row names a tool that is not in the catalog, every row speaks the vocabulary."""
    catalog = set(names)
    return {"unmapped": sorted(catalog - RETIRED.keys()),
            "stale": sorted(RETIRED.keys() - catalog),
            "off_vocabulary": vocabulary_errors()}
