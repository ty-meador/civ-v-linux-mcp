"""The Culture Overview's swap tab (GitLab #12).

cultureoverview.lua puts one work per class up for swapping (GetSwappableGreatWriting/Art/Artifact,
set through Network.SendSetSwappableGreatWork with -1 to clear), lists every other civ's offers
(Player:GetOthersGreatWorks) and swaps with Network.SendSwapGreatWorks only when an offer is selected
and we have a work of the same class put up. Music is commented out in stock.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
local works = {
  [100] = { name = 'TXT_KEY_W_ILIAD', era = 'Ancient', creator = 0, class = 3 },
  [101] = { name = 'TXT_KEY_W_ODYSSEY', era = 'Ancient', creator = 0, class = 3 },
  [200] = { name = 'TXT_KEY_A_MONA', era = 'Renaissance', creator = 0, class = 1 },
  [300] = { name = 'TXT_KEY_W_THEIRS', era = 'Classical', creator = 3, class = 3 },
  [301] = { name = 'TXT_KEY_A_THEIRS', era = 'Medieval', creator = 3, class = 1 },
  [400] = { name = 'TXT_KEY_R_THEIRS', era = 'Ancient', creator = 1, class = 2 },
}
Game = {
  GetGreatWorkName = function(i) return works[i].name end,
  GetGreatWorkEraShort = function(i) return works[i].era end,
  GetGreatWorkCreator = function(i) return works[i].creator end,
  GetGreatWorkClass = function(i) return works[i].class end,
  GetGreatWorkTooltip = function(i, viewer) return 'tip ' .. i .. ' for ' .. viewer end,
  GetGreatWorkCurrentThemingBonus = function(i) return i == 100 and 2 or 0 end,
}
Locale = { ConvertTextKey = function(k) return (k:gsub('^TXT_KEY_[WAR]_', '')) end }
OFFER = { writing = 100, art = -1, artifact = -1 }
SENT = {}
Network = {
  SendSetSwappableGreatWork = function(pid, cls, idx) SENT[#SENT + 1] = { 'set', pid, cls, idx } end,
  SendSwapGreatWorks = function(pid, mine, partner, theirs) SENT[#SENT + 1] = { 'swap', pid, mine, partner, theirs } end,
}
Players = {
  [0] = {
    GetSwappableGreatWriting = function() return OFFER.writing end,
    GetSwappableGreatArt = function() return OFFER.art end,
    GetSwappableGreatArtifact = function() return OFFER.artifact end,
    GetGreatWorks = function(_, cls)
      if cls == 3 then return { { Index = 100, Creator = 0 }, { Index = 101, Creator = 0 } } end
      if cls == 1 then return { { Index = 200, Creator = 0 } } end
      return {}
    end,
    GetOthersGreatWorks = function() return {
      { iPlayer = 3, WritingIndex = 300, WritingCreator = 3, ArtIndex = 301, ArtCreator = 3, ArtifactIndex = -1, ArtifactCreator = -1 },
      { iPlayer = 1, WritingIndex = -1, WritingCreator = -1, ArtIndex = -1, ArtCreator = -1, ArtifactIndex = 400, ArtifactCreator = 1 },
    } end,
  },
  [1] = { GetCivilizationShortDescriptionKey = function() return 'TXT_KEY_W_MAYA' end },
  [3] = { GetCivilizationShortDescriptionKey = function() return 'TXT_KEY_W_PERSIA' end },
}
"""


class GreatWorkSwapTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_tab_lists_our_offers_candidates_and_their_offers(self):
        self.run_lua("""
        local s = H.great_work_swap(0)
        assert(s.ours.writing.offered.work_id == 100 and s.ours.writing.offered.name == 'ILIAD', H.json(s.ours.writing))
        assert(#s.ours.writing.candidates == 2 and s.ours.writing.candidates[1].theming_bonus == 2 and s.ours.writing.candidates[2].theming_bonus == 0)
        assert(s.ours.art.offered == nil and #s.ours.art.candidates == 1 and s.ours.art.candidates[1].work_id == 200)
        assert(s.ours.artifact.offered == nil and #s.ours.artifact.candidates == 0)
        assert(s.ours.music == nil, 'music is not on the stock tab')
        assert(#s.theirs == 2)
        assert(s.theirs[1].player == 3 and s.theirs[1].civ == 'PERSIA' and s.theirs[1].writing.work_id == 300 and s.theirs[1].writing.class == 'writing')
        assert(s.theirs[1].art.work_id == 301 and s.theirs[1].art.era == 'Medieval' and s.theirs[1].artifact == nil)
        assert(s.theirs[2].player == 1 and s.theirs[2].artifact.work_id == 400 and s.theirs[2].artifact.tooltip == 'tip 400 for 0')
        """)

    def test_set_swappable_accepts_only_our_works_of_that_class(self):
        self.run_lua("""
        local r = H.set_swappable_great_work('writing', 101, 0)
        assert(r.ok and SENT[1][1] == 'set' and SENT[1][3] == 3 and SENT[1][4] == 101, H.json(r))
        r = H.set_swappable_great_work('writing', -1, 0)
        assert(r.ok and r.cleared == true and SENT[2][4] == -1)
        r = H.set_swappable_great_work('art', 101, 0)
        assert(r.ok == false and #SENT == 2, 'a writing is not an art candidate')
        r = H.set_swappable_great_work('writing', 300, 0)
        assert(r.ok == false and #SENT == 2, 'their work is not ours')
        r = H.set_swappable_great_work('music', 100, 0)
        assert(r.ok == false and #SENT == 2)
        """)

    def test_swap_needs_an_offer_and_our_work_of_the_same_class(self):
        self.run_lua("""
        local r = H.swap_great_works(300, 0)
        assert(r.ok and r.ours == 100 and r.partner == 3 and r.theirs == 300 and r.class == 'writing', H.json(r))
        assert(SENT[1][1] == 'swap' and SENT[1][3] == 100 and SENT[1][4] == 3 and SENT[1][5] == 300)
        r = H.swap_great_works(301, 0)
        assert(r.ok == false and r.class == 'art' and #SENT == 1, 'no art put up')
        r = H.swap_great_works(999, 0)
        assert(r.ok == false and #SENT == 1, 'not on offer')
        OFFER.art = 200
        r = H.swap_great_works(301, 0)
        assert(r.ok and r.ours == 200 and #SENT == 2)
        """)


if __name__ == "__main__":
    unittest.main()
