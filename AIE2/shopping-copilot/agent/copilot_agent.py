"""
agent/copilot_agent.py — CopilotAgent: ReAct loop + guardrail pipeline + step tracking.

Entry points (được main.py gọi):
    agent.chat(session_id, user_id, user_message) → dict with steps[]
    agent.confirm(session_id, token) → dict
"""

import os
import json
import uuid
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage, SystemMessage
from groq import RateLimitError, APIStatusError

from guardrails import (
    rate_limiter,
    check_input,
    validate_tool_call,
    request_confirmation,
    verify_confirmation_token,
    filter_output,
    with_fallback,
    MaxIterationsExceeded,
    MAX_TOOL_ITERATIONS,
)
from memory import SessionStore, CacheStore
from tools import all_shopping_tools
from llm.prompt import SYSTEM_PROMPT

logger = logging.getLogger("agent.copilot_agent")

TOOLS_MAP: Dict[str, Any] = {t.name: t for t in all_shopping_tools}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_tool_call(tc: Any) -> dict:
    """Chuẩn hóa tool_call từ object hoặc dict về dict để xử lý thống nhất."""
    if hasattr(tc, "name"):
        return {"name": tc.name, "args": tc.args, "id": tc.id}
    if isinstance(tc, dict):
        return {"name": tc.get("name", ""), "args": tc.get("args", {}), "id": tc.get("id", tc.get("tool_call_id", ""))}
    raise TypeError(f"Unexpected tool_call type: {type(tc)}")


