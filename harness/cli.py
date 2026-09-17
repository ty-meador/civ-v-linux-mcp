"""Command-line front-end automation (lobby / staging / status) for one game instance.

    python -m harness.cli status                 # which screen, mode, turn
    python -m harness.cli lan-games              # games advertised on the LAN
    python -m harness.cli join-lan <ip|serverID> [--nick Claude] [--no-ready]
    python -m harness.cli host-lan [--name "LLM Harness"] [--open 1 2] [--nick Claude] [--launch]
    python -m harness.cli host-hotseat --humans 0 1 [--nick 1=Claude]
    python -m harness.cli slots | ready | unready | launch | leave
    python -m harness.cli wait-ingame            # block until the map is live, print detected seat
    python -m harness.cli lua "print(Game.GetGameTurn())" [--state InGame]

The instance is selected by CIV5_TUNERD_SOCK (default: $XDG_RUNTIME_DIR/civ5-tuner.sock).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .client import TunerdError
from .game import Game


def J(v) -> str:
    return json.dumps(v, indent=1, ensure_ascii=False)


def cmd_status(g: Game, a) -> None:
    screen = g.front_end_screen()
    out = {"screen": screen, "tunerd": g.c.path}
    if screen == "InGame":
        try:
            g.detect_seat()
            out["seat"] = g.seat
            out["turn_state"] = g.turn_state()
            if out["turn_state"]["mode"] in ("lan", "internet"):
                out["players"] = g.net_players()
        except (TunerdError, TimeoutError) as e:
            out["error"] = str(e)
    elif screen == "StagingRoom":
        out["staging"] = g.staging_status()
    print(J(out))


def cmd_lan_games(g: Game, a) -> None:
    print(J(g.lan_games(refresh_seconds=a.seconds)))


def cmd_join_lan(g: Game, a) -> None:
    target: str | int = int(a.host) if a.host.isdigit() else a.host
    print(J(g.join_lan(target, nickname=a.nick, ready=not a.no_ready, timeout=a.timeout)))


def cmd_host_lan(g: Game, a) -> None:
    print(J(g.host_lan(game_name=a.name, open_seats=a.open, nickname=a.nick, launch=a.launch, map_script=a.map,
                       world_size=a.size, closed_seats=a.close, handicap=a.handicap)))


def cmd_host_hotseat(g: Game, a) -> None:
    nicks = {int(k): v for k, v in (kv.split("=", 1) for kv in a.nick or [])}
    g.host_hotseat(human_seats=a.humans, game_name=a.name, nicknames=nicks, launch=not a.no_launch)
    print("hosted hotseat; launching" if not a.no_launch else J(g.staging_status()))


def cmd_slots(g: Game, a) -> None:
    print(J(g.staging_status()))


def cmd_ready(g: Game, a) -> None:
    g.set_ready(a.cmd == "ready")
    print(J(g.staging_status()))


def cmd_launch(g: Game, a) -> None:
    g.launch_game()
    print("launch requested")


def cmd_leave(g: Game, a) -> None:
    g.leave_to_main_menu()
    print("left to main menu")


def cmd_wait_ingame(g: Game, a) -> None:
    g.wait_ingame(timeout=a.timeout)
    g.detect_seat()
    print(J({"seat": g.seat, "mode": g.mode(), "turn_state": g.turn_state()}))


def cmd_lua(g: Game, a) -> None:
    for line in g.lua(a.state, a.code, timeout=30):
        print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sock", default=os.environ.get("CIV5_TUNERD_SOCK"), help="tunerd unix socket (env CIV5_TUNERD_SOCK)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("lan-games"); p.add_argument("--seconds", type=float, default=4.0)
    p = sub.add_parser("join-lan"); p.add_argument("host"); p.add_argument("--nick"); p.add_argument("--no-ready", action="store_true"); p.add_argument("--timeout", type=float, default=90)
    p = sub.add_parser("host-lan"); p.add_argument("--name", default="LLM Harness"); p.add_argument("--open", type=int, nargs="*", default=[1]); p.add_argument("--nick"); p.add_argument("--launch", action="store_true")
    p.add_argument("--map", help="map script file name substring, e.g. continents.lua"); p.add_argument("--size", help="WORLDSIZE_* type")
    p.add_argument("--close", type=int, nargs="*", default=[], help="slots to close (SS_CLOSED)"); p.add_argument("--handicap", help="HANDICAP_* type for human slots")
    p = sub.add_parser("host-hotseat"); p.add_argument("--humans", type=int, nargs="+", default=[0, 1]); p.add_argument("--name", default="LLM Harness"); p.add_argument("--nick", nargs="*", help="seat=name"); p.add_argument("--no-launch", action="store_true")
    sub.add_parser("slots"); sub.add_parser("ready"); sub.add_parser("unready"); sub.add_parser("launch"); sub.add_parser("leave")
    p = sub.add_parser("wait-ingame"); p.add_argument("--timeout", type=float, default=600)
    p = sub.add_parser("lua"); p.add_argument("code"); p.add_argument("--state", default="InGame")
    a = ap.parse_args(argv)

    try:
        g = Game(a.sock)
    except (FileNotFoundError, ConnectionRefusedError) as e:
        print(f"tunerd not reachable ({e}); start it with: python3 -m harness.tunerd", file=sys.stderr)
        return 2
    fn = {"status": cmd_status, "lan-games": cmd_lan_games, "join-lan": cmd_join_lan, "host-lan": cmd_host_lan,
          "host-hotseat": cmd_host_hotseat, "slots": cmd_slots, "ready": cmd_ready, "unready": cmd_ready,
          "launch": cmd_launch, "leave": cmd_leave, "wait-ingame": cmd_wait_ingame, "lua": cmd_lua}[a.cmd]
    try:
        fn(g, a)
    except (TunerdError, TimeoutError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
