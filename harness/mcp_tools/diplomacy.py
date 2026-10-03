"""Diplomacy: leader screens, deals, city-states, war and peace, the victory overviews.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

from harness import mcp_server as core
from harness.mcp_server import mcp, J, guarded


def _with_next(g, out):
    """Another leader queued behind the one just answered (live t136: China, Portugal and Russia in a row at
    one turn start): hand over the next question with the reply, as respond_discussion does, plus the gate
    it raises, so the caller needs no extra read to learn the table is still not free and which tool
    settles it. Anything that cannot be read leaves the reply as it was."""
    if not (isinstance(out, dict) and out.get("ok")):
        return out
    try:
        if not g.discussion_pending():
            return out
        nxt = g.discussion()
        out["still_pending"] = True
        out["next"] = {k: nxt.get(k) for k in ("screen", "player", "leader", "speech", "buttons", "how_to_answer")}
        if nxt.get("screen") == "trade":
            out["next"]["deal"] = g.incoming_deal().get("items")
        out["gate"] = core._gate({"active_player": g.seat, "my_turn": True, "paused": False, "processing": False,
                                  "discussion_pending": True,
                                  "trade_state": "DiploTrade" if nxt.get("screen") == "trade" else None}, g.seat)
    except Exception:  # noqa: BLE001 -- the answer itself was given; the hand-over is a courtesy
        pass
    return out


@mcp.tool()
@guarded
def dismiss_discussion() -> str:
    """Leave an AI leader's negotiation/demand/trade-offer screen (see wait_for_my_turn's discussion_pending)
    without agreeing to anything. For a trade already on the table, prefer incoming_deal + refuse_deal.
    Also closes a plain leader greeting (first meeting, echo of a war/peace just made), and every greeting
    queued behind it (`closed_count`), stopping at a screen that needs an answer. When another leader is queued behind this one (several can wait at a turn start), the answer carries
    `still_pending: true`, `next` (their screen, words, buttons and the deal on the table) and the `gate` it
    raises: answer that one next, no discussion() read needed."""
    g = core.game()
    return J(_with_next(g, g.dismiss_discussion()))


@mcp.tool()
@guarded
def discussion() -> str:
    """What the open leader screen says: the leader, their mood, their speech, the response buttons
    (id + text) and, on a trade screen, the deal on the table; screen="greeting" is a plain
    first-meeting / war / peace message with nothing to decide. Call this whenever turn_status or
    wait_for_my_turn reports discussion_pending, then answer with respond_discussion(button_id),
    accept_deal / refuse_deal (trade screen), or dismiss_discussion (plain acknowledgement, no buttons)."""
    return J(core.game().discussion())


@mcp.tool()
@guarded
def respond_discussion(button_id: int, expect: str = "") -> str:
    """Press one of the response buttons listed by discussion() (1-4). Use this for AI demands,
    warnings, requests and post-deal remarks that offer choices such as apologise / dismiss / threaten.
    expect: optional words the button's text must contain (e.g. "no interest"); if it does not, nothing is
    pressed and the real buttons come back -- guards against pressing a remembered id on a different screen. When another leader is queued behind this one (several can wait at a turn start), the answer carries
    `still_pending: true`, `next` (their screen, words, buttons and the deal on the table) and the `gate` it
    raises: answer that one next, no discussion() read needed."""
    return J(core.game().respond_discussion(button_id, expect))


@mcp.tool()
@guarded
def incoming_deal() -> str:
    """Read the current trade table (scratch deal): items already offered, who they are from. A
    VOTE_COMMITMENT row names the resolution, the pledged choice and the number of votes (`votes`); a
    THIRD_PARTY_WAR / THIRD_PARTY_PEACE row names the third party (`other` player id, `other_name`, `minor`).
    Empty items means no deal is on the table. Does not mutate the deal or open the trade screen."""
    return J(core.game().incoming_deal())


@mcp.tool()
@guarded
def current_deals() -> str:
    """Diplomacy Overview current deals: who, items, turns remaining until each expires.
    Refuses if a trade is already on the scratch table (answer incoming_deal first). Does not
    construct or propose anything."""
    return J(core.game().current_deals())


@mcp.tool()
@guarded
def accept_deal() -> str:
    """Accept an incoming trade already on the table (see incoming_deal). Does not construct a new deal.
    To make an offer of my own use propose_deal. The answer carries the AI's `remark`, the `accepted_items`
    and measured `effects` (gold per turn, deal count, resources before vs after); `new_deal` is the row the deal
    now holds in current_deals (a renewal's offered rows carry the old deal's end; the new end replaces it, the
    offered one stays as `final_turn_offered`). When another leader is queued behind this one (several can wait at a turn start), the answer carries
    `still_pending: true`, `next` (their screen, words, buttons and the deal on the table) and the `gate` it
    raises: answer that one next, no discussion() read needed."""
    g = core.game()
    return J(_with_next(g, g.accept_deal()))


@mcp.tool()
@guarded
def refuse_deal() -> str:
    """Refuse an incoming trade already on the table (see incoming_deal). Does not construct a new deal. When another leader is queued behind this one (several can wait at a turn start), the answer carries
    `still_pending: true`, `next` (their screen, words, buttons and the deal on the table) and the `gate` it
    raises: answer that one next, no discussion() read needed."""
    g = core.game()
    return J(_with_next(g, g.refuse_deal()))


@mcp.tool()
@guarded
def trade_catalog(player_id: int) -> str:
    """What can currently go on a trade table with this major civ (gold, GPT, embassy, open borders, pacts,
    resources, cities as name + `pop`, with x/y only once the plot is revealed, `third_party.war/peace.us/them`
    (the Other Players pocket: every third civ both sides know, `ok` or greyed with the screen's reason), World Congress `vote_commitments`:
    one row per pending proposal + choice either side may pledge, with `votes_us`/`votes_them`), `peace` (at war: the Negotiate
    Peace gate -- `ok`, `locked_turns`, the screen's `note`; the treaty itself is seeded on both sides of any table by the screens). Each resource carries `class`, `us_available`/`them_available` (spare copies each side holds)
    and `last_copy: true` when exporting it would give away our only copy of a luxury (costs happiness).
    Read-only: does not construct or send a deal. City-states: use city_state_gifts."""
    return J(core.game().trade_catalog(player_id))


@mcp.tool()
@guarded
def city_state_gifts(player_id: int) -> str:
    """Gold gift tiers and friendship for a met city-state. See minor_gold_gift to actually gift.
    `ally` is what the city-state screen's ally tooltip shows: {us: true}, {none: true, to_become_ally},
    or the current ally (named only if met) with `to_become_ally` = influence we still need to pass it.
    Other majors' influence is not visible to a player and is not returned.
    Each tier carries `influence_after` and `makes_ally` -- whether that gift actually takes the alliance,
    or `short_by` how much it would miss the civ currently holding it."""
    return J(core.game().city_state_gifts(player_id))


@mcp.tool()
@guarded
def city_capture_options() -> str:
    """When pending_popups shows BUTTONPOPUP_CITY_CAPTURED: the plunder, and each choice the popup offers (liberate /
    annex / puppet / raze) with its unhappiness change and the warmonger warning from the button tooltip."""
    return J(core.game().city_capture_options())


@mcp.tool()
@guarded
def choose_city_capture(choice: str) -> str:
    """Decide a captured city: choice = liberate | annex | puppet | raze (only those city_capture_options lists)."""
    return J(core.game().choose_city_capture(choice))


@mcp.tool()
@guarded
def war_consequences(player_id: int) -> str:
    """Read before declare_war (or city_state_action declare_war): what the game's confirmation screen warns about --
    a Declaration of Friendship being broken, denouncements, city-states allied to the target that join the war,
    majors protecting a targeted city-state, and trade routes that would be cancelled."""
    return J(core.game().war_consequences(player_id))


@mcp.tool()
@guarded
def city_state_actions(player_id: int) -> str:
    """The city-state screen beyond gifts: influence, `quest_list` (structured: type, turns_left, kill-camp
    x/y when that camp is revealed, contest scores), plus the same quest tooltip text as `quests`. Whether I
    can pledge / revoke protection, demand tribute (gold amount, or a Worker; `details` explains the strength
    check), declare war, or make peace."""
    return J(core.game().city_state_actions(player_id))


@mcp.tool()
@guarded
def city_state_action(player_id: int, action: str) -> str:
    """Press one city-state screen button. action: pledge | revoke_pledge | bully_gold | bully_unit |
    declare_war | make_peace. Refused with the current state when the screen would not offer it."""
    return J(core.game().city_state_action(player_id, action))


@mcp.tool()
@guarded
def gift_tile_improvement_options(player_id: int) -> str:
    """The city-state screen's "Gift Improvement" button, and the hexes it would highlight. `can` /
    `cost` / `why_not` are the button (allies only, and the gold has to be there); `plots` is every
    tile within `search_radius` of that city-state's capital where the gift is legal -- the same
    magenta hexes the stock interface mode lights up. A tile I have not revealed is listed as bare
    coordinates. Empty `plots` with `can` true means the ally has nothing left worth improving."""
    return J(core.game().gift_tile_improvement_options(player_id))


@mcp.tool()
@guarded
def gift_tile_improvement(player_id: int, x: int, y: int) -> str:
    """Buy a city-state an improvement on one of its tiles (clicking a highlighted hex). `x`/`y` must
    be a plot from `gift_tile_improvement_options`. Reports the gold spent, the improvement that
    appeared, and influence before/after."""
    return J(core.game().gift_tile_improvement(player_id, x, y))


@mcp.tool()
@guarded
def minor_gold_gift(player_id: int, amount: int) -> str:
    """Gift gold to a city-state. `amount` must be city_state_gifts' small, medium, or large tier.
    Check that tier's `makes_ally` first: influence bought is not the alliance bought when another major
    is sitting above me. The reply says `still_short` when the gift lands under the current ally."""
    return J(core.game().minor_gold_gift(player_id, amount))


@mcp.tool()
@guarded
def demographics() -> str:
    """Demographics: our value/rank and public best, average and worst for population, food,
    production, gold, land, soldiers, approval and literacy. Unmet best/worst identities are masked."""
    return J(core.game().demographics())


@mcp.tool()
@guarded
def domination_progress() -> str:
    """Original capitals of met civilizations and their current holders; unrevealed coordinates
    and unmet holders are masked. Includes whether our team controls each capital."""
    return J(core.game().domination_progress())


@mcp.tool()
@guarded
def wonder_overview() -> str:
    """World wonders held by met civilizations (Global Relations). Locations and captured/builder
    details only for cities in sight."""
    return J(core.game().wonder_overview())


@mcp.tool()
@guarded
def city_state_bonuses(minor_id: int) -> str:
    """Met city-state's trait/bonus and personality tooltips, current food/culture/faith/happiness/
    science benefits, unit gift estimate, unique military unit and exported resources."""
    return J(core.game().city_state_bonuses(minor_id))


@mcp.tool()
@guarded
def gift_unit_options(minor_id: int) -> str:
    """Units that can currently be gifted to this met city-state (the Gift Unit button), with the
    button's figures: `influence_gain` and `travel_turns` (the unit walks there; the influence lands with
    it). While a gift is still on its way (`in_transit.arrives_in`) the list is empty (`why_empty`): a
    city-state takes one gift at a time. gift_unit sends one."""
    return J(core.game().gift_unit_options(minor_id))


@mcp.tool()
@guarded
def gift_unit(minor_id: int, unit_id: int) -> str:
    """Gift one of my units to a met city-state (Network.SendGiftUnit). Verifies the unit left
    our army; `influence_gain` / `travel_turns` say what it earns and when (not at once). Refused while
    an earlier gift is still on its way. Use gift_unit_options to see who can go."""
    return J(core.game().gift_unit(minor_id, unit_id))


@mcp.tool()
@guarded
def diplomacy() -> str:
    """Civs and city-states I have met: at war, score (majors), ally/friends (city-states). Unmet players are omitted."""
    return J(core.game().diplomacy())


@mcp.tool()
@guarded
def relationship(player_id: int) -> str:
    """Our standing with one civ or city-state: their visible approach toward us, friendship /
    denouncements / embassies / open borders / research agreement / defensive pact, the opinion lines
    the game shows, their public relations with every civ we have met (wars, friendships,
    denouncements, city-state alliances) and the recent messages they sent us. `discuss` lists the
    Discuss-screen buttons a human would see (share intrigue, stop spreading religion, stop spying,
    don't settle, stop digging, declare friendship). discussion() includes this for the leader on screen; call it
    directly before proposing or answering anything."""
    return J(core.game().relationship(player_id))


@mcp.tool()
@guarded
def declare_war(player_id: int) -> str:
    """Declare war on a civ I have met. Irreversible for a while (can't make peace again immediately). Bypasses the leader-head screen entirely."""
    return J(core.game().declare_war(player_id))


@mcp.tool()
@guarded
def make_peace(player_id: int, items: list[dict] | None = None) -> str:
    """Offer peace to a civ I'm at war with, through the real trade screen: the treaty goes on both sides and
    `items` (same shapes as propose_deal: GOLD, GOLD_PER_TURN, RESOURCES, CITIES, THIRD_PARTY_WAR/PEACE...) are
    the terms, from_us picking who gives what. An AI answers on the spot (`accepted`, `reply`, `at_war` afterwards;
    it can refuse for a while after a declaration even when nothing locks it). A human seat gets it as a pending
    proposal (`pending: true`) to accept_deal / refuse_deal on its turn. Refused with the leader screen's reason
    while locked into war (see trade_catalog(player_id).peace). Any propose_deal while at war is the same peace deal."""
    return J(core.game().make_peace(player_id, items))


@mcp.tool()
@guarded
def denounce(player_id: int) -> str:
    """Publicly denounce another civ. Worsens relations with them and their friends; cannot be undone."""
    return J(core.game().denounce(player_id))


@mcp.tool()
@guarded
def spaceship_status() -> str:
    """Science-victory progress: whether the Apollo Program is done, for each spaceship part how many are needed,
    already in the ship, built but not yet delivered to the capital, and which tech unlocks it; plus met rivals
    that finished Apollo and how many parts they have (the Victory Progress screen's space race). `complete` once
    every part is in the ship, with `game_over` (the win ends the game at once) and a note on the last part's
    unit, which the engine never gets to remove."""
    return J(core.game().spaceship_status())


@mcp.tool()
@guarded
def culture_overview() -> str:
    """Culture-victory race (the Culture Overview screen): for each met major civ, how many civs it is Influential
    on out of how many it needs, its tourism, and its influence on every other major civ -- level (exotic ..
    dominant), percent, tourism per turn, trend, and turns_to_influential while rising. A civ you have not met
    appears as "unknown". Use it when a "Culture Victory Contender" alert names a rival."""
    return J(core.game().culture_overview())


@mcp.tool()
@guarded
def propose_friendship(player_id: int) -> str:
    """Ask an AI civ for a Declaration of Friendship (the leader screen's "work together"). Refused when already
    friends, asked too recently, at war or unmet. The reply says whether they accepted. Declarations expire after
    their term (a "Declaration of Friendship Has Expired" notification) -- this is how to renew one."""
    return J(core.game().propose_friendship(player_id))


@mcp.tool()
@guarded
def accept_friendship(player_id: int) -> str:
    """Accept a pending Declaration of Friendship proposal (turn_digest's leader_message with state
    DISCUSS_WORK_WITH_US). Works even if the discussion dialog was already dismissed/declined -- the
    request stays acceptable server-side. Check diplomacy() or `IsDoF` via diplo_event's underlying call
    if you need to confirm it actually took."""
    return J(core.game().accept_friendship(player_id))


@mcp.tool()
@guarded
def diplo_event(event: str, player_id: int, data1: int = 0, data2: int = 0) -> str:
    """Escape hatch for any other diplomatic action not covered above (accept/decline a coop-war offer,
    respond to a denounce request, agree to work with someone, etc). `event` is a FromUIDiploEventTypes
    name, with or without its FROM_UI_DIPLO_EVENT_ prefix -- see docs/NOTES.md for the list. Read a
    pending leader_message in turn_digest first to know what's being asked and what data1/data2 should be."""
    return J(core.game().diplo_event(event, player_id, data1, data2))


@mcp.tool()
@guarded
def propose_deal(player_id: int, items: list[dict], ask_counter: bool = False) -> str:
    """Offer a trade to another civ. With an AI: drives the game's real leader / trade screens, proposes, reads
    the reply, closes them and reports measured `effects` (gold, gold/turn, happiness, per-resource
    import/export before vs after): nothing to poll afterwards. With another human seat: puts the same table
    on the PvP deal screen (`pvp: true`, `pending: true`); that seat answers with accept_deal / refuse_deal.
    items: [{"type":"RESOURCES","resource":"RESOURCE_DYE","from_us":true,"amount":1},
            {"type":"GOLD_PER_TURN","from_us":false,"amount":5}]
    Types: GOLD / GOLD_PER_TURN (amount), RESOURCES (resource, amount), OPEN_BORDERS, ALLOW_EMBASSY,
    DEFENSIVE_PACT, RESEARCH_AGREEMENT, TRADE_AGREEMENT (from_us picks the direction), CITIES (city_id),
    VOTE_COMMITMENT (resolution_id, choice_id, repeal), THIRD_PARTY_WAR / THIRD_PARTY_PEACE (other: player
    id), PEACE_TREATY (implied while at war: any deal then is peace with terms; or make_peace).
    Read trade_catalog(player_id) first: what is legal, how much gold each side can put up, which cities may
    be traded (capitals never), the vote and third-party rows. Lump-sum gold needs a Declaration of Friendship
    (a Brave New World rule; trade_catalog's gold.note says so); gold per turn is not gated. Refuses without
    opening a screen an amount that is not a positive whole number or beyond what that side has, a city
    outside the catalog, or an item that does not land on the table at the requested amount. ask_counter=true
    also returns the AI's counter-offer (`counter.items`), which can go straight back in. Timed items last the
    game's deal length (30 turns). Item rules in full: how_to_play("propose_deal")."""
    return J(core.game().propose_deal(player_id, items, ask_counter=ask_counter))


@mcp.tool()
@guarded
def demand(player_id: int, items: list[dict]) -> str:
    """The leader screen's Demand button: tell an AI leader to hand over `items` for nothing, through the
    game's real screens (Demand -> table with only THEIR pocket -> DEMAND -> the leader's answer), then
    close up and report `accepted`, `reply` and measured `effects` like propose_deal. items take
    propose_deal's shapes and are all from_us:false (GOLD, GOLD_PER_TURN, RESOURCES, CITIES, OPEN_BORDERS,
    ALLOW_EMBASSY...); pick from trade_catalog(player_id)'s `them` side. AI leaders only (a human seat has no
    leader screen: propose_deal sends them a table), and the button is greyed at war (make_peace instead).
    As in the stock game a refused demand is remembered against you by that leader; use it deliberately."""
    return J(core.game().demand(player_id, items))


@mcp.tool()
@guarded
def negotiate_deal(player_id: int, items: list[dict], mode: str = "equalize") -> str:
    """Ask an AI civ about a deal without committing to it (the trade screen's helper buttons), then close
    the screen. mode="equalize": put a draft on the table and ask what would make it acceptable;
    "what_will_ai_give": list only my items (from_us=true) and see what the AI offers for them;
    "what_does_ai_want": list only their items (from_us=false) and see what the AI asks in return.
    `items` takes propose_deal's rows, from_us saying who gives each one -- there is no offer/give/receive shape:
    [{"type":"RESOURCES","resource":"RESOURCE_GOLD","from_us":true,"amount":1}, {"type":"GOLD_PER_TURN","from_us":false,"amount":5}]
    Returns the AI's reply and the resulting table `items`, which can be passed to propose_deal as-is."""
    return J(core.game().negotiate_deal(player_id, items, mode=mode))
