"""
graph/workflows/agent.py — AgentWorkflow.

Native LangGraph với LLM node + ToolExecutor node (tự loop).

AgentWorkflow dùng cho:
  - intent="agent": câu hỏi mở không khớp workflow nào
  - LLM tự quyết định tool_calls và loop

Nodes:
  llm_node       — gọi Bedrock LLM với tool_calls binding
  tools_node     — execute tool_calls từ LLM response
  should_continue — conditional: có tool_calls → tools_node, không → END

Flow: START → llm_node → (tool_calls?) → tools_node → llm_node → ... → END
"""

from __future__ import annotations

import time
import json
import logging
from typing import Literal, TYPE_CHECKING

from langgraph.graph import StateGraph, START, END

from src.graph.state import ShoppingState

logger = logging.getLogger("graph.workflows.agent")

class LLMNode:
    """
    Node gọi Bedrock LLM với all_shopping_tools binding.
    Thêm AIMessage vào messages, LangGraph sẽ loop tiếp nếu có tool_calls.
    """

    def __init__(self):
        self._llm = None
        self._max_iterations = 7

    def _get_llm(self):
        if self._llm is None:
            import os
            from langchain_aws import ChatBedrockConverse
            from src.tools import all_shopping_tools
            model = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
            region = os.getenv("BEDROCK_REGION", "ap-southeast-1")
            try:
                base_llm = ChatBedrockConverse(
                    model=model,
                    region_name=region,
                    temperature=0.1,
                    max_tokens=1024,
                )
                self._llm = base_llm.bind_tools(all_shopping_tools)
                logger.info("[LLM_NODE] LLM initialized: %s", model)
            except Exception as e:
                logger.error("[LLM_NODE] Failed to init LLM: %s", e)
        return self._llm

    async def __call__(self, state: ShoppingState) -> dict:
        t0 = time.monotonic_ns()
        llm = self._get_llm()
        if llm is None:
            return {
                "final_answer": "LLM chưa được cấu hình. Vui lòng kiểm tra AWS credentials.",
                "node_durations": {"LLMNode": _ms(t0)},
            }

        from src.llm.prompt import SYSTEM_PROMPT
        from langchain_core.messages import SystemMessage

        messages = list(state.get("messages", []))

        # Inject product context nếu đã được resolve tập trung
        product_context = ""
        pid = state.get("current_product_id")
        pname = state.get("resolved_product_name")
        if pid and pname:
            product_context = (
                f"\n[RESOLVED PRODUCT] Sản phẩm **{pname}** đã được xác định, "
                f"product_id={pid}. Khi cần dùng product_id cho tool, "
                f"dùng giá trị này thay vì gọi get_product_id lại."
            )

        # Prepend system prompt nếu chưa có
        if not any(hasattr(m, "type") and m.type == "system" for m in messages):
            content = SYSTEM_PROMPT + product_context
            messages = [SystemMessage(content=content)] + messages
        elif product_context:
            # Append context vào system message cuối
            for m in messages:
                if hasattr(m, "type") and m.type == "system":
                    if isinstance(m.content, str):
                        m.content += product_context
                    elif isinstance(m.content, list):
                        m.content.append({"type": "text", "text": product_context})
                    break

        retry_count = state.get("retry_count", 0)
        if retry_count >= self._max_iterations:
            return {
                "final_answer": "Đã đạt giới hạn vòng lặp. Vui lòng thử lại.",
                "node_durations": {"LLMNode": _ms(t0)},
            }

        try:
            response = await llm.ainvoke(messages)

            # Normalize content nếu là list of blocks (Bedrock format)
            content = response.content
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "reasoning_content":
                            continue
                        if "text" in part:
                            text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                    elif hasattr(part, "text"):
                        text_parts.append(part.text)
                if not response.tool_calls:
                    response = response.model_copy(update={"content": "".join(text_parts)})

            # Nếu không có tool_calls → đây là final answer
            if not getattr(response, "tool_calls", None):
                final = response.content if isinstance(response.content, str) else "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in (response.content if isinstance(response.content, list) else [])
                )
                return {
                    "messages": [response],
                    "final_answer": final,
                    "retry_count": retry_count,
                    "node_durations": {"LLMNode": _ms(t0)},
                }

            # Có tool_calls → thêm vào messages để tools_node xử lý
            return {
                "messages": [response],
                "retry_count": retry_count + 1,
                "node_durations": {"LLMNode": _ms(t0)},
            }

        except Exception as e:
            logger.error("[LLM_NODE] Error: %s", e)
            return {
                "final_answer": f"Lỗi kết nối Bedrock: {str(e)[:150]}",
                "errors": [{"node": "LLMNode", "error": str(e)[:200]}],
                "node_durations": {"LLMNode": _ms(t0)},
            }


