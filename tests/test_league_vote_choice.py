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


def test_yes_word_becomes_one():
    g = _game()
    g.league_cast_votes([{"resolution_id": 17, "direction": "repeal", "choice": "Yea", "num_votes": 3}])
    assert "choice=1" in g.sent[-1].replace(" ", "")


def test_unknown_word_refused():
    g = _game()
    r = g.league_cast_votes([{"resolution_id": 17, "direction": "repeal", "choice": "maybe", "num_votes": 3}])
    assert r["ok"] is False and not g.sent
