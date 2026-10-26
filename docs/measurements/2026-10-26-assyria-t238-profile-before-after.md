# play_loop --profile, Assyria t238 (S10), before the tool surface (worktree at 7f38d77, the commit before stage 0) and after (main at ea3a6ec), 2026-10-26

## before
```
[16:41:49] ended turn 238 (played 1 this session)
[16:41:49] profile turn 238: 9.1 s wall
[16:41:49]   phase wait_for_my_turn                 4.6 s  x2     30 trips,    0.7 s in the game
[16:41:49]   phase resolve_units_need_orders        2.3 s  x1     35 trips,    1.5 s in the game
[16:41:49]   phase end_turn                         1.3 s  x1      4 trips,    1.1 s in the game
[16:41:49]   phase ensure_production                0.2 s  x1      2 trips,    0.2 s in the game
[16:41:49]   phase ensure_trade_routes              0.2 s  x1      1 trips,    0.2 s in the game
[16:41:49]   unit_mission                          34 trips     1.3 s    0.04 s each
[16:41:49]   end_turn                               4 trips     1.1 s    0.27 s each
[16:41:49]   wait_for_my_turn                      30 trips     0.7 s    0.02 s each
[16:41:49]   units                                  3 trips     0.6 s    0.19 s each
[16:41:49]   cities                                 1 trips     0.1 s    0.05 s each
```

## after
```
[16:42:52] ended turn 238 (played 1 this session)
[16:42:52] profile turn 238: 8.9 s wall
[16:42:52]   phase wait_for_my_turn                 4.5 s  x2     30 trips,    0.7 s in the game
[16:42:52]   phase resolve_units_need_orders        2.2 s  x1     35 trips,    1.4 s in the game
[16:42:52]   phase end_turn                         1.3 s  x1      4 trips,    1.1 s in the game
[16:42:52]   phase ensure_production                0.2 s  x1      2 trips,    0.2 s in the game
[16:42:52]   phase ensure_trade_routes              0.2 s  x1      1 trips,    0.2 s in the game
[16:42:52]   unit_mission                          34 trips     1.2 s    0.04 s each
[16:42:52]   end_turn                               4 trips     1.1 s    0.27 s each
[16:42:52]   wait_for_my_turn                      30 trips     0.7 s    0.02 s each
[16:42:52]   units                                  3 trips     0.5 s    0.18 s each
[16:42:52]   cities                                 1 trips     0.1 s    0.05 s each
```

The same save, the same heuristic player, the same 72 trips (30 wait, 35 unit orders, 4 end, 2 production, 1 trade route); 9.1 s against 8.9 s wall. The surface work changed no trip: scripts/play_loop.py drives harness.Game, and the nine tools run the same handlers.