class CopilotAgent:
    def __init__(self):
        self._sessions = SessionStore()
        self._cache = CacheStore()
        self.llm = self._build_llm()
        self._steps: List[Dict[str, Any]] = []

    # ── helpers ──

    def _add_step(self, action: str, status: str, detail: str, duration_ms: int):
        self._steps.append({
            "action": action,
            "status": status,
            "detail": detail,
            "duration_ms": duration_ms,
        })

    def _time(self, action: str) -> tuple:
        start = _now_ms()
        return start, action

    def _end(self, start: int, action: str, status: str, detail: str):
        self._add_step(action, status, detail, _now_ms() - start)

    def _build_llm(self) -> ChatGroq:
        api_key = os.environ.get("GROQ_API_KEY")
        model = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
        llm = ChatGroq(
            api_key=api_key,
            model=model,
            temperature=0.3,
            max_retries=0,        # fail fast — tự xử lý retry ở ReAct loop
            timeout=30,           # timeout 30s per request
        )
        return llm.bind_tools(all_shopping_tools)

    # ── debug: expose memory stores ──
    @property
    def sessions(self) -> "SessionStore":
        return self._sessions

    @property
    def cache_store(self) -> "CacheStore":
        return self._cache

    # ── public API ──

    @with_fallback  # L6
    async def chat(self, session_id: str, user_id: str, user_message: str) -> Dict[str, Any]:
        self._steps = []

        # L1: Rate Limiter
        s, a = self._time("RateLimiter")
        rate_result = rate_limiter.check_rate_limit(user_id)
        if not rate_result.is_allowed:
            detail = rate_result.blocked_reason
            self._end(s, a, "BLOCK", detail)
            return {"status": "error", "reply": detail, "session_id": session_id, "steps": list(self._steps)}
        self._end(s, a, "PASS", f"{rate_result.remaining_minute} req remaining this minute")

        # L2a: Input Filter
        s, a = self._time("InputFilter")
        filter_result = check_input(user_message)
        if not filter_result.is_safe:
            detail = filter_result.blocked_reason or "Tin nhắn bị chặn bởi bộ lọc đầu vào."
            self._end(s, a, "BLOCK", detail)
            return {"status": "error", "reply": detail, "session_id": session_id, "steps": list(self._steps)}
        self._end(s, a, "PASS", "Không phát hiện prompt injection")

        # Session
        session = self._sessions.get_or_create(session_id, user_id)
        self._sessions.append_message(session_id, "user", user_message)

        # Build messages
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in session["messages"]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
            elif msg["role"] == "tool":
                messages.append(ToolMessage(
                    content=msg["content"],
                    tool_call_id=msg.get("tool_call_id", ""),
                ))

        # ReAct Loop
        iterations = 0
        while iterations < MAX_TOOL_ITERATIONS:
            s_llm, a_llm = self._time("LLMInvoke")
            try:
                response = await self.llm.ainvoke(messages)
                self._end(s_llm, a_llm, "OK", f"iter={iterations + 1}")
            except RateLimitError as e:
                detail = f"Rate limited: {str(e)[:100]}"
                self._end(s_llm, a_llm, "BLOCK", detail)
                return {
                    "status": "error",
                    "reply": "Hệ thống AI đang quá tải. Vui lòng đợi vài giây rồi thử lại.",
                    "session_id": session_id,
                    "steps": list(self._steps),
                }
            except APIStatusError as e:
                detail = f"API error {e.status_code}: {str(e)[:100]}"
                self._end(s_llm, a_llm, "ERROR", detail)
                return {
                    "status": "error",
                    "reply": f"Dịch vụ AI gặp lỗi (HTTP {e.status_code}). Vui lòng thử lại sau.",
                    "session_id": session_id,
                    "steps": list(self._steps),
                }
            except Exception as e:
                self._end(s_llm, a_llm, "ERROR", str(e)[:120])
                return {
                    "status": "error",
                    "reply": f"Lỗi kết nối AI: {str(e)[:120]}",
                    "session_id": session_id,
                    "steps": list(self._steps),
                }

            raw_tool_calls = getattr(response, "tool_calls", None) or []
            if raw_tool_calls:
                for raw_tc in raw_tool_calls:
                    tc = _normalize_tool_call(raw_tc)
                    tc_name = tc["name"]
                    tc_args = tc["args"]
                    tc_id = tc["id"]
                    args_preview = json.dumps(tc_args, ensure_ascii=False)

                    # Step 1: Tool Call (validate + check cache)
                    s_tc, a_tc = self._time(tc_name)
                    validation = validate_tool_call(tc_name, tc_args, user_id)
                    if not validation.is_valid:
                        self._end(s_tc, a_tc, "BLOCK", f"L3: {validation.violation_type} — {validation.blocked_reason} | args={args_preview}")
                        messages.append(AIMessage(content=validation.blocked_reason))
                        continue

                    cache_key = (tc_name, dict(tc_args))
                    cached = self._cache.get(*cache_key)
                    if cached:
                        self._end(s_tc, a_tc, "CACHE", f"Cache HIT | args={args_preview}")
                        messages.append(ToolMessage(content=cached, tool_call_id=tc_id))
                        continue

                    tool_fn = TOOLS_MAP.get(tc_name)
                    if tool_fn is None:
                        self._end(s_tc, a_tc, "ERROR", f"Tool not found in TOOLS_MAP | args={args_preview}")
                        continue
                    self._end(s_tc, a_tc, "PASS", f"Validation OK | args={args_preview}")

                    # Step 2: Tool Execution (gRPC call + result)
                    s_ex, a_ex = self._time(f"Exec: {tc_name}")
                    try:
                        result = await tool_fn.ainvoke(tc_args)
                    except Exception as e:
                        detail = f"Exception: {str(e)[:200]} | args={args_preview}"
                        self._end(s_ex, a_ex, "ERROR", detail)
                        messages.append(AIMessage(content=f"Lỗi khi gọi {tc_name}: {str(e)[:120]}"))
                        continue

                    # Check for PENDING (confirmation gate)
                    parsed = None
                    try:
                        parsed = json.loads(result)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    if parsed and parsed.get("status") == "pending":
                        self._end(s_ex, a_ex, "PENDING", f"Cần xác nhận từ user | args={args_preview} | msg={parsed.get('message', '')}")
                        self._sessions.set_pending(
                            session_id,
                            parsed["token"],
                            "AddItem",
                            parsed.get("action_data"),
                        )
                        result_pending = {
                            "status": "pending",
                            "reply": parsed["message"],
                            "token": parsed["token"],
                            "session_id": session_id,
                            "steps": list(self._steps),
                        }
                        self._sessions.append_message(session_id, "assistant", result_pending["reply"])
                        return result_pending

                    # Cache result (read-only tools)
                    if tc_name not in ("add_to_cart_tool", "get_cart_tool"):
                        self._cache.set(*cache_key, result)

                    result_preview = result[:200].replace("\n", "\\n")
                    self._end(s_ex, a_ex, "OK", f"Result: {result_preview}")
                    messages.append(ToolMessage(content=result, tool_call_id=tc_id))
                    iterations += 1
            else:
                # Final answer
                final = response.content if hasattr(response, "content") else str(response)

                # L5: Output Filter
                s5, a5 = self._time("OutputFilter")
                output = filter_output(final)
                final = output.filtered_response
                redacted_count = len(output.redacted_items) if hasattr(output, "redacted_items") else 0
                self._end(s5, a5, "PASS", f"Redacted {redacted_count} items" if redacted_count else "Không có PII")

                # Response Formatter: restructure thành markdown, bỏ icon
                sf, af = self._time("ResponseFormatter")
                try:
                    from agent.response_formatter import format_response
                    formatted = format_response(final)
                    if formatted:
                        final = formatted
                        self._end(sf, af, "OK", f"Restructured to markdown ({len(final)} chars)")
                    else:
                        self._end(sf, af, "SKIP", "Giữ nguyên bản gốc")
                except Exception as e:
                    self._end(sf, af, "ERROR", str(e)[:100])

                self._sessions.append_message(session_id, "assistant", final)
                self._sessions.touch(session_id)

                # Record token usage
                if hasattr(response, "usage_metadata"):
                    total_tokens = getattr(response.usage_metadata, "total_tokens", 0)
                    rate_limiter.record_token_usage(user_id, total_tokens)

                return {
                    "status": "ok",
                    "reply": final,
                    "session_id": session_id,
                    "steps": list(self._steps),
                }

        raise MaxIterationsExceeded()

    async def confirm(self, session_id: str, token: str) -> Dict[str, Any]:
        is_valid, action_data = verify_confirmation_token(token)
        if not is_valid:
            return {"status": "error", "reply": "Token không hợp lệ hoặc đã hết hạn."}

        import grpc
        from protos import demo_pb2_grpc, demo_pb2

        channel = grpc.insecure_channel(os.environ.get("CART_ADDR", "localhost:7070"))
        try:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            stub.AddItem(demo_pb2.AddItemRequest(
                user_id=action_data["user_id"],
                item=demo_pb2.CartItem(
                    product_id=action_data["params"]["product_id"],
                    quantity=action_data["params"]["quantity"],
                ),
            ))
            self._sessions.clear_pending(session_id)
            return {"status": "ok", "reply": "✅ Đã thêm vào giỏ hàng thành công!"}
        except grpc.RpcError as e:
            return {"status": "error", "reply": f"Lỗi gRPC: {e.details()}"}
        finally:
            channel.close()
