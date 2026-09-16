# How the stock UI issues player commands (call-site excerpts)

## Unit missions (unitpanel.lua / worldview.lua)
```lua

else--if plot == UI.GetGotoPlot() then
end
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_RANGED_ATTACK, plotX, plotY);
Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_COMMAND, CommandTypes.COMMAND_CANCEL_ALL);
Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, eInterfaceModeMission, plotX, plotY, 0, false, bShift);
Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, iMission, plotX, plotY, 0, false, bShift);
Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, MissionTypes.MISSION_DISEMBARK, plotX, plotY, 0, false, bShift);
Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, MissionTypes.MISSION_EMBARK, plotX, plotY, 0, false, bShift);
Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, MissionTypes.MISSION_RANGE_ATTACK, plotX, plotY, 0, false, bShift);
if bBombardEnemy == false then
if bShift == false and pHeadSelectedUnit:AtPlot(plot) then
if eInterfaceModeMission ~= MissionTypes.NO_MISSION then
if pHeadSelectedCity and pHeadSelectedCity:CanRangeStrike() then
if pHeadSelectedCity:CanRangeStrikeAt(plotX,plotY, true, true) then
if pHeadSelectedUnit and pHeadSelectedUnit:CanRangeStrikeAt(plotX, plotY, true, true) then
if (pHeadSelectedUnit:CanDisembarkOnto(plot)) then
if (pHeadSelectedUnit:CanEmbarkOnto(pHeadSelectedUnit:GetPlot(), plot)) then
if pHeadSelectedUnit then
if UI.CanDoInterfaceMode(interfaceMode) then
local activePlayerID = Game.GetActivePlayer();
local eInterfaceModeMission = GameInfoTypes[GameInfo.InterfaceModes[interfaceMode].Mission];
local interfaceMode = UI.GetInterfaceMode();
UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION);
```

## Selecting units / moving (worldview.lua, ingame.lua)
```lua
Data1 = UI.GetHeadSelectedUnit():GetID(),
elseif( bDisplayCivilianYields and UI.CanSelectionListFound() ) then
Game.CycleUnits(true, false, false);
Game.CycleUnits(true, true, false);
Game.SelectionListMove(plot,  bAlt, bShift, bCtrl);
Game.SelectionListMove(plot, false, false, false);
if( bDisplayCivilianYields and UI.CanSelectionListWork() and bShowYields) then
if (not UI.CanSelectionListFound()) then
if (not UI.CanSelectionListWork()) then
if (UI.CanSelectionListFound() and player:GetNumCities() > 0) then
if (UI.CanSelectionListWork()) then
if( UI.GetHeadSelectedUnit() ~= NULL ) then
if UI.GetHeadSelectedUnit() then
local pHeadSelectedUnit = UI.GetHeadSelectedUnit();
local pUnit = UI.GetHeadSelectedUnit();
local unit = UI.GetHeadSelectedUnit();
--print("Game.SelectionListMove(plot,  bAlt, bShift, bCtrl);");
UI.CanSelectionListFound() ) then
--UI.LookAt(lastCityEntered:Plot(), 1);
UI.LookAt(lastCityEnteredPlot, 2);
UI.LookAtSelectionPlot(0);
UI.SetInterfaceMode( InterfaceModeTypes.INTERFACEMODE_MOVE_TO );
--UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION);
UI.SetInterfaceMode( InterfaceModeTypes.INTERFACEMODE_SELECTION );
UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION);
```

## City production / purchase (productionpopup / cityview)
```lua
Game.CityPurchaseBuilding(city, iData, eYield);
Game.CityPurchaseProject(city, iData, eYield);
Game.CityPurchaseUnit(city, iData, eYield);
Game.CityPushOrder(city, eOrder, iData, false, not g_append, true);
--Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_ADD_SPECIALIST, iSpecialist, iBuilding);
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_ADD_SPECIALIST, iSpecialist, iBuilding);
--Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_NO_AUTO_ASSIGN_SPECIALISTS, -1, -1, bValue);
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_NO_AUTO_ASSIGN_SPECIALISTS, -1, -1, bValue);
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_NO_AUTO_ASSIGN_SPECIALISTS, -1, -1, true);
--Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_REMOVE_SPECIALIST, iSpecialist, iBuilding);
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_REMOVE_SPECIALIST, iSpecialist, iBuilding);
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_POP_ORDER, num);
Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_SWAP_ORDER, num);
--Network.SendCityBuyPlot(pHeadSelectedCity:GetID(), plotX, plotY);
Network.SendCityBuyPlot(pHeadSelectedCity:GetID(), plotX, plotY);
Network.SendSellBuilding(pCity:GetID(), g_iBuildingToSell);
Network.SendSetCityAIFocus( pCity:GetID(), focus );
Network.SendUpdateCityCitizens(pCity:GetID());
```

