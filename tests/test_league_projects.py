"""World's Fair / International Games / ISS, as the production tooltip and the completion popup show them.

The tooltip (GetProjectDetails) is percent complete, our hammers, and the reward text. Other
civilizations' contributions are not on that screen. They appear only when the project finishes,
and an unmet civ is named as unknown there. An active project must not list the split.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
Locale = { ConvertTextKey = function(k)
  local names = {
    TXT_KEY_LEAGUE_PROJECT_WORLD_FAIR = "World's Fair",
    TXT_KEY_PROCESS_WORLD_FAIR_HELP = "Contribute this city's production towards the World's Fair.",
    TXT_KEY_PROCESS_WEALTH_HELP = "Wealth converts 25% of production into gold.",
    TXT_KEY_PROCESS_WEALTH = "Wealth",
  }
  return names[k] or k
end }
GameDefines = {
  MAX_MAJOR_CIVS = 4,
  LEAGUE_PROJECT_REWARD_TIER_1_THRESHOLD = 0.5,
  LEAGUE_PROJECT_REWARD_TIER_2_THRESHOLD = 1,
}
local contrib = { [0] = 35000, [1] = 70000, [2] = 10000 }
local tiers = { [0] = 1, [1] = 2, [2] = 0 }
local alive = { [0] = true, [1] = true, [2] = false }
local function player(i)
  return {
    IsAlive = function() return alive[i] end,
    IsMinorCiv = function() return false end,
    GetTeam = function() return i end,
    GetCivilizationShortDescription = function() return "Civ" .. i end,
  }
end
Players = { [0] = player(0), [1] = player(1), [2] = player(2) }
Teams = { [0] = { IsHasMet = function() return false end } }
local projects = {
  { ID = 1, Type = "LEAGUE_PROJECT_WORLD_FAIR", Process = "PROCESS_WORLD_FAIR",
    Description = "TXT_KEY_LEAGUE_PROJECT_WORLD_FAIR" },
}
complete = false
league = {
  IsProjectActive = function(_, id) return id == 1 and not complete end,
  IsProjectComplete = function(_, id) return id == 1 and complete end,
  GetProjectCost = function() return 210000 end,
  GetProjectCostPerPlayer = function() return 35000 end,
  GetMemberContribution = function(_, i) return contrib[i] or 0 end,
  GetMemberContributionTier = function(_, i) return tiers[i] or 0 end,
  IsMember = function(_, i) return i <= 2 end,
  GetProjectDetails = function() return "This project is 54% completed." end,
  GetProjectRewardTierDetails = function(_, tier)
    if tier == 1 then return "Bronze: 175 or more" end
    if tier == 2 then return "Silver: 350 or more" end
    return "Gold: highest contributor"
  end,
  IsInSession = function() return false end,
  GetID = function() return 0 end,
  GetName = function() return "Congress" end,
  GetRemainingProposalsForMember = function() return 1 end,
  CanPropose = function() return true end,
  GetHostMember = function() return 0 end,
  CalculateStartingVotesForMember = function() return 2 end,
  GetTurnsUntilSession = function() return 8 end,
  GetInactiveResolutions = function() return {} end,
  GetActiveResolutions = function() return {} end,
  GetEnactProposals = function() return {} end,
  GetRepealProposals = function() return {} end,
}
Game.GetNumActiveLeagues = function() return 1 end
Game.GetActiveLeague = function() return league end
Game.GetVotesNeededForDiploVictory = function() return 0 end
Game.IsUnitedNationsActive = function() return false end
GameInfo = {
  LeagueProjects = function()
    local i = 0
    return function() i = i + 1; return projects[i] end
  end,
}
"""


class LeagueProjectTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_an_active_project_matches_the_tooltip_and_hides_the_split(self):
        self.run_lua("""
        local r = H.league_projects(0)
        assert(#r == 1, 'only the active project')
        local p = r[1]
        assert(p.project == 'LEAGUE_PROJECT_WORLD_FAIR')
        assert(p.name == "World's Fair")
        assert(p.process == 'PROCESS_WORLD_FAIR')
        assert(p.active == true and p.complete == false)
        -- 35000 + 70000 + 10000 dead = 115000; floor(100 * 115000 / 210000) = 54
        assert(p.progress_percent == 54, tostring(p.progress_percent))
        assert(p.cost == 2100 and p.cost_per_player == 350)
        assert(p.our_contribution == 350 and p.our_tier == 1)
        assert(p.tier_1_at == 175 and p.tier_2_at == 350, tostring(p.tier_1_at) .. '/' .. tostring(p.tier_2_at))
        assert(p.details == 'This project is 54% completed.')
        assert(#p.rewards == 3 and p.rewards[1].tier == 1)
        assert(p.contributors == nil, 'the split is not on screen until the project finishes')
        local st = H.league_status(0)
        assert(st.has_league and #st.projects == 1 and st.projects[1].contributors == nil)
        """)

    def test_xml_percent_thresholds_are_the_same_hammers(self):
        """The defines are 50 and 100 in XML. This build's Lua reports 0.5 and 1. Both mean 175 and 350."""
        self.run_lua("""
        GameDefines.LEAGUE_PROJECT_REWARD_TIER_1_THRESHOLD = 50
        GameDefines.LEAGUE_PROJECT_REWARD_TIER_2_THRESHOLD = 100
        local p = H.league_projects(0)[1]
        assert(p.tier_1_at == 175 and p.tier_2_at == 350, tostring(p.tier_1_at) .. '/' .. tostring(p.tier_2_at))
        """)

    def test_a_finished_project_lists_contributions_and_hides_an_unmet_civ(self):
        self.run_lua("""
        complete = true
        local p = H.league_projects(0)[1]
        assert(p.complete == true and p.active == false)
        assert(#p.contributors == 2, 'the dead civ is not on the popup')
        local first, second = p.contributors[1], p.contributors[2]
        assert(first.tier == 2 and first.contribution == 700 and first.civ == 'unknown' and first.player == nil)
        assert(second.you == true and second.player == 0 and second.contribution == 350 and second.tier == 1)
        """)

    def test_the_production_row_carries_the_tooltip_not_the_split(self):
        self.run_lua("""
        local procs = {
          { ID = 1, Type = 'PROCESS_WEALTH', Help = 'TXT_KEY_PROCESS_WEALTH_HELP', Description = 'TXT_KEY_PROCESS_WEALTH' },
          { ID = 2, Type = 'PROCESS_WORLD_FAIR', Help = 'TXT_KEY_PROCESS_WORLD_FAIR_HELP',
            Description = 'TXT_KEY_LEAGUE_PROJECT_WORLD_FAIR' },
        }
        GameInfo.Processes = function()
          local i = 0
          return function() i = i + 1; return procs[i] end
        end
        local city = {
          IsPuppet = function() return false end,
          CanMaintain = function(_, id) return true end,
        }
        Players[0].GetCityByID = function() return city end
        local r = H.available_production(1, 0)
        assert(r.ok)
        local by = {}
        for _, e in ipairs(r.items) do by[e.item] = e end
        assert(by.PROCESS_WEALTH.help == 'Wealth converts 25% of production into gold.')
        assert(by.PROCESS_WEALTH.league_project == nil)
        assert(by.PROCESS_WEALTH.name == 'Wealth')
        local fair = by.PROCESS_WORLD_FAIR
        assert(fair.help == "Contribute this city's production towards the World's Fair.")
        assert(fair.name == "World's Fair")
        assert(fair.league_project.progress_percent == 54)
        assert(fair.league_project.our_contribution == 350)
        assert(fair.league_project.tier_1_at == 175)
        assert(fair.league_project.details == 'This project is 54% completed.')
        assert(fair.league_project.contributors == nil)
        """)


if __name__ == "__main__":
    unittest.main()
