# Save library: the reproduction states

Every live claim in `docs/GAPS.md` and `CHANGELOG.md` names one of these states. They are copies of the
game's own `.Civ5Save` files (GitLab #28); the originals live under
`~/.local/share/Aspyr/Sid Meier's Civilization 5/Saves/` (`single/` and `hotseat/`).

| Key | File | Game | Turn | Use it for |
|---|---|---|---|---|
| S1 | `Pocatello_0266 solo-final` | solo, Shoshone (Pocatello), Emperor, 4 AI majors met, World Congress | 266 | AI diplomacy (Demand, propose/negotiate_deal, Discuss), embassies, spies, late-game culture/religion screens, city hovers, Freedom ideology (switch button grey) |
| S2 | `Alpha-Bravo_0227 peace` | hotseat, two human seats: Alpha (Korea, seat 0) vs Bravo (Austria, seat 1), Duel, Atomic start, at peace after a war | 227 | PvP deals, scratch-deal payload reads, city-state greeting popup |
| S2a | `Alpha-Bravo_0229 pvp-deals` | same, after the first accept/refuse round trips | 229 | current_deals between humans |
| S2v | `Alpha-Bravo_0233 vote-pledge` | same; Alpha's Diplomat in Vienna, Alpha hosts the UN, Cultural Heritage Sites proposed, Bravo's Yea pledge + open borders running to t258 | 233 | World Congress vote commitments on the trade table |
| S2b | `Alpha-Bravo_0237 peace-terms` | same; Bravo's turn 237 right after accepting peace + Silk + Salzburg (treaty to t247, deal to t262) | 237 | the ceded city's first turns, peace-with-terms deal rows, a fresh 10-turn forced peace; war again from t247 for the human-captor half of #22 |
| S3 | `Pocatello_0266 combat-lab` | S1 plus barbarian test units: Warrior on the hills at (49,18), Archer at (48,18), raider at (47,13) beside a Worker; Musketman 630799 has Drill I | 266 | combat previews and modifier rows (rough/open terrain, flanking, Great General, vs barbarians), barbarian captures in sight; fire support is off in stock BNW |

## Loading one

The files keep the game's own names, so copy one back into the matching folder (`single/` for S1 and S3,
`hotseat/` for the S2 family) and load it by its bare name with the harness at the main menu:

```
python -m harness.cli lua "Events.ExitToMainMenu()"            # only if a game is already loaded
.venv/bin/python scripts/mcp_call.py --seat 0 load_save '{"filename": "Alpha-Bravo_0237 peace-terms"}'
```

A hotseat save loads only through the hotseat listing, which `load_save` searches. After a hotseat load the
game sits paused on the hand-off screen: `wait_for_my_turn` on the *active* seat clears it.

## Making a new one

`quick_save` writes `Saves/single/quick/QuickSave.Civ5Save` for every mode (hotseat too), one slot, so name
anything worth keeping right away:

```
.venv/bin/python scripts/mcp_call.py --seat 1 quick_save '{}'
cp "$SAVES/single/quick/QuickSave.Civ5Save" "$SAVES/hotseat/Alpha-Bravo_0240 what-it-shows.Civ5Save"
```

Scenario surgery goes through `harness.cli lua` (`Players[p]:InitUnit`, `Teams[t]:SetHasTech`,
`Teams[a]:Meet(b)`, `Players[p]:ChangeGold`, `Unit:SetHasPromotion`); `docs/GAPS.md` records what each
spawn cost (a barbarian spawned onto a Great General's tile destroys the general).
