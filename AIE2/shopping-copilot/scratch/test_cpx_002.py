import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.copilot_agent import CopilotAgent

async def main():
    agent = CopilotAgent()
    user_id = "test_user"
    session_id = "test_session"
    message = "Tôi có $150 USD, convert sang VND xem tôi có đủ mua kính thiên văn rẻ nhất không?"
    
    print(f"User: {message}")
    result = await agent.chat(session_id, user_id, message)
    
    print(f"\nIntent: {result.get('intent')}")
    print(f"\nEvidence: {result.get('evidence')}")
    print(f"\nReply: {result.get('reply')}")
    print(f"\nSteps: {result.get('steps')}")

if __name__ == "__main__":
    asyncio.run(main())
