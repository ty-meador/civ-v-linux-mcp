-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L = H._ns.L

-- The social policy screen as the player sees it: adopted policies, policies adoptable right now,
-- branches with unlocked / can-unlock flags, and whether a policy is affordable this turn.
function H.available_policies(pid)
  local p = Players[pid]
  local out = { adopted = {}, adoptable = {}, branches = {}, culture = p:GetJONSCulture(),
                next_policy_cost = p:GetNextPolicyCost(), free_policies = p:GetNumFreePolicies(),
                free_tenets = p.GetNumFreeTenets and p:GetNumFreeTenets() or 0 }
  -- v260: the screen's tenet buttons light up for culture, a free policy OR a free tenet (socialpolicypopup.lua
  -- 575/608/645, the "Free Tenets" label beside them); the two tenets an ideology grants were invisible here
  -- (live t173, Mongolia: free_policies 0, can_adopt_now false, choose_policy said can_adopt_another false
  -- while the second tenet was still owed and ENDTURN_BLOCKING_FREE_POLICY stood). A free tenet buys only a
  -- tenet of the adopted ideology, never an ordinary policy: `tenets_only` says when that is all there is.
  local affordable = out.free_policies > 0 or out.culture >= out.next_policy_cost
  out.can_adopt_now = affordable or out.free_tenets > 0
  out.tenets_only = (not affordable and out.free_tenets > 0) or nil
  for b in GameInfo.PolicyBranchTypes() do
    local blocked = false
    if p.IsPolicyBranchBlocked then blocked = p:IsPolicyBranchBlocked(b.ID) end
    local finished = false
    if p.IsPolicyBranchFinished then finished = p:IsPolicyBranchFinished(b.ID) end
    -- The engine's CanUnlockPolicyBranch stays true for a branch already unlocked (live Doge t215);
    -- the screen shows no unlock button there, so the row says so too.
    local unlocked = p:IsPolicyBranchUnlocked(b.ID)
    out.branches[#out.branches + 1] = { branch = b.Type, unlocked = unlocked,
      can_unlock = (not unlocked) and p:CanUnlockPolicyBranch(b.ID) or false, blocked = blocked, finished = finished,
      era = b.EraPrereq, ideology = b.PurchaseByLevel or false }
  end
  local open = {}
  for _, b in ipairs(out.branches) do if b.unlocked and not b.finished then open[b.branch] = true end end
  out.locked = {}
  for pol in GameInfo.Policies() do
    local branch = pol.PolicyBranchType
    if p:HasPolicy(pol.ID) then
      out.adopted[#out.adopted + 1] = { policy = pol.Type, branch = branch }
    elseif p:CanAdoptPolicy(pol.ID, true) then  -- true: ignore the culture cost, list what the tree offers next
      out.adoptable[#out.adoptable + 1] = { policy = pol.Type, branch = branch, name = L(pol.Description) }
    elseif open[branch] and not (pol.Level and pol.Level > 0) then
      -- GitLab #123 (Siam t14, t21): the rest of an open branch was invisible, and the agent took its absence
      -- for a bug. The engine's tree: BNW's Legalism needs Oligarchy; Landed Elite and Monarchy need Legalism
      -- (Policy_PrereqPolicies). Each locked policy says what it still needs.
      local needs = {}
      pcall(function()
        for r in GameInfo.Policy_PrereqPolicies{ PolicyType = pol.Type } do
          if r.PolicyType == pol.Type and r.PrereqPolicy then
            local pre = GameInfo.Policies[r.PrereqPolicy]
            if not (pre and p:HasPolicy(pre.ID)) then needs[#needs + 1] = r.PrereqPolicy end
          end
        end
      end)
      out.locked[#out.locked + 1] = { policy = pol.Type, branch = branch, name = L(pol.Description), needs = needs }
    end
  end
  if #out.locked > 0 then
    out.locked_note = "the policies of an open branch not offered yet, with the policies they need first (the engine's tree)"
  else
    out.locked = nil
  end
  return out
end
