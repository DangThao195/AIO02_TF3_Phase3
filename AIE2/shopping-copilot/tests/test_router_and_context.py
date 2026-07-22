import os
import sys
import unittest
import asyncio

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

from src.agent.copilot_agent import CopilotAgent
import src.agent.copilot_agent as copilot_agent_module


class TestRouterAndContext(unittest.TestCase):
    def test_builds_search_plan_for_clear_search_request(self):
        agent = CopilotAgent.__new__(CopilotAgent)
        session = {"context": {}}

        plan = agent._build_deterministic_tool_plan("tìm kính thiên văn dưới 100 đô", session)

        self.assertIsNotNone(plan)
        self.assertEqual(plan[0]["name"], "search_products_v2")
        self.assertIn("kính thiên văn", plan[0]["args"]["query"])

    def test_builds_cart_plan_from_previous_product_context(self):
        agent = CopilotAgent.__new__(CopilotAgent)
        session = {"context": {"last_product_name": "Vintage Typewriter"}}

        plan = agent._build_deterministic_tool_plan("thêm nó vào giỏ", session)

        self.assertIsNotNone(plan)
        self.assertEqual(plan[0]["name"], "get_product_id")
        self.assertEqual(plan[1]["name"], "add_to_cart_tool")

    def test_normalizes_vietnamese_to_english_for_stable_routing(self):
        agent = CopilotAgent.__new__(CopilotAgent)

        normalized = agent._normalize_user_message_to_english("xem review cái đó")

        self.assertIn("review", normalized.lower())
        self.assertIn("that", normalized.lower())

    def test_builds_structured_schema_for_search_queries(self):
        agent = CopilotAgent.__new__(CopilotAgent)
        session = {"context": {}}

        schema = agent._build_request_schema("find telescope under 100 dollars", session)

        self.assertEqual(schema["intent"], "search")
        self.assertEqual(schema["constraints"]["price_max"], 100)
        self.assertIn("telescope", schema["product_query"])

    def test_builds_structured_schema_for_cart_actions(self):
        agent = CopilotAgent.__new__(CopilotAgent)
        session = {"context": {"last_product_name": "Vintage Typewriter"}}

        schema = agent._build_request_schema("add it to cart", session)

        self.assertEqual(schema["intent"], "add_to_cart")
        self.assertEqual(schema["product_reference"]["name"], "Vintage Typewriter")
        self.assertTrue(schema["needs_product_lookup"])

    def test_classifies_category_requests_with_typo(self):
        agent = CopilotAgent.__new__(CopilotAgent)
        session = {"context": {}}

        schema = agent._build_request_schema("your catagory list in shop", session)
        plan = agent._build_deterministic_tool_plan("your catagory list in shop", session)

        self.assertEqual(schema["intent"], "list_categories")
        self.assertEqual(plan[0]["name"], "get_categories")

    def test_classifies_inventory_requests_as_all_products(self):
        agent = CopilotAgent.__new__(CopilotAgent)
        session = {"context": {}}

        schema = agent._build_request_schema("show me all products in the shop", session)
        plan = agent._build_deterministic_tool_plan("show me all products in the shop", session)

        self.assertEqual(schema["intent"], "list_products")
        self.assertEqual(plan[0]["name"], "get_all_products")

    def test_chat_uses_deterministic_plan_without_llm(self):
        agent = CopilotAgent()
        agent.llm = None

        original_tool = copilot_agent_module.TOOLS_MAP.get("search_products_v2")

        class DummyTool:
            async def ainvoke(self, args):
                return '{"status":"success","products":[{"name":"Vintage Typewriter","price_units":65,"price_nanos":500000000}]}'

        copilot_agent_module.TOOLS_MAP["search_products_v2"] = DummyTool()

        try:
            result = asyncio.run(agent.chat("fallback-session", "fallback-user", "find telescope"))
        finally:
            if original_tool is not None:
                copilot_agent_module.TOOLS_MAP["search_products_v2"] = original_tool
            else:
                copilot_agent_module.TOOLS_MAP.pop("search_products_v2", None)

        self.assertEqual(result["status"], "ok")
        self.assertIn("Vintage Typewriter", result["reply"])

    def test_chat_synthesizes_final_answer_from_tool_output(self):
        agent = CopilotAgent()

        class DummyLLM:
            async def ainvoke(self, messages):
                return type("Response", (), {"content": "The best-reviewed option is Vintage Typewriter.", "usage_metadata": None})()

        class DummyTool:
            async def ainvoke(self, args):
                return '{"status":"success","products":[{"name":"Vintage Typewriter","price_units":65,"price_nanos":500000000}]}'

        original_tool = copilot_agent_module.TOOLS_MAP.get("search_products_v2")
        original_llm = agent.llm
        agent.llm = DummyLLM()
        copilot_agent_module.TOOLS_MAP["search_products_v2"] = DummyTool()

        try:
            result = asyncio.run(agent.chat("synthesis-session", "synthesis-user", "which product has the best reviews"))
        finally:
            if original_tool is not None:
                copilot_agent_module.TOOLS_MAP["search_products_v2"] = original_tool
            else:
                copilot_agent_module.TOOLS_MAP.pop("search_products_v2", None)
            agent.llm = original_llm

        self.assertEqual(result["status"], "ok")
        self.assertIn("Vintage Typewriter", result["reply"])
        self.assertIn("best-reviewed", result["reply"].lower())
        self.assertNotIn("Found 1 products:", result["reply"])


if __name__ == "__main__":
    unittest.main()
