"""HTTP/JSON API so multiple LLMs (any provider, not just Claude) can each play one seat of the same game
-- the "pitboss with other frontier models" mode. One process serves every configured seat; each seat is
its own always-connected Civ5 instance (see scripts/launch_seat.sh), reached through its own `tunerd`.

    cp harness/seats.example.json harness/seats.json   # fill in real api_key values
    python3 -m harness.tunerd --port <seat port> --sock $XDG_RUNTIME_DIR/civ5-<name>.sock   # one per seat
    python3 -m harness.http_server --host 0.0.0.0 --port 8765

A client authenticates as one seat with `X-API-Key: <that seat's key>` and only ever sees/acts on that
seat's `Game()` -- there is no way to address another seat's game through this API. Interactive docs (and a
machine-readable spec other providers' tool-calling can ingest) are served at /docs and /openapi.json.

Every route mirrors a harness/mcp_server.py tool 1:1 (same underlying game.py calls, same JSON shapes) --
see that module's docstrings for what each one does; this file only adds HTTP plumbing and per-seat auth.

The raw-Lua escape hatch (`lua()` in mcp_server.py) is NOT exposed here unless a seat's `seats.json` entry
sets `"allow_lua": true`. An unguarded raw Lua call already crashed this harness once (see docs/NOTES.md);
that risk is smaller with Claude on a local MCP connection than with an arbitrary, less-known model reachable
over the network, so it defaults off.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .client import TunerdError
from .game import Game

DEFAULT_SEATS_FILE = Path(__file__).with_name("seats.json")

app = FastAPI(
    title="Civ V multi-LLM harness",
    description="One HTTP API per seat in a shared game of Civilization V. Authenticate with X-API-Key.",
)

_seats: dict[str, dict] = {}          # seat name -> its seats.json entry
_key_to_seat: dict[str, str] = {}     # api_key -> seat name
_games: dict[str, Game] = {}          # seat name -> lazily-connected Game()


def load_seats(path: Path) -> None:
    global _seats, _key_to_seat
    if not path.exists():
        raise SystemExit(f"no seats file at {path} -- copy harness/seats.example.json to harness/seats.json and fill it in")
    data = json.loads(path.read_text())
    _seats = {k: v for k, v in data.items() if not k.startswith("_")}
    _key_to_seat = {}
    for name, seat in _seats.items():
        key = seat.get("api_key")
        if not key or key == "REPLACE_ME":
            raise SystemExit(f"seat {name!r} has no real api_key set in {path}")
        if key in _key_to_seat:
            raise SystemExit(f"seats {_key_to_seat[key]!r} and {name!r} share an api_key -- each seat needs its own")
        _key_to_seat[key] = name


def game_for(seat_name: str) -> Game:
    g = _games.get(seat_name)
    if g is None:
        seat = _seats[seat_name]
        sock = seat.get("sock") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"civ5-{seat_name}.sock")
        try:
            g = Game(sock)
        except OSError as e:
            # tunerd for this seat isn't running (no socket file / connection refused) -- a clean 502, not
            # a bare 500: caught live, the first version of this let a raw FileNotFoundError/
            # ConnectionRefusedError through uncaught since Game()/Civ5() raise OSError subclasses here,
            # not TunerdError/ConnectionError (those come later, from calls that reach a live tunerd).
            raise HTTPException(status_code=502, detail=f"tunerd for seat {seat_name!r} not reachable at {sock}: {e}")
        configured_seat = seat.get("seat")  # only needed for hotseat; network games auto-detect
        g.seat = int(configured_seat) if configured_seat is not None else 1
        _games[seat_name] = g
    return g


def current_seat(x_api_key: str | None = Header(None, description="This seat's API key from seats.json")) -> str:
    # Header(None) + a manual None check (rather than Header(...) required) so a missing key and a wrong
    # key both come back as the same clean 401 -- Header(...) alone makes FastAPI 422 a missing header
    # before this function ever runs, which is a confusing inconsistency for API consumers to handle.
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    name = _key_to_seat.get(x_api_key)
    if name is None:
        raise HTTPException(status_code=401, detail="unknown API key")
    return name


def current_game(seat_name: str = Depends(current_seat)) -> Game:
    g = game_for(seat_name)
    seat = _seats[seat_name]
    if seat.get("seat") is None:
        try:
            if g.mode() != "hotseat":
                g.detect_seat()
        except (TunerdError, TimeoutError):
            pass  # front end / not in a game yet -- fine for lobby-ish calls, action calls will error clearly
    return g


def call(fn, *a, **k) -> Any:
    """Same error-shape contract as mcp_server.py's guarded(): a game/connection problem is a clean 502
    with the message, never a bare 500."""
    try:
        return fn(*a, **k)
    except (TunerdError, TimeoutError, ConnectionError) as e:
        raise HTTPException(status_code=502, detail=str(e))


# ------------------------------------------------------------------ request models
class MoveUnit(BaseModel):
    unit_id: int
    x: int
    y: int


class UnitMission(BaseModel):
    unit_id: int
    mission: str
    x: int = -1
    y: int = -1
    build: str | None = None  # MISSION_BUILD: e.g. "BUILD_FARM" -- do not use x/y for this, see harness/game.py


class SetProduction(BaseModel):
    city_id: int
    item: str


class PurchaseProduction(BaseModel):
    city_id: int
    item: str
    yield_type: str = "GOLD"


class SetResearch(BaseModel):
    tech: str


class StealTech(BaseModel):
    tech: str
    victim: int


class LoadSave(BaseModel):
    filename: str


class PlayerAction(BaseModel):
    player_id: int


class MinorGoldGift(BaseModel):
    player_id: int
    amount: int  # one of city_state_gifts' small/medium/large tier amounts


class RespondDiscussion(BaseModel):
    button_id: int


class ChoosePromotion(BaseModel):
    unit_id: int
    promotion: str


class ChooseFreeGreatPerson(BaseModel):
    unit: str


class CityId(BaseModel):
    city_id: int


class DiploEvent(BaseModel):
    event: str
    player_id: int
    data1: int = 0
    data2: int = 0


class CityRangedAttack(BaseModel):
    city_id: int
    x: int
    y: int


class ChoosePolicy(BaseModel):
    policy: str


class UnlockPolicyBranch(BaseModel):
    branch: str


class FoundPantheon(BaseModel):
    belief: str


class FoundReligion(BaseModel):
    religion: str
    beliefs: list[str]
    city_x: int
    city_y: int
    custom_name: str = ""


class EnhanceReligion(BaseModel):
    religion: str
    belief4: str
    belief5: str
    city_x: int
    city_y: int
    custom_name: str = ""


class EstablishTradeRoute(BaseModel):
    unit_id: int
    dest_x: int
    dest_y: int
    trade_type: int


class UnitId(BaseModel):
    unit_id: int


class MoveSpy(BaseModel):
    agent_id: int
    target_player_id: int
    target_city_id: int
    as_diplomat: bool = False


class StageCoup(BaseModel):
    agent_id: int


class ProposeDeal(BaseModel):
    player_id: int
    items: list[dict]
    ask_counter: bool = False


class NegotiateDeal(BaseModel):
    player_id: int
    items: list[dict] = []
    mode: str = "equalize"



class LeagueProposeEnact(BaseModel):
    resolution_type: str
    choice: int = -1


class LeagueProposeRepeal(BaseModel):
    resolution_id: int


class LeagueCastVotes(BaseModel):
    votes: list[dict]


class LuaCode(BaseModel):
    code: str


# ------------------------------------------------------------------ observation
@app.get("/status", summary="Whose turn, turn number, blockers, and greeting/tech/discussion screens")
def status(g: Game = Depends(current_game)):
    return call(g.turn_state)


@app.get("/wait_for_my_turn", summary="Block (up to timeout_seconds) until it is my turn")
def wait_for_my_turn(timeout_seconds: int = 90, g: Game = Depends(current_game)):
    return call(g.wait_for_my_turn, timeout=timeout_seconds)


@app.post("/dismiss_discussion", summary="Leave an AI leader's negotiation/demand/trade-offer screen")
def dismiss_discussion(g: Game = Depends(current_game)):
    return call(g.dismiss_discussion)


@app.get("/players", summary="Network games: human players, connected/turn-active/ended-turn")
def players(g: Game = Depends(current_game)):
    return call(g.net_players)


@app.get("/overview", summary="My empire at a glance")
def overview(g: Game = Depends(current_game)):
    return call(g.summary)


@app.get("/turn_digest", summary="Everything recorded since my last call")
def turn_digest(g: Game = Depends(current_game)):
    return {"events": call(g.events_since_last), "notifications": call(g.notifications)}


@app.get("/units", summary="My units")
def units(g: Game = Depends(current_game)):
    return call(g.units)


@app.get("/cities", summary="My cities")
def cities(g: Game = Depends(current_game)):
    return call(g.cities)


@app.get("/map_window", summary="Revealed plots within radius of (x, y); vis=false means fogged")
def map_window(x: int, y: int, radius: int = 3, g: Game = Depends(current_game)):
    return call(g.plots_around, x, y, radius)


@app.get("/explore_frontier", summary="Fog edge for a unit: revealed plots of its domain bordering unrevealed ones, nearest first")
def explore_frontier(unit_id: int, limit: int = 12, g: Game = Depends(current_game)):
    return call(g.explore_frontier, unit_id, limit=limit)


@app.get("/known_world", summary="All revealed plots plus own empire, met civs, notifications")
def known_world(g: Game = Depends(current_game)):
    return call(g.known_world)


@app.get("/diplomacy", summary="Met civs and city-states: war, score, ally")
def diplomacy(g: Game = Depends(current_game)):
    return call(g.diplomacy)


@app.get("/available_research", summary="Techs this seat can research right now")
def available_research(g: Game = Depends(current_game)):
    return call(g.available_research)


@app.get("/available_production", summary="What a city can produce right now")
def available_production(city_id: int, g: Game = Depends(current_game)):
    return call(g.available_production, city_id)


@app.get("/available_unit_actions", summary="Legal unit-panel actions for a given unit right now")
def available_unit_actions(unit_id: int, g: Game = Depends(current_game)):
    return call(g.available_unit_actions, unit_id)


@app.get("/available_trade_routes", summary="Valid trade-route destinations for a given trade unit right now")
def available_trade_routes(unit_id: int, g: Game = Depends(current_game)):
    return call(g.available_trade_routes, unit_id)


@app.get("/spies", summary="My spies: rank, state, where stationed, can_stage_coup")
def spies(g: Game = Depends(current_game)):
    return call(g.spies)


@app.get("/available_spy_cities", summary="Where a given spy could be sent right now, with success potential")
def available_spy_cities(agent_id: int, g: Game = Depends(current_game)):
    return call(g.available_spy_cities, agent_id)


@app.get("/league_status", summary="World Congress: what I can propose (between sessions) or vote on (during one)")
def league_status(g: Game = Depends(current_game)):
    return call(g.league_status)


# ------------------------------------------------------------------ actions
@app.post("/move_unit")
def move_unit(body: MoveUnit, g: Game = Depends(current_game)):
    return call(g.move_unit, body.unit_id, body.x, body.y)


@app.post("/unit_mission")
def unit_mission(body: UnitMission, g: Game = Depends(current_game)):
    return call(g.unit_mission, body.unit_id, body.mission, body.x, body.y, build=body.build)


@app.post("/set_production")
def set_production(body: SetProduction, g: Game = Depends(current_game)):
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT", "PROJECT": "ORDER_CREATE",
              "PROCESS": "ORDER_MAINTAIN"}[body.item.split("_", 1)[0]]
    return call(g.set_production, body.city_id, order, body.item)


@app.get("/purchase_cost", summary="Cost to rush-buy an item with gold/faith right now, and whether it's purchasable")
def purchase_cost(city_id: int, item: str, yield_type: str = "GOLD", g: Game = Depends(current_game)):
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT"}[item.split("_", 1)[0]]
    return call(g.purchase_cost, city_id, order, item, yield_type)


@app.post("/purchase_production")
def purchase_production(body: PurchaseProduction, g: Game = Depends(current_game)):
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT"}[body.item.split("_", 1)[0]]
    return call(g.purchase_production, body.city_id, order, body.item, body.yield_type)


@app.get("/steal_tech_options", summary="ENDTURN_BLOCKING_STEAL_TECH: civs/techs a spy can take a tech from")
def steal_tech_options(g: Game = Depends(current_game)):
    return call(g.steal_tech_options)


@app.post("/steal_tech", summary="Take a stolen tech from `victim`; clears ENDTURN_BLOCKING_STEAL_TECH")
def steal_tech(body: StealTech, g: Game = Depends(current_game)):
    return call(g.steal_tech, body.tech, body.victim)


@app.post("/set_research")
def set_research(body: SetResearch, g: Game = Depends(current_game)):
    return call(g.set_research, body.tech)


@app.post("/quick_save")
def quick_save(g: Game = Depends(current_game)):
    return call(g.quick_save)


@app.post("/load_save")
def load_save(body: LoadSave, g: Game = Depends(current_game)):
    return call(g.load_save, body.filename)


@app.post("/load_latest")
def load_latest(g: Game = Depends(current_game)):
    return call(g.load_latest)


@app.post("/end_turn")
def end_turn(autosave: bool = True, g: Game = Depends(current_game)):
    return call(g.end_turn, autosave)


@app.post("/declare_war")
def declare_war(body: PlayerAction, g: Game = Depends(current_game)):
    return call(g.declare_war, body.player_id)


@app.post("/make_peace")
def make_peace(body: PlayerAction, g: Game = Depends(current_game)):
    return call(g.make_peace, body.player_id)


@app.post("/denounce")
def denounce(body: PlayerAction, g: Game = Depends(current_game)):
    return call(g.denounce, body.player_id)


@app.post("/accept_friendship")
def accept_friendship(body: PlayerAction, g: Game = Depends(current_game)):
    return call(g.accept_friendship, body.player_id)


@app.post("/diplo_event")
def diplo_event(body: DiploEvent, g: Game = Depends(current_game)):
    return call(g.diplo_event, body.event, body.player_id, body.data1, body.data2)


@app.post("/city_ranged_attack")
def city_ranged_attack(body: CityRangedAttack, g: Game = Depends(current_game)):
    return call(g.city_ranged_attack, body.city_id, body.x, body.y)


@app.post("/upgrade_unit", summary="Upgrade a unit for gold (Warrior -> Swordsman ...); returns the NEW unit_id")
def upgrade_unit(body: UnitId, g: Game = Depends(current_game)):
    return call(g.upgrade_unit, body.unit_id)


class PopupButton(BaseModel):
    button: int


@app.get("/generic_popup", summary="Read the open yes/no confirmation popup: text and numbered buttons")
def generic_popup(g: Game = Depends(current_game)):
    return call(g.generic_popup)


@app.post("/answer_popup", summary="Press a button of the open generic confirmation popup")
def answer_popup(body: PopupButton, g: Game = Depends(current_game)):
    return call(g.answer_popup, body.button)


@app.post("/disband_unit", summary="Disband (delete) one of my units; frees maintenance and strategic resources")
def disband_unit(body: UnitId, g: Game = Depends(current_game)):
    return call(g.disband_unit, body.unit_id)


@app.post("/choose_policy")
def choose_policy(body: ChoosePolicy, g: Game = Depends(current_game)):
    return call(g.choose_policy, body.policy)


@app.post("/unlock_policy_branch")
def unlock_policy_branch(body: UnlockPolicyBranch, g: Game = Depends(current_game)):
    return call(g.unlock_policy_branch, body.branch)


@app.post("/found_pantheon")
def found_pantheon(body: FoundPantheon, g: Game = Depends(current_game)):
    return call(g.found_pantheon, body.belief)


@app.post("/found_religion")
def found_religion(body: FoundReligion, g: Game = Depends(current_game)):
    return call(g.found_religion, body.religion, body.beliefs, body.city_x, body.city_y, body.custom_name)


@app.post("/enhance_religion")
def enhance_religion(body: EnhanceReligion, g: Game = Depends(current_game)):
    return call(g.enhance_religion, body.religion, body.belief4, body.belief5, body.city_x, body.city_y, body.custom_name)


@app.post("/establish_trade_route")
def establish_trade_route(body: EstablishTradeRoute, g: Game = Depends(current_game)):
    return call(g.establish_trade_route, body.unit_id, body.dest_x, body.dest_y, body.trade_type)


@app.post("/plunder_trade_route")
def plunder_trade_route(body: UnitId, g: Game = Depends(current_game)):
    return call(g.plunder_trade_route, body.unit_id)


@app.post("/move_spy")
def move_spy(body: MoveSpy, g: Game = Depends(current_game)):
    return call(g.move_spy, body.agent_id, body.target_player_id, body.target_city_id, body.as_diplomat)


@app.post("/stage_coup")
def stage_coup(body: StageCoup, g: Game = Depends(current_game)):
    return call(g.stage_coup, body.agent_id)


@app.post("/league_propose_enact")
def league_propose_enact(body: LeagueProposeEnact, g: Game = Depends(current_game)):
    return call(g.league_propose_enact, body.resolution_type, body.choice)


@app.post("/league_propose_repeal")
def league_propose_repeal(body: LeagueProposeRepeal, g: Game = Depends(current_game)):
    return call(g.league_propose_repeal, body.resolution_id)


@app.post("/league_cast_votes")
def league_cast_votes(body: LeagueCastVotes, g: Game = Depends(current_game)):
    return call(g.league_cast_votes, body.votes)


@app.post("/propose_deal", summary="Offer a trade to an AI through the real trade screen; returns accepted/reply/effects")
def propose_deal(body: ProposeDeal, g: Game = Depends(current_game)):
    return call(g.propose_deal, body.player_id, body.items, ask_counter=body.ask_counter)


@app.post("/negotiate_deal", summary="Ask an AI what would make a deal work (equalize / what_will_ai_give / what_does_ai_want) without proposing")
def negotiate_deal(body: NegotiateDeal, g: Game = Depends(current_game)):
    return call(g.negotiate_deal, body.player_id, body.items, mode=body.mode)





@app.post("/lua", summary="Raw Lua escape hatch -- only if this seat's seats.json sets allow_lua: true")
def lua(body: LuaCode, seat_name: str = Depends(current_seat)):
    if not _seats[seat_name].get("allow_lua"):
        raise HTTPException(status_code=403, detail="allow_lua is not enabled for this seat in seats.json")
    return call(game_for(seat_name).lua, "InGame", body.code, 20)


def main(argv=None) -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--seats-file", default=str(DEFAULT_SEATS_FILE))
    a = ap.parse_args(argv)
    load_seats(Path(a.seats_file))
    print(f"serving {len(_seats)} seat(s) ({', '.join(_seats)}) on http://{a.host}:{a.port} (docs at /docs)")
    uvicorn.run(app, host=a.host, port=a.port)


# ------------------------------------------------------------------ parity with mcp_server.py (added 2026-09-17)
@app.get("/turn_status", summary="Alias of /status (the MCP tool's name)")
def turn_status(g: Game = Depends(current_game)):
    return call(g.turn_state)


@app.get("/discussion", summary="What an AI leader is saying right now and the response buttons")
def discussion(g: Game = Depends(current_game)):
    return call(g.discussion)


@app.post("/respond_discussion", summary="Press one of discussion's response buttons (1-4)")
def respond_discussion(body: RespondDiscussion, g: Game = Depends(current_game)):
    return call(g.respond_discussion, body.button_id)


@app.get("/incoming_deal", summary="The deal on the trade table (an AI offer), read-only")
def incoming_deal(g: Game = Depends(current_game)):
    return call(g.incoming_deal)


@app.post("/accept_deal", summary="Accept the offer on the trade table")
def accept_deal(g: Game = Depends(current_game)):
    return call(g.accept_deal)


@app.post("/refuse_deal", summary="Refuse the offer on the trade table")
def refuse_deal(g: Game = Depends(current_game)):
    return call(g.refuse_deal)


@app.get("/trade_catalog", summary="What can go on a trade table with this major civ")
def trade_catalog(player_id: int, g: Game = Depends(current_game)):
    return call(g.trade_catalog, player_id)


@app.get("/trade_routes", summary="My active trade routes with turns_left and per-turn yields")
def trade_routes(g: Game = Depends(current_game)):
    return call(g.trade_routes)


@app.get("/city_state_gifts", summary="Gold gift tiers / friendship with a city-state")
def city_state_gifts(player_id: int, g: Game = Depends(current_game)):
    return call(g.city_state_gifts, player_id)


@app.post("/minor_gold_gift", summary="Gift a city-state gold (a city_state_gifts tier amount)")
def minor_gold_gift(body: MinorGoldGift, g: Game = Depends(current_game)):
    return call(g.minor_gold_gift, body.player_id, body.amount)


@app.get("/relationship", summary="One civ in depth: agreements, history of what they said, relations")
def relationship(player_id: int, g: Game = Depends(current_game)):
    return call(g.relationship, player_id)


@app.get("/available_policies", summary="Social policies adoptable now, branches, culture")
def available_policies(g: Game = Depends(current_game)):
    return call(g.available_policies)


@app.get("/available_city_strikes", summary="Plots a city can bombard right now")
def available_city_strikes(city_id: int, g: Game = Depends(current_game)):
    return call(g.available_city_strikes, city_id)


@app.post("/choose_promotion", summary="Pick a promotion for a unit that earned one")
def choose_promotion(body: ChoosePromotion, g: Game = Depends(current_game)):
    return call(g.choose_promotion, body.unit_id, body.promotion)


@app.get("/free_great_person_options", summary="Great People claimable for free right now")
def free_great_person_options(g: Game = Depends(current_game)):
    return call(g.free_great_person_options)


@app.post("/choose_free_great_person", summary="Claim a free Great Person (unit type from the options)")
def choose_free_great_person(body: ChooseFreeGreatPerson, g: Game = Depends(current_game)):
    return call(g.choose_free_great_person, body.unit)


if __name__ == "__main__":
    main()
