---------------------------------------------------------------- JSON
local function esc(s)
  return s:gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' elseif c == '\\' then return '\\\\'
    elseif c == '\n' then return '\\n' elseif c == '\r' then return '\\r' elseif c == '\t' then return '\\t'
    else return string.format('\\u%04x', c:byte()) end end)
end
function H.json(v, depth)
  depth = depth or 0
  local t = type(v)
  if t == "nil" then return "null"
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if v == math.floor(v) then return string.format("%d", v) end
    return string.format("%.6g", v)
  elseif t == "string" then return '"' .. esc(v) .. '"'
  elseif t == "table" then
    if depth > 14 then return '"<deep>"' end
    if v[1] ~= nil or next(v) == nil then
      local parts = {}
      for i = 1, #v do parts[i] = H.json(v[i], depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do parts[#parts + 1] = '"' .. esc(tostring(k)) .. '":' .. H.json(val, depth + 1) end
    return "{" .. table.concat(parts, ",") .. "}"
  else return '"<' .. t .. '>"' end
end
function H.emit(v) print("@@HJ@@" .. H.json(v) .. "@@HJ@@") end
