"""The small reply gaps of the Maya t203-t237 run (GitLab #148), one line each in the issue, one test each here.

A league choice keeps only the lines its details add; a member's unknown interests are a flag; the vote reply
says what was voted; the third-party peace rows nobody can use are counted, not listed; the runtime's plain text
keeps a bare icon's name; a fogged city plot names its city; a completed league project names our tier; a
batch counts its refusals; a leader's remark is never the next leader's opening line; a trade unit's route end
is one row.
"""
import unittest
from unittest import mock

import test_mcp_safety as support
from test_combat_narration import narrate

from harness import mcp_server  # noqa: F401  -- the server registers its tool modules; import it before one of them
from harness.game_parts.deals import DealsMixin
from harness.mcp_tools import batch as batch_mod


class LeagueLeanTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_choice_keeps_only_the_lines_it_adds_to_the_resolution(self):
        self.run_lua("""
        local cd = H.choice_details
        local base = "World Leader\\nThe member with the most votes becomes World Leader.\\nVotes needed: 42"
        assert(cd(base, base) == nil, 'the same text adds nothing')
        local full = base .. "\\nGrateful: Venice, Sweden\\nAngry: China"
        assert(cd(base, full) == "Grateful: Venice, Sweden\\nAngry: China", cd(base, full))
        local mid = "World Leader\\nCandidate: Pacal\\nThe member with the most votes becomes World Leader.\\nVotes needed: 42"
        assert(cd(base, mid) == "Candidate: Pacal", cd(base, mid))
        assert(cd(nil, "all of it") == "all of it", 'no resolution text: the choice keeps its own')
        assert(cd(base, nil) == nil and cd(base, "") == nil)
        """)

    def test_unknown_member_interests_are_a_flag_not_a_paragraph(self):
        self.run_lua("""
        local md = H.member_details
        local row = {}
        md(row, "Delegates: 4[NEWLINE][NEWLINE]Their interests are largely a mystery.")
        assert(row.interests_unknown == true and row.details == "Delegates: 4", H.json(row))
        row = {}
        md(row, "Their interests are largely a mystery.")
        assert(row.interests_unknown == true and row.details == nil, H.json(row))
        row = {}
        md(row, "Delegates: 4[NEWLINE]Wants: Arts Funding")
        assert(row.interests_unknown == nil and row.details == "Delegates: 4\\nWants: Arts Funding", H.json(row))
        """)

    def test_the_vote_reply_says_what_was_voted(self):
        self.run_lua("""
        sent = {}
        GameInfo = { Resolutions = { RESOLUTION_EMBARGO = { Type = 'RESOLUTION_EMBARGO', VoterDecision = 'RESOLUTION_DECISION_YES_OR_NO' },
                                     RESOLUTION_HOST = { Type = 'RESOLUTION_HOST', VoterDecision = 'RESOLUTION_DECISION_MAJOR_CIV_MEMBER' } },
                     ResolutionDecisions = { RESOLUTION_DECISION_MAJOR_CIV_MEMBER = { ID = 3 } } }
        Game.GetActiveLeague = function() return {
          IsInSession = function() return true end, GetID = function() return 1 end,
          GetRemainingVotesForMember = function() return 5 end,
          GetEnactProposals = function() return { { ID = 17, Type = 'RESOLUTION_EMBARGO', ProposerDecision = 4 },
                                                  { ID = 18, Type = 'RESOLUTION_HOST' } } end,
          GetRepealProposals = function() return {} end,
          GetResolutionName = function(_, typ, id, decision) return typ == 'RESOLUTION_EMBARGO' and 'Embargo [ICON_X] Venice' or 'Choose Host' end,
          GetTextForChoice = function(_, decision_id, cid) assert(decision_id == 3); return cid == 2 and '[ICON_CIV] Pacal (Maya)' or '?' end,
        } end
        Network = { SendLeagueVoteEnact = function(...) sent[#sent + 1] = { ... } end,
                    SendLeagueVoteRepeal = function() end, SendLeagueVoteAbstain = function() end }
        local r = H.league_cast_votes({ { resolution_id = 17, direction = 'enact', num_votes = 3, choice = 1 },
                                        { resolution_id = 18, direction = 'enact', num_votes = 2, choice = 2 } }, 0, false)
        assert(r.ok and r.votes_cast == 5 and #r.votes == 2, H.json(r))
        local a, b = r.votes[1], r.votes[2]
        assert(a.resolution_id == 17 and a.name == 'Embargo Venice' and a.choice == 'yes' and a.num_votes == 3 and a.direction == 'enact', H.json(a))
        assert(b.resolution_id == 18 and b.name == 'Choose Host' and b.choice == 2 and b.choice_text == 'Pacal (Maya)', H.json(b))
        """)

    def test_a_completed_project_notice_names_our_tier_and_reward(self):
        self.run_lua("""
        H.league_projects = function(pid) return {
          { project = 'LEAGUE_PROJECT_WORLD_GAMES', name = 'International Games', our_contribution = 412, our_tier = 2,
            rewards = { { tier = 1, text = 'Tier 1: +3 Happiness' }, { tier = 2, text = 'Tier 2: Golden Age' }, { tier = 3, text = 'Tier 3: ...' } } },
          { project = 'LEAGUE_PROJECT_WORLD_FAIR', name = "World's Fair", our_contribution = 0, our_tier = 0, rewards = {} } } end
        local d = { text = 'The International Games project has been completed.', player = 0 }
        H.attach_league_project(d, {})
        assert(d.league_project and d.league_project.our_tier == 2 and d.league_project.reward == 'Tier 2: Golden Age', H.json(d))
        assert(d.league_project.our_contribution == 412 and d.league_project.note == nil, H.json(d))
        d = { text = "The World's Fair project has been completed.", player = 0 }
        H.attach_league_project(d, {})
        assert(d.league_project.our_tier == 0 and d.league_project.note:find('below tier 1', 1, true), H.json(d))
        d = { text = 'A Great Person has been born!', player = 0 }
        H.attach_league_project(d, {})
        assert(d.league_project == nil, 'other notices untouched')
        """)


class PlainTextIconTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_bare_icon_keeps_its_name_as_the_python_side_does(self):
        self.run_lua("""
        local pt = H._ns.plain_text
        assert(pt('+2 [ICON_CULTURE], +2 [ICON_TOURISM]') == '+2 Culture, +2 Tourism', pt('+2 [ICON_CULTURE], +2 [ICON_TOURISM]'))
        assert(pt('+3 [ICON_GOLD] Gold') == '+3 Gold', pt('+3 [ICON_GOLD] Gold'))
        assert(pt('Yields 2 [ICON_PRODUCTION]') == 'Yields 2 Production', pt('Yields 2 [ICON_PRODUCTION]'))
        assert(pt('Portugal[ICON_IDEOLOGY_ORDER][ICON_IDEOLOGY_ORDER], Russia') == 'Portugal Ideology Order Ideology Order, Russia',
               pt('Portugal[ICON_IDEOLOGY_ORDER][ICON_IDEOLOGY_ORDER], Russia'))
        assert(pt('[ICON_BULLET]Wine (2 [ICON_HAPPINESS_1]).') == '• Wine (2 Happiness).', pt('[ICON_BULLET]Wine (2 [ICON_HAPPINESS_1]).'))
        """)


class ThirdPartyPeaceRowsTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_civs_nobody_is_at_war_with_are_counted_not_listed(self):
        self.run_lua("""
        TradeableItems = { TRADE_ITEM_THIRD_PARTY_WAR = 12, TRADE_ITEM_THIRD_PARTY_PEACE = 11 }
        GameDefines = { MAX_CIV_PLAYERS = 5 }
        local function player(id, team, name, minor)
          return { GetID = function() return id end, GetTeam = function() return team end, GetName = function() return name end,
                   IsMinorCiv = function() return minor end, IsAlive = function() return true end,
                   GetAlly = function() return -1 end, IsMinorPermanentWar = function() return false end,
                   IsWillAcceptPeaceWithPlayer = function() return true end }
        end
        Players = { [0] = player(0, 0, 'Maya', false), [1] = player(1, 1, 'Venice', false), [2] = player(2, 2, 'China', false),
                    [3] = player(3, 3, 'Zurich', true), [4] = player(4, 4, 'Sweden', false) }
        WAR = { ['2:1'] = true, ['1:2'] = true }   -- Venice and China fight
        Teams = {}
        for t = 0, 4 do
          Teams[t] = { IsHasMet = function() return true end, IsAtWar = function(_, o) return WAR[t .. ':' .. o] == true end,
                       IsForcePeace = function() return false end }
        end
        Locale = { ConvertTextKey = function(k) return ({ TXT_KEY_DIPLO_NOT_AT_WAR = 'These players are not at war.',
                                                            TXT_KEY_DIPLO_ALREADY_AT_WAR = 'Already at war' })[k] or k end }
        local deal = { IsPossibleToTradeItem = function(_, from, to, item, team)
          if item == 11 then return from == 1 and team == 2 end   -- Venice can make peace with China
          return not (from == 1 and team == 2)                     -- anyone can declare war except Venice on China (already)
        end }
        local out = H.third_party_catalog(deal, 0, 1)
        assert(#out.peace.us == 0 and out.peace.us_not_at_war_omitted == 3, H.json(out.peace))
        assert(#out.peace.them == 1 and out.peace.them[1].name == 'China' and out.peace.them[1].ok == true, H.json(out.peace.them))
        assert(out.peace.them_not_at_war_omitted == 2, H.json(out.peace))
        assert(#out.war.us == 3 and #out.war.them == 3, 'war rows stay: each reason is a fact: ' .. H.json(out.war))
        for _, row in ipairs(out.war.them) do if row.name == 'China' then assert(row.note == 'Already at war', H.json(row)) end end
        """)


class FoggedCityPlotTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_fogged_city_plot_names_its_city_in_the_index_form(self):
        self.run_lua("""
        GameInfo = { Terrains = { [0] = { Type = 'TERRAIN_PLAINS' } }, Resources = {}, Improvements = {}, Routes = { [0] = { Type = 'ROUTE_ROAD' } } }
        local zurich = { GetName = function() return 'Zurich' end, GetOwner = function() return 7 end, IsCapital = function() return true end,
                         GetX = function() return 27 end, GetY = function() return 62 end,
                         GetPopulation = function() error('population is live state') end,
                         GetReligiousMajority = function() error('religion is live state') end }
        GameDefines = { MAX_CIV_PLAYERS = 8 }
        Teams = { [0] = { IsHasMet = function() return true end } }
        Players = { [7] = { IsMinorCiv = function() return true end, IsAlive = function() return true end, GetTeam = function() return 7 end,
                            Cities = function() local done = false; return function() if done then return nil end; done = true; return zurich end end } }
        local plot = { IsRevealed = function() return true end, IsVisible = function() return false end,
                       GetX = function() return 27 end, GetY = function() return 62 end, GetTerrainType = function() return 0 end,
                       IsHills = function() return false end, IsMountain = function() return false end, IsRiver = function() return false end,
                       IsLake = function() return false end, GetResourceType = function() return -1 end,
                       GetRevealedImprovementType = function() return -1 end, GetRevealedRouteType = function() return 0 end,
                       GetRevealedOwner = function() return 7 end,
                       IsCity = function() error('fog cheat: IsCity') end, GetPlotCity = function() error('fog cheat: GetPlotCity') end,
                       GetFeatureType = function() error('live feature read on a fogged plot') end }
        local e = H.describe_plot(plot, 0)
        assert(e.vis == false and e.route == 'ROAD' and e.owner == 7, H.json(e))
        assert(e.city and e.city.name == 'Zurich' and e.city.owner == 7 and e.city.minor == true and e.city.capital == true and e.city.fogged == true, H.json(e.city))
        assert(e.city.pop == nil and e.city.religion == nil and e.city.strength == nil, 'the index facts only: ' .. H.json(e.city))
        """)


