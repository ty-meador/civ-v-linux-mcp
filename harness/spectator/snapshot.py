"""The dynamic map, on demand: players, cities, units, borders, the active player and the turn, fog ignored.

Everything the page draws that moves. Units late in a big game are a few hundred rows (~15 KB); the owner grid is
one character per plot with a legend (character -> player id). Runs through the raw client's query.
"""
from __future__ import annotations

from typing import Any

from . import query as Q

LUA = r"""
local out = { ok = true, turn = Game.GetGameTurn(), active = Game.GetActivePlayer(), players = {}, cities = {}, units = {} }
pcall(function() out.over = Game.GetGameState() ~= GameplayGameStateTypes.GAMESTATE_ON end)
local POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
local owner_char, legend, n = {}, {}, 0
local function short(t, prefix) return t and (t:gsub("^" .. prefix, "")) or "?" end
for pid = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
  local p = Players[pid]
  if p and p:IsEverAlive() then
    local row = { id = pid, alive = p:IsAlive(), human = p:IsHuman(), minor = p:IsMinorCiv(), barb = p:IsBarbarian(),
                  team = p:GetTeam(), score = p:GetScore() }
    pcall(function() row.name = p:GetName() end)
    pcall(function()
      local ci = GameInfo.Civilizations[p:GetCivilizationType()]
      row.civ = ci and Locale.ConvertTextKey(ci.ShortDescription) or nil
    end)
    pcall(function() row.gold = p:GetGold() end)
    pcall(function()
      local pc = GameInfo.PlayerColors[p:GetPlayerColor()]
      local c1 = pc and GameInfo.Colors[pc.PrimaryColor]
      local c2 = pc and GameInfo.Colors[pc.SecondaryColor]
      if c1 then row.color = { math.floor(c1.Red * 255 + 0.5), math.floor(c1.Green * 255 + 0.5), math.floor(c1.Blue * 255 + 0.5) } end
      if c2 then row.color2 = { math.floor(c2.Red * 255 + 0.5), math.floor(c2.Green * 255 + 0.5), math.floor(c2.Blue * 255 + 0.5) } end
    end)
    out.players[#out.players + 1] = row
    if row.alive then
      n = n + 1
      local ch = n <= #POOL and POOL:sub(n, n) or "?"
      owner_char[pid] = ch
      legend[ch] = pid
      for c in p:Cities() do
        local city = { id = c:GetID(), o = pid, x = c:GetX(), y = c:GetY(), pop = c:GetPopulation(), cap = c:IsCapital() }
        pcall(function() city.n = c:GetName() end)
        pcall(function() city.hp = c:GetMaxHitPoints() - c:GetDamage() end)
        pcall(function() city.puppet = c:IsPuppet() end)
        out.cities[#out.cities + 1] = city
      end
      for u in p:Units() do
        local ui = GameInfo.Units[u:GetUnitType()]
        local unit = { id = u:GetID(), o = pid, x = u:GetX(), y = u:GetY(), t = short(ui and ui.Type, "UNIT_"),
                       hp = u:GetCurrHitPoints() }
        pcall(function() unit.mhp = u:GetMaxHitPoints() end)
        pcall(function() if not u:IsCombatUnit() then unit.civ = true end end)
        pcall(function()
          local d = u:GetDomainType()
          unit.d = (d == DomainTypes.DOMAIN_SEA and "S") or (d == DomainTypes.DOMAIN_AIR and "A") or "L"
        end)
        pcall(function() if u:IsEmbarked() then unit.emb = true end end)
        out.units[#out.units + 1] = unit
      end
    end
  end
end
local w, h = Map.GetGridSize()
local rows = {}
for y = h - 1, 0, -1 do
  local line = {}
  for x = 0, w - 1 do
    local p = Map.GetPlot(x, y)
    local o = p and p:GetOwner() or -1
    line[#line + 1] = (o >= 0 and owner_char[o]) or "."
  end
  rows[#rows + 1] = table.concat(line)
end
out.owners = { rows = rows, legend = legend }
return out
"""


def read(client: Any, timeout: float = 60) -> dict:
    return Q.query(client, LUA, timeout=timeout)


def valid(s: Any) -> bool:
    return (isinstance(s, dict) and s.get("ok") is True and isinstance(s.get("turn"), int)
            and isinstance(s.get("players"), list) and isinstance(s.get("units"), list)
            and isinstance(s.get("cities"), list))
