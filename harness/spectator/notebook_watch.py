"""The seats' notebooks from disk: notes, assignments and orders per seat, whenever a file changes.

harness/notes.py keeps one JSON file per game and seat, `<game_key>-seat<N>.json`, under the notes dir. The
spectator reads the files directly (no trips) and emits the seat's current notes, assignments and orders each time
the file's mtime moves. The `briefing` snapshot in the same file is the seat's private comparison base and is not
emitted. Several games' files share the directory: the game whose files were written most recently is the one being
played, and only its seats are followed (live 2026-09-29: the newest seat-1 file belonged to an older hotseat).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import notes as notes_mod

SEAT_FILE = re.compile(r"^(?P<key>.+)-seat(?P<seat>\d+)\.json$")
NOTE_LIMIT = 40


class NotebookWatch:
    def __init__(self, notes_dir: str | None = None):
        self.dir = Path(notes_dir) if notes_dir else notes_mod.notes_dir()
        self.seen: dict[int, tuple[str, float]] = {}      # seat -> (path, mtime) last emitted

    def poll(self) -> list[dict]:
        """One record per seat whose newest notebook file changed since the last poll."""
        try:
            files = list(self.dir.glob("*-seat*.json"))
        except OSError:
            return []
        by_game: dict[str, dict[int, tuple[float, Path]]] = {}
        for p in files:
            m = SEAT_FILE.match(p.name)
            if not m:
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            by_game.setdefault(m.group("key"), {})[int(m.group("seat"))] = (mtime, p)
        if not by_game:
            return []
        key = max(by_game, key=lambda k: max(mt for mt, _ in by_game[k].values()))
        out = []
        for seat, (mtime, p) in sorted(by_game[key].items()):
            if self.seen.get(seat) == (str(p), mtime):
                continue
            rec = load(p)
            if rec is None:
                continue
            self.seen[seat] = (str(p), mtime)
            out.append({"seat": seat, "game": key, **rec})
        return out


def load(p: Path) -> dict | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    return {"notes": notes[-NOTE_LIMIT:],
            "assignments": data.get("assignments") if isinstance(data.get("assignments"), list) else [],
            "orders": data.get("orders") if isinstance(data.get("orders"), list) else []}