class BatchRefusedCountTests(unittest.TestCase):
    def test_a_batch_counts_its_refusals(self):
        def run(actions, results, skipped, deferred, stop):
            results.extend([{"i": 0, "result": {"ok": True}}, {"i": 1, "result": {"ok": False, "err": "no"}},
                            {"i": 2, "result": {"ok": False, "err": "no"}}])

        with mock.patch.object(batch_mod, "_run_orders", side_effect=run), \
                mock.patch.object(batch_mod, "_finish_deferred"), mock.patch.object(batch_mod.core, "game"):
            out = batch_mod.run_batch([{"tool": "x"}] * 3, stop_on_refusal=False)
        self.assertEqual((out["ok"], out["done"], out["refused"]), (False, 3, 2))

        def run_ok(actions, results, skipped, deferred, stop):
            results.append({"i": 0, "result": {"ok": True}})

        with mock.patch.object(batch_mod, "_run_orders", side_effect=run_ok), \
                mock.patch.object(batch_mod, "_finish_deferred"), mock.patch.object(batch_mod.core, "game"):
            out = batch_mod.run_batch([{"tool": "x"}])
        self.assertNotIn("refused", out)


class LeaderRemarkTests(unittest.TestCase):
    def _settle(self, screens, player):
        g = mock.Mock()
        g.discussion = mock.Mock(side_effect=screens)
        with mock.patch("harness.game_parts.deals.time.sleep"), \
                mock.patch("harness.game_parts.deals.time.monotonic", side_effect=[0, 0.1, 0.2, 5, 5, 5]):
            return DealsMixin._settle_leader_remark(g, player=player), g

    def test_another_leaders_screen_is_not_this_leaders_remark(self):
        dido = {"pending": True, "screen": "discussion", "player": 5, "leader": "Dido", "speech": "Greetings from Carthage.",
                "buttons": [{"id": 1, "text": "Fine", "disabled": False}]}
        out, g = self._settle([dido], player=3)
        self.assertEqual(out, {})
        g.dismiss_discussion.assert_not_called()

    def test_the_same_leaders_follow_up_is_next_once(self):
        china = {"pending": True, "screen": "discussion", "player": 3, "speech": "You will regret this.",
                 "buttons": [{"id": 1, "text": "Noted", "disabled": False}]}
        out, _ = self._settle([china], player=3)
        self.assertEqual(out["remark"], "You will regret this.")
        self.assertTrue(out["next"]["same_leader"])
        self.assertEqual(out["next"]["player"], 3)
        self.assertNotIn("follow_up", out)

    def test_a_plain_remark_is_dismissed_as_before(self):
        remark = {"pending": True, "screen": "discussion", "player": 3, "speech": "Very well.", "buttons": [], "can_go_back": True}
        out, g = self._settle([remark], player=3)
        self.assertEqual(out, {"remark": "Very well.", "remark_dismissed": True})
        g.dismiss_discussion.assert_called_once()


class TradeUnitRouteEndTests(unittest.TestCase):
    def test_a_routes_end_is_one_row_even_without_a_plunder_notice(self):
        out = narrate([{"kind": "turn_end", "turn": 230, "data": {"player": 0}},
                       {"kind": "unit_destroyed", "turn": 230, "data": {"player": 0, "unit": 942100, "unit_type": "CARAVAN", "x": 28, "y": 61}},
                       {"kind": "turn_start", "turn": 231, "data": {"player": 0}},
                       {"kind": "unit_lost", "turn": 231, "data": {"unit_id": 942100, "unit": "CARAVAN", "x": 28, "y": 61, "hp_before": 100}}])
        self.assertEqual([e["kind"] for e in out], ["turn_end", "turn_start", "unit_lost"])
        self.assertIn("trade route ended", out[-1]["data"]["summary"])

    def test_a_combat_units_destroyed_row_is_kept(self):
        out = narrate([{"kind": "unit_destroyed", "turn": 230, "data": {"player": 0, "unit": 77, "unit_type": "SPEARMAN", "x": 1, "y": 1}},
                       {"kind": "turn_start", "turn": 231, "data": {"player": 0}},
                       {"kind": "unit_lost", "turn": 231, "data": {"unit_id": 77, "unit": "SPEARMAN", "x": 1, "y": 1, "hp_before": 40}}])
        self.assertIn("unit_destroyed", [e["kind"] for e in out])


if __name__ == "__main__":
    unittest.main()
