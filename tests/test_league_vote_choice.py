from harness.game import Game


def _game():
    g = Game.__new__(Game)
    g._pid = lambda pid=None: 0
    g.sent = []
    g.q = lambda body: g.sent.append(body) or {"ok": True}
    return g


def test_repeal_without_choice_is_refused():
    g = _game()
    r = g.league_cast_votes([{"resolution_id": 17, "direction": "repeal", "num_votes": 12}])
    assert r["ok"] is False and r["nothing_cast"] and not g.sent


def test_yes_word_becomes_one_and_the_votes_reach_the_wire_as_a_table():
    """Live Assyria t244 (2026-10-26): the votes went as a Lua source string (the pre-v285 `_lua_items`
    encoding) through the call path, which encodes a list itself, and league.lua's ipairs got a string."""
    g = _game()
    g.league_cast_votes([{"resolution_id": 17, "direction": "repeal", "choice": "Yea", "num_votes": 3}])
    call = g.sent[-1]
    assert call.args == [[{"resolution_id": 17, "direction": "repeal", "choice": 1, "num_votes": 3}], False]   # abstain flag after the votes (#89)
    body = str(call).replace(" ", "")
    assert "({{" in body and '["choice"]=1' in body and '("{' not in body   # a table of tables, not a quoted string


def test_unknown_word_refused():
    g = _game()
    r = g.league_cast_votes([{"resolution_id": 17, "direction": "repeal", "choice": "maybe", "num_votes": 3}])
    assert r["ok"] is False and not g.sent
