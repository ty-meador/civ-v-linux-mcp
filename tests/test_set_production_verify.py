from harness.game import Game


def _game(replies):
    g = Game.__new__(Game)
    g._pid = lambda pid=None: 0
    it = iter(replies)
    g.q = lambda body: next(it)
    return g


def test_dropped_order_is_reported(monkeypatch):
    monkeypatch.setattr("harness.game.time.sleep", lambda s: None)
    g = _game([{"ok": True, "id": 5}, {"ok": True},
               {"ok": True, "production": "", "turns": 2147483647, "queue": []}])
    r = g.set_production(8192, "ORDER_TRAIN", "UNIT_SS_BOOSTER", append=True)
    assert r["ok"] is False and "not queued" in r["err"]


def test_queued_order_passes(monkeypatch):
    monkeypatch.setattr("harness.game.time.sleep", lambda s: None)
    g = _game([{"ok": True, "id": 5}, {"ok": True},
               {"ok": True, "production": "SS Booster", "turns": 12, "queue": ["UNIT_SS_BOOSTER"]}])
    assert g.set_production(8192, "ORDER_TRAIN", "UNIT_SS_BOOSTER")["ok"] is True