class ToolsNode:
    """
    Node execute tất cả tool_calls từ LLM response cuối cùng.
    Tích hợp L4 validate + cache + retry từ ToolExecutor.
    """

    def __init__(self):
        self._tools_map = None

    def _get_tools_map(self):
        if self._tools_map is None:
            from src.graph.nodes.tool_executor import TOOLS_MAP
            self._tools_map = TOOLS_MAP
        return self._tools_map

    async def __call__(self, state: ShoppingState) -> dict:
        t0 = time.monotonic_ns()
        messages = state.get("messages", [])
        user_id = state.get("user_id", "anonymous")
        session_id = state.get("session_id", "")

        # Tìm AIMessage cuối cùng có tool_calls
        ai_message = None
        for msg in reversed(messages):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                ai_message = msg
                break

        if ai_message is None:
            return {"node_durations": {"ToolsNode": _ms(t0)}}

        from langchain_core.messages import ToolMessage
        from src.guardrails.tool_validator import validate_tool_call
        from src.memory.store import CacheStore
        from src.guardrails.confirmation import request_confirmation

        cache_store = CacheStore()
        tool_messages = []
        pending_action = None

        for tc in ai_message.tool_calls:
            tc_name = tc.get("name") if isinstance(tc, dict) else tc.name
            tc_args = tc.get("args", {}) if isinstance(tc, dict) else tc.args
            tc_id = tc.get("id", "") if isinstance(tc, dict) else tc.id

            tools_map = self._get_tools_map()
            tool_fn = tools_map.get(tc_name)
            if tool_fn is None:
                tool_messages.append(ToolMessage(content=f"[ERROR] Tool {tc_name} không tồn tại", tool_call_id=tc_id))
                continue

            # L4 Validate
            validation = validate_tool_call(tc_name, tc_args, user_id)
            if not validation.is_valid:
                tool_messages.append(ToolMessage(content=f"[GUARDRAIL] {validation.blocked_reason}", tool_call_id=tc_id))
                continue

            # Cache check
            WRITE_TOOLS = {"add_to_cart_tool", "get_cart_tool", "get_shipping_quote_tool"}
            if tc_name not in WRITE_TOOLS:
                cached = cache_store.get(tc_name, tc_args)
                if cached:
                    tool_messages.append(ToolMessage(content=cached, tool_call_id=tc_id))
                    continue

            # Execute
            try:
                result = await tool_fn.ainvoke(tc_args)

                # Check pending confirmation
                try:
                    parsed = json.loads(result) if isinstance(result, str) else result
                    if isinstance(parsed, dict) and parsed.get("status") == "pending":
                        pending_action = {
                            "token": parsed["token"],
                            "message": parsed.get("message", "Vui lòng xác nhận."),
                            "action": "AddItem",
                        }
                        tool_messages.append(ToolMessage(content=parsed.get("message", ""), tool_call_id=tc_id))
                        continue
                except Exception:
                    pass

                # Cache result (read-only tools)
                if tc_name not in WRITE_TOOLS and isinstance(result, str):
                    cache_store.set(tc_name, tc_args, result)

                tool_messages.append(ToolMessage(
                    content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc_id,
                ))

            except Exception as e:
                logger.error("[TOOLS_NODE] %s error: %s", tc_name, e)
                tool_messages.append(ToolMessage(
                    content=f"[ERROR] {tc_name}: {str(e)[:100]}",
                    tool_call_id=tc_id,
                ))

        updates: dict = {
            "messages": tool_messages,
            "node_durations": {"ToolsNode": _ms(t0)},
        }
        if pending_action:
            updates["pending_action"] = pending_action

        return updates


def _should_continue(state: ShoppingState) -> Literal["tools", "__end__"]:
    """Conditional edge: có tool_calls → tools, không → END."""
    messages = state.get("messages", [])
    # Nếu đã có final_answer → END
    if state.get("final_answer"):
        return "__end__"
    # Nếu pending_action → END
    if state.get("pending_action"):
        return "__end__"
    # Nếu message cuối có tool_calls → tools
    for msg in reversed(messages):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            return "tools"
        break
    return "__end__"


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# AgentWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_agent_workflow():
    """
    Tạo AgentWorkflow subgraph.

    Native LangGraph với LLMNode + ToolsNode.
    LLM tự quyết định tool_calls, graph loop cho đến khi không còn tool_calls.
    """
    logger.info("[AGENT_WORKFLOW] Creating native LangGraph AgentWorkflow")

    builder = StateGraph(ShoppingState)

    builder.add_node("llm", LLMNode())
    builder.add_node("tools", ToolsNode())

    builder.add_edge(START, "llm")
    builder.add_conditional_edges(
        "llm",
        _should_continue,
        {"tools": "tools", "__end__": END},
    )
    builder.add_edge("tools", "llm")  # loop

    return builder.compile()
