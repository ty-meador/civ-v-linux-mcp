-- The Culture Overview screen (cultureoverview.lua): its victory tab (every met major civ's influential-on count
-- out of the number needed, and tourism) and its influence tab, where any met civ can be selected to see its
-- influence level on every other living major; civs we have not met show as "unknown", as they do there.
-- Live t444: "Venice only needs ... 2 more civilizations to win a Culture Victory" with no way to see which.
function H.culture_overview(pid)
  local me = Players[pid]
  local myTeam = Teams[me:GetTeam()]
  local levels = { [0] = "exotic", "familiar", "popular", "influential", "dominant" }
  local trends = {}
  pcall(function()
    trends[InfluenceLevelTrend.INFLUENCE_TREND_FALLING] = "falling"
    trends[InfluenceLevelTrend.INFLUENCE_TREND_STATIC] = "static"
    trends[InfluenceLevelTrend.INFLUENCE_TREND_RISING] = "rising"
  end)
  local function civname(p) return Locale.Lookup(p:GetCivilizationShortDescriptionKey()) end
  local out = { civs = {} }
  for i = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
    local s = Players[i]
    if s and s:IsAlive() and not s:IsMinorCiv() and myTeam:IsHasMet(s:GetTeam()) then
      local row = { player = i, civ = civname(s), influential_on = s:GetNumCivsInfluentialOn(),
                    needed = s:GetNumCivsToBeInfluentialOn(), tourism = s:GetTourism(), on = {} }
      if i == pid then row.you = true end
      for j = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
        local t = Players[j]
        if j ~= i and t and t:IsAlive() and not t:IsMinorCiv() then
          local lvl = s:GetInfluenceLevel(j)
          if lvl ~= InfluenceLevelTypes.NO_INFLUENCE_LEVEL then
            local culture = t:GetJONSCultureEverGenerated()
            local e = { level = levels[lvl] or lvl,
                        percent = culture > 0 and math.floor(100 * s:GetInfluenceOn(j) / culture) or 0,
                        tourism_per_turn = math.floor(s:GetInfluencePerTurn(j)),
                        trend = trends[s:GetInfluenceTrend(j)] }
            if myTeam:IsHasMet(t:GetTeam()) then e.player = j; e.civ = civname(t) else e.civ = "unknown" end
            local turns = s:GetTurnsToInfluential(j)
            if e.trend == "rising" and lvl < 3 and turns and turns < 999 then e.turns_to_influential = turns end
            row.on[#row.on + 1] = e
          end
        end
      end
      out.civs[#out.civs + 1] = row
    end
  end
  return out
end

-- The Victory Progress screen's space race (victoryprogress.lua SetProjectValue: Team:GetProjectCount against
-- Project_VictoryThresholds, shown for every known civ that finished Apollo), plus what the tech tree / city
-- screens show a human about the parts: prerequisite tech, whether we have it, finished part units waiting to
-- be moved into the capital. Live t406: which part needs which tech took a raw GameInfo query to find out.
function H.spaceship_status(pid)
  local p = Players[pid]
  local team = Teams[p:GetTeam()]
  local apollo = GameInfoTypes.PROJECT_APOLLO_PROGRAM
  local out = { apollo_done = apollo and team:GetProjectCount(apollo) >= 1 or false, parts = {}, rivals = {} }
  local waiting = {}
  for u in p:Units() do
    local t = GameInfo.Units[u:GetUnitType()]
    if t and t.Type:find("^UNIT_SS_") then waiting[t.Type] = (waiting[t.Type] or 0) + 1 end
  end
  for v in GameInfo.Project_VictoryThresholds() do
    local proj = GameInfoTypes[v.ProjectType]
    local unitType = v.ProjectType:gsub("^PROJECT_", "UNIT_")
    local urow = GameInfo.Units[unitType]
    local tech = urow and urow.PrereqTech or nil
    out.parts[#out.parts + 1] = {
      part = unitType, needed = v.Threshold, in_ship = team:GetProjectCount(proj),
      built_not_delivered = waiting[unitType] or 0,
      tech = tech, have_tech = tech and team:IsHasTech(GameInfoTypes[tech]) or false }
  end
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local q = Players[i]
    if i ~= pid and q and q:IsEverAlive() and not q:IsMinorCiv() and team:IsHasMet(q:GetTeam()) then
      local qt = Teams[q:GetTeam()]
      if apollo and qt:GetProjectCount(apollo) >= 1 then
        local r = { player = i, civ = q:GetCivilizationShortDescription(), parts_in_ship = 0 }
        for v in GameInfo.Project_VictoryThresholds() do r.parts_in_ship = r.parts_in_ship + qt:GetProjectCount(GameInfoTypes[v.ProjectType]) end
        out.rivals[#out.rivals + 1] = r
      end
    end
  end
  out.note = "finished part units must be moved into the capital and added to the ship (the unit's action there)"
  return out
end
