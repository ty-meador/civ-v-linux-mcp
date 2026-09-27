function H.notifications(pid)
  local p = Players[pid]
  local out = {}
  local n = p:GetNumNotifications()
  for i = 0, n - 1 do
    if not p:GetNotificationDismissed(i) then
      out[#out + 1] = { index = i, turn = p:GetNotificationTurn(i), summary = p:GetNotificationSummaryStr(i), text = p:GetNotificationStr(i) }
    end
  end
  return out
end