## Research / policies / religion / diplomacy
```lua
if Network.SendTurnUnready() then
Network.SendArchaeologyChoice(Game.GetActivePlayer(), g_iUnitIndex, g_iChoice);
Network.SendChangeIdeology();
Network.SendChangeWar(eRivalTeam, true);
Network.SendChangeWar(eRivalTeam, true);	
Network.SendChangeWar(g_iMinorCivTeamID, false);
Network.SendChangeWar(g_iMinorCivTeamID, true);
Network.SendChangeWar( g_WarTarget, true);
Network.SendChat( text, g_iChatTeam, g_iChatPlayer );
Network.SendDiploVote(iVotePlayer);
Network.SendEnhanceReligion(Game.GetActivePlayer(), g_CurrentReligionID, customName, g_Beliefs[4], g_Beliefs[5], g_iCityX, g_iCityY);
Network.SendFaithPurchase(Game.GetActivePlayer(), v1, v2);
Network.SendFoundPantheon(Game.GetActivePlayer(), g_BeliefID);
Network.SendFoundReligion(Game.GetActivePlayer(), g_CurrentReligionID, customName, beliefsToSend[1], beliefsToSend[2], beliefsToSend[3], beliefsToSend[4], g_iCityX, g_iCityY);
Network.SendGoodyChoice(playerID, pPlot:GetX(), pPlot:GetY(), iGoodyType, pUnit:GetID());
Network.SendGreatPersonChoice(playerID, unit.ID);
Network.SendIdeologyChoice(Game.GetActivePlayer(), g_iChoice);
Network.SendLeagueProposeEnact(controller.LeagueId, proposal.Type, controller.ActivePlayerId, choice);
Network.SendLeagueVoteAbstain(controller.LeagueId, controller.ActivePlayerId, controller.VotesAvailable);
Network.SendLeagueVoteEnact(controller.LeagueId, entry.ResolutionId, controller.ActivePlayerId, votes, choice);	
Network.SendLeagueVoteRepeal(controller.LeagueId, entry.ResolutionId, controller.ActivePlayerId, votes, choice);	
Network.SendLiberateMinor(eMinor, iCityID);
Network.SendLiberateMinor(iLiberatedPlayer, cityID);
Network.SendMayaBonusChoice(playerID, unit.ID);
Network.SendMoveSpy(Game.GetActivePlayer(), g_SelectedAgentID, -1, -1, false);
Network.SendMoveSpy(Game.GetActivePlayer(), selectedAgentIndex, v.PlayerID, v.CityID, false);
Network.SendMoveSpy(Game.GetActivePlayer(), selectedAgentIndex, v.PlayerID, v.CityID, true);
Network.SendPledgeMinorProtection(g_iMinorCivID, false);
Network.SendPledgeMinorProtection(g_iMinorCivID, true);
Network.SendResearch(eTech, 0, iValue, false);
Network.SendResearch(eTech, 0, stealingTechTargetPlayerID, UIManager:GetShift());
Network.SendResearch(eTech, iDiscover, -1, false);
Network.SendResearch(eTech, iValue, -1, false); -- iValue is number of free (non-espionage) techs
Network.SendResearch(eTech, player:GetNumFreeTechs(), -1, UIManager:GetShift());
Network.SendStageCoup(Game.GetActivePlayer(), v.AgentID);
Network.SendUpdatePolicies(g_SelectedTenet, true, true);
Network.SendUpdatePolicies(iNewPolicyBranch, bPolicy, true);
Network.SendUpdatePolicies(m_gPolicyID, m_gAdoptingPolicy, true);
--Network.SendUpdatePolicies(policyBranchIndex, false, true);
--Network.SendUpdatePolicies(policyIndex, true, true);
```

