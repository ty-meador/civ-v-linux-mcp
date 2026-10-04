"""The client label of a ledger row and a turn claim comes from the SDK's per-request Context (mcp 2.x).

Until 2026-10-04 `_client_info` read `request_context` off the server object, an attribute mcp 2.x does not
have, so every row of a Claude Code or scripts/mcp_session.py session was written without `client` (417 rows
that day) and a turn-claim refusal could never say `same_client`. The tool manager passes the Context to
call_tool; the first clientInfo seen is kept for the claim, which is written from a worker thread.
"""
from types import SimpleNamespace

import pytest

from harness import call_ledger
from harness import mcp_server


def _context(name="claude-code", version="2.1.289", field="client_info"):
    info = SimpleNamespace(name=name, version=version)
    params = SimpleNamespace(**{field: info})          # mcp 2.x: client_info; 1.x: clientInfo
    session = SimpleNamespace(client_params=params)
    return SimpleNamespace(request_context=SimpleNamespace(session=session))


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(mcp_server, "_CLIENT_INFO", None)
    monkeypatch.delenv(call_ledger.CLIENT_ENV, raising=False)


def test_client_info_comes_from_the_request_context():
    info = mcp_server._client_info(_context())
    assert (info.name, info.version) == ("claude-code", "2.1.289")
    assert call_ledger.client(info) == "claude-code/2.1.289"


def test_the_older_sdk_spelling_is_read_too():
    info = mcp_server._client_info(_context("codex", "1.0", field="clientInfo"))
    assert call_ledger.client(info) == "codex/1.0"


def test_first_client_info_is_kept_for_calls_without_a_context():
    assert mcp_server._client_info() is None          # nothing seen yet: no label, no crash
    mcp_server._client_info(_context("probe", "9.9"))
    kept = mcp_server._client_info()                   # the claim lambda calls it this way, off-request
    assert call_ledger.client(kept) == "probe/9.9"


def test_a_context_without_a_session_is_tolerated():
    class Raising:
        @property
        def request_context(self):
            raise LookupError("outside a request")

    assert mcp_server._client_info(Raising()) is None
    assert mcp_server._client_info(SimpleNamespace(request_context=None)) is None
