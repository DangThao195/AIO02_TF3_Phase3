import asyncio

from src.agent.copilot_agent import CopilotAgent


def test_confirm_cancel_clears_pending_state(monkeypatch):
    agent = CopilotAgent()
    session_id = "sess-cancel"
    user_id = "user-1"

    agent._sessions.get_or_create(session_id, user_id)
    agent._sessions.set_pending(
        session_id,
        "test-token",
        "AddItem",
        {"product_id": "ABC123", "quantity": 1},
    )

    monkeypatch.setattr(
        "src.agent.copilot_agent.verify_confirmation_token",
        lambda token: (
            True,
            {
                "user_id": user_id,
                "params": {"product_id": "ABC123", "quantity": 1},
            },
        ),
    )

    result = asyncio.run(agent.confirm(session_id, "test-token", confirmed=False))

    assert result["status"] == "cancelled"
    assert agent._sessions.dump(session_id)["pending_confirmation"] == {}
