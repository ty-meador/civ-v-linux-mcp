#!/usr/bin/env python3
"""Run one LLM CLI (codex or grok) as a hotseat seat, in fresh instances of N turns each.

Each cycle starts a new CLI process (a fresh context window) with the same prompt: read AGENTS.md
in the seat directory, play N game turns through the civ5 MCP tools, write a report into
reports/, stop. When the process exits the loop starts the next cycle. A file named STOP in the
seat directory ends the loop after the current cycle; STOP_NOW kills the current cycle too.

Usage:
  scripts/llm_seat_loop.py --agent codex --seat 0 --dir ~/projects/codex-seat \
      --model gpt-5.6-terra --effort low --turns 20
  scripts/llm_seat_loop.py --agent grok --seat 1 --dir ~/projects/grok-desk-seat \
      --model grok-4.7 --effort low --turns 20

Logs: <log-dir>/<agent>-c<cycle>.jsonl (the CLI's event stream) and <agent>-c<cycle>.err.
The loop's own line-per-event log is <log-dir>/<agent>-loop.log (cycle start/end, exit code,
report path), which is what an observer tails.
"""
import argparse
import datetime as dt
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROMPT = """Read AGENTS.md in this directory first: it says who you are and how the civ5 tools work.

This is one instance of a long game; your context will be reset after this instance. Play exactly
{turns} game turns of your seat, then stop:

1. Call `briefing(since="turn")` first. Your notes from earlier instances (`recall`, and the
   `assignments` shown in the briefing) are the memory that survives resets; trust them over guesses.
   The game turn you see in that first status is T0.
2. Each turn: act on the briefing's decisions and `status.todo`, give every idle unit a standing
   `give_order` where a plan spans turns, `remember()` what future-you must know, then `finish_turn`.
   Use `skip_quiet_turns` when nothing needs you.
3. Stop after `finish_turn` has ended turn T0+{last_offset} (that is {turns} turns ended by you). Do
   not end more turns than that. If the game ends, or a tool reports the game or the bridge is down,
   stop at once instead.
4. Then write `reports/{stamp}.md` in this directory (a plain file, nothing else on disk) with these
   headings: **Turns** (T0 to the last turn you ended, and what you did in one line per turn),
   **Stumbles** (every tool refusal, error, retry, confusing answer, or moment you did not know what
   to call: quote the tool, the arguments and the answer verbatim), **Wishes** (what a tool should
   have told you or done to make this easier), **State for next instance** (your plan, in the words
   you also left with `remember`). Then reply with one line and finish.

Rules: only the civ5 MCP tools touch the game; never run scripts or shell commands against it,
never call `lua`, never `set_seat`, never load a save or leave the game, never write outside this
directory. The other human seat is another LLM; you see nothing of its turn, and you do not try to.
Play to win.
"""


def build_cmd(agent: str, model: str, effort: str, prompt: str, seat_dir: Path, last_msg: Path):
    if agent == "codex":
        return [
            "codex", "exec", "-C", str(seat_dir), "--skip-git-repo-check",
            "--sandbox", "workspace-write", "--json", "-o", str(last_msg),
            "-m", model, "-c", f"model_reasoning_effort={effort!r}",
            # exec never asks; without this the civ5 tools are refused with
            # "MCP tool call requires approval, but approval policy is never"
            "-c", "approval_policy='never'",
            "-c", 'mcp_servers.civ5.default_tools_approval_mode="approve"',
            prompt,
        ]
    if agent == "grok":
        return [
            "grok", "-p", prompt, "-m", model, "--effort", effort,
            "--always-approve", "--no-subagents", "--no-plan",
            "--output-format", "streaming-json",
        ]
    raise SystemExit(f"unknown agent {agent!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", choices=["codex", "grok"], required=True)
    ap.add_argument("--seat", type=int, required=True, help="only for the log line; the seat is pinned in the CLI's MCP config")
    ap.add_argument("--dir", required=True, help="the seat directory (AGENTS.md, reports/)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--turns", type=int, default=20)
    ap.add_argument("--cycles", type=int, default=0, help="0 = until STOP")
    ap.add_argument("--cycle-timeout", type=int, default=4 * 3600, help="seconds before a cycle is killed")
    ap.add_argument("--log-dir", default=str(Path(__file__).resolve().parent.parent / "logs" / "night"))
    ap.add_argument("--start-cycle", type=int, default=1)
    args = ap.parse_args()

    seat_dir = Path(args.dir).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    (seat_dir / "reports").mkdir(parents=True, exist_ok=True)
    loop_log = log_dir / f"{args.agent}-loop.log"

    def log(msg: str) -> None:
        line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {args.agent} seat {args.seat}: {msg}"
        with loop_log.open("a") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    cycle = args.start_cycle
    quick = 0
    log(f"loop start pid {os.getpid()} model {args.model} effort {args.effort} turns/cycle {args.turns}")
    while True:
        if (seat_dir / "STOP").exists() or (seat_dir / "STOP_NOW").exists():
            log("STOP file present, loop ends")
            return 0
        if args.cycles and cycle >= args.start_cycle + args.cycles:
            log("cycle budget spent, loop ends")
            return 0
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        prompt = PROMPT.format(turns=args.turns, last_offset=args.turns - 1, stamp=f"c{cycle}-{stamp}")
        last_msg = log_dir / f"{args.agent}-c{cycle}.last.md"
        out = (log_dir / f"{args.agent}-c{cycle}.jsonl").open("ab")
        err = (log_dir / f"{args.agent}-c{cycle}.err").open("ab")
        cmd = build_cmd(args.agent, args.model, args.effort, prompt, seat_dir, last_msg)
        t0 = time.time()
        log(f"cycle {cycle} start")
        proc = subprocess.Popen(cmd, cwd=str(seat_dir), stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        killed = ""
        while True:
            try:
                rc = proc.wait(timeout=15)
                break
            except subprocess.TimeoutExpired:
                pass
            if (seat_dir / "STOP_NOW").exists():
                killed = "STOP_NOW"
            elif time.time() - t0 > args.cycle_timeout:
                killed = "cycle timeout"
            if killed:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    rc = proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    rc = proc.wait()
                break
        out.close()
        err.close()
        reports = sorted(p for p in (seat_dir / "reports").glob(f"c{cycle}-*.md"))
        log(f"cycle {cycle} end rc {rc} after {int(time.time() - t0)} s"
            + (f" ({killed})" if killed else "")
            + (f" report {reports[-1].name}" if reports else " NO REPORT"))
        cycle += 1
        if killed == "STOP_NOW":
            return 0
        # a cycle that ends within a minute did not play: back off instead of spinning
        if time.time() - t0 < 60:
            quick += 1
            pause = min(600, 60 * quick)
            log(f"cycle ended early ({quick} in a row); pausing {pause} s")
            time.sleep(pause)
        else:
            quick = 0
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
