import asyncio
from src.agent.copilot_agent import CopilotAgent

async def main():
    agent = CopilotAgent()
    # Mocking the session state so that compare has something to compare
    session = agent.sessions.get_or_create("test-session", "test-user")
    session["context"] = {
        "last_search_ids": ["66VCHSJNUP", "OLJCESPC7Z"]
    }
    
    print("Testing compare intent...")
    plan = agent._build_plan_from_intent({"task_type": "compare"}, "test-user")
    exec_result = await agent._execute_and_aggregate(plan, "test-user", session)
    print("EVIDENCE:")
    import json
    print(json.dumps(exec_result.get("evidence"), indent=2))
    
if __name__ == "__main__":
    asyncio.run(main())
