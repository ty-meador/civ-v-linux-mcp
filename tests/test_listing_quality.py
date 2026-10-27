"""The listing as TDQS lints it (docs/measurements/2026-10-27-tdqs-report.json): every one of the nine tools
carries MCP annotations, every listed parameter a `description`, and each description a statement of purpose
within the client cut. The score itself is a manual, metered call and is never taken here."""
import unittest

from harness import mcp_server
from harness.mcp_tools import surface as S
from harness.surface import listing as L
from harness.surface import vocabulary as V

CLIENT_CUT = 2000


def _tool(name):
    return mcp_server.mcp._tool_manager.get_tool(name)


class ListingQualityTests(unittest.TestCase):
    def test_every_tool_has_annotations_that_say_what_it_does_to_the_world(self):
        for name in V.TOOLS:
            a = _tool(name).annotations
            self.assertIsNotNone(a, name)
            self.assertIsNotNone(a.read_only_hint, name)
            self.assertIsNotNone(a.idempotent_hint, name)
            self.assertIs(a.open_world_hint, False, name)
            self.assertTrue(a.title, name)
        for name in ("inspect", "question", "reference"):
            self.assertTrue(_tool(name).annotations.read_only_hint, name)
        for name in ("turn", "order", "answer", "notebook", "batch", "session"):
            self.assertFalse(_tool(name).annotations.read_only_hint, name)
            self.assertIsNotNone(_tool(name).annotations.destructive_hint, name)
        for name in ("order", "batch", "session", "notebook"):
            self.assertTrue(_tool(name).annotations.destructive_hint, name)

    def test_every_listed_parameter_has_a_description(self):
        for name in V.TOOLS:
            props = _tool(name).parameters.get("properties", {})
            missing = [p for p, sch in props.items() if not sch.get("description")]
            self.assertEqual(missing, [], f"{name}: parameters without a description")
        self.assertNotIn("ctx", _tool("turn").parameters["properties"])

    def test_order_keeps_its_descriptions_in_both_variants(self):
        for variant in (L.ONEOF, L.FLAT):
            sch = L.order_schema(S.BASE_ORDER_SCHEMA, variant)
            for p in ("to", "action", "id", "args", "action_id"):
                self.assertTrue(sch["properties"][p].get("description"), (variant, p))
            self.assertEqual(sch["properties"]["to"]["enum"], list(V.ACTIONS))
        self.assertIn("oneOf", L.order_schema(S.BASE_ORDER_SCHEMA, L.ONEOF))

    def test_descriptions_open_with_a_purpose_and_fit_the_client_cut(self):
        for name in V.TOOLS:
            d = _tool(name).description or ""
            self.assertLess(len(d), CLIENT_CUT, name)
            self.assertNotIn("today's", d.split(".")[0], f"{name}: the first sentence names what it is for, not an old name")
        for name, word in (("session", "Saves, loads and the seat"), ("notebook", "My memory"), ("turn", "The clock"),
                           ("order", "An order to something I own"), ("batch", "Many orders in one call")):
            self.assertTrue((_tool(name).description or "").startswith(word), name)
        for name in ("turn", "order", "answer", "notebook", "session", "batch"):
            self.assertIn("Returns", _tool(name).description, f"{name}: says what comes back")


if __name__ == "__main__":
    unittest.main()
