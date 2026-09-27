"""Per-game memory for the seat: the notes a human player keeps in their head between turns.

An LLM's context is compacted or lost between sessions; a human remembers "I am going Tradition then
Rationalism, Askia will backstab me, keep two archers in Moson Kahni". `Notebook` stores those notes
beside the game (not inside the save: the save format is not ours) keyed by a `game_key` the caller
derives from stable in-game facts, so every save of the same game shares one notebook and a different
game never sees it. Notes carry the turn they were written on; the caller decides which to surface.

Storage: `$CIV5_NOTES_DIR` or `$XDG_DATA_HOME/civ5-harness/notes` (default `~/.local/share/...`),
one JSON file per game key. No game connection is needed to read or write a notebook. The same file keeps the
seat's last turn-briefing snapshot under `briefing` (harness/briefing.py), what the next briefing compares against,
and the structured `assignments` (harness/assignments.py): role, purpose, fingerprinted units and cities, target,
completion condition, review triggers and status, beside the prose notes and independent of them.
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
    def remember(self, text: str, turn: int, tag: str = "", replace_id: int | None = None,
                 retag: bool = False) -> dict:
        """Append a note, or with `replace_id` rewrite that note in place.

        A replace is guarded: a non-empty `tag` that differs from the stored tag refuses to write (the id
        was probably wrong: a scout note over the plan) unless `retag` is true; an empty tag keeps the stored
        one. Every successful replace returns `previous` (the id, text, tag and turn it overwrote) so a
        mistaken overwrite can be undone by writing the old text back."""
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
                if n.get("id") != replace_id:
                    continue
                stored_tag = n.get("tag", "")
                if tag and tag != stored_tag and not retag:
                    return {"ok": False, "id": replace_id, "stored_tag": stored_tag, "tag": tag,
                            "err": f"note {replace_id} is tagged {stored_tag!r}, not {tag!r}: nothing written. "
                                   f"Pass the right replace_id, an empty tag to keep {stored_tag!r}, "
                                   f"or retag=true to change it"}
                previous = {"id": n.get("id"), "text": n.get("text", ""), "tag": stored_tag, "turn": n.get("turn")}
                n.update({"text": text, "turn": turn, "tag": tag or stored_tag})
                self._save(data)
                out = {"ok": True, "note": n, "replaced": True, "previous": previous}
                if tag and tag != stored_tag:
                    out["retagged"] = True
                return out
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

    # ------------------------------------------------------------ briefing baseline (#30)
    def briefing_baseline(self) -> dict | None:
        """The snapshot the seat's previous briefing left (harness/briefing.py), or None."""
        b = self._load().get("briefing")
        return b if isinstance(b, dict) else None

    def set_briefing_baseline(self, snap: dict) -> None:
        data = self._load()
        data["briefing"] = snap
        self._save(data)

    # ------------------------------------------------------------ assignments (#33)
    # Stored under `assignments` in the same file; harness/assignments.py holds the logic. Status is active,
    # completed, cancelled or replaced; only active ones are reconciled or shown in a briefing.
    def assignments(self, status: str = "active") -> list[dict]:
        rows = [a for a in self._load().get("assignments") or [] if isinstance(a, dict)]
        if status == "all":
            return rows
        if status == "closed":
            return [a for a in rows if a.get("status") != "active"]
        return [a for a in rows if a.get("status") == status]

    def add_assignment(self, record: dict, turn: int, replace_id: int | None = None) -> dict:
        from .assignments import MAX_ACTIVE, MAX_CLOSED
        data = self._load()
        rows = data.setdefault("assignments", [])
        old = None
        if replace_id is not None:
            old = next((a for a in rows if a.get("id") == replace_id), None)
            if old is None or old.get("status") != "active":
                return {"ok": False, "err": f"no active assignment {replace_id} to replace",
                        "active_ids": [a.get("id") for a in rows if a.get("status") == "active"]}
        active = sum(1 for a in rows if a.get("status") == "active") - (1 if old else 0)
        if active >= MAX_ACTIVE:
            return {"ok": False, "err": f"{MAX_ACTIVE} active assignments already: close_assignment finished or "
                                        "abandoned ones first"}
        nid = data.get("next_assignment_id") or (max([a.get("id", 0) for a in rows] + [0]) + 1)
        record = {**record, "id": nid, "status": "active", "created_turn": turn, "updated_turn": turn}
        record.setdefault("history", []).append({"turn": turn, "what": "created" + (f", replacing {replace_id}" if old else "")})
        if old:
            # The obsolete version never competes with its replacement: closed, pointing at it.
            record["replaces"] = replace_id
            old.update({"status": "replaced", "replaced_by": nid, "closed_turn": turn})
            old.setdefault("history", []).append({"turn": turn, "what": f"replaced by {nid}"})
        rows.append(record)
        data["next_assignment_id"] = nid + 1
        self._prune(data, MAX_CLOSED)
        self._save(data)
        return {"ok": True, "assignment": record, **({"replaced": replace_id} if old else {})}

    def update_assignment(self, assignment_id: int, changes: dict, turn: int, what: str,
                          close: str | None = None) -> dict:
        """Apply `changes` to an active assignment (amend), or close it with status `close`."""
        from .assignments import MAX_CLOSED
        data = self._load()
        rows = data.get("assignments") or []
        a = next((r for r in rows if r.get("id") == assignment_id), None)
        if a is None:
            return {"ok": False, "err": f"no assignment {assignment_id}", "ids": [r.get("id") for r in rows]}
        if a.get("status") != "active":
            out = {"ok": False, "err": f"assignment {assignment_id} is {a.get('status')}, not active"}
            if a.get("replaced_by"):
                out["replaced_by"] = a["replaced_by"]
            return out
        previous = {k: a.get(k) for k in changes}
        a.update(changes)
        a["updated_turn"] = turn
        if close:
            a["status"], a["closed_turn"] = close, turn
        hist = a.setdefault("history", [])
        hist.append({"turn": turn, "what": what})
        del hist[:-10]
        self._prune(data, MAX_CLOSED)
        self._save(data)
        return {"ok": True, "assignment": a, **({"previous": previous} if changes else {})}

    def store_observations(self, updates: dict) -> None:
        """What a reconcile saw, per assignment id: the target's latest sighting and the plots the assigned
        units stand on (so a missing unit is looked for where it was last)."""
        if not updates:
            return
        data = self._load()
        for a in data.get("assignments") or []:
            u = updates.get(a.get("id"))
            if not u or a.get("status") != "active":
                continue
            if "seen" in u:
                a["seen"] = u["seen"]
            for uid, x, y in u.get("unit_plots") or []:
                for ref in a.get("units") or []:
                    if ref.get("id") == uid:
                        ref["x"], ref["y"] = x, y
        self._save(data)

    @staticmethod
    def _prune(data: dict, keep_closed: int) -> None:
        rows = data.get("assignments") or []
        closed = [a for a in rows if a.get("status") != "active"]
        if len(closed) > keep_closed:
            drop = {id(a) for a in closed[:len(closed) - keep_closed]}
            data["assignments"] = [a for a in rows if id(a) not in drop]
