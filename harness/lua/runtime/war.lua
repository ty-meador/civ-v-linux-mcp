-- BUTTONPOPUP_CITY_CAPTURED (popupsgeneric/puppetcitypopup.lua): Data1 city, Data2 gold, Data3 culture,
-- Data4 great works, Data5 player to liberate (-1 none), Option1 minor-civ buyout. Buttons: Liberate
-- (Network.SendLiberateMinor), Annex (TASK_ANNEX_PUPPET, hidden by MayNotAnnex), Puppet (TASK_CREATE_PUPPET),
-- Raze (TASK_RAZE behind CanRaze); tooltips carry the unhappiness delta and GetWarmongerPreviewString.
function H.city_capture_popup(pid)
  local info = H.popups[ButtonPopupTypes.BUTTONPOPUP_CITY_CAPTURED]
  if not info or info.player ~= pid then return nil end
  return info
end
function H.city_capture_options(pid)
  local info = H.city_capture_popup(pid)
  if not info then return { ok = false, err = "no captured-city choice is pending" } end
  local p = Players[pid]
  local c = p:GetCityByID(info.data1)
  if not c then return { ok = false, err = "captured city not found" } end
  local prev = c:GetPreviousOwner()
  local base = p:GetUnhappiness()
  local annex = p:GetUnhappinessForecast(c, nil) - base
  if info.option1 then annex = p:GetUnhappinessForecast(nil, c) - base end
  local puppet = p:GetUnhappinessForecast(nil, c) - base
  local war = (prev ~= -1 and info.option2) and p:GetWarmongerPreviewString(prev) or nil
  local out = { ok = true, city = { id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation() },
                gold = info.data2, culture = info.data3, great_works = info.data4,
                happiness_now = p:GetExcessHappiness(), options = {} }
  if info.data5 and info.data5 ~= -1 then
    out.options[#out.options + 1] = { choice = "liberate", to = Players[info.data5]:GetName(),
                                      effect = p:GetLiberationPreviewString(info.data5) }
  end
  if not p:MayNotAnnex() then
    out.options[#out.options + 1] = { choice = "annex", unhappiness = annex, warmonger = war }
  end
  out.options[#out.options + 1] = { choice = "puppet", unhappiness = puppet, warmonger = war }
  if p:CanRaze(c) then
    out.options[#out.options + 1] = { choice = "raze", unhappiness = annex, warmonger = war,
                                      note = "annexed while it burns down one population per turn" }
  end
  return out
end

function H.choose_city_capture(choice, pid)
  local st = H.city_capture_options(pid)
  if not st.ok then return st end
  local offered = false
  for _, o in ipairs(st.options) do if o.choice == choice then offered = true end end
  if not offered then return { ok = false, err = "not offered for this city", options = st.options } end
  local info = H.city_capture_popup(pid)
  local id = info.data1
  if choice == "liberate" then
    Network.SendLiberateMinor(info.data5, id)
  else
    local task = ({ annex = TaskTypes.TASK_ANNEX_PUPPET, puppet = TaskTypes.TASK_CREATE_PUPPET, raze = TaskTypes.TASK_RAZE })[choice]
    Network.SendDoTask(id, task, -1, -1, false, false, false, false)
  end
  return { ok = true, choice = choice, city = st.city }
end

-- What BNW's declare-war confirmation lists (declarewarpopup.lua GatherData): DoF / denouncements with the
-- rival, city-states allied to it (they join the war), majors protecting a targeted city-state, and the
-- trade routes between us that the war cancels. Running deals with the rival end too; the popup reads them
-- through the scratch deal, which this harness never touches headlessly, so they are not itemised here.
function H.war_consequences(other, pid)
  local p, o = Players[pid], Players[other]
  if not o or not o:IsAlive() then return { ok = false, err = "no such living player" } end
  local team = Teams[p:GetTeam()]
  if not team:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  local out = { ok = true, target = o:GetName(), minor = o:IsMinorCiv(), at_war = team:IsAtWar(o:GetTeam()),
                can_declare_war = team:CanDeclareWar(o:GetTeam()) }
  if not o:IsMinorCiv() then
    out.declaration_of_friendship = p:IsDoF(other)
    if out.declaration_of_friendship then out.dof_turns_left = GameDefines.DOF_EXPIRATION_TIME - p:GetDoFCounter(other) end
    out.we_denounced_them = p:IsDenouncedPlayer(other)
    out.they_denounced_us = o:IsDenouncedPlayer(pid)
    out.allied_city_states = {}
    for i = GameDefines.MAX_MAJOR_CIVS, GameDefines.MAX_CIV_PLAYERS - 1 do
      local cs = Players[i]
      if cs and cs:IsAlive() and cs:GetAlly() == other then
        out.allied_city_states[#out.allied_city_states + 1] = { id = i, name = cs:GetName() }
      end
    end
  else
    out.protected_by = {}
    for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
      local m = Players[i]
      if i ~= pid and m and m:IsAlive() and m:IsProtectingMinor(other) then
        out.protected_by[#out.protected_by + 1] = { id = i, civ = m:GetCivilizationShortDescription() }
      end
    end
    out.we_protect_it = p:IsProtectingMinor(other)
  end
  out.trade_routes_lost = {}
  for _, v in ipairs(p:GetTradeRoutes()) do
    if v.ToID == other then
      out.trade_routes_lost[#out.trade_routes_lost + 1] = { ours = true, from = v.FromCityName, to = v.ToCityName }
    end
  end
  for _, v in ipairs(p:GetTradeRoutesToYou()) do
    if v.FromID == other then
      out.trade_routes_lost[#out.trade_routes_lost + 1] = { ours = false, from = v.FromCityName, to = v.ToCityName }
    end
  end
  out.note = "running deals with this player end as well (see their trade screen)"
  return out
end
