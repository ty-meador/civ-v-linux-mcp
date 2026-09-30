"""Tail a JSONL call ledger (harness/call_ledger.py): new complete rows on every poll, from where it left off.

A file that shrank (truncated, rotated) is read again from the start; a partial last line waits for its newline;
a line that is not JSON is skipped. No inotify: the spectator polls twice a second, which is finer than a trip.
"""
from __future__ import annotations

import json
import os
from typing import Iterator


class LedgerTail:
    def __init__(self, path: str, from_start: bool = False):
        self.path = path
        self.offset = 0
        self.partial = b""
        if not from_start:
            try:
                self.offset = os.path.getsize(path)
            except OSError:
                self.offset = 0

    def poll(self) -> list[dict]:
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []
        if size < self.offset:
            self.offset, self.partial = 0, b""
        if size == self.offset:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(size - self.offset)
        except OSError:
            return []
        self.offset = size
        data = self.partial + chunk
        lines = data.split(b"\n")
        self.partial = lines.pop()          # b"" when the chunk ended in a newline
        return list(_rows(lines))


def _rows(lines: list[bytes]) -> Iterator[dict]:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            yield r
