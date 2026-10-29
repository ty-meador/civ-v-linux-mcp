"""An accepted or sent proposal carries no answer rows (GitLab #68)."""
import unittest

from harness.game_parts.deals import table_as_proposed


class ProposalTableTests(unittest.TestCase):
    def test_answers_go_and_the_items_stay(self):
        table = {"n": 2, "items": [{"type": "RESOURCES", "resource": "RESOURCE_FUR", "from_us": True}],
                 "answers": [{"tool": "answer", "args": {"choice": "accept"}}, {"tool": "answer", "args": {"choice": "refuse"}}]}
        out = table_as_proposed(table)
        self.assertNotIn("answers", out)
        self.assertEqual(out["items"], table["items"])
        self.assertIn("nothing here is to be answered", out["note"])
        self.assertIn("answers", table, "the read's own dict is left alone")

    def test_a_table_without_rows_is_untouched(self):
        self.assertEqual(table_as_proposed({"n": 0, "items": []}), {"n": 0, "items": []})
        self.assertIsNone(table_as_proposed(None))


if __name__ == "__main__":
    unittest.main()
