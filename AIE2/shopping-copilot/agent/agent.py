"""
agent/agent.py — Public API entry point cho Shopping Copilot Agent.

Convenience re-export để các module khác import ngắn gọn:
    from agent import agent
    agent.chat(session_id, user_id, message)

Tương đương:
    from agent.copilot_agent import CopilotAgent
    CopilotAgent().chat(...)
"""

from agent.copilot_agent import CopilotAgent

# Singleton instance dùng chung trong process
_agent_instance: CopilotAgent | None = None


def _get_agent() -> CopilotAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CopilotAgent()
    return _agent_instance


def chat(session_id: str, user_id: str, user_message: str) -> dict:
    return _get_agent().chat(session_id, user_id, user_message)


def confirm(session_id: str, token: str) -> dict:
    return _get_agent().confirm(session_id, token)