## Deals (UI.Do* deal helpers, tradelogic.lua / diplotrade.lua)
```lua
bCanTradeResource = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_RESOURCES, resType, 1);	-- 1 here is 1 quanity of the Resource, which is the minimum possible
bCanTradeResource = g_Deal:IsPossibleToTradeItem(g_iUs, g_iThem, TradeableItems.TRADE_ITEM_RESOURCES, resType, 1);	-- 1 here is 1 quanity of the Resource, which is the minimum possible
bDefensivePactAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_DEFENSIVE_PACT, g_iDealDuration);
bDefensivePactAllowed = g_Deal:IsPossibleToTradeItem(iPlayer, g_iUs, TradeableItems.TRADE_ITEM_DEFENSIVE_PACT, g_iDealDuration);
bEmbassyAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_ALLOW_EMBASSY, g_iDealDuration);
bGoldTradeAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_GOLD, 1);	-- 1 here is 1 Gold, which is the minimum possible
-- bGoldTradeAllowed = g_Deal:IsPossibleToTradeItem(iPlayer, g_iUs, TradeableItems.TRADE_ITEM_GOLD, 1);	-- 1 here is 1 Gold, which is the minimum possible
bGPTAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_GOLD_PER_TURN, 1, g_iDealDuration);	-- 1 here is 1 GPT, which is the minimum possible
bOpenBordersAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_OPEN_BORDERS, g_iDealDuration);
bOpenBordersAllowed = g_Deal:IsPossibleToTradeItem(iPlayer, g_iUs, TradeableItems.TRADE_ITEM_OPEN_BORDERS, g_iDealDuration);
bResearchAgreementAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_RESEARCH_AGREEMENT, g_iDealDuration);
bResearchAgreementAllowed = g_Deal:IsPossibleToTradeItem(iPlayer, g_iUs, TradeableItems.TRADE_ITEM_RESEARCH_AGREEMENT, g_iDealDuration);   
bTradeAgreementAllowed = g_Deal:IsPossibleToTradeItem(g_iThem, g_iUs, TradeableItems.TRADE_ITEM_TRADE_AGREEMENT, g_iDealDuration);
bTradeAgreementAllowed = g_Deal:IsPossibleToTradeItem(iPlayer, g_iUs, TradeableItems.TRADE_ITEM_TRADE_AGREEMENT, g_iDealDuration);  
elseif( g_Deal:IsPossibleToTradeItem( iFromPlayer, iToPlayer, tradeType, iLoopTeam ) ) then
g_Deal:AddAllowEmbassy(g_iThem);
g_Deal:AddAllowEmbassy(g_iUs);
g_Deal:AddCityTrade( playerID, cityID );
g_Deal:AddDeclarationOfFriendship(g_iThem);
g_Deal:AddDeclarationOfFriendship(g_iUs);
g_Deal:AddDefensivePact( g_iThem, g_iDealDuration );
g_Deal:AddDefensivePact( g_iUs, g_iDealDuration );
g_Deal:AddGoldPerTurnTrade( g_iThem, iGoldPerTurn, g_iDealDuration );
g_Deal:AddGoldPerTurnTrade( g_iUs, iGoldPerTurn, g_iDealDuration );
g_Deal:AddGoldTrade( g_iThem, iAmount );
g_Deal:AddGoldTrade( g_iUs, iAmount );
g_Deal:AddOpenBorders( g_iThem, g_iDealDuration );
g_Deal:AddOpenBorders( g_iUs, g_iDealDuration );
g_Deal:AddPeaceTreaty( g_iThem, GameDefines.PEACE_TREATY_LENGTH );
g_Deal:AddPeaceTreaty( g_iUs, GameDefines.PEACE_TREATY_LENGTH );
g_Deal:AddResearchAgreement( g_iThem, g_iDealDuration );
g_Deal:AddResearchAgreement( g_iUs, g_iDealDuration );
g_Deal:AddResourceTrade( g_iThem, resourceId, iAmount, g_iDealDuration );
g_Deal:AddResourceTrade( g_iUs, resourceId, iAmount, g_iDealDuration );
g_Deal:AddThirdPartyPeace( iWho, iOtherPlayer, GameDefines.PEACE_TREATY_LENGTH );
g_Deal:AddThirdPartyPeace( iWho, iOtherTeam, GameDefines.PEACE_TREATY_LENGTH );
g_Deal:AddThirdPartyWar( iWho, iOtherPlayer );
g_Deal:AddThirdPartyWar( iWho, iOtherTeam );
g_Deal:AddTradeAgreement( g_iThem, g_iDealDuration );
g_Deal:AddTradeAgreement( g_iUs, g_iDealDuration );
g_Deal:AddVoteCommitment(iFromPlayer, iResolutionID, iVoteChoice, iNumVotes, bRepeal);
g_Deal:ChangeGoldPerTurnTrade( g_iThem, iGoldPerTurn, g_iDealDuration );
g_Deal:ChangeGoldPerTurnTrade( g_iUs, iGoldPerTurn, g_iDealDuration );
g_Deal:ChangeGoldTrade( g_iThem, iGold );
g_Deal:ChangeGoldTrade( g_iUs, iGold );
g_Deal:ChangeResourceTrade( g_iThem, iResourceID, iNumResource, g_iDealDuration );
g_Deal:ChangeResourceTrade( g_iUs, iResourceID, iNumResource, g_iDealDuration );
g_Deal:ClearItems();
g_Deal:IsPossibleToTradeItem( iFromPlayer, iToPlayer, tradeType, iLoopTeam ) ) then
g_Deal:RemoveByType( TradeableItems.TRADE_ITEM_ALLOW_EMBASSY, g_iThem );
```

