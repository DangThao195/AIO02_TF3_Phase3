"""
agent/copilot_agent.py — CopilotAgent: Structured Reasoning Architecture.

Triển khai AWS Bedrock (Amazon Nova) làm LLM backend.
6-layer pipeline: Intent Parser -> Planner -> Executor -> Evidence Aggregator -> Answer Generator -> Guard.
"""

import os
import json
import uuid
import time
import hashlib
import logging
from typing import Dict, Any, List, Optional

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from src.guardrails import (
    rate_limiter,
    check_input,
    check_input_bedrock,
    sanitize_pii_from_input,
    validate_tool_call,
    request_confirmation,
    verify_confirmation_token,
    filter_output,
    with_fallback,
    MaxIterationsExceeded,
    MAX_TOOL_ITERATIONS,
)
from src.memory import SessionStore, CacheStore
from src.tools import all_shopping_tools
from src.tools.catalog_tool import get_all_products, get_categories, get_top_rated_products
from src.llm.prompt import SYSTEM_PROMPT, INTENT_PARSE_PROMPT, EVIDENCE_SYNTHESIS_PROMPT

# ── AIE Mandates Engine Integration (Mandates #23, #24, #25) ──
from src.aie_mandates_engine import (
    get_cache, get_tracer, get_user_memory, get_circuit_breaker, get_gateway,
    retry_with_backoff, validate_llm_output
)

logger = logging.getLogger("agent.copilot_agent")

TOOLS_MAP: Dict[str, Any] = {t.name: t for t in all_shopping_tools}

def _now_ms() -> int:
    return int(time.time() * 1000)

