"""Crash detection + auto-restart for one game instance.

`tunerd` never dies when the game does -- it just keeps retrying `TunerClient.connect` forever (by
design: the game re-arms its tuner listener on its own after some transitions, e.g. leaving the staging
room, and a plain reconnect is the right response then). What's missing is telling "briefly re-arming"
apart from "the process is actually gone and needs relaunching" -- that's this module's job.

Run one supervisor per instance, alongside its `tunerd`:

    python -m harness.supervisor --name civ5-llm --sock $XDG_RUNTIME_DIR/civ5-llm.sock \\
        --pid-file logs/civ5-llm.pid --launch-cmd "scripts/launch_llm_client.sh"

`--pid-file` is written by scripts/launch_civ5.sh (the reaper's PID; Steam's reaper exits once the whole
sandboxed process tree, Civ5XP included, exits -- a cheap, reliable enough "is this instance still up"
signal without having to find the actual Civ5XP leaf PID through several layers of container wrapping).

On a confirmed-dead instance, the supervisor reruns `--launch-cmd`, waits for the main menu, then replays
whatever `harness/game.py`'s `_save_rejoin()` last recorded (written automatically by `join_lan`/
`host_lan`/`host_hotseat`) to get back into the game, and records a `reconnected` event so `turn_digest`
tells the LLM plainly that some turns may have been missed. Hotseat games can't be auto-rejoined this way
(there's no persistent lobby to reconnect to) -- the supervisor relaunches to the main menu and logs that a
save needs to be reloaded manually.

Without `--launch-cmd` the supervisor only observes and logs; it never restarts anything.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

from .client import Civ5, TunerdError
from .game import Game


def log(msg: str) -> None:
    print(f"[supervisor {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def pid_alive(pid_file: str | None) -> bool | None:
    """True/False if known, None if the pid file doesn't exist or can't be read (treat as unknown --
    unknown must never trigger a restart, to avoid ever double-launching a still-running instance)."""
    if not pid_file or not os.path.exists(pid_file):
        return None
    try:
        pid = int(pathlib.Path(pid_file).read_text().strip())
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (ValueError, OSError):
        return None


def wait_for_main_menu(g: Game, timeout: float, poll: float = 3.0) -> None:
    """g.c.wait_state() fails FAST (tunerd's own connect retry budget is ~1s) rather than blocking for
    `timeout` when the game's tuner port isn't listening yet at all -- true for the first ~45-60s of a cold
    boot (see docs/NOTES.md). Retry here at the polling level instead, the same way game.py's wait_ingame()
    already has to."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            g.c.wait_state("MainMenu", 5)
            return
        except (TunerdError, OSError) as e:
            last_err = e
            time.sleep(poll)
    raise TimeoutError(f"main menu never became reachable within {timeout}s (last error: {last_err})")


def rejoin(sock: str, menu_timeout: float) -> None:
    """After a relaunch: wait for the main menu, then replay the last-saved rejoin state."""
    g = Game(sock)
    wait_for_main_menu(g, menu_timeout)
    state = g.load_rejoin_state()
    if not state:
        log("relaunched to the main menu; no saved rejoin state, stopping here")
        return
    kind = state.get("kind")
    if kind == "lan_join":
        log(f"rejoining LAN game at {state.get('host')!r}")
        g.join_lan(state["host"], nickname=state.get("nickname"), ready=True, timeout=90)
    elif kind == "lan_host":
        log("re-hosting the LAN lobby (launching it again is a separate, manual step)")
        g.host_lan(game_name=state.get("game_name", "LLM Harness"), open_seats=state.get("open_seats"),
                   nickname=state.get("nickname"))
        return
    elif kind == "hotseat":
        log("hotseat games have no persistent lobby to auto-rejoin; relaunched to the main menu only -- "
            "reload the autosave manually if you want to continue this game")
        return
    else:
        log(f"unrecognised rejoin state {kind!r}; leaving at the main menu")
        return
    g.wait_ingame()
    g.note_reconnected()
    log("back in game")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sock", required=True, help="the instance's tunerd unix socket")
    ap.add_argument("--name", required=True, help="instance name, for log lines only")
    ap.add_argument("--pid-file", help="reaper PID file written by launch_civ5.sh (logs/<name>.pid)")
    ap.add_argument("--launch-cmd", help="shell command to relaunch this instance; omit to observe only")
    ap.add_argument("--check-interval", type=float, default=15.0)
    ap.add_argument("--grace-seconds", type=float, default=90.0, help="how long disconnected before considering a restart")
    ap.add_argument("--menu-timeout", type=float, default=180.0, help="how long to wait for the main menu after relaunch (cold boot is ~45-60s)")
    ap.add_argument("--max-restarts", type=int, default=5, help="safety cap against a crash-restart-crash loop")
    a = ap.parse_args(argv)

    bad_since: float | None = None
    restarts = 0
    log(f"watching {a.name} ({a.sock}); restart {'enabled' if a.launch_cmd else 'DISABLED (observing only)'}")
    while True:
        connected = False
        try:
            c = Civ5(a.sock)
            try:
                connected = bool(c.call(op="ping").get("connected"))
            finally:
                c.close()
        except (OSError, TunerdError):
            connected = False  # tunerd itself unreachable counts as "not connected"

        now = time.time()
        if connected:
            if bad_since is not None:
                log(f"{a.name} reconnected on its own")
            bad_since = None
        else:
            if bad_since is None:
                bad_since = now
            elapsed = now - bad_since
            if elapsed >= a.grace_seconds:
                alive = pid_alive(a.pid_file)
                if alive:
                    pass  # process is up, just not re-armed yet (normal after leaving staging room etc.)
                elif alive is None:
                    log(f"{a.name} disconnected {elapsed:.0f}s; no pid file to confirm the process is gone, not restarting")
                elif not a.launch_cmd:
                    log(f"{a.name} disconnected {elapsed:.0f}s and process is gone; no --launch-cmd configured, not restarting")
                elif restarts >= a.max_restarts:
                    log(f"{a.name} disconnected {elapsed:.0f}s and process is gone; restart cap ({a.max_restarts}) reached, giving up")
                else:
                    restarts += 1
                    log(f"{a.name} disconnected {elapsed:.0f}s and process is gone; relaunching (attempt {restarts}/{a.max_restarts})")
                    subprocess.Popen(a.launch_cmd, shell=True)
                    bad_since = None
                    try:
                        rejoin(a.sock, a.menu_timeout)
                    except Exception as e:  # keep supervising no matter what went wrong
                        log(f"rejoin after relaunch failed: {e}")
        time.sleep(a.check_interval)


if __name__ == "__main__":
    sys.exit(main())
