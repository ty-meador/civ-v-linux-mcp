"""Per-game memory for the seat: the notes a human player keeps in their head between turns.

An LLM's context is compacted or lost between sessions; a human remembers "I am going Tradition then
Rationalism, Askia will backstab me, keep two archers in Moson Kahni". `Notebook` stores those notes
beside the game (not inside the save: the save format is not ours) keyed by a `game_key` the caller
derives from stable in-game facts, so every save of the same game shares one notebook and a different
game never sees it. Notes carry the turn they were written on; the caller decides which to surface.

Storage: `$CIV5_NOTES_DIR` or `$XDG_DATA_HOME/civ5-harness/notes` (default `~/.local/share/...`),
one JSON file per game key. No game connection is needed to read or write a notebook.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


MAX_NOTES = 200
MAX_TEXT = 2000


def notes_dir() -> Path:
    d = os.environ.get("CIV5_NOTES_DIR")
    if d:
        return Path(d)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "civ5-harness" / "notes"


def safe_key(key: str) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", key.strip()) or "game"
    return key[:120]


class Notebook:
    def __init__(self, game_key: str, seat: int):
        self.key = safe_key(f"{game_key}-seat{seat}")
        self.path = notes_dir() / f"{self.key}.json"

    # ------------------------------------------------------------ io
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {"next_id": 1, "notes": []}
        if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
            return {"next_id": 1, "notes": []}
        data.setdefault("next_id", max([n.get("id", 0) for n in data["notes"]] + [0]) + 1)
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0))
        os.replace(tmp, self.path)

    # ------------------------------------------------------------ api
    def remember(self, text: str, turn: int, tag: str = "", replace_id: int | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "err": "empty note"}
        if len(text) > MAX_TEXT:
            return {"ok": False, "err": f"note longer than {MAX_TEXT} characters; split it"}
        tag = (tag or "").strip()[:40]
        data = self._load()
        notes = data["notes"]
        if replace_id is not None:
            for n in notes:
                if n.get("id") == replace_id:
                    n.update({"text": text, "turn": turn, "tag": tag or n.get("tag", "")})
                    self._save(data)
                    return {"ok": True, "note": n, "replaced": True}
            return {"ok": False, "err": f"no note with id {replace_id}", "ids": [n.get("id") for n in notes]}
        note = {"id": data["next_id"], "turn": turn, "tag": tag, "text": text}
        data["next_id"] += 1
        notes.append(note)
        dropped = 0
        if len(notes) > MAX_NOTES:
            dropped = len(notes) - MAX_NOTES
            del notes[:dropped]
        self._save(data)
        out = {"ok": True, "note": note, "count": len(notes)}
        if dropped:
            out["dropped_oldest"] = dropped
        return out

    def recall(self, tag: str = "", limit: int = 50) -> dict:
        notes = self._load()["notes"]
        if tag:
            notes = [n for n in notes if n.get("tag") == tag]
        notes = notes[-max(1, limit):]
        return {"ok": True, "notes": notes, "count": len(notes), "game": self.key}

    def forget(self, note_id: int) -> dict:
        data = self._load()
        before = len(data["notes"])
        data["notes"] = [n for n in data["notes"] if n.get("id") != note_id]
        if len(data["notes"]) == before:
            return {"ok": False, "err": f"no note with id {note_id}", "ids": [n.get("id") for n in data["notes"]]}
        self._save(data)
        return {"ok": True, "forgotten": note_id, "count": len(data["notes"])}

    def latest(self, limit: int = 8) -> list[dict]:
        """The most recent notes, for the turn hand-off: the plan arrives with the turn."""
        return self._load()["notes"][-limit:]