class CopilotAgent:
    def __init__(self):
        self._sessions = SessionStore()
        self._cache = CacheStore()
        self.llm = self._build_llm()
        self._steps: List[Dict[str, Any]] = []

        # Mandates Engine Singletons
        self._mandate_cache = get_cache()
        self._user_memory = get_user_memory()
        self._tracer = get_tracer()
        self._circuit_breaker = get_circuit_breaker()
        self._gateway = get_gateway()

    def _build_llm(self):
        model = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
        region = os.getenv("BEDROCK_REGION", "ap-southeast-1")
        try:
            return ChatBedrockConverse(
                model=model,
                region_name=region,
                temperature=0.1,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error(f"[AGENT] Cannot init Bedrock LLM: {e}")
            return None

    def _time(self, action: str) -> tuple:
        return _now_ms(), action

    def _end(self, start: int, action: str, status: str, detail: str):
        self._steps.append({
            "action": action,
            "status": status,
            "detail": detail,
            "duration_ms": _now_ms() - start,
        })

    def _extract_text(self, response: Any) -> str:
        final = response.content if hasattr(response, "content") else str(response)
        if isinstance(final, list):
            text_parts = []
            for part in final:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
                elif hasattr(part, "text"):
                    text_parts.append(part.text)
            final = "".join(text_parts)
        return final or ""

    # LAYER 1: Intent Parser
    async def _parse_intent_with_llm(self, user_message: str, session: dict) -> dict:
        if not self.llm:
            # Fallback keyword logic if LLM is down
            lower = user_message.lower()
            if "cart" in lower or "giỏ hàng" in lower:
                if "add" in lower or "thêm" in lower:
                    return {"task_type": "add_to_cart", "target_entity": "cart", "context_reference": "this"}
                return {"task_type": "view_cart", "target_entity": "cart"}
            if "review" in lower or "đánh giá" in lower:
                if "highest" in lower or "best" in lower or "cao nhất" in lower:
                    return {"task_type": "rank", "target_entity": "product", "ranking_by": "review_score"}
                return {"task_type": "get_reviews", "target_entity": "review"}
            if "category" in lower or "danh mục" in lower:
                return {"task_type": "list_categories", "target_entity": "category"}
            if "all products" in lower or "tất cả sản phẩm" in lower:
                return {"task_type": "list_products", "target_entity": "product"}
            return {"task_type": "search", "target_entity": "product", "product_query": user_message}

        context = session.get("context", {})
        
        # FIX #3: Use a shallow copy to avoid mutating the session's context dict
        context_for_prompt = dict(context)
        if "last_search_results" in context_for_prompt:
            context_for_prompt["_display_list"] = [
                f"{i+1}. {p.get('name')}" for i, p in enumerate(context_for_prompt["last_search_results"])
            ]
            
        context_str = json.dumps(context_for_prompt, ensure_ascii=False)
        chat_history = self._sessions.get_recent_history_str(session.get("session_id", ""))
        prompt = INTENT_PARSE_PROMPT.format(chat_history=chat_history, context=context_str, user_message=user_message)
        
        # ── Check Cache cho Intent Parser ──
        prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        cache_key = f"intent:{prompt_hash}"
        cached_intent = self._cache.get_raw(cache_key)
        if cached_intent is not None:
            logger.debug("Cache HIT for Intent Parser")
            return cached_intent

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            text = self._extract_text(response)
            # clean code block if any
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            parsed_intent = json.loads(text.strip())
            
            # Lưu vào cache trong 10 phút
            self._cache.set_raw(cache_key, parsed_intent, ttl=600)
            return parsed_intent
        except Exception as e:
            logger.error(f"Intent parse failed: {e}")
            return {"task_type": "search", "target_entity": "product", "product_query": user_message}

    # Structured context resolution — trusts LLM's context_reference & ordinal_index
    def _resolve_context_references(self, intent: dict, session: dict) -> dict:
        context = session.get("context", {})
        context_ref = intent.get("context_reference", "none")
        ordinal = intent.get("ordinal_index")

        # Check ordinal reference first (e.g., thứ 1, thứ 2, 2nd, etc.)
        last_results = context.get("last_search_results", [])
        if ordinal and isinstance(ordinal, int) and 1 <= ordinal <= len(last_results):
            target_p = last_results[ordinal - 1]
            intent["product_id"] = target_p.get("id")
            intent["product_name"] = target_p.get("name")
            return intent

        # Try to fuzzy match product_name against last_search_results
        pname = intent.get("product_name", "").lower()
        if pname and not intent.get("product_id"):
            for p in last_results:
                db_name = p.get("name", "").lower()
                # If db_name is a substring of pname or vice-versa
                if db_name in pname or pname in db_name:
                    intent["product_id"] = p.get("id")
                    intent["product_name"] = p.get("name") # normalize name
                    break

        if context_ref in ["this", "that", "it", "previous", "last", "these"]:
            if context.get("last_product_name") and not intent.get("product_name"):
                intent["product_name"] = context["last_product_name"]
            if context.get("last_product_id") and not intent.get("product_id"):
                intent["product_id"] = context["last_product_id"]
        return intent

    # LAYER 2: LLM-driven Planner with Rule-based Fallback
    async def _build_plan_with_llm(self, intent: dict, user_id: str, session: dict) -> List[dict]:
        task_type = intent.get("task_type", "unknown")
        if task_type in ["greeting", "unknown", "unsupported_cart_action", "clarify"]:
            return []

        # Try LLM Planner
        if self.llm:
            try:
                from src.llm.prompt import LLM_PLANNER_PROMPT
                ctx_dict = session.get("context", {})
                # Lightweight context summary
                ctx_summary = {
                    "last_product_id": ctx_dict.get("last_product_id"),
                    "last_product_name": ctx_dict.get("last_product_name"),
                    "last_search_count": len(ctx_dict.get("last_search_results", [])),
                    "_display_list": ctx_dict.get("_display_list", [])
                }
                prompt = LLM_PLANNER_PROMPT.format(
                    context_json=json.dumps(ctx_summary, ensure_ascii=False),
                    intent_json=json.dumps(intent, ensure_ascii=False),
                    user_id=user_id
                )
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                text = self._extract_text(response).strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]
                
                plan = json.loads(text.strip())
                if isinstance(plan, list) and len(plan) <= 6:
                    # Validate tool names in plan
                    valid_tools = set(TOOLS_MAP.keys()).union({"__fetch_reviews_for_context__"})
                    if all(isinstance(step, dict) and step.get("name") in valid_tools for step in plan):
                        logger.info(f"[PLANNER] LLM generated plan with {len(plan)} steps")
                        return plan
            except Exception as e:
                logger.warning(f"[PLANNER] LLM plan generation failed ({e}), falling back to heuristic planner")

        # Fallback Heuristic Planner
        return self._build_plan_from_intent(intent, user_id)

    # LAYER 2 (Fallback): Generic Rule-based Planner
    def _build_plan_from_intent(self, intent: dict, user_id: str) -> List[dict]:
        task_type = intent.get("task_type", "unknown")
        plan = []

        if task_type == "add_to_cart":
            pid = intent.get("product_id")
            pname = intent.get("product_name")
            if pid:
                plan.append({"name": "add_to_cart_tool", "args": {"user_id": user_id, "product_id": pid, "quantity": intent.get("quantity", 1)}})
            elif pname:
                plan.append({"name": "get_product_id", "args": {"product_name": pname}})
                plan.append({"name": "add_to_cart_tool", "args": {"user_id": user_id, "product_id": "$PREV", "quantity": intent.get("quantity", 1)}})
            else:
                plan.append({"name": "add_to_cart_tool", "args": {"user_id": user_id, "product_id": "$CTX", "quantity": intent.get("quantity", 1)}})
        elif task_type == "view_cart":
            plan.append({"name": "get_cart_tool", "args": {"user_id": user_id}})
        elif task_type == "get_reviews":
            pname = intent.get("product_name")
            pid = intent.get("product_id")
            if pid:
                plan.append({"name": "get_product_reviews_tool", "args": {"product_id": pid}})
            elif pname:
                plan.append({"name": "get_product_id", "args": {"product_name": pname}})
                plan.append({"name": "get_product_reviews_tool", "args": {"product_id": "$PREV"}})
            else:
                plan.append({"name": "__fetch_reviews_for_context__", "args": {}})
        elif task_type == "lookup":
            pname = intent.get("product_name") or intent.get("product_query", "")
            if pname:
                plan.append({"name": "search_products_v2", "args": {"query": pname}})
        elif task_type in ["rank", "compare"]:
            # PRIORITY: Check for review ranking first (most specific)
            if intent.get("ranking_by") == "review_score":
                category = intent.get("constraints", {}).get("category")
                if category:
                    plan.append({"name": "get_best_reviewed_products_tool", "args": {"limit": 10, "category": category}})
                else:
                    plan.append({"name": "get_best_reviewed_products_tool", "args": {"limit": 10}})
            elif intent.get("product_query"):
                plan.append({"name": "search_products_v2", "args": {"query": intent.get("product_query")}})
                plan.append({"name": "__fetch_reviews_for_context__", "args": {}})
            else:
                plan.append({"name": "__fetch_reviews_for_context__", "args": {}})
        elif task_type == "list_categories":
            plan.append({"name": "get_categories", "args": {}})
        elif task_type == "list_products":
            plan.append({"name": "get_all_products", "args": {}})
        elif task_type == "search":
            # PRIORITY: Check for price constraints first
            constraints = intent.get("constraints", {})
            price_max = constraints.get("price_max")
            price_min = constraints.get("price_min")
            
            if price_max is not None or price_min is not None:
                # Use price filter tool
                args = {"limit": 20}
                if price_max is not None:
                    args["max_price"] = price_max
                if price_min is not None:
                    args["min_price"] = price_min
                plan.append({"name": "get_products_by_price_range", "args": args})
            else:
                # Regular search
                q = intent.get("product_query", "")
                plan.append({"name": "search_products_v2", "args": {"query": q}})
        elif task_type == "convert_currency":
            plan.append({"name": "convert_currency_tool", "args": {
                "from_currency": intent.get("from_currency", "USD"),
                "to_currency": intent.get("to_currency", "VND"),
                "amount_units": intent.get("quantity", 1),
            }})
        elif task_type == "get_shipping":
            address = intent.get("shipping_address") or intent.get("product_query", "")
            plan.append({"name": "get_shipping_quote_tool", "args": {"address": address}})
        elif task_type == "get_recommendations":
            if intent.get("target_entity") == "cart":
                plan.append({"name": "get_cart_tool", "args": {"user_id": user_id}})
                plan.append({"name": "get_recommendations_tool", "args": {"product_id": "$PREV_CART"}})
            else:
                pname = intent.get("product_name")
                pid = intent.get("product_id")
                if pid:
                    plan.append({"name": "get_recommendations_tool", "args": {"product_id": pid}})
                elif pname:
                    plan.append({"name": "get_product_id", "args": {"product_name": pname}})
                    plan.append({"name": "get_recommendations_tool", "args": {"product_id": "$PREV"}})
                else:
                    plan.append({"name": "get_recommendations_tool", "args": {"product_id": "$CTX"}})

        if intent.get("needs_reviews"):
            plan.append({"name": "__fetch_reviews_for_context__", "args": {}})

        return plan

    # LAYER 3 & 4: Executor + Evidence Aggregator
    async def _execute_and_aggregate(self, plan: List[dict], user_id: str, session: dict) -> dict:
        import asyncio
        evidence = {}
        prev_result = None

        for step in plan:
            tc_name = step["name"]
            tc_args = dict(step.get("args", {}))
            
            # Resolve dependencies
            if tc_args.get("product_id") == "$PREV":
                if isinstance(prev_result, dict) and prev_result.get("status") == "not_found":
                    pname = prev_result.get('product_name', '')
                    return {"status": "error", "error": f"Xin lỗi, không tìm thấy sản phẩm '{pname}' trong hệ thống. Vui lòng kiểm tra lại tên sản phẩm hoặc thử tìm kiếm bằng từ khóa khác."}
                if isinstance(prev_result, dict) and prev_result.get("product_id"):
                    tc_args["product_id"] = prev_result["product_id"]
                elif session.get("context", {}).get("last_product_id"):
                    tc_args["product_id"] = session["context"]["last_product_id"]
                else:
                    return {"status": "error", "error": "Xin lỗi, không thể xác định sản phẩm bạn đang muốn thực hiện thao tác. Vui lòng tìm kiếm sản phẩm trước."}

            elif tc_args.get("product_id") == "$PREV_CART":
                if isinstance(prev_result, dict) and prev_result.get("items"):
                    tc_args["product_id"] = prev_result["items"][0]["product_id"]
                else:
                    return {"status": "error", "error": "Your cart is empty. Cannot find related products."}

            elif tc_args.get("product_id") == "$CTX":
                if session.get("context", {}).get("last_product_id"):
                    tc_args["product_id"] = session["context"]["last_product_id"]
                else:
                    return {"status": "error", "error": "Xin lỗi, không thể xác định sản phẩm từ ngữ cảnh trước đó. Bạn vui lòng tìm kiếm hoặc chỉ định rõ sản phẩm nhé."}

            if tc_name == "__fetch_reviews_for_context__":
                search_ids = session.get("context", {}).get("last_search_ids", [])
                if not search_ids and session.get("context", {}).get("last_product_id"):
                    search_ids = [session["context"]["last_product_id"]]
                
                rev_tool = TOOLS_MAP.get("get_product_reviews_tool")
                
                async def fetch_one(pid):
                    try:
                        r_str = await rev_tool.ainvoke({"product_id": pid})
                        return json.loads(r_str)
                    except Exception as e:
                        return {"product_id": pid, "status": "error", "error": str(e)}

                all_reviews = await asyncio.gather(*[fetch_one(pid) for pid in search_ids[:5]])
                
                evidence[tc_name] = {
                    "status": "success", 
                    "products_context": session.get("context", {}).get("last_search_results", []),
                    "results": list(all_reviews)
                }
                continue

            validation = validate_tool_call(tc_name, tc_args, user_id)
            if not validation.is_valid:
                return {"status": "error", "error": f"Blocked: {validation.blocked_reason}"}

            tool_fn = TOOLS_MAP.get(tc_name)
            if not tool_fn:
                continue

            try:
                # ── Kiểm tra Cache Tool ──
                cached_str = self._cache.get(tc_name, tc_args)
                if cached_str is not None:
                    res_str = cached_str
                    logger.debug(f"Cache HIT for tool {tc_name}")
                else:
                    res_str = await tool_fn.ainvoke(tc_args)
                    self._cache.set(tc_name, tc_args, res_str)
                    logger.debug(f"Cache MISS for tool {tc_name}")

                try:
                    res_json = json.loads(res_str)
                except Exception:
                    res_json = {"raw": res_str}
                
                prev_result = res_json
                evidence[tc_name] = res_json

                # Update context
                ctx = session.setdefault("context", {})
                if tc_name == "get_product_id" and res_json.get("status") == "success":
                    ctx["last_product_id"] = res_json.get("product_id")
                    ctx["last_product_name"] = res_json.get("product_name")
                elif tc_name == "search_products_v2" and res_json.get("status") == "success":
                    prods = res_json.get("products", [])
                    if prods:
                        ctx["last_product_id"] = prods[0]["id"]
                        ctx["last_product_name"] = prods[0]["name"]
                        ctx["last_search_ids"] = [p["id"] for p in prods]
                        ctx["last_search_results"] = prods
                elif tc_name == "get_all_products" and res_json.get("status") == "success":
                    prods = res_json.get("products", [])
                    if prods:
                        ctx["last_search_ids"] = [p["id"] for p in prods]
                        ctx["last_search_results"] = prods

                if res_json.get("status") == "pending":
                    return res_json # Return immediately for pending actions

            except Exception as e:
                evidence[tc_name] = {"status": "error", "error": str(e)}

        # Persist the updated context to SessionStore
        if "session_id" in session:
            self._sessions.save(session["session_id"], session)

        return {"status": "success", "evidence": evidence}

    async def _check_faithfulness(self, evidence: dict, reply: str) -> bool:
        if not self.llm or not evidence:
            return True
        if "sự cố kỹ thuật" in reply.lower() or "không có thông tin" in reply.lower() or len(reply) < 30:
            return True
        
        prompt = f"""
You are a faithfulness checker. Compare the REPLY with the EVIDENCE.
If the REPLY contains specific facts (like numbers, specs, features) that are NOT supported by the EVIDENCE, return "FAIL".
Otherwise, return "PASS".
EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)[:32000]}
REPLY:
{reply}
"""
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            text = self._extract_text(response).strip().upper()
            return "FAIL" not in text
        except Exception as e:
            logger.error(f"Faithfulness check failed: {e}")
            return True

    # LAYER 5 & 6: Answer Generator + Grounding
    async def _generate_grounded_answer(self, user_message: str, evidence: dict, intent: dict) -> str:
        if not self.llm:
            return f"Evidence retrieved: {json.dumps(evidence, ensure_ascii=False)[:500]}"

        # Inject intent metadata into evidence so LLM has full context
        # to generate appropriate responses for ALL task types (greeting, unknown,
        # unsupported_cart_action, etc.) in the user's own language — no hardcoded strings.
        evidence["__intent_meta__"] = {
            "task_type": intent.get("task_type"),
            "target_entity": intent.get("target_entity"),
        }

        # ── Attribute mismatch detection ──────────────────────────────────────
        # If the user searched with a specific attribute/subtype (product_query),
        # check whether any returned product's name actually contains that attribute.
        # If none match, inject a flag so the synthesis LLM can reliably report
        # "no matching products" rather than mislabeling mismatched results.
        # This is a pre-validation step so the LLM doesn't need to reason about it.
        product_query = intent.get("product_query", "")
        if product_query and intent.get("task_type") in ["list_products", "search"]:
            # Collect all product names returned in evidence
            all_product_names: list[str] = []
            for tool_result in evidence.values():
                if isinstance(tool_result, dict):
                    for p in tool_result.get("products", []):
                        if isinstance(p, dict) and p.get("name"):
                            all_product_names.append(p["name"].lower())

            if all_product_names:
                query_terms = [t.strip().lower() for t in product_query.split() if len(t.strip()) > 2]
                any_match = any(
                    any(term in name for name in all_product_names)
                    for term in query_terms
                )
                if not any_match:
                    evidence["__intent_meta__"]["attribute_unmatched"] = True
                    evidence["__intent_meta__"]["requested_attribute"] = product_query

        ev_str = json.dumps(evidence, ensure_ascii=False)
        prompt = EVIDENCE_SYNTHESIS_PROMPT.format(user_message=user_message, evidence=ev_str)

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ])
            return self._extract_text(response)
        except Exception as e:
            print(f"=== SYNTHESIS ERROR EXCEPTION ===: {e}")
            logger.error(f"Synthesis failed: {e}")
            return "Xin lỗi, tôi không có thông tin chi tiết về câu hỏi này dựa trên dữ liệu hiện tại."

    @with_fallback
    async def chat(self, session_id: str, user_id: str, user_message: str) -> Dict[str, Any]:
        self._steps = []

        s1, a1 = self._time("RateLimiter")
        rate_res = rate_limiter.check_rate_limit(user_id)
        if not rate_res.is_allowed:
            self._end(s1, a1, "BLOCK", rate_res.blocked_reason)
            return {"status": "error", "reply": rate_res.blocked_reason, "session_id": session_id, "steps": list(self._steps)}
        self._end(s1, a1, "PASS", "Rate OK")

        s2, a2 = self._time("InputFilter")
        if not check_input_bedrock(user_message).is_safe:
            detail = "Message blocked by safety filters."
            self._end(s2, a2, "BLOCK", detail)
            return {"status": "error", "reply": detail, "session_id": session_id, "steps": list(self._steps), "intent": {}, "evidence": {}}
        self._end(s2, a2, "PASS", "Safety OK")

        # Sanitize PII from user_message before any LLM call.
        # This ensures the LLM never "sees" raw PII (SSN, credit card, email, phone)
        # and therefore cannot accidentally summarize, mention, or echo it in outputs.
        user_message = sanitize_pii_from_input(user_message)

        session = self._sessions.get_or_create(session_id, user_id)
        self._sessions.append_message(session_id, "user", user_message)

        # ── Mandate #23: Check Semantic Cache with User Isolation ──
        cached_res = self._mandate_cache.get(user_message, user_id=user_id)
        if cached_res:
            reply = cached_res["response"]
            self._end(s2, a2, "PASS", "Semantic Cache HIT")
            self._sessions.append_message(session_id, "assistant", reply)
            return {
                "status": "ok",
                "reply": reply,
                "session_id": session_id,
                "steps": list(self._steps),
                "intent": {"task_type": "cached"},
                "evidence": {},
                "cache_hit": True,
            }

        # ── Mandate #23: Inject Cross-Session Long-Term Memory ──
        user_mem = self._user_memory.recall(user_id)
        if user_mem:
            session_ctx = session.setdefault("context", {})
            session_ctx["user_memory"] = user_mem
            logger.info("[AGENT] Recalled cross-session memory for user %s: %s", user_id, user_mem.get("preferences"))

        # L1: Parse Intent
        s3, a3 = self._time("IntentParser")
        raw_intent = await self._parse_intent_with_llm(user_message, session)
        intent = self._resolve_context_references(raw_intent, session)
        self._end(s3, a3, "OK", f"Parsed: {intent.get('task_type')} on {intent.get('target_entity')}")

        if intent.get("needs_clarification"):
            reply = intent.get("clarification_question", "Could you please clarify?")
            self._sessions.append_message(session_id, "assistant", reply)
            return {"status": "ok", "reply": reply, "session_id": session_id, "steps": list(self._steps), "intent": intent, "evidence": {}}

        # Short-circuit: task types that never require tool execution.
        # Route them directly to answer generation with empty evidence so the LLM
        # produces a principled refusal/greeting grounded in the intent meta,
        # not an implementation detail (e.g. "cart is empty").
        _NO_TOOL_TASKS = {"greeting", "unknown", "unsupported_cart_action", "clarify"}
        if intent.get("task_type") in _NO_TOOL_TASKS:
            s_skip, a_skip = self._time("AnswerGenerator")
            reply = await self._generate_grounded_answer(user_message, {}, intent)
            output_filtered = filter_output(reply)
            reply = output_filtered.filtered_response
            self._end(s_skip, a_skip, "OK", f"Direct answer for task_type={intent.get('task_type')}")
            self._sessions.append_message(session_id, "assistant", reply)
            self._sessions.touch(session_id)
            return {
                "status": "ok",
                "reply": reply,
                "session_id": session_id,
                "steps": list(self._steps),
                "intent": intent,
                "evidence": {},
            }

        # L2: Planner
        s4, a4 = self._time("Planner")
        plan = await self._build_plan_with_llm(intent, user_id, session)
        self._end(s4, a4, "OK", f"Plan steps: {len(plan)}")

        # L3 & L4: Execute and Aggregate
        s5, a5 = self._time("Executor")
        exec_result = await self._execute_and_aggregate(plan, user_id, session)
        self._end(s5, a5, "OK", f"Execution status: {exec_result.get('status')}")

        if exec_result.get("status") == "pending":
            reply = exec_result.get("message", "Confirmation needed.")
            self._sessions.set_pending(session_id, exec_result["token"], "AddItem", exec_result.get("action_data"))
            self._sessions.append_message(session_id, "assistant", reply)
            return {
                "status": "pending",
                "reply": reply,
                "token": exec_result["token"],
                "session_id": session_id,
                "steps": list(self._steps),
                "intent": intent,
                "evidence": exec_result.get("evidence", {}),
            }

        if exec_result.get("status") == "error":
            reply = exec_result.get("error", "Error executing plan.")
            self._sessions.append_message(session_id, "assistant", reply)
            return {"status": "error", "reply": reply, "session_id": session_id, "steps": list(self._steps), "intent": intent, "evidence": exec_result.get("evidence", {})}

        # L5 & L6: Answer Gen + Guarding
        s6, a6 = self._time("AnswerGenerator")
        reply = await self._generate_grounded_answer(user_message, exec_result.get("evidence", {}), intent)
        logger.info(f"=== DEBUG RAW REPLY ===\n{reply}\n=======================")
        
        # Faithfulness Guard (skip for exact SQL DB queries like list_products and list_categories)
        if intent.get("task_type") not in ["greeting", "unsupported_cart_action", "unknown", "list_products", "list_categories"]:
            is_faithful = await self._check_faithfulness(exec_result.get("evidence", {}), reply)
            logger.info(f"[DEBUG_FAITHFULNESS] Is faithful: {is_faithful}")
            if not is_faithful:
                logger.warning("[GUARDRAIL] Hallucination detected. Overriding reply.")
                reply = "Xin lỗi, tôi không có thông tin chi tiết về câu hỏi này dựa trên dữ liệu hiện tại."
                
        output_filtered = filter_output(reply)
        reply = output_filtered.filtered_response
        self._end(s6, a6, "OK", "Answer generated and filtered")

        # ── Mandate #23: Save Successful Response to Semantic Cache (User Isolated) ──
        if intent.get("task_type") not in ["unsupported_cart_action", "unknown"]:
            self._mandate_cache.set(user_message, reply, user_id=user_id, ttl=300)

        self._sessions.append_message(session_id, "assistant", reply)
        self._sessions.touch(session_id)

        return {
            "status": "ok",
            "reply": reply,
            "session_id": session_id,
            "steps": list(self._steps),
            "intent": intent,
            "evidence": exec_result.get("evidence", {}),
            "cache_hit": False,
        }

    async def confirm(self, session_id: str, token: str, confirmed: bool = True) -> Dict[str, Any]:
        is_valid, action_data = verify_confirmation_token(token)
        if not is_valid:
            return {"status": "error", "reply": "Token không hợp lệ hoặc đã hết hạn."}

        self._sessions.clear_pending(session_id)

        if not confirmed:
            self._sessions.append_message(session_id, "user", "Hủy xác nhận")
            self._sessions.append_message(session_id, "assistant", "❌ Đã hủy thao tác thêm vào giỏ hàng.")
            return {"status": "cancelled", "reply": "❌ Đã hủy thao tác thêm vào giỏ hàng."}

        import grpc
        from src.protos import demo_pb2_grpc, demo_pb2
        from src.tools.service_config import CART_ADDR

        channel = grpc.insecure_channel(CART_ADDR)
        try:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            stub.AddItem(demo_pb2.AddItemRequest(
                user_id=action_data["user_id"],
                item=demo_pb2.CartItem(
                    product_id=action_data["params"]["product_id"],
                    quantity=action_data["params"]["quantity"],
                ),
            ))
            self._sessions.append_message(session_id, "user", "Xác nhận hành động")
            self._sessions.append_message(session_id, "assistant", "✅ Đã thêm vào giỏ hàng thành công!")
            return {"status": "ok", "reply": "✅ Đã thêm vào giỏ hàng thành công!"}
        except grpc.RpcError as e:
            return {"status": "error", "reply": f"Lỗi gRPC: {e.details()}"}
        finally:
            channel.close()

    @property
    def sessions(self) -> "SessionStore":
        return self._sessions

    @property
    def cache_store(self) -> "CacheStore":
        return self._cache