## Diplomacy conversation (leaderhead / diplomacy popups)
```lua
--Events.AILeaderMessage.Add( LeaderMessageHandler );
Events.AILeaderMessage.Add( LeaderMessageHandler );
Events.LeavingLeaderViewMode.Add( OnLeavingLeader );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_AGGRESSIVE_MILITARY_WARNING_RESPONSE, g_iAIPlayer, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_AI_REQUEST_DENOUNCE_RESPONSE, g_iAIPlayer, iButtonID, iAgainstPlayer );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_ATTACKED_MINOR_RESPONSE, g_iAIPlayer, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_BULLIED_MINOR_RESPONSE, g_iAIPlayer, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_CAUGHT_YOUR_SPY_RESPONSE, g_iAIPlayer, iButtonID, iAgainstPlayer);
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_COOP_WAR_NOW_RESPONSE, g_iAIPlayer, iButtonID, iAgainstPlayer );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_COOP_WAR_OFFER, g_iAIPlayer, iLeaderId, -1 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_COOP_WAR_RESPONSE, g_iAIPlayer, iButtonID, iAgainstPlayer );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_DEMAND_HUMAN_REFUSAL, g_iThem, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_DENOUNCE, g_iAIPlayer, 0, 0 );				
--Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_DENOUNCE, g_iAIPlayer, iLeaderId, -1 );
--Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_EXPANSION_SERIOUS_WARNING_RESPONSE, g_iAIPlayer, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_EXPANSION_SERIOUS_WARNING_RESPONSE, g_iThem, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_EXPANSION_WARNING_RESPONSE, g_iAIPlayer, iButtonID, 0 );
--Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR, g_iAIPlayer, 1, 0);
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR, rivalTeam:GetLeaderID(), 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR, Teams[eRivalTeam]:GetLeaderID(), 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_DONT_SETTLE, g_iAIPlayer, 0, 0 );
--Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_END_WORK_WITH_US, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_SHARE_INTRIGUE, g_iAIPlayer, iIntriguePlotter, iIntrigueType);
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_STOP_DIGGING, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_STOP_SPREADING_RELIGION, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_STOP_SPYING, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_STOP_SPYING, g_iAIPlayer, 1, 0 );
--Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_WORK_WITH_US, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_WORK_WITH_US, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_WANTS_DISCUSSION, g_iAIPlayer, 0, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_I_ATTACKED_YOUR_MINOR_CIV_RESPONSE, g_iAIPlayer, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_I_ATTACKED_YOUR_MINOR_CIV_RESPONSE, g_iAIPlayer, iButtonID, iMinor );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_I_BULLIED_YOUR_MINOR_CIV_RESPONSE, g_iAIPlayer, iButtonID, iMinor );
--Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_KILLED_MINOR_RESPONSE, g_iAIPlayer, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_KILLED_MINOR_RESPONSE, g_iThem, iButtonID, 0 );
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_KILLED_MY_SPY_RESPONSE, g_iAIPlayer, 2, iAgainstPlayer);
Game.DoFromUIDiploEvent( FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_KILLED_MY_SPY_RESPONSE, g_iAIPlayer, iButtonID, iAgainstPlayer);
```

