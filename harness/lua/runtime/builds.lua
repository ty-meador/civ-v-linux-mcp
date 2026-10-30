-- A plot build's state, read once and the same way everywhere (GitLab #165, #140).
local info_type, short = H._ns.info_type, H._ns.short
--
-- The stock unit panel prints a worker's progress as "Trading Post (4)": GetBuildTurnsLeft + 1
-- (unitpanel.lua line 392). The order reply used to print the raw number and the unit row the panel's,
-- one apart, so a camp read `turns_left 3` on the order and `build_turns_left 4` on the row the same
-- second (#165). One function gives the panel's number to every reader.
--
-- An Archaeologist's dig keeps the unit's GetBuildType at -1 while the plot carries the build's
-- progress (#140, live Maya t218: `buildtype -1, completed true` the second the dig started, the
-- Trading Post under it gone). The plot is the record of a running build; the unit's own build type
-- is read first and the plot second, for the unit that is on MISSION_BUILD.

-- The panel's remaining-turns number for `bt` on `plot`, or nil when the engine has none (4000+ is its
-- "never"; a plot with nothing of this build in progress reads the full time, which is still its number).
function H.build_turns_left(plot, bt, pid)
  if not plot or not bt or bt < 0 then return nil end
  local ok, turns = pcall(function() return plot:GetBuildTurnsLeft(bt, pid, 0, 0) end)
  if ok and type(turns) == "number" and turns >= 0 and turns < 4000 then return turns + 1 end
  return nil
end

-- The build in progress on `plot`, as plothelpmanager.lua's under-construction line reads it: { build, turns_left }
-- or nil. GetBuildProgress is live information, so callers keep this to visible plots.
function H.plot_under_construction(plot, pid)
  if not (plot and GameInfo and GameInfo.Builds) then return nil end
  local found = nil
  pcall(function()
    for b in GameInfo.Builds() do
      if b and b.ID and plot:GetBuildProgress(b.ID) > 0 then
        found = { build = b.Type, id = b.ID, turns_left = H.build_turns_left(plot, b.ID, pid) }
        return
      end
    end
  end)
  return found
end

-- What `u` is building: { build = BUILD_*, turns_left } from its own build type, else from the plot it stands
-- on when its mission is MISSION_BUILD (a dig), else nil.
function H.unit_build(u, pid, plot)
  if not u then return nil end
  local bt = -1
  pcall(function() bt = u.GetBuildType and u:GetBuildType() or -1 end)
  plot = plot or (u.GetPlot and u:GetPlot()) or nil
  if bt and bt >= 0 then
    local row = GameInfo.Builds and GameInfo.Builds[bt]
    return { build = row and row.Type or nil, id = bt, turns_left = H.build_turns_left(plot, bt, pid) }
  end
  local on_build = false
  pcall(function()
    local m = u.GetMissionType and u:GetMissionType() or -1
    on_build = m ~= -1 and MissionTypes and m == MissionTypes.MISSION_BUILD
  end)
  if not on_build then return nil end
  local uc = H.plot_under_construction(plot, pid)
  if uc then uc.from_plot = true end
  return uc
end

local DIG = "BUILD_ARCHAEOLOGY_DIG"
local ARTIFACT_RESOURCES = { RESOURCE_ARTIFACTS = true, RESOURCE_HIDDEN_ARTIFACTS = true }

-- Whether `u` can ever dig (an Archaeologist): the dig build is among its class's actions.
function H.can_dig(u)
  local can = false
  pcall(function()
    local info = GameInfo.Units[u:GetUnitType()]
    can = info ~= nil and (info.Class == "UNITCLASS_ARCHAEOLOGIST" or info.Type == "UNIT_ARCHAEOLOGIST")
  end)
  return can
end

-- The dig sites an Archaeologist can see (#140): every revealed plot whose resource is an artifact, nearest
-- first, with its owner and whether a dig already runs there. `limit` rows (default 12); `sites_total` counts
-- them all. A site on another civ's land needs open borders, as the stock build does.
function H.dig_sites(u, pid, limit)
  if not (u and H.can_dig(u)) then return nil end
  limit = limit or 12
  local team = Players[pid]:GetTeam()
  local ux, uy = u:GetX(), u:GetY()
  local rows = {}
  local nplots = Map.GetNumPlots and Map.GetNumPlots() or 0
  for i = 0, nplots - 1 do
    local plot = Map.GetPlotByIndex(i)
    if plot and plot:IsRevealed(team, false) then
      local res = plot:GetResourceType(team)
      local info = res and res >= 0 and GameInfo.Resources[res] or nil
      if info and ARTIFACT_RESOURCES[info.Type] then
        local row = { x = plot:GetX(), y = plot:GetY(), resource = info.Type,
                      distance = Map.PlotDistance(ux, uy, plot:GetX(), plot:GetY()) }
        local owner = plot:GetOwner()
        if owner and owner >= 0 then
          row.owner_id = owner
          row.owner = H.owner_label(owner, pid)
        end
        if plot:IsVisible(team, false) then
          local uc = H.plot_under_construction(plot, pid)
          if uc and uc.build == DIG then row.dig_running = true; row.turns_left = uc.turns_left end
          pcall(function()
            local imp = plot:GetImprovementType()
            if imp >= 0 then row.improvement = short(info_type(GameInfo.Improvements, imp)) end
          end)
        end
        rows[#rows + 1] = row
      end
    end
  end
  table.sort(rows, function(a, b)
    if a.distance ~= b.distance then return a.distance < b.distance end
    return a.x < b.x or (a.x == b.x and a.y < b.y)
  end)
  local total = #rows
  while #rows > limit do table.remove(rows) end
  return { sites = rows, sites_total = total,
           hint = "order(to='unit', action='mission', args={mission: 'MISSION_BUILD', build: 'BUILD_ARCHAEOLOGY_DIG'}) on the site; the dig replaces the improvement there and consumes the Archaeologist when it completes" }
end