## End turn / blocking (actioninfopanel.lua)
```lua
function OnEndTurnClicked()
local player = Players[Game.GetActivePlayer()];
if not player:IsTurnActive() then
print("Player's turn not active");
return;
end
if Game.IsProcessingMessages() then
print("The game is busy processing messages");
return;
end
if Network.HasSentNetTurnComplete() and PreGame.IsMultiplayerGame() then
if Network.SendTurnUnready() then
OnEndTurnDirty();
end
return;
end
local blockingType = player:GetEndTurnBlockingType();
local blockingNotificationIndex = player:GetEndTurnBlockingNotificationIndex();
if (blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_POLICY
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_RESEARCH
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_FREE_TECH
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_PRODUCTION
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_DIPLO_VOTE
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_FREE_ITEMS
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_FREE_POLICY
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_FOUND_PANTHEON
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_FOUND_RELIGION
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_ENHANCE_RELIGION
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_STEAL_TECH
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_MAYA_LONG_COUNT
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_FAITH_GREAT_PERSON
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_CITY_RANGE_ATTACK
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_CHOOSE_IDEOLOGY) then
UI.ActivateNotification(blockingNotificationIndex);
elseif (blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_UNIT_PROMOTION) then
for v in player:Units() do
if (v:IsPromotionReady()) then
local pPlot = v:GetPlot();
UI.LookAt(pPlot, 0);
UI.SelectUnit(v);
local hex = ToHexFromGrid( Vector2(pPlot:GetX(), pPlot:GetY() ) );
Events.GameplayFX(hex.x, hex.y, -1);
break;
end
end
elseif (blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_STACKED_UNITS
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS
or blockingType == EndTurnBlockingTypes.ENDTURN_BLOCKING_UNITS) then
local pUnit = player:GetFirstReadyUnit();
if (pUnit) then
local pPlot = pUnit:GetPlot();
UI.LookAt(pPlot, 0);
UI.SelectUnit(pUnit);
local hex = ToHexFromGrid( Vector2(pPlot:GetX(), pPlot:GetY() ) );
Events.GameplayFX(hex.x, hex.y, -1);				
end	
else
if (not UI.CanEndTurn()) then
print("UI thinks that we can't end turn, but the notification system disagrees");
end
local iEndTurnControl = GameInfoTypes.CONTROL_ENDTURN;
Game.DoControl(iEndTurnControl)	
end
end
Controls.EndTurnButton:RegisterCallback( Mouse.eLClick, OnEndTurnClicked );
```

## EndTurnBlockingTypes handled by the UI
```
EndTurnBlockingTypes.ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF EndTurnBlockingTypes.ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY 
EndTurnBlockingTypes.ENDTURN_BLOCKING_CHOOSE_IDEOLOGY EndTurnBlockingTypes.ENDTURN_BLOCKING_CITY_RANGE_ATTACK 
EndTurnBlockingTypes.ENDTURN_BLOCKING_DIPLO_VOTE EndTurnBlockingTypes.ENDTURN_BLOCKING_ENHANCE_RELIGION 
EndTurnBlockingTypes.ENDTURN_BLOCKING_FAITH_GREAT_PERSON EndTurnBlockingTypes.ENDTURN_BLOCKING_FOUND_PANTHEON 
EndTurnBlockingTypes.ENDTURN_BLOCKING_FOUND_RELIGION EndTurnBlockingTypes.ENDTURN_BLOCKING_FREE_ITEMS 
EndTurnBlockingTypes.ENDTURN_BLOCKING_FREE_POLICY EndTurnBlockingTypes.ENDTURN_BLOCKING_FREE_TECH 
EndTurnBlockingTypes.ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS 
EndTurnBlockingTypes.ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES EndTurnBlockingTypes.ENDTURN_BLOCKING_MAYA_LONG_COUNT 
EndTurnBlockingTypes.ENDTURN_BLOCKING_MINOR_QUEST EndTurnBlockingTypes.ENDTURN_BLOCKING_POLICY 
EndTurnBlockingTypes.ENDTURN_BLOCKING_PRODUCTION EndTurnBlockingTypes.ENDTURN_BLOCKING_RESEARCH 
EndTurnBlockingTypes.ENDTURN_BLOCKING_STACKED_UNITS EndTurnBlockingTypes.ENDTURN_BLOCKING_STEAL_TECH 
EndTurnBlockingTypes.ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS EndTurnBlockingTypes.ENDTURN_BLOCKING_UNIT_PROMOTION 
EndTurnBlockingTypes.ENDTURN_BLOCKING_UNITS EndTurnBlockingTypes.NO_ENDTURN_BLOCKING_TYPE 
```
