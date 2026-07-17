# Shopping Copilot — AI Agent System Package

> **Version:** 3.2.0 | **Date:** 2026-07-17 | **Team:** AIO02 — TF3
> **Architecture:** 2-Layer Planner (Intent Parser → Task Graph Builder) + DAG-based Tool Executor + Reflection + Template-First Response + Semantic Decision Gate Layer (Nova Lite, §10.6)
> This document is the complete system specification. Anyone can rebuild the entire module from this document.

---

## Table of Contents

1. [What is Shopping Copilot?](#1-what-is-shopping-copilot)
2. [System Architecture](#2-system-architecture)
3. [Project Structure](#3-project-structure)
4. [How It Works — End-to-End Flow](#4-how-it-works--end-to-end-flow)
5. [Guardrail Pipeline (6 Security Layers)](#5-guardrail-pipeline-6-security-layers)
6. [Tool System v2 — Fixed Output Schema](#6-tool-system-v2--fixed-output-schema)
7. [2-Layer Planner](#7-2-layer-planner)
8. [Tool Executor (DAG Runner)](#8-tool-executor-dag-runner)
8.5. [Reflection Node](#85-reflection-node)
9. [Write + Confirm Flow](#9-write--confirm-flow)
10. [Response Verifier (Template-First)](#10-response-verifier-template-first)
10.5. [HallucinationGuard & FallbackGenerator](#105-hallucinationguard--fallbackgenerator)
10.6. [Semantic Decision Gate Layer (Nova Lite)](#106-semantic-decision-gate-layer-nova-lite)
11. [System Prompt Design](#11-system-prompt-design)
12. [State Design](#12-state-design)
13. [Cache Strategy (Redis)](#13-cache-strategy-redis)
13a. [Resource Limits & Production Guardrails](#13a-resource-limits--production-guardrails)
13b. [Observability Metrics](#13b-observability-metrics)
14. [API Server](#14-api-server)
15. [Configuration & Environment](#15-configuration--environment)
16. [Running the System](#16-running-the-system)
17. [Testing](#17-testing)
18. [Operating Costs](#18-operating-costs)
19. [Limitations & Roadmap](#19-limitations--roadmap)

---

## 1. What is Shopping Copilot?

Shopping Copilot is an **AI shopping assistant** for TechX Corp's e-commerce platform. It lets customers interact using natural language — asking questions, searching products, reading reviews, and adding items to their cart — all through a chat interface.

Think of it as a smart shopping companion that understands both English and Vietnamese, knows how to use the store's backend systems, and is designed with security at every level.

### What can it do?

| Capability | Example Query | How it works |
|---|---|---|
| Search products | "Find telescopes under $200" | Multi-strategy search via ProductCatalog gRPC |
| Get reviews | "What do people say about the camping stove?" | Fetches reviews via ProductReview gRPC |
| Manage cart | "Add 2 tents to my cart" | AddItem via CartService gRPC (with confirmation) |
| View cart | "What's in my cart?" | GetCart via CartService gRPC |
| Get recommendations | "What else might I like?" | ListRecommendations via Recommendation gRPC |
| Convert currency | "How much is that in VND?" | Convert via Currency gRPC |
| Shipping estimate | "How much to ship to Hanoi?" | GetQuote via Shipping REST |

### Design Principles

| Principle | What it means |
|---|---|
| **2-Layer Planner** | Intent Parser (rule-based → LLM fallback) + Task Graph Builder (LLM chọn tool + nối dependency) — argument filling chuyển xuống Executor |
| **DAG-based Execution** | Plan là DAG (node + edges), Executor chạy song song node độc lập qua `asyncio.gather` |
| **Reflection + Partial Replan** | Executor → Reflection → cần replan? → Planner (chỉ sửa node lỗi, không restart full) |
| **Template-First Response** | Cart/shipping/currency/review dùng template trực tiếp từ tool output; LLM chỉ gọi khi cần summarize/compare/explain |
| **Defense-in-Depth** | 6 independent security layers — each stops a different attack vector |
| **Zero-cost path** | Fast regex checks + cache handle most requests; LLM only used when needed |
| **Stateless by design** | Confirmation tokens use HMAC signatures — no server-side storage needed |
| **Grounded responses** | Every answer traces back to real database/catalog data |
| **Never trust the LLM** | Both input and output are independently validated |
| **Fixed Tool Output Schema** | Mỗi tool có output schema cố định — planner biết trước dữ liệu nhận được |
| **Binary Gate cho quyết định nhị phân** | Các điểm quyết định Yes/No (plan hợp lệ?, hallucination ngữ nghĩa?, replan?) dùng Nova Lite ép output tối giản — rẻ và nhanh hơn nhiều so với để LLM sinh câu trả lời tự do (§10.6) |
| **Confidence-gated execution** | Mỗi plan/step có confidence score; nếu < threshold → route sang `ask_user` thay vì execute mù |

---

## 2. System Architecture

### High-Level Overview

```
                    ┌─────────────────────────────────────┐
                    │          Customer (User)             │
                    │   (Web App / Mobile / Chat UI)       │
                    └───────────────┬─────────────────────┘
                                    │ HTTP POST /api/chat
                                    ▼
               ┌───────────────────────────────────────────────────┐
               │            FastAPI Server (main.py)               │
               │                                                    │
               │  ┌───────────────────────────────────────────────┐ │
               │  │          Copilot Graph (LangGraph)            │ │
               │  │                                               │ │
               │  │  START → input_guard                          │ │
               │  │    ├── blocked ──────────────────────────┐   │ │
               │  │    └── pass → INTENT_PARSER              │   │ │
               │  │                  │ (rule-based ─ LLM     │   │ │
               │  │                  │   fallback)           │   │ │
               │  │           TASK_GRAPH_BUILDER             │   │ │
               │  │          (LLM chọn tool + nối edge)     │   │ │
               │  │                  │                       │   │ │
               │  │        TOOL_EXECUTOR (DAG runner)        │   │ │
               │  │      ┌────► parallel node ────┐         │   │ │
               │  │      │    └► parallel node ←──┤         │   │ │
               │  │      └────► sequential node    │         │   │ │
               │  │               │                │         │   │ │
               │  │          REFLECTION             │         │   │ │
               │  │       ├── pass ──────────────── │         │   │ │
               │  │       └── replan ──► TGB (partial)       │   │ │
               │  │               │ pause? (write confirm)    │   │ │
               │  │           RESPONSE_VERIFIER               │   │ │
               │  │       (template ── LLM theo complexity)   │   │ │
               │  │               │                           │   │ │
               │  │        HALLUCINATION_GUARD                │   │ │
               │  │       ├── pass (≥80%)                     │   │ │
               │  │       │    → answer_generator → END       │   │ │
               │  │       └── fail (<80%)                     │   │ │
               │  │            → FALLBACK_GENERATOR           │   │ │
               │  │                 → answer_generator → END  │   │ │
               │  └───────────────────────────────────────────┘   │ │
               │                                                   │
               │  [L1-L6 Guardrails wrap relevant nodes]          │
               └───────────────────────────────────────────────────┘
                                    │
                                    ▼
               ┌───────────────────────────────────────────────────┐
               │          TechX Corp EKS Microservices             │
               │                                                   │
               │  ┌──────────┐ ┌───────────┐ ┌───────────────┐   │
               │  │  Cart    │ │  Product   │ │  Product      │   │
               │  │  Service │ │  Catalog   │ │  Reviews      │   │
               │  ├──────────┤ ├───────────┤ ├───────────────┤   │
               │  │ Valkey   │ │ Postgres   │ │ Postgres      │   │
               │  └──────────┘ └───────────┘ └───────────────┘   │
               │                                                   │
               │  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
               │  │Currency  │ │Recommend │ │ Shipping │        │
               │  │Service   │ │-ation    │ │ Service  │        │
               │  ├──────────┤ ├──────────┤ ├──────────┤        │
               │  │ (memory) │ │ (memory)  │ │ (memory) │        │
               │  └──────────┘ └──────────┘ └──────────┘        │
               └───────────────────────────────────────────────────┘
```

### So sánh v2 vs v3

| Khía cạnh | v2 (Intent + Workflows) | v3.2 (2-Layer Planner + DAG + Reflection) |
|---|---|---|
| Luồng quyết định | intent_classifier → router → workflow fixed | Intent Parser (rule → LLM fallback) → Task Graph Builder (DAG) |
| Workflow | 7 subgraph riêng (search, review, cart...) | Không workflow — DAG runner duy nhất |
| Tool gọi | Mỗi workflow gọi tool riêng trong subgraph | Task Graph Builder chọn tool + nối edge → Executor chạy DAG |
| Entity extraction | EntityExtractor node riêng | Intent Parser + Executor (resolve tại runtime) |
| Resolve product | ResolveProductNode riêng | Executor chạy search → resolve product_id tự động |
| Plan structure | Workflow fixed (tuyến tính) | DAG (node + edges, chạy song song node độc lập) |
| Tool orchestration | Trong tay LLM (react loop) | Trong code (DAG runner) |
| Reflection | Không có | Reflection node sau Executor → partial replan nếu cần |
| Response | ResponseEditor (LLM rewrite) | Template-first (cart/shipping/currency/review) + LLM cho summarize/compare |
| Tool output | Free text + raw fields | Fixed schema, price normalized |
| Hallucination check | Không có | Rule-based (groundedness score ≥80%) + semantic claim check |
| Confidence scoring | Không có | Mỗi plan/step có confidence; < threshold → ask_user |
| Planner memory | Không có | Lưu `last_search`, `current_cart`, `product_id` → feed vào reasoning context |

---

## 3. Project Structure

```
shopping-copilot/
│
├── graph/                           # LangGraph StateGraph
│   ├── __init__.py
│   ├── main_graph.py                # build_graph() — planner-centric flow
│   ├── state.py                     # ShoppingState (updated v3)
│   ├── edges.py                     # route_after_input_guard
│   │
│   ├── nodes/                       # Graph nodes
│   │   ├── __init__.py
│   │   ├── input_guard.py           # L1 + L2a + L2b
│   │   ├── intent_parser.py         # ⏳ Rule-based (→ LLM fallback) — parse intent + entities
│   │   ├── task_graph_builder.py    # ⏳ LLM chọn tool + nối edge → DAG plan
│   │   ├── tool_executor.py         # ⏳ DAG runner (parallel, conditional, cache, confirm, retry)
│   │   ├── reflection.py            # ⏳ Post-execution check → partial replan signal
│   │   ├── response_verifier.py     # ⏳ Template-first + LLM fallback, temperature động
│   │   ├── hallucination_guard.py   # ⏳ Rule-based + semantic claim check (score ≥80%)
│   │   ├── fallback_generator.py    # ⏳ Template fallback khi hallucination detected
│   │   ├── answer_generator.py      # L5 + format
│   │   └── confirmation.py          # HMAC confirmation handler
│   │
│   ├── gates/                       # Semantic Decision Gate Layer (Nova Lite)
│   │   ├── __init__.py
│   │   ├── gate_node.py             # ⏳ Shared Gate Node interface
│   │   ├── routing_gate.py          # ⏳ Fast path detection
│   │   ├── plan_validity_gate.py    # ⏳ DAG validity check
│   │   ├── semantic_hallucination_gate.py  # ⏳ Semantic hallucination check
│   │   ├── confirm_parse_gate.py    # ⏳ Natural language confirm parse
│   │   └── replan_gate.py           # ⏳ Replan decision gate
│   │
│   └── workflows/                   # ❌ ĐÃ XOÁ (v3 planner-centric)
│
├── guardrails/                      # ✅ 6 security layers — GIỮ NGUYÊN
│   ├── __init__.py
│   ├── rate_limiter.py              # L1: Per-pod rate limiting
│   ├── input_filter.py              # L2: Regex (38+ patterns) + Bedrock
│   ├── tool_validator.py            # L3: Allow-list + isolation + bounds
│   ├── confirmation.py              # L4: HMAC stateless confirmation tokens
│   ├── output_filter.py             # L5: PII & system info redaction
│   └── fallback.py                  # L6: Never-crash exception handler
│
├── tools/                           # LangChain tools → EKS gRPC
│   ├── __init__.py                  # Imports all tools (triggers registry)
│   ├── registry.py                  # ✅ ToolRegistry + ToolSpec (đăng ký tập trung)
│   ├── cart_tool.py                 # add_to_cart_tool, get_cart_tool
│   ├── review_tool.py               # get_product_reviews_tool
│   ├── recommendation_tool.py       # get_recommendations_tool
│   ├── currency_tool.py             # convert_currency_tool
│   ├── shipping_tool.py             # get_shipping_quote_tool (REST)
│   ├── product_tool.py              # get_product_details_tool
│   ├── checkout_tool.py             # checkout_tool (WRITE)
│   ├── order_tool.py                # get_order_status_tool
│   └── search/                      # ✅ Multi-strategy search module
│       ├── __init__.py              # search_products_v2 (output schema updated)
│       ├── orchestrator.py
│       ├── query_analyzer.py
│       ├── strategies.py
│       ├── ranker.py
│       ├── reranker.py
│       ├── synonym_cache.py
│       ├── models.py                # SearchToolResponse — output schema
│       └── cache.py
│
├── llm/                             # LLM abstraction layer
│   ├── __init__.py
│   ├── llm.py                       # LLMClient (Groq API) + MockLLMClient
│   └── prompt.py                    # ⏳ System prompt (planner prompt)
│
├── memory/                          # Session & cache storage
│   ├── __init__.py
│   ├── store.py                     # In-memory TTL + LRU (dev)
│   └── redis_store.py               # Redis cache client (production — §13)
│
├── protos/                          # gRPC protobuf (compiled)
│
├── spec/                            # Design documents
│   ├── agentic_design.md            # This file
│   └── guardrail_design_doc.md      # Guardrail deep-dive
│
├── tests/
│   └── test_interactive.py          # CLI test (mock/live/no-llm)
│
├── main.py                          # FastAPI server entry point
├── requirements.txt
└── .env
```

### Build Status (v3.2)

| Module | Status | Notes |
|---|---|---|
| `guardrails/` | ✅ Built | All 6 layers, importable |
| `memory/store.py` | ✅ Built | SessionStore + CacheStore |
| `main.py` | ✅ Built | FastAPI with 4 endpoints |
| `protos/` | ✅ Built | Compiled protobuf |
| `tools/registry.py` | ✅ Built | ToolRegistry + ToolSpec (singleton) |
| `tools/__init__.py` | ✅ Built | All tools exported + auto-register vào registry |
| `tools/search/` | ✅ Built | Multi-strategy search |
| `tools/product_tool.py` | ✅ Built | get_product_details_tool |
| `tools/checkout_tool.py` | ✅ Built | checkout_tool (WRITE) |
| `tools/order_tool.py` | ✅ Built | get_order_status_tool |
| `llm/llm.py` | ✅ Built | Groq API + MockLLMClient |
| `graph/nodes/input_guard.py` | ✅ Built | Kept from v2 |
| `graph/nodes/answer_generator.py` | ✅ Built | Kept from v2 |
| `graph/nodes/confirmation.py` | ✅ Built | Kept from v2 |
| `graph/nodes/intent_parser.py` | ⏳ Not built | New — spec in §7 |
| `graph/nodes/task_graph_builder.py` | ⏳ Not built | New — spec in §7 |
| `graph/nodes/tool_executor.py` | ⏳ Not built | New — DAG runner, spec in §8 |
| `graph/nodes/reflection.py` | ⏳ Not built | New — spec in §8.5 |
| `graph/nodes/response_verifier.py` | ⏳ Not built | New — template-first + LLM |
| `graph/nodes/hallucination_guard.py` | ⏳ Not built | New — spec in §10.5 |
| `graph/nodes/fallback_generator.py` | ⏳ Not built | New — template fallback on hallucination |
| `graph/gates/` | ⏳ Not built | 6 gate files, spec in §10.6 |
| `graph/main_graph.py` | ⏳ Update needed | New DAG-centric edges + reflection |
| `graph/state.py` | ⏳ Update needed | Add tool_history, dependency_graph, confidence, ... |
| `llm/prompt.py` | ⏳ Empty | TGB prompt spec in §11 |
| `tests/test_interactive.py` | ✅ Built | 3 modes (mock/live/no-llm) |

---

## 4. How It Works — End-to-End Flow

### Normal Chat Flow (Read Operations)

```
POST /api/chat
  Body: { message: "what's in my cart?",
          session_id: "550e8400-...",
          user_id: "user_abc123" }
          
  Step 1 → FastAPI receives request, calls graph.ainvoke()
  Step 2 → [L6] Fallback wrapper activates
  Step 3 → input_guard: [L1] rate limit + [L2a] regex filter + [L2b] Bedrock
  Step 4 → PLANNER: LLM sinh plan dựa trên query + tool output schemas
               Example plan: [{"tool": "get_cart_tool", "args": {"user_id": "..."}}]
  Step 5 → TOOL_EXECUTOR_LOOP: iterate plan
               a. [L3] validate tool call (allow-list, bounds, user isolation)
               b. Cache check (read tools only)
               c. Execute tool → gRPC call
               d. Normalize output (price formatting, schema validation)
               e. Append result to state.tool_results
  Step 6 → response_verifier: từ tool_results + user query
               a. Tính complexity score
               b. Chọn temperature (0.1-0.6)
               c. LLM sinh câu trả lời grounded
  Step 7 → answer_generator: [L5] output filter + format
  Step 8 → Return { reply, session_id } to user
```

### Add-to-Cart Flow (Write + Confirm)

```
POST /api/chat
  Body: { message: "add 2 telescopes to my cart", ... }
  
  Steps 1-3: Same as read flow
  Step 4: PLANNER sinh plan:
               [{"tool": "search_products_v2", ...},
                {"tool": "add_to_cart_tool", ...}]
  Step 5: TOOL_EXECUTOR_LOOP
               a. search_products_v2 → tìm product_id
               b. add_to_cart_tool → [L4] confirmation gate
               c. Tool returns {status: "pending", token: "eyJ..."}
               d. Loop PAUSES → graph checkpoint
               e. Return token to user
  Step 6: User clicks "Confirm" → POST /api/confirm
  Step 7: Resume graph → execute AddItem gRPC
  Step 8: response_verifier → "Đã thêm 2 telescope vào giỏ!"
```

### Error Flow (Never Crash)

```
Any exception:
  → Caught by @with_fallback [L6]
  
  Planner fails?        → "Xin lỗi, tôi chưa hiểu yêu cầu của bạn"
  Tool unavailable?      → "Dịch vụ tạm thời không khả dụng"
  Invalid plan?          → "Tôi không thể thực hiện yêu cầu này"
  Token expired?         → "Phiên xác nhận đã hết hạn"
  
  → NEVER returns HTTP 500 — always a friendly message
```

---

## 5. Guardrail Pipeline (6 Security Layers)

The system uses **Defense-in-Depth**: 6 independent layers, each stopping a different attack vector. They run in sequence, and any layer can block the request.

```
Execution order in v3 graph:
  [L6] @with_fallback ← wraps EVERYTHING — never crash
    → [L1] rate_limiter.check_rate_limit()       ← stop spam
    → [L2a] check_input()                        ← regex patterns
    → [L2b] check_input_bedrock()                ← semantic (optional)
    → PLANNER node (LLM sinh plan)
    → TOOL_EXECUTOR_LOOP (iterate plan)
        → [L3] validate_tool_call()              ← every tool call
        → [L4] request_confirmation()            ← write actions only
        → Tool execution (gRPC → EKS)
    → [L5] filter_output()                       ← redact PII
```

Giữ nguyên toàn bộ logic guardrail từ v2. Chi tiết xem [`guardrail_design_doc.md`](guardrail_design_doc.md).

### Guardrail Mapping (v3)

| Guardrail | Node | Cơ chế |
|---|---|---|
| L1: Rate Limiter | `input_guard` | `rate_limiter.check_rate_limit()` |
| L2a: Regex Input | `input_guard` | `check_input()` |
| L2b: Bedrock Guardrail | `input_guard` | `check_input_bedrock()` (optional) |
| L3: Tool Validator | `tool_executor` | `validate_tool_call()` mỗi lần gọi tool |
| L4: Confirmation Gate | `tool_executor` (write tools) | `request_confirmation()` → PAUSE |
| L5: Output Filter | `answer_generator` | `filter_output()` |
| L6: Fallback | Wraps graph | `@with_fallback` decorator |

---

## 6. Tool System v2 — Fixed Output Schema

### Nguyên tắc mới

1. Mỗi tool có **fixed output schema** (JSON Schema) — không mô tả use case
2. **Price normalization**: tất cả tool gộp `price_units` + `price_nanos` → `price: string`
3. Output schema được dùng trong **Planner system prompt** để LLM biết trước dữ liệu
4. Tool được đăng ký vào **Tool Registry** — thêm tool mới không cần sửa prompt
5. Planner đọc schema động từ registry, không hardcode

### Tool Inventory

| Tool | File | Backend | Action |
|---|---|---|---|---|
| `search_products_v2` | `tools/search/__init__.py` | ProductCatalog | Read |
| `get_product_details_tool` | `tools/product_tool.py` | ProductCatalog | Read |
| `get_product_reviews_tool` | `tools/review_tool.py` | ProductReview | Read |
| `add_to_cart_tool` | `tools/cart_tool.py` | Cart | **Write** |
| `get_cart_tool` | `tools/cart_tool.py` | Cart | Read |
| `get_recommendations_tool` | `tools/recommendation_tool.py` | Recommendation | Read |
| `convert_currency_tool` | `tools/currency_tool.py` | Currency | Read |
| `get_shipping_quote_tool` | `tools/shipping_tool.py` | Shipping | Read |
| `checkout_tool` | `tools/checkout_tool.py` | Checkout + Payment | **Write** |
| `get_order_status_tool` | `tools/order_tool.py` | Accounting | Read |

### 6.1 Tool Registry

**File:** `tools/registry.py` (NEW)

Tool Registry là nguồn truth duy nhất cho tất cả tool metadata — schema đầu vào, schema đầu ra, mô tả, examples. Planner đọc từ registry để xây prompt động; Executor đọc để resolve tool function.

#### ToolSpec

```python
# tools/registry.py

from __future__ import annotations
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    """
    Specification cho một tool — chứa mọi thứ Planner + Executor cần biết.
    Không chứa implementation — chỉ chứa metadata.
    """
    name: str                                      # Tên tool (dùng trong plan)
    description: str                               # Mô tả ngắn cho planner LLM
    input_schema: dict[str, Any]                   # JSON Schema for input args
    output_schema: dict[str, Any]                  # JSON Schema for output
    is_write: bool = False                         # True nếu cần confirmation
    examples: list[dict] = field(default_factory=list)  # Few-shot examples
    retry_config: dict = field(default_factory=lambda: {"max_retries": 1})
```

Người implement tạo `ToolSpec` instances cho từng tool dựa trên bảng dưới đây, đăng ký qua `ToolRegistry.register()` khi module được import.

| Tool | File | Backend | Action | Input (required) | Output (key fields) | DB source | Ghi chú |
|---|---|---|---|---|---|---|---|
| `search_products_v2` | `tools/search/__init__.py` | ProductCatalog | Read | `query` (str) | `status`, `total`, `products[]` (id, name, price, description, image, categories) | `products` | price_units+nanos → price string; picture → image filename; categories comma-separated → array |
| `get_product_details_tool` | `tools/product_tool.py` | ProductCatalog | Read | `product_id` (str) | `status`, `product` (id, name, price, desc, image, categories, rating, review_count) | `products` + `productreviews` (rating/review_count aggregate) | |
| `get_product_reviews_tool` | `tools/review_tool.py` | ProductReview | Read | `product_id` (str), `limit` (int, opt), `sort` (enum, opt) | `status`, `average_score`, `total_reviews`, `distribution`, `reviews[]` (review_id, username, score, body) | `reviews.productreviews` | score NUMERIC(2,1); review_id INTEGER auto-increment; cần JOIN với `products` lấy product_name |
| `add_to_cart_tool` | `tools/cart_tool.py` | Cart | **Write** | `product_id` (str), `quantity` (int, opt) | `status` (pending/confirmed/denied/error), `token`, `message`, `item` | `cart` (user_id, product_id, quantity) | Cần JOIN với `products` để lấy name/price; name/price không có trong cart table |
| `get_cart_tool` | `tools/cart_tool.py` | Cart | Read | (none) | `status`, `items[]` (product_id, name, price, quantity, image), `subtotal`, `item_count` | `cart` + JOIN `products` | subtotal = SUM(price × quantity) |
| `get_recommendations_tool` | `tools/recommendation_tool.py` | Recommendation | Read | `product_id` (str, opt), `context` (str, opt), `limit` (int, opt) | `status`, `reason`, `products[]` (id, name, price, desc, image, rating) | Không có bảng riêng: (1) same-category, (2) full-text search, (3) popular | |
| `convert_currency_tool` | `tools/currency_tool.py` | Currency | Read | `amount` (num), `from` (str), `to` (str) | `status`, `from`, `to`, `original_amount`, `converted_amount`, `rate`, `formatted` | Không có DB — gọi external API hoặc hardcode mapping | |
| `get_shipping_quote_tool` | `tools/shipping_tool.py` | Shipping | Read | `zip_code` (str), `items_count` (int, opt), `cart_total` (str, opt) | `status`, `destination`, `options[]` (provider, cost, delivery_days, delivery_window, description) | Business rules (free >$100, flat rate) | cost dùng units/nanos pattern |
| `checkout_tool` | `tools/checkout_tool.py` | Checkout+Payment | **Write** | `shipping_address` (object), `shipping_provider` (str), `note` (str, opt) | `status` (pending/confirmed/denied/error), `token`, `order_id`, `total`, `summary` | `accounting.order`, `orderitem`, `shipping` | Cần INSERT vào 3 tables; total/summary computed |
| `get_order_status_tool` | `tools/order_tool.py` | Accounting | Read | `order_id` (str) | `status`, `order_id`, `total`, `tracking_number`, `shipping_address`, `items[]` | `accounting.order`, `orderitem`, `shipping` | Không có order_status, carrier, timeline trong DB |

Mỗi tool cần implement output normalization: gộp `price_units` + `price_nanos` → `price` string; gộp `shipping_cost_units` + `shipping_cost_nanos` → `cost` string.

#### Registry class

```python
# tools/registry.py (continued)

class ToolRegistry:
    """
    Central registry — singleton pattern.
    - Tool tự đăng ký khi module được import
    - Planner đọc động để build prompt
    - Executor đọc để lấy function + retry config
    """

    _specs: dict[str, ToolSpec] = {}
    _fns: dict[str, Any] = {}

    @classmethod
    def register(cls, spec: ToolSpec, fn: Any = None) -> None:
        """Đăng ký tool spec (và optional function)."""
        cls._specs[spec.name] = spec
        if fn is not None:
            cls._fns[spec.name] = fn

    @classmethod
    def get_spec(cls, name: str) -> Optional[ToolSpec]:
        return cls._specs.get(name)

    @classmethod
    def get_fn(cls, name: str) -> Optional[Any]:
        return cls._fns.get(name)

    @classmethod
    def get_all_specs(cls) -> dict[str, ToolSpec]:
        return dict(cls._specs)

    @classmethod
    def get_all_schemas_text(cls) -> str:
        """
        Sinh text mô tả schemas cho planner prompt.
        Đây là output duy nhất mà planner nhìn thấy — không cần
        hardcode schema trong prompt.
        """
        lines = []
        for name, spec in cls._specs.items():
            lines.append(f"### {name}")
            lines.append(spec.description)
            lines.append("Input:")
            lines.append(f"```json\n{json.dumps(spec.input_schema, indent=2, ensure_ascii=False)}\n```")
            lines.append("Output:")
            lines.append(f"```json\n{json.dumps(spec.output_schema, indent=2, ensure_ascii=False)}\n```")
            lines.append("")
        return "\n".join(lines)

    @classmethod
    def clear(cls) -> None:
        """Dùng trong test."""
        cls._specs.clear()
        cls._fns.clear()
```

#### Register tool tại startup

Mỗi tool file tự đăng ký với `ToolSpec` (global variable trong module đó) khi import: gọi `ToolRegistry.register(spec_instance, fn=tool_function)`. Không cần import `ToolSpec` class — instances đã có sẵn ở module-level.

#### Lợi ích

| Trước (TOOL_OUTPUT_SCHEMAS static) | Sau (ToolRegistry) |
|---|---|
| Schema hardcode trong dict | Mỗi tool tự đăng ký bằng `ToolSpec` |
| Thêm tool → sửa `tools/__init__.py` + prompt | Thêm tool → chỉ cần register — prompt tự cập nhật |
| Planner đọc từ global dict | Planner đọc `ToolRegistry.get_all_schemas_text()` |
| Không có input_schema → planner tự guess args | Input schema rõ ràng → planner biết chính xác args |
| Không có examples gắn với tool | Mỗi tool tự mang examples → few-shot chất lượng hơn |



### Price Normalization

Mọi tool output phải gộp `price_units` (BIGINT) + `price_nanos` (INT) thành `price` string. Quy tắc:
- `nanos // 10_000_000` → 2 decimal cents (vd: nanos=960_000_000 → 96 cents)
- USD: format `$units.cents` (vd: `$101.96`)
- Non-USD: format `units.cents currency` (vd: `101.96 EUR`)
- Shipping: dùng `shipping_cost_units` + `shipping_cost_nanos` + `shipping_cost_currency_code`
- Không expose `price_units`, `price_nanos` hay `price_usd.units` trong output
- `picture` → `image` (filename, consumer ghép CDN base URL)
- `categories` comma-separated TEXT → array

### Write Tool Confirmation

Các write tool (`add_to_cart_tool`, `checkout_tool`) có `is_write=True` — Executor Loop tự động:

1. Gọi tool → nhận `{"status": "pending", "token": "...", "message": "..."}`
2. PAUSE execution → chờ user confirm/reject
3. User confirm → gọi lại với token → `{"status": "confirmed", ...}`

Chi tiết ở [§9 Write + Confirm Flow](#9-write--confirm-flow).

---

## 7. 2-Layer Planner

**Files:** `graph/nodes/intent_parser.py` (NEW), `graph/nodes/task_graph_builder.py` (NEW)

Planner được tách thành **2 lớp** với ranh giới rõ ràng:

```
User query
  │
  ▼
┌─────────────────────────────────────┐
│  Layer 1: Intent Parser              │
│  - Rule-based cho case đơn giản      │
│  - LLM fallback cho case phức tạp    │
│  - Output: intent + entities          │
│  - Confidence score                   │
└─────────────┬───────────────────────┘
              │ parsed intent + entities
              ▼
┌─────────────────────────────────────┐
│  Layer 2: Task Graph Builder         │
│  - LLM chọn tool cần gọi              │
│  - Nối edge dependency giữa các node  │
│  - KHÔNG parse entity/argument         │
│  - Output: DAG (nodes + edges)        │
│  - Confidence score per node          │
└─────────────┬───────────────────────┘
              │ DAG plan
              ▼
        Tool Executor (resolve args tại runtime)
```

### Lý do tách

| Vấn đề cũ (Planner gộp) | Giải pháp (2 lớp) |
|---|---|
| LLM phải làm 3 việc cùng lúc: parse intent + entity + chọn tool + fill args → accuracy kém | Intent Parser (rule, nhanh) + TGB (LLM, chỉ chọn tool + nối edge) |
| Argument filling lẫn với planning → plan sai nếu extract sai entity | Argument filling chuyển xuống Executor resolve tại runtime |
| Hardcode entity trong plan → fragile | Entity resolve ở Executor với helper an toàn (`first()`, `safe_index()`, §8) |
| Không có confidence → chạy plan mù dù LLM không chắc chắn | Cả 2 lớp output confidence → < threshold → `ask_user` |

---

### 7.1 Layer 1: Intent Parser

**File:** `graph/nodes/intent_parser.py`

#### Thuật toán

1. Lấy user query từ `state.messages[-1]`
2. **Rule-based match** (zero-cost path): chạy regex patterns lên query
   - Pattern set: `cart_view`, `cart_add`, `search`, `review`, `recommend`, `currency`, `shipping`, `checkout`, `greeting`
   - Mỗi pattern match → gán score: `1.0` nếu match toàn bộ query, `0.8` nếu match substring
   - Nếu intent có score ≥ 0.8 → dùng ngay (fast path)
3. **Entity extraction rule-based**: số lượng (`quantity`), khoảng giá (`min_price`/`max_price`)
4. **LLM fallback** (khi rule không đủ tự tin): gọi LLM với prompt ngắn (<100 tokens), yêu cầu trả JSON `{intent, entities, confidence}`
5. **Output**: `{intent, entities, confidence, node_durations}`

#### Rule patterns tham khảo

| Intent | Pattern (rút gọn) |
|---|---|
| `cart_view` | `xem\|giỏ\|cart\|co.*giỏ` |
| `cart_add` | `thêm\|add\|cho.*vào\|bỏ.*vào` |
| `search` | `tìm\|search\|kiếm\|find` |
| `review` | `review\|đánh giá\|nhận xét\|sao` |
| `recommend` | `gợi ý\|recommend\|suggest\|tương tự` |
| `currency` | `VND\|JPY\|EUR\|đổi.*tiền\|convert` |
| `shipping` | `ship\|vận chuyển\|giao.*hàng\|phí.*ship` |
| `checkout` | `thanh toán\|checkout\|mua\|đặt.*hàng\|order` |
| `greeting` | `^(hi\|hello\|chào\|hey\|ok\|có.*giúp)` |

Entity extraction rules: `(\d+)\s*(cái|chiếc|tents?|items?)` → `quantity`; `dưới|under|< $(\d+)` → `max_price`; `trên|over|> $(\d+)` → `min_price`.

### 7.2 Layer 2: Task Graph Builder (TGB)

**File:** `graph/nodes/task_graph_builder.py`

Task Graph Builder **chỉ** làm 2 việc:
1. **Chọn tool** nào cần gọi dựa trên intent + entities (từ Intent Parser)
2. **Nối edge dependency** giữa các tool node

Argument filling và entity resolution **không** nằm ở đây — chuyển hết xuống Tool Executor (§8).

#### DAG Schema

```python
# graph/nodes/task_graph_builder.py

class DAGNode(TypedDict):
    id: str                              # Unique node ID (VD: "node_0", "node_1")
    tool: str                            # Tên tool (trong ToolRegistry)
    description: str                     # Tại sao gọi tool này
    depends_on: list[str]                # Node IDs phải chạy trước
    condition: Optional[dict]            # Conditional branching (xem §8.3)
    confidence: float                    # 0.0-1.0 (TGB tự đánh giá)

class DAGPlan:
    nodes: list[DAGNode]
    edges: list[tuple[str, str]]         # (from_node_id, to_node_id)
```

#### So sánh: Plan cũ (list) vs DAG mới

| Khía cạnh | List cũ | DAG mới |
|---|---|---|
| Cấu trúc | `[step1, step2, step3]` | `{nodes: [...], edges: [...]}` |
| Song song | Không — chạy tuần tự | Node không có dependency → chạy song song |
| Conditional | Không | `condition` field per node |
| Dependency | implicit (index-based) | Explicit `depends_on: ["node_0"]` |
| Partial replan | Impossible (phải restart) | Chỉ sửa node lỗi, giữ node khác |

#### Thuật toán

1. Đọc `state`: `intent`, `entities`, `planner_memory`
2. **Build prompt động**: đọc tất cả tool schemas từ `ToolRegistry.get_all_schemas_text()` + format `planner_memory` → ghép vào `TGB_PROMPT` template (§11)
3. **Gọi LLM** (`temperature=0.2`, `response_format=json_object`): LLM trả DAG plan gồm `{nodes, edges, reasoning, overall_confidence}`
4. **Validate DAG**:
   - Mỗi `node.tool` phải tồn tại trong `ToolRegistry`
   - Mỗi `depends_on` ID phải là node ID hợp lệ
   - Không self-reference
5. **Tính overall_confidence** = average confidence các node
6. **Output**: `{plan (DAG), plan_step_index=0, current_goal, planner_reasoning, plan_confidence, node_durations}`

#### Build prompt logic

```
TGB_PROMPT.format(
    tool_schemas_text=ToolRegistry.get_all_schemas_text(),
    user_query=query,
    intent=intent,
    entities=json.dumps(entities),
    planner_memory=format_memory(planner_memory),
)
```

`format_memory`: nếu có `last_search` / `current_cart_items` / `last_product_id` / `last_intent` → tạo text ngữ cảnh ngắn; nếu không → "(không có dữ liệu phiên trước)".

### Planner Memory (ngắn hạn)

Intent Parser và TGB đều có quyền truy cập `state.planner_memory` — ngữ cảnh ngắn hạn giữa các lượt chat:

```python
# graph/state.py — trong PlannerMemory
planner_memory: dict = {
    "last_search": str,          # Query search gần nhất
    "last_product_id": str,      # Product ID vừa xem
    "current_cart_items": int,   # Số items trong giỏ
    "last_intent": str,          # Intent của lượt trước
}
```

Điều này giúp TGB không cần lập kế hoạch từ đầu mỗi lượt — VD: user hỏi "review cái đó" sau khi search → TGB biết `product_id` từ memory thay vì phải search lại.

### Variable Reference Syntax (mở rộng)

Giữ nguyên `$steps[i].path` từ v3.1 nhưng bổ sung helper an toàn:

| Syntax | Ý nghĩa | Ví dụ resolve |
|---|---|---|
| `"$steps[node_id].path"` | Output của node (by ID), JSON path | `"$steps[node_0].products[0].id"` |
| `"$session.user_id"` | `user_id` từ session | `"$session.user_id"` |
| `"$session.session_id"` | `session_id` từ session | `"$session.session_id"` |
| `"$input.entities.field"` | Entity từ Intent Parser | `"$input.entities.quantity"` → `2` |
| `"$memory.field"` | Planner memory field | `"$memory.last_product_id"` |
| `"$first(steps[node_id].path, default=null)"` | An toàn: lấy đầu tiên hoặc default | `"$first(steps[node_0].products, default=null)"` |
| `"$exists(steps[node_id].path)"` | Boolean check: field có tồn tại không? | `"$exists(steps[node_0].products[0])"` |
| `"$safe_index(steps[node_id].path, index, default=null)"` | Index an toàn, không IndexError | `"$safe_index(steps[node_0].products, 0, default=null)"` |

Chi tiết resolve helpers ở [§8.2 Variable Reference Resolver](#82-variable-reference-resolver).

### DAG Behavior Examples

| User Query | DAG sinh ra |
|---|---|
| "Find telescopes under $200" | `{nodes: [{id:"n0", tool:"search_products_v2", depends_on:[], confidence:0.95}], edges: []}` |
| "Add 2 telescopes to my cart" | `{nodes: [{id:"n0", tool:"search_products_v2", depends_on:[], confidence:0.9}, {id:"n1", tool:"add_to_cart_tool", depends_on:["n0"], confidence:0.85}], edges: [("n0","n1")]}` |
| "Review tent and recommend similar" | `{nodes: [{id:"n0", tool:"search_products_v2", depends_on:[], confidence:0.95}, {id:"n1", tool:"get_product_reviews_tool", depends_on:["n0"], confidence:0.9}, {id:"n2", tool:"get_recommendations_tool", depends_on:["n0"], confidence:0.9}], edges: [("n0","n1"),("n0","n2")]}` — **n1 và n2 chạy song song** |
| "Review tent and convert price" | `{nodes: [{id:"n0", tool:"search_products_v2", depends_on:[], confidence:0.95}, {id:"n1", tool:"get_product_reviews_tool", depends_on:["n0"], confidence:0.9}, {id:"n2", tool:"convert_currency_tool", depends_on:["n0"], confidence:0.9}], edges: [("n0","n1"),("n0","n2")]}` — n1, n2 song song |
| "Place order" | `{nodes: [], edges: [], overall_confidence: 0.0}` — tool denied, trả lời thẳng |

---

## 8. Tool Executor (DAG Runner)

**File:** `graph/nodes/tool_executor.py` (NEW — replaces sequential loop)

### Vai trò

Centralized DAG runner. Nhận `DAGPlan` từ Task Graph Builder, chạy các node theo thứ tự topological:
- Node không có dependency → chạy song song (`asyncio.gather`)
- Node có dependency → chạy sau khi dependency hoàn thành
- Resolve variable references (với helper an toàn `$first()`, `$safe_index()`)
- L3 validation per call
- Cache check/set (read tools)
- Price normalization
- L4 confirmation (write tools → pause graph)
- Retry per-tool
- Conditional branching (dừng hoặc hỏi user dựa trên result)

### Flow

```
Tool Executor (DAG Runner):
  ng_done = set()       # Node IDs đã hoàn thành
  node_outputs = {}     # {node_id: normalized_output}
  
  While len(ng_done) < len(plan.nodes):
    ready = [n for n in plan.nodes 
             if n.id not in ng_done 
             and all(dep in ng_done for dep in n.depends_on)]
    
    # Chạy song song tất cả node ready (không dependency)
    results = await asyncio.gather(*[
      _execute_node(n, node_outputs, state) for n in ready
    ])
    
    for n, result in zip(ready, results):
      if result is None:  # Lỗi — ghi vào tool_results, không dừng
        continue
      
      # Conditional branching: check condition trước khi tiếp tục
      if n.condition:
        branch = _evaluate_condition(result, n.condition)
        if branch == "ask_user":
          → PAUSE, hỏi user (VD: "Tìm thấy 0 kết quả. Bạn muốn thử từ khóa khác?")
        elif branch == "stop":
          → Dừng DAG, trả kết quả hiện tại
        # else "continue": chạy node phụ thuộc bình thường
      
      ng_done.add(n.id)
      node_outputs[n.id] = result
  
  → All nodes done → move to REFLECTION
```

### 8.1 DAG Runner Implementation

**File:** `graph/nodes/tool_executor.py`

#### Thuật toán chính

```
DAG Runner:
  node_map = index nodes by ID
  in_degree = {node_id: set(depends_on)}
  done = {}       # node IDs đã hoàn thành
  node_outputs = {}  # {node_id: normalized_result}
  errors = {}
  
  while len(done) < len(nodes):
    ready_nodes = [n for n in nodes if n.id not in done and all deps in done]
    if no ready_nodes → deadlock, break
    
    # Chạy song song tất cả ready_nodes
    results = await asyncio.gather(*[execute_node(n) for n in ready_nodes])
    
    for each result:
      if exception/None → ghi errors, continue
      if node has condition → evaluate → ask_user/stop/continue
      done.add(n.id); node_outputs[n.id] = result
```

#### `execute_node` — từng bước cho 1 node

1. **Resolve variable references**: thay `$steps[node_id].path` / `$session.*` / `$input.entities.*` / `$memory.*` / `$first(...)` / `$exists(...)` / `$safe_index(...)` bằng giá trị thực từ `node_outputs` / `state`
2. **L3 Validate**: `validate_tool_call(tool_name, resolved_args, user_id)` — allow-list, bounds, user isolation
3. **Cache check**: nếu là read tool và cache hit → return cached (skip gRPC)
4. **Execute tool với retry**: gọi `ToolRegistry.get_fn(tool_name).ainvoke(args)`, retry theo per-tool config
5. **Normalize output**: gộp `price_units`+`price_nanos` → `price` string
6. **Cache set**: nếu read tool → lưu cache
7. **Return**: `(normalized_dict, source)` — source = `"grpc"` | `"cached"`

### 8.2 Variable Reference Resolver

Resolve các variable reference trong `node.args` trước khi gọi tool. Resolve đệ quy cho dict/list lồng nhau. Nếu bất kỳ reference nào resolve ra `None` → node fail (không execute).

| Syntax | Resolve logic |
|---|---|
| `$steps[node_id].path` | `node_outputs[node_id]` → JSON path traversal (hỗ trợ `array[index]`) |
| `$session.field` | `state.get(field)` |
| `$input.entities.field` | `state.entities.get(field)` |
| `$memory.field` | `state.planner_memory.get(field)` |
| `$first(steps[nid].path, default=val)` | Lấy `path[0]` nếu là list, nếu empty/null → return `default` |
| `$exists(steps[nid].path)` | Boolean: path có tồn tại trong `node_outputs[nid]` không? |
| `$safe_index(steps[nid].path, idx, default=val)` | `path[idx]` nếu index hợp lệ, nếu không → `default` |

Default value parsing: `null`/`None` → Python `None`; `true`/`false` → bool; số → int/float; giữ nguyên string.

### 8.3 Conditional Branching

Condition format trong DAG node:
```json
{"on": "total", "==0": "ask_user", ">1": "ask_choose", "default": "continue"}
```

Logic: lấy `result[on_path]` → so khớp lần lượt `==N`, `!=N`, `>N`, `<N`, `null`, `not_null` → action đầu tiên match. Fallback: `default`.

Actions: `ask_user` → pause graph, trả message cho user; `stop` → dừng DAG, giữ kết quả hiện tại; `continue` → chạy node phụ thuộc bình thường.

### 8.4 Tool Execution & Retry

Per-tool retry config (tham khảo):

| Tool | Max retries | Ghi chú |
|---|---|---|
| Read tools (search, product, review, recommend, currency, shipping, cart) | 2 | Exponential backoff 0.5s, 1s |
| Write tool (add_to_cart) | 1 | Không retry checkout — tránh charge thẻ 2 lần |

Output normalization: gọi `normalize_product()` trên từng item trong `products`/`items` array — gộp price units/nanos → price string.

---

## 8.5 Reflection Node

**File:** `graph/nodes/reflection.py` (NEW)

### Vai trò

Reflection chạy sau Tool Executor, kiểm tra kết quả thực thi và quyết định:
- **PASS**: kết quả đủ tốt → chuyển sang Response Verifier
- **REPLAN**: kết quả không đạt → gọi lại Task Graph Builder (**partial replan**, chỉ sửa node lỗi, không restart full DAG)

```
ToolExecutor → REFLECTION
                   │
              ┌────┴────┐
              │         │
           pass      replan
              │         │
              ▼         ▼
      ResponseVerifier  TaskGraphBuilder (partial)
                              │
                              ▼
                         ToolExecutor (chỉ chạy node mới)
```

### Khi nào trigger replan?

| Trigger | Điều kiện | Hành động |
|---|---|---|
| **0 kết quả** | Node search/review/recommend trả `total=0` hoặc empty list | Replan: thử query khác, bỏ filter, hoặc thông báo user |
| **Tool lỗi liên tục** | ≥2 tool errors trong cùng 1 DAG run | Replan: chọn tool fallback hoặc đơn giản hoá plan |
| **Confidence thấp** | `plan_confidence < 0.5` sau execution | Replan: xác nhận lại intent với user |
| **Missing dependency** | Node A cần output node B nhưng B lỗi | Replan: bỏ node phụ thuộc, chạy alternative path |
| **Semantic gate fail** | `semantic_hallucination_detected = True` | Replan: yêu cầu TGB sinh plan mới với tool khác |

Tất cả trigger đều có threshold riêng và được kiểm soát bởi `replan_gate` (Nova Lite, §10.6) — không replan mù.

### Partial Replan (không restart full DAG)

Khác với v3.1 (failure = trả lỗi cho user), Reflection + TGB hỗ trợ **partial replan**:

```
Ví dụ: DAG 3 node [search → review, recommend]
  - search: OK
  - review: OK  
  - recommend: ERROR (gRPC timeout)

Partial replan:
  1. TGB nhận: nodes đã OK = [search, review], node lỗi = [recommend]
  2. TGB chỉ sinh node mới thay thế recommend node
  3. Executor chỉ chạy node mới, không chạy lại search/review
```

### Thuật toán

1. Đọc `tool_results`, `errors`, `plan_confidence`, `replan_count` từ state
2. Kiểm tra lần lượt 4 trigger:
   - **Zero result**: tool nào trả `total=0` hoặc empty products/items list?
   - **Tool errors**: số lượng `errors` ≥ 2?
   - **Low confidence**: `plan_confidence < 0.5`?
   - **Semantic hallucination**: `semantic_hallucination_detected == True`?
3. Nếu **không có issue nào** → `reflection_result = "pass"`
4. Nếu **có issue**:
   - Nếu `replan_count >= 2` → force pass (giới hạn replan)
   - Nếu chưa đạt giới hạn → `reflection_result = "replan"`, `replan_count += 1`
5. Output: `{reflection_result, replan_count, reflection_issues, node_durations}`

### Graph edges với Reflection

```
ToolExecutor → REFLECTION
                  │
             pass │   replan
                  ▼         ▼
         ResponseVerifier  TaskGraphBuilder (partial → chỉ sửa node lỗi)
                                  │
                                  ▼
                             ToolExecutor (chỉ chạy node mới)

Route function: trả về state.reflection_result ("pass" | "replan")
```

### Cost

| Item | Cost | Latency |
|---|---|---|
| Reflection check | **$0** (rule-based, không LLM) | <2ms |
| Partial replan (TGB) | 1 LLM call + 1 Gate call (replan_gate) | ~400-800ms |
| Compare: full restart | 1 LLM call + chạy lại tất cả tool | Phí gấp 2-5x |

---

## 9. Write + Confirm Flow

### Kiến trúc

Write tools (hiện tại chỉ `add_to_cart_tool`) có output schema chứa `status: "pending"`. Tool Executor phát hiện → **pause graph execution** → lưu checkpoint → trả token về client.

```
TaskGraphBuilder → DAG: [search, add_to_cart]
  ↓
ToolExecutor Loop:
  step 0: search_products_v2 → OK → continue
  step 1: add_to_cart_tool → request_confirmation()
    → {"status": "pending", "token": "eyJ...", "message": "Xác nhận thêm 2x telescope?"}
    → PAUSE graph
    → Lưu plan_step_index=2 vào checkpoint
    → Return token to API
  ↓
User clicks Confirm → POST /api/confirm {session_id, token}
  ↓
main.py:
  1. verify_confirmation_token(token) → is_valid?
  2. graph.ainvoke(Command(resume={"confirmed": True}))
  ↓
ToolExecutor Loop RESUMES:
  step 2 (resumed): Execute gRPC AddItem thật
    → approve → response_verifier → answer_generator → END
```

### Confirmation Token

Giữ nguyên HMAC token từ v2:

```python
# guardrails/confirmation.py
Token = Base64URL(payload_json) + "." + HMAC-SHA256(payload, SECRET_KEY)
Payload: {user_id, action, params, exp (Unix + 300s)}
```

### State Resumption

Khi user confirm (`POST /api/confirm` → `verify_confirmation_token` → `Command(resume={"confirmed": True})`), graph resume từ checkpoint. Logic resume trong ToolExecutor:

1. Kiểm tra `state.confirmed == True` và `state.pending_action` tồn tại
2. Đọc action params từ `pending_action` (user_id, product_id, quantity)
3. Gọi gRPC `AddItem` thật đến CartService
4. Xoá `pending_action`, ghi kết quả vào `tool_results`
5. Tiếp tục flow: response_verifier → answer_generator

---

## 10. Response Verifier (Template-First)

**File:** `graph/nodes/response_verifier.py` (NEW — replaces `response_editor`)

### Vai trò

Response Verifier áp dụng **Template-First** strategy: các deterministic path (cart, shipping, currency, review) dùng **template trực tiếp từ tool output**, không gọi LLM. LLM chỉ được gọi khi cần summarize/compare/explain — nơi thực sự cần ngôn ngữ tự nhiên linh hoạt.

### Template-First Decision Tree

```
tool_results
  │
  ├── Cart (get_cart_tool) ──────────────► Template items + subtotal
  ├── Shipping (get_shipping_quote_tool) ─► Template cost + delivery_days
  ├── Currency (convert_currency_tool) ────► Template formatted + rate
  ├── Reviews (get_product_reviews_tool) ─► Template avg_score + top review
  ├── Confirm (add_to_cart pending) ───────► Template confirm message
  │
  ├── Search (search_products_v2) ────────►
  │     ┌── single + ≤3 items ───► Template
  │     └── multi / >3 items ─────► LLM summarize
  │
  ├── Recommend + Review combined ────────► LLM (cần compare/explain)
  │
  └── Multi-tool complex ────────────────► complexity > 0.5 → LLM
                                            complexity ≤ 0.5 → template ghép
```

Lợi ích:
- **Giảm token**: ~60% request không cần LLM cho response
- **Giảm hallucination**: template output luôn grounded 100%
- **Giảm latency**: template <1ms vs LLM 200-800ms

### Template Set

```python
# graph/nodes/response_verifier.py — templates

TEMPLATES = {
    "cart": [
        "Giỏ hàng của bạn có {count} món: {items}. Tổng cộng {total}.",
        "Bạn đang có {count} sản phẩm trong giỏ: {items}. Tạm tính {total}.",
    ],
    "cart_empty": [
        "Giỏ hàng của bạn hiện đang trống.",
        "Bạn chưa có sản phẩm nào trong giỏ hàng.",
    ],
    "shipping": [
        "Phí vận chuyển tới {destination} là {cost}, giao trong {days} ngày qua {provider}.",
        "Dự kiến phí ship {cost} tới {destination}, thời gian giao {days} ngày ({provider}).",
    ],
    "currency": [
        "{amount} {from} tương đương khoảng {converted} {to} (tỷ giá {rate}).",
        "{amount} {from} hiện tại đổi được {converted} {to}.",
    ],
    "reviews": [
        "Sản phẩm được đánh giá {avg}/5 sao với {total} lượt nhận xét. {top_review}",
        "Sản phẩm đạt {avg}/5 sao từ {total} đánh giá. {top_review}",
    ],
    "reviews_none": [
        "Sản phẩm này chưa có đánh giá nào.",
        "Hiện tại chưa có ai đánh giá sản phẩm này.",
    ],
    "confirm": [
        "Vui lòng xác nhận: thêm {quantity} {product_name} vào giỏ hàng.",
        "Bạn có muốn thêm {quantity} {product_name} vào giỏ không?",
    ],
    "search_single": [
        "Tôi tìm thấy {count} sản phẩm: {product_list}.",
        "Đây là {count} sản phẩm tôi tìm được: {product_list}.",
    ],
    "search_none": [
        "Tôi không tìm thấy sản phẩm nào phù hợp.",
        "Rất tiếc, không có sản phẩm nào khớp với yêu cầu.",
    ],
}
```

### Selection Logic (Strategy Decision Tree)

1. **Xác định tool types** từ `tool_results` keys
2. **Deterministic paths** (luôn template, không LLM):
   - Chỉ `get_cart_tool` → template `cart` (hoặc `cart_empty`)
   - Chỉ `get_shipping_quote_tool` → template `shipping`
   - Chỉ `convert_currency_tool` → template `currency`
   - Chỉ `get_product_reviews_tool` → template `reviews`
3. **Search path**: nếu chỉ `search_products_v2`:
   - `total ≤ 3` (và > 0) → template `search_single`
   - Còn lại → LLM summarize
4. **Multi-tool path**: tính `complexity_score` → nếu > 0.5 → LLM, còn lại template ghép

### Complexity Scoring

4 factors, mỗi factor cộng dồn, clamp tối đa 1.0:

| Factor | Điều kiện | Điểm |
|---|---|---|
| Query length | > 20 từ / > 10 từ | +0.2 / +0.1 |
| Số tool được gọi | mỗi tool +0.1, tối đa +0.3 | up to 0.3 |
| Result size | > 10 items / > 5 items | +0.2 / +0.1 |
| Write action | có pending action | +0.1 |

**Temperature selection**: `complexity < 0.2` → 0.1; `< 0.5` → 0.3; `< 0.8` → 0.4; còn lại → 0.6.

### Implementation — Thuật toán

1. Lấy `user_query` từ messages, `tool_results` và `entities` từ state
2. Gọi `select_response_strategy(tool_results, user_query)`:
   - Template path: render template với dữ liệu từ tool_results, chọn random variant từ TEMPLATES set
   - LLM path: build `VERIFIER_PROMPT` với `tool_results_text` format, gọi LLM với temperature động
3. Ghi `final_answer` vào state
4. Output: `{final_answer, node_durations}`

### Skip Conditions

| Condition | Hành động |
|---|---|
| Không có tool_results | Dùng `final_answer` từ guardrail violation |
| Có lỗi guardrail | Giữ nguyên message guardrail |
| LLM unavailable | Dùng raw tool results text |
| Write tool pending | Giữ nguyên message "Vui lòng xác nhận..." |

---

## 10.5 HallucinationGuard & FallbackGenerator

**Files:** `graph/nodes/hallucination_guard.py` (NEW), `graph/nodes/fallback_generator.py` (NEW)

### Vai trò

ResponseVerifier dùng LLM để sinh câu trả lời — LLM có thể hallucinate (thêm thông tin không có trong tool results, sai giá, sai tên sản phẩm).

HallucinationGuard là lớp rule-based check, **zero LLM cost**, phát hiện hallucination bằng cách đối chiếu từng claim trong answer với tool results.

### Vị trí trong graph

```
ToolExecutorLoop → ResponseVerifier → HALLUCINATION_GUARD
                                           ↓ pass (groundedness ≥ 80%)
                                      AnswerGenerator → END
                                           ↓ fail (groundedness < 80%)
                                      FALLBACK_GENERATOR → AnswerGenerator → END
```

### Các kiểu claim check

| Check | Pattern / Cơ chế | Nguồn (tool_results) | Hard Rule | Trọng số |
|---|---|---|---|---|
| **Price** | `\$\d+(?:\.\d{2})?` hoặc `\d+\s*USD` | `products[].price`, `items[].price`, `total` | Mọi price trong answer phải exact match | 0.15 |
| **Entity** | Noun phrase extract: danh từ riêng viết hoa, tên sản phẩm/category | `products[].name`, `categories`, `items[].name` | Mọi entity không có trong known set → violation. Nếu total=0, mọi mention đều violation | **0.40** |
| **Count** | `"(\d+)\s*(sản phẩm\|kết quả\|đánh giá\|món)"` | `total`, `len(reviews)`, `len(products)` | Exact number match | 0.15 |
| **Score** | `"(\d+\.?\d*)\s*[/\\]\s*5"` hoặc `"(\d+\.?\d*)\s*sao"` | `average_score` | Match với ±0.1 tolerance | 0.15 |
| **Action confirm** | `"đã thêm"`, `"đã xoá"`, `"đã cập nhật"` | `pending_action` status, `confirmed` field | Chỉ cho phép nếu action đã confirm | 0.15 |
| **Semantic (attribute claim)** | Regex claim patterns: `"(có|được|sử dụng|phù hợp|dành cho|chất liệu|tính năng|nặng|nhẹ|màu|công dụng)"` — mọi claim về thuộc tính/công dụng sản phẩm | `products[].description`, `products[].name` | Claim attribute phải xuất hiện trong description hoặc name của tool output; nếu không → violation | **0.25** |

**Entity check** có trọng số cao nhất (0.40) vì:
- Nói về sản phẩm không tồn tại = hallucination nghiêm trọng nhất
- 1 entity violation duy nhất đủ kéo groundedness từ 1.0 → 0.6 → fallback ngay
- Zero-result path: nếu search trả về `total=0`, mọi product mention trong answer đều là automatic violation

**Semantic check** (mới, 0.25) bắt hallucination tinh vi hơn — LLM có thể nói đúng product name nhưng thêm thuộc tính không có trong description. VD: tool output ghi "phù hợp cho người mới bắt đầu", answer nói "tốt nhất cho chuyên gia" → semantic violation ngay cả khi entity và price đều đúng.<｜｜DSML｜｜parameter name="replaceAll" string="false">false

### Groundedness Score — Thuật toán

1. **Input**: `answer` (string từ ResponseVerifier), `tool_results`, `pending_action`
2. **Kiểm tra lần lượt các claim type** — mỗi violation trừ penalty khỏi groundedness score (bắt đầu từ 1.0, clamp [0, 1]):

| Check | Phương pháp | Penalty |
|---|---|---|
| **Price** | Regex `\$\d+(?:\.\d{2})?` → từng price phải exact match với tool_results | -0.15 |
| **Entity** | Noun phrase extraction: token viết hoa + bigram trong known set → mọi entity phải nằm trong known_products/known_categories; nếu total=0 → mọi mention đều violation (-0.50) | -0.40 |
| **Count** | Regex `(\d+)\s*(sản phẩm\|kết quả\|đánh giá\|món)` → exact number match với tool data | -0.15 |
| **Score** | Regex `(\d+\.?\d*)\s*/?\s*5` → match ±0.1 tolerance | -0.15 |
| **Action confirm** | Regex `(đã thêm\|đã xoá\|đã cập nhật)` → chỉ cho phép nếu action đã confirm | -0.15 |
| **Semantic attribute** | Regex patterns cho claim thuộc tính (phù hợp, chất liệu, tính năng, màu sắc, công dụng...) → claim phải xuất hiện trong product description/name | -0.25 |

3. **Entity extraction strategies**:
   - Token viết hoa (VD: "Telescope") → check trong known set
   - Bigram xuất hiện trong known set (VD: "Camping Stove")
   - Category từ known set → check trong answer
4. **Quyết định**:
   - `groundedness_score >= 0.8` → PASS (giữ nguyên answer)
   - `groundedness_score < 0.8` → FAIL → set `hallucination_detected=True`, `final_answer=None` → signal FallbackGenerator

### FallbackGenerator — Thuật toán

Khi groundedness < 80%, FallbackGenerator dùng **template** thay vì LLM để tạo câu trả lời — đảm bảo 100% grounded.

1. Xác định tool types từ `tool_results` keys
2. Nếu `pending_action.status == "pending"` → template confirm
3. Nếu single tool → chọn template tương ứng tool type
4. Nếu multi tool → ghép các template single tool

Mỗi tool type có 3-4 biến thể template, **random chọn** để tránh robotic:

| Tool type | Template variant (rút gọn) |
|---|---|
| `search_products_v2` (0 results) | "Tôi không tìm thấy sản phẩm nào..." / "Rất tiếc..." |
| `search_products_v2` (≤5 items) | "Tôi tìm thấy {n} sản phẩm: {list}." |
| `search_products_v2` (>5 items) | "Tôi tìm thấy {n} sản phẩm, trong đó có {list}. Bạn muốn xem thêm?" |
| `get_cart_tool` (empty) | "Giỏ hàng của bạn hiện đang trống." |
| `get_cart_tool` (has items) | "Giỏ hàng có {count} món: {items}. Tổng cộng {total}." |
| `get_product_reviews_tool` (none) | "Sản phẩm này chưa có đánh giá nào." |
| `get_product_reviews_tool` | "Sản phẩm được đánh giá {avg}/5 sao. {top_review}" |
| `get_recommendations_tool` | "Gợi ý dành cho bạn: {products}." |
| `convert_currency_tool` | "{amount} {from} tương đương {converted} {to} (tỷ giá {rate})." |
| `get_shipping_quote_tool` | "Phí vận chuyển ước tính {cost}, giao trong {days} ngày." |
| Confirm (write pending) | "Vui lòng xác nhận: thêm {quantity} {product_name} vào giỏ hàng." |

Nguyên tắc: không technical terms (JSON, error raw, tool name), tiếng Việt tự nhiên, mọi số liệu từ `tool_results`.

### Graph Edge Update

```
response_verifier → HALLUCINATION_GUARD
                       ↓ pass (groundedness ≥ 0.8)
                  AnswerGenerator → END
                       ↓ fail (groundedness < 0.8)
                  FALLBACK_GENERATOR → AnswerGenerator → END

Route after grounding: state.hallucination_detected → "fail", else "pass"
```

### Cost

| Item | Cost | Latency |
|---|---|---|
| HallucinationGuard | **$0** (rule-based regex) | <3ms |
| FallbackGenerator | **$0** (template render) | <1ms |

### Skip Conditions

| Condition | Hành động |
|---|---|
| Không có tool_results | Auto PASS (score=1.0, không claims để check) |
| Answer trống | Auto PASS (giữ nguyên) |
| Fallback cũng fail | Không thể — template là static, đã grounded |
| Confirmation pending | Fallback dùng template confirm, không check |
| Guardrail violation trước đó | Giữ nguyên message guardrail |
| known set rỗng + total>0 | Entity check không có đối chiếu → no entity violations |
| known set rỗng + total=0 | Mọi noun phrase trong answer → entity_zero_result violation |

---

## 10.6 Semantic Decision Gate Layer (Nova Lite)

**Files:** `graph/gates/gate_node.py` (NEW — shared), `graph/gates/*.py` (per-gate config)

### Vai trò

Các layer rule-based (L1-L6, HallucinationGuard §10.5) xử lý tốt **surface fact** (giá, số lượng, entity có/không tồn tại) nhưng không xử lý được **semantic fact** — những câu hỏi cần suy luận ngôn ngữ mà regex/rule không bao quát nổi (VD: "claim này có thực sự được tool output support về mặt ý nghĩa, không chỉ trùng từ khoá?"). Đây là chỗ bổ sung một **Gate Node** dùng LLM, nhưng ép output chỉ `Yes`/`No` (kèm optional `reason` ngắn ở gate rủi ro cao) để giữ cost gần với rule-based.

**Model dùng cho toàn bộ Gate Layer: Amazon Nova Lite** (qua Amazon Bedrock).

Lý do chọn Nova Lite thay vì Nova Micro hoặc Nova Pro:

| Model | Input / 1M tokens | Output / 1M tokens | Nhận xét |
|---|---|---|---|
| Nova Micro | $0.035 | $0.14 | Rẻ nhất, nhưng yếu hơn ở suy luận ngữ nghĩa nhiều bước (VD: đối chiếu claim ngầm định với tool output) |
| **Nova Lite** | **$0.06** | **$0.24** | Đủ khả năng ngôn ngữ cho binary semantic judgment, chi phí chênh lệch với Micro không đáng kể ở scale Yes/No (vài phần triệu USD/call) |
| Nova Pro | $0.80 | $3.20 | Quá đắt cho một quyết định nhị phân — dành cho Planner/Verifier nếu cần, không dành cho Gate |

Nova Lite là điểm cân bằng: đắt hơn Micro ~1.7x nhưng vẫn rẻ hơn Groq/Bedrock Claude 10-100 lần, trong khi độ tin cậy phân loại nhị phân tốt hơn rõ rệt so với Micro theo benchmark public của Bedrock.

### Gate Node — Interface

**File:** `graph/gates/gate_node.py`

Tất cả gate dùng chung một interface với Amazon Nova Lite (`amazon.nova-lite-v1:0`):

```
GateResult = {
    decision: bool,       # True = Yes, False = No
    reason: Optional[str] # chỉ set cho gate rủi ro cao
    latency_ms: float,
    tokens: {input: int, output: int}
}

GateNode(question: str, context: str, want_reason: bool = False) → GateResult
```

Nguyên tắc gọi:
- `system` prompt: "Bạn là bộ phân loại nhị phân. Chỉ trả lời đúng 1 từ: YES hoặc NO." (+ reason line nếu `want_reason`)
- `temperature = 0.0` (deterministic — classification, không generation)
- `max_tokens = 3` (hoặc 25 nếu có reason)
- Parse: `text.upper().startswith("YES")` → decision; dòng sau "\n" → reason

### Các Gate được thêm vào graph

| Gate | Vị trí | Câu hỏi (rút gọn) | `reason`? | Trigger |
|---|---|---|---|---|
| `routing_gate` | Trước Planner | "Câu hỏi này có match rule pattern đơn giản (fast path) không?" | Không | Chỉ chạy khi L2a regex không match rõ ràng — case rõ thì đi thẳng rule, không tốn Gate call |
| `plan_validity_gate` | Sau Planner, trước Tool Executor | "Plan này có đủ step để trả lời intent gốc, không thiếu dependency?" | Có | Luôn chạy nếu `len(plan) > 1` (plan đơn bước bỏ qua) |
| `semantic_hallucination_gate` | Sau HallucinationGuard §10.5, chỉ khi **pass** rule-based | "Claim '<X>' có thực sự được suy ra từ tool output này, hay là LLM tự suy diễn?" | Có | Chỉ chạy trên **claim còn lại sau rule-based** (không phải toàn bộ answer) — xem §10.6.1 |
| `confirm_parse_gate` | `confirmation.py`, khi resume | "Phản hồi của user có phải là đồng ý xác nhận hành động không?" | Không | Thay cho parse cứng "ừ/ok/được" — bắt được biến thể ngôn ngữ tự nhiên |
| `replan_gate` | Reflection (sau Tool Executor, khi có lỗi/0 kết quả) | "Kết quả hiện tại có đạt được goal ban đầu không, hay cần replan?" | Có | Chỉ chạy khi tool trả `total=0` hoặc lỗi liên tục ≥2 lần |

Nguyên tắc chung: **Gate chỉ chạy khi rule-based không đủ tự tin xử lý** — không thay thế L1-L6 hay HallucinationGuard, mà là lớp bổ sung phía sau, giữ nguyên "zero-cost path" cho phần lớn request (Design Principle #3).

### 10.6.1 Semantic gate không thay HallucinationGuard — chạy tiếp nối

Rule-based (§10.5) chạy trước, **miễn phí**, loại được phần lớn hallucination surface-level (giá sai, entity không tồn tại). Semantic gate chỉ chạy trên phần **claim đã pass rule-based** để bắt loại hallucination tinh vi hơn — claim đúng từ khoá nhưng sai ý nghĩa (VD: tool ghi "phù hợp người mới bắt đầu", answer diễn giải thành "tốt nhất cho chuyên gia thiên văn"). Vì vậy số lượng claim đưa vào semantic gate luôn nhỏ hơn hoặc bằng số claim ban đầu, giữ cost thấp.

### Cost per Gate call (Nova Lite, tính theo pricing thực tế ở trên)

| Gate | Input tokens (ước tính) | Output tokens | Cost/call |
|---|---|---|---|
| `routing_gate` | ~150 (query + instruction ngắn) | 1 | ~$0.000009 |
| `plan_validity_gate` | ~400 (plan JSON + tool schema tóm tắt) | ~20 (có reason) | ~$0.000029 |
| `semantic_hallucination_gate` | ~250/claim (claim + tool snippet) | ~18 (có reason) | ~$0.000019/claim |
| `confirm_parse_gate` | ~100 (user reply + instruction) | 1 | ~$0.000006 |
| `replan_gate` | ~350 (goal + tool_results tóm tắt) | ~18 (có reason) | ~$0.000025 |

**Worst case per request** (routing + plan_validity + 2 semantic claims + replan, tất cả cùng trigger — hiếm gặp): `0.000009 + 0.000029 + 2×0.000019 + 0.000025 ≈ $0.0001` — vẫn nhỏ hơn 1 lần gọi ResponseVerifier sinh câu trả lời tự do (~$0.0002-0.0006 tuỳ độ dài, xem §18).

**Typical case** (chỉ `semantic_hallucination_gate` chạy trên 1-2 claim, các gate khác skip vì rule đã đủ tự tin): **~$0.00002-0.00004/request** — tăng chưa tới 0.05₫ mỗi request so với v3 hiện tại.

### Trade-off

| Điểm | Được | Mất |
|---|---|---|
| **Coverage** | Bắt được hallucination ngữ nghĩa mà regex không thấy (claim đúng từ khoá, sai ý) | Nova Lite vẫn có thể đoán sai ở case mơ hồ ranh giới (không phải oracle) — cần theo dõi false positive/negative qua log `reason` |
| **Cost** | Rẻ hơn 5-20x so với gọi lại full LLM answer để re-verify | Vẫn là chi phí cộng thêm so với rule-based thuần ($0 trước đây) |
| **Latency** | 1 Gate call Nova Lite thường 150-400ms — nhanh hơn nhiều so với 1 lần sinh answer đầy đủ | Nếu 3-4 gate trigger cùng lúc và chạy tuần tự, cộng dồn latency đáng kể → nên chạy song song (`asyncio.gather`) các gate độc lập (VD: `plan_validity_gate` và `routing_gate` không phụ thuộc nhau) |
| **Độ tin cậy quyết định** | `temperature=0.0` + prompt ép format → decision ổn định, dễ test | Không nên dùng Gate cho quyết định có hậu quả không thể hoàn tác (VD: checkout thật) mà không có rule-based hoặc human confirm đi kèm — Gate là lớp *hỗ trợ*, không thay L3/L4 |
| **Vận hành** | Threshold đơn giản (Yes/No), dễ A/B test và log | Thêm 1 external dependency (Bedrock call) vào critical path — cần timeout + fallback về rule-based mặc định nếu Nova Lite lỗi/timeout (không block toàn bộ request) |

### Fallback khi Gate lỗi/timeout

Mỗi gate có `DEFAULT_DECISION` riêng, thiên về hướng an toàn (VD: `semantic_hallucination_gate` timeout → `decision=False` = fallback template). Cấu trúc: `try: await gate_node(...)` / `except (TimeoutError, BedrockError):` dùng `GateResult(decision=DEFAULT_DECISION[gate_name], reason="gate_unavailable")`.

---

## 11. System Prompt Design

### 11.1 Task Graph Builder Prompt

**File:** `llm/prompt.py` — Prompt text (không code):

```
Bạn là Task Graph Builder của Shopping Copilot — trợ lý mua sắm AI của TechX Corp.
Nhiệm vụ của bạn là chọn tool cần gọi và nối edge dependency giữa chúng.

## Tool Output Schemas
{tool_schemas_text}

## DAG Format
Trả về JSON: {"reasoning": "...", "overall_confidence": 0.95,
  "nodes": [{"id": "n0", "tool": "tool_name", "description": "...",
             "depends_on": [], "condition": null, "confidence": 0.95}],
  "edges": [["n0", "n1"]]}

## Quy tắc
1. KHÔNG fill argument/entity — chỉ chọn tool và nối edge.
2. Node không dependency → depends_on: [] → Executor chạy song song.
3. Node B cần output node A → depends_on: ["A_id"].
4. add_to_cart_tool là write tool → cần user confirm sau.
5. Không chọn tool cho: place order, charge, empty cart.
6. Đánh giá confidence 0.0-1.0 cho mỗi node.

## Planner Memory
{planner_memory}

## Few-shot examples
[4 examples: search single-tool, add-to-cart 2-tool, review+recommend parallel, conditional search]

User query: {user_query}
Intent: {intent}
Entities: {entities}
DAG:
```

### 11.2 Response Verifier Prompt

**File:** `llm/prompt.py` — Prompt text:

```
Bạn là trợ lý bán hàng của TechX Corp, đang trò chuyện trực tiếp với khách hàng.
Nhiệm vụ của bạn là trả lời dựa trên dữ liệu thật từ hệ thống.

## Dữ liệu
Tool results: {tool_results_text}

## Quy tắc
1. CHỈ dùng thông tin trong tool results — KHÔNG thêm chi tiết không có.
2. Giữ nguyên giá cả ($99.99), tên sản phẩm, số lượng.
3. KHÔNG markdown, emoji, technical terms.
4. Xưng hô "tôi" — "bạn", lịch sự, gần gũi.
5. Trả lời bằng tiếng Việt.

Khách hàng hỏi: {user_query}
Trả lời:
```

### 11.3 System Prompt Injection (Dynamic Tool Schemas)

Cả TGB prompt và Verifier prompt đều được build động với tool schemas từ `ToolRegistry`:

- **TGB prompt**: `TGB_PROMPT.format(tool_schemas_text=registry.get_all_schemas_text(), user_query, intent, entities=json.dumps(entities), planner_memory=format_memory(...))`
- **Verifier prompt**: `VERIFIER_PROMPT.format(tool_results_text=tool_results_text, user_query=user_query)`

Thêm tool mới → chỉ cần `ToolRegistry.register(spec)` → prompt tự cập nhật ở lần gọi tiếp theo.

---

## 12. State Design

```python
# graph/state.py — v3.2

class ShoppingState(TypedDict, total=False):
    # ── Core message history ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 2-Layer Planner (§7) ──
    plan: dict                         # DAGPlan {nodes: [...], edges: [...]}
    plan_step_index: int               # Resume position (0-based)
    current_goal: str                  # Intent hiện tại (vd: "search", "cart_add")
    planner_reasoning: str             # TGB reasoning text (cho logging/debug)
    plan_confidence: float             # 0.0-1.0 — overall confidence của DAG

    # ── Entities (extracted by IntentParser + TGB) ──
    intent: str                        # search | review | cart | shipping | agent | unknown
    entities: dict                     # {"product_name": "...", "quantity": 2, ...}
    resolved_entities: dict            # Entities đã resolve (product_id thực tế)

    # ── Tool results ──
    tool_results: Annotated[dict, merge_tool_results]  # {node_id: normalized_result}
    tool_history: Annotated[list, accumulate_tool_history]  # List of past tool_results per session

    # ── Dependency graph ──
    dependency_graph: dict             # {node_id: [dep_node_ids]} — runtime dep tracking

    # ── Response Verifier ──
    complexity_score: float            # 0.0-1.0 (set bởi verifier)
    final_answer: str                  # Câu trả lời cuối cùng

    # ── Hallucination Guard ──
    groundedness_score: float          # 0.0-1.0 (set bởi HallucinationGuard)
    hallucination_detected: bool       # True nếu groundedness < threshold → fallback
    fallback_used: bool                # True nếu FallbackGenerator đã chạy

    # ── Semantic Decision Gates (§10.6, Nova Lite) ──
    gate_decisions: dict                # {gate_name: {"decision": bool, "reason": str|None}}
    semantic_hallucination_detected: bool  # True nếu semantic_hallucination_gate trả No cho ≥1 claim
    replan_count: int                  # Số lần replan_gate đã trigger replan

    # ── Reflection (§8.5) ──
    reflection_result: str             # "pass" | "replan"
    reflection_issues: list            # [{"type": "zero_result", "node": "n0", ...}]

    # ─️─ Confidence ──
    confidence: float                  # 0.0-1.0 — overall confidence của cả lượt
    retry_count: int                   # Số lần retry (accumulated)

    # ── Planner Memory (ngắn hạn, §7) ──
    planner_memory: dict               # {"last_search": "...", "last_product_id": "...", "current_cart_items": 0, "last_intent": "..."}

    # ── Session ──
    session_id: str
    user_id: str
    trace_id: str

    # ── Confirmation ──
    pending_action: Optional[dict]     # {"token": "...", "action": "AddItem", ...}
    confirmed: bool                    # User confirmed (resume signal)

    # ── Guardrail ──
    guardrail_violations: list         # [{"guardrail": "...", "type": "...", ...}]

    # ── Error ──
    errors: Annotated[dict, accumulate_errors]   # {node_id: error_message}

    # ── Telemetry ──
    node_durations: Annotated[dict, merge_node_durations]
```

### So sánh v2 vs v3.2 State

| Field | v2 | v3.2 | Ghi chú |
|---|---|---|---|
| `plan` | — | ✅ DAGPlan | DAG (nodes + edges) thay vì list |
| `plan_step_index` | — | ✅ | Resume position trong DAG |
| `current_goal` | — | ✅ New | Intent hiện tại, dùng cho TGB + Reflection |
| `planner_reasoning` | — | ✅ New | TGB reasoning log |
| `plan_confidence` | — | ✅ New | Confidence của toàn bộ DAG |
| `intent` | ✅ | ✅ | Vẫn giữ |
| `entities` | ✅ | ✅ | Vẫn giữ |
| `resolved_entities` | — | ✅ New | Product ID thực tế đã resolve |
| `tool_results` | ✅ | ✅ | Same, key = node_id |
| `tool_history` | — | ✅ New | Lịch sử tool results qua các lượt |
| `dependency_graph` | — | ✅ New | Runtime dependency tracking |
| `complexity_score` | — | ✅ | Cho response_verifier |
| `final_answer` | ✅ | ✅ | Same |
| `groundedness_score` | — | ✅ | Cho hallucination guard |
| `hallucination_detected` | — | ✅ | Signal cho fallback route |
| `fallback_used` | — | ✅ | Logging/monitoring |
| `gate_decisions` | — | ✅ | Log Gate calls |
| `semantic_hallucination_detected` | — | ✅ | Signal riêng cho semantic hallucination |
| `replan_count` | — | ✅ | Giới hạn vòng lặp replan |
| `reflection_result` | — | ✅ New | pass / replan — từ Reflection node |
| `reflection_issues` | — | ✅ New | Chi tiết issue cho partial replan |
| `confidence` | — | ✅ New | Overall confidence của cả lượt |
| `planner_memory` | — | ✅ New | Short-term memory giữa các lượt |
| `retry_count` | — | ✅ | Số lần retry |
| `pending_action` | ✅ | ✅ | Same |
| `confirmed` | ✅ | ✅ | Same |
| `errors` | ✅ | ✅ | Same |
| `guardrail_violations` | ✅ | ✅ | Same |
| `node_durations` | ✅ | ✅ | Same |
| `pending_workflows` | ✅ | ❌ Removed | Không còn workflow |
| `current_product_id` | ✅ | ❌ Removed | Trong resolved_entities |
| `resolved_product_name` | ✅ | ❌ Removed | Trong tool_results |
| `candidate_products` | ✅ | ❌ Removed | Trong tool_results |

---

## 13. Cache Strategy (Redis)

### Mục tiêu

Cache không phải để giảm thời gian phản hồi của LLM mà để giảm:
- gRPC call đến EKS microservices (ProductCatalog, Cart, Recommendation, Currency)
- REST call (Shipping)
- LLM Planning (cache DAG plan cho query lặp)
- Search, Recommendation, Currency API

đồng thời tránh cache nhầm dữ liệu riêng tư của người dùng.

### 13.1 Phân loại cache

5 loại cache với TTL riêng:

| Cache | Dữ liệu | TTL | Redis Namespace |
|---|---|---|---|
| L1 Planner Cache | DAG plan (nodes + edges) | 5 phút | `db0` / `planner:*` |
| L2 Search Cache | Top N Product IDs | 10 phút | `db1` / `search:*` |
| L3 Product Cache | Product detail (name, price, description, rating, image) | 30 phút | `db1` / `product:*` |
| L4 External Cache | Currency rate, shipping quote, recommendation | 30-60 phút | `db1` / `currency:*`, `shipping:*`, `recommend:*` |
| L5 Session Cache | Planner memory (last_search, current_cart, history) | 30 phút | `db2` / `session:*` |

Lý do tách logical database:
- **DB0 (Planner)**: DAG plans — dung lượng nhỏ, quan trọng, cần hit rate cao
- **DB1 (Tool)**: Tool results — dung lượng lớn nhất, LRU eviction
- **DB2 (Session)**: Dữ liệu session — TTL cố định, không LRU

### 13.2 Planner Cache

Cache DAG plan do Task Graph Builder sinh ra để tránh gọi LLM cho query giống hệt lần trước.

```
Query: "Find telescope under $200"
Planner → DAG: search → recommendation
Lần sau cùng query → không gọi LLM, dùng cached DAG
```

**Key**: `planner:<SHA256(query)>`
**Value**: DAG JSON (`{nodes, edges, overall_confidence}`)
**TTL**: 5 phút
**Điều kiện cache**:
- `plan_confidence >= 0.9`
- Không cache nếu confidence thấp (< 0.9) hoặc plan bị denied (empty nodes)

### 13.3 Search Cache

Cache quan trọng nhất — chiếm phần lớn traffic gRPC đến ProductCatalog.

**Key**: `search:<SHA256(language + query + price_range + category)>`
**TTL**: 10 phút
**Dữ liệu cache**: `Top N Product IDs` (không cache raw protobuf)
**Lý do**: Product detail có thể thay đổi (giá, description) — chỉ cache danh sách ID, detail luôn fetch real-time hoặc từ Product Cache.

```
Key: search:{sha256(lang + query + price_range + category)}
Value: list[str] — top N Product IDs (không cache raw protobuf)
```

### 13.4 Product Cache

Cache chi tiết sản phẩm theo ProductID.

**Key**: `product:<product_id>`
**TTL**: 30 phút
**Dữ liệu**: `name`, `price`, `description`, `rating`, `image`
**Không cache**: `stock`, `inventory` (dành cho realtime inventory sau này)

```
Key: product:{product_id}
Value: {id, name, price, description, image, rating, categories}
```

### 13.5 Recommendation Cache

Recommendation rất tốn gRPC — cache theo product_id hoặc user_id.

| Loại | Key | TTL |
|---|---|---|
| Non-personalized | `recommend:<product_id>:<limit>` | 15 phút |
| Personalized | `recommend:<user_id>:<product_id>` | 5 phút |

Personalized TTL ngắn hơn vì thay đổi theo hành vi người dùng.

### 13.6 Currency & Shipping Cache

| Cache | Key | TTL |
|---|---|---|
| Currency | `currency:<from>:<to>` | 1 giờ |
| Shipping | `shipping:<SHA256(zip + cart_total)>` | 10 phút |

Tỷ giá ít biến động — không cần gọi API liên tục.

### 13.7 Session Cache

Lưu Planner Memory ngắn hạn giữa các lượt chat:

```
planner_memory = {last_search, last_product_id, current_cart_items, last_intent, history: list (max 6 turns)}
```

**Key**: `session:<session_id>`
**TTL**: 30 phút
**Storage**: Redis DB2 (không dùng in-memory — để pod restart không mất context)

### 13.8 Cache Flow

```
Executor
  │
  ├── Cache Lookup
  │     ├── Hit → Return cached
  │     └── Miss → Call Tool → Validate → Redis SETEX → Return
```

**Chỉ cache sau khi**:
1. Tool thành công (`status = success`)
2. Output hợp lệ theo schema (valid JSON + đủ required fields)
3. Không phải write tool (`add_to_cart_tool`, `checkout_tool`)
4. Không chứa dữ liệu riêng tư của user (trừ session cache được phân vùng theo session_id)

**Confirmation tokens**: Giữ nguyên HMAC stateless (§9) — không cache, không Redis.

### 13.9 Redis Key Convention

```
planner:{sha256(query)}
search:{sha256(lang + query + price_range + category)}
product:{product_id}
recommend:{product_id}:{limit}           # non-personalized
recommend:{user_id}:{product_id}         # personalized
currency:{from}:{to}
shipping:{sha256(zip + cart_total)}
session:{session_id}
```

Hash toàn bộ query/params bằng SHA256, lấy 16 ký tự đầu để tránh key quá dài.

### 13.10 Cache Invalidation

Design hiện tại chưa có invalidation. Bổ sung cơ chế:

**Event-driven invalidation** (khi admin sửa sản phẩm):
```
ProductUpdated Event → Redis subscriber → xóa:
- product:{product_id}
- search:* (flush search cache)
- recommend:* (flush recommend cache)
```

Dùng Redis Pub/Sub: publisher gửi `{"type": "product_updated", "product_id": "..."}`, subscriber cache manager nhận → xoá `product:{id}`, flush `search:*`, `recommend:*`.

**Passive invalidation**: TTL tự động hết hạn — đủ cho hầu hết use case. Invalidation chỉ cần cho admin update product.

### 13.11 Redis Architecture

```
                   +----------------+
                   |   LangGraph    |
                   +-------+--------+
                           |
                    Cache Manager
                           |
         +-----------------+-----------------+
         |                 |                 |
    Planner Cache     Tool Cache       Session Cache
    (DB0)             (DB1)            (DB2)
         |                 |                 |
   DAG Plans       Search/Product/    Planner Memory
                   Currency/Shipping/
                   Recommendation
```

**Lợi ích tách logical database**:
- Dễ cấu hình TTL theo từng nhóm
- Dễ theo dõi tỷ lệ cache hit riêng
- Hạn chế xoá nhầm dữ liệu (flush DB1 không ảnh hưởng DB0/DB2)
- Có thể gán maxmemory-policy riêng (DB0: noeviction, DB1: allkeys-lru, DB2: volatile-ttl)

### 13.12 Migration từ in-memory sang Redis

Hiện tại `memory/store.py` dùng in-memory dict (`CacheStore`). Production chuyển sang Redis:

| Giai đoạn | Cache | Storage | Ghi chú |
|---|---|---|---|
| Dev/Test | Tool cache | In-memory (`CacheStore`) | TTL + LRU sẵn có |
| Production | Planner + Tool cache | Redis DB0 + DB1 | Cần Redis instance |
| Production | Session cache | Redis DB2 | Cần Redis + session fallback |

```
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHE_ENABLED = env("CACHE_ENABLED", "true")
```

File mới: `memory/redis_store.py` — Redis-backed implementation của CacheStore interface.

---

## 13a. Resource Limits & Production Guardrails

Các giới hạn cứng (hard limits) để đảm bảo hệ thống ổn định trong production, ngăn DAG mở rộng quá mức, LLM lặp lại nhiều lần, hoặc backend bị quá tải.

### 13a.1 Max Tool Calls

Một request tối đa **≤ 8 tool calls** (tổng số node trong DAG).

```
Ví dụ hợp lệ: search → product → review → recommend → currency → shipping → cart → checkout
```

Nếu vượt: Planner phải ưu tiên hoặc hỏi user, không execute mù.

### 13a.2 Max DAG Depth

**≤ 5 levels** (độ sâu tối đa của dependency chain).

Nếu sâu hơn: Planner phải chia nhỏ.

### 13a.3 Max Parallel Nodes

**≤ 4** nodes chạy đồng thời trong một batch `asyncio.gather`.

Lý do: tránh 20+ gRPC call cùng lúc đến backend (EKS microservices không có connection pool đủ lớn).

### 13a.4 Replan Limit

**Max Replan = 1** mỗi request. Sau 1 lần replan, dù kết quả thế nào cũng force pass.

Implementation trong `reflection.py`: nếu `replan_count >= 1` → force `reflection_result = "pass"`.

### 13a.5 Retry Strategy

| Loại tool | Retry | Ghi chú |
|---|---|---|
| Read tool (search, product, review, recommend, currency) | **2 lần** | Exponential backoff (0.5s, 1s) |
| Write tool (add_to_cart) | **0 hoặc 1 lần** | Không retry checkout — tránh charge thẻ 2 lần |
| Checkout | **0 lần** | Fail → báo user, không retry mù |

### 13a.6 LLM Timeout

| LLM Call | Timeout | Hành động khi timeout |
|---|---|---|
| Planner (Task Graph Builder) | **3s** | Fallback → template response |
| Response Verifier (LLM path) | **4s** | Fallback → template response |
| Semantic Gate (Nova Lite) | **2s** | Dùng `DEFAULT_DECISION` (§10.6) |

### 13a.7 Tool Timeout

| Tool | Timeout |
|---|---|
| Default tool | **2s** |
| Shipping (REST) | **3s** |
| Recommendation | **2s** |
| Search | **2s** |

### 13a.8 P95 End-to-End Latency

**< 5s** cho toàn bộ request (từ user gửi đến nhận reply).

Nếu vượt: template response ngay, background fetch nếu cần.

### 13a.9 Conversation History

Không gửi toàn bộ lịch sử cho LLM. Giới hạn:
- **6 lượt gần nhất** (kế thừa từ `SessionStore._SESSION_MAX_MESSAGES`)
- Hoặc **2000 token** (whichever comes first)

### 13a.10 Planner Memory

Giới hạn dung lượng: **20 KB** mỗi session.

Memory chỉ gồm các field cố định: `last_search`, `last_product_id`, `current_cart_items`, `last_intent`.

Không lưu raw messages vào planner memory — messages đã có trong SessionStore.

### 13a.11 Search / Recommend / Review Limits

| Kết quả | Giới hạn |
|---|---|
| Search | **Top 20** products (không trả 500 cho LLM) |
| Recommendation | **Top 5** items |
| Review | **Top 10** reviews (LLM không cần 300 review) |

### 13a.12 Max Response Length

**1200 tokens** (khoảng ~900 chữ).

Nếu dài hơn: tóm tắt hoặc template response.

### 13a.13 Redis Max Cache Size

LRU eviction, maxmemory cấu hình theo dung lượng Redis cluster:

| DB | Policy | Maxmemory gợi ý |
|---|---|---|
| DB0 (Planner) | `noeviction` | 256 MB |
| DB1 (Tool) | `allkeys-lru` | 2 GB |
| DB2 (Session) | `volatile-ttl` | 512 MB |

---

## 13b. Observability Metrics

Để đánh giá hiệu quả cache + resource limits trong production:

| Metric | Target | Nguồn |
|---|---|---|
| Cache Hit Rate (Product) | > 80% | Redis INFO / cache stats |
| Cache Hit Rate (Search) | > 60% | Redis INFO / cache stats |
| Planner Cache Hit Rate | > 50% | Redis INFO / cache stats |
| Average Tool Calls / Request | < 4 | LangGraph telemetry |
| Average DAG Depth | < 4 | LangGraph telemetry |
| Reflection Rate | < 10% request | Graph node counter |
| Replan Success Rate | > 90% | Graph node counter |
| Tool Timeout Rate | < 1% | ToolExecutor metric |
| LLM Timeout Rate | < 0.5% | LLM client metric |
| P95 End-to-End Latency | < 5s | FastAPI middleware |
| Redis Memory Usage | < 80% capacity | Redis INFO memory |
| Cache Invalidation Events | monitor | Redis Pub/Sub counter |

---

## 14. API Server

Giữ nguyên từ v2. Chi tiết xem v2 spec §9.

### Endpoints

| Method | Path | Description | Request Body | Response |
|---|---|---|---|---|
| `POST` | `/api/chat` | Send a message | `{message, session_id, user_id}` | `{status, reply, token?, session_id}` |
| `POST` | `/api/confirm` | Confirm a pending action | `{session_id, token}` | `{status, reply}` |
| `GET` | `/health` | Health check | — | `{status: "ok"}` |
| `GET` | `/` | Server info | — | `{service, version, endpoints}` |

### Graph Invocation Flow

**`POST /api/chat`**:
1. Gọi `graph.ainvoke({messages, session_id, user_id, trace_id})`
2. Kiểm tra `result.pending_action` → return `{status: "pending", reply, token, session_id}`
3. Kiểm tra `result.guardrail_violations` → return `{status: "error", reply: violation.detail}`
4. Mặc định → `{status: "ok", reply: final_answer, session_id}`

**`POST /api/confirm`**:
1. `verify_confirmation_token(req.token)` — kiểm tra HMAC signature + expiry
2. Nếu không hợp lệ → `{status: "error", reply: "Token không hợp lệ."}`
3. Nếu hợp lệ → `graph.ainvoke(Command(resume={"confirmed": True}))` → resume từ checkpoint
4. Return `{status, reply: final_answer}`

---

## 15. Configuration & Environment

Giữ nguyên từ v2. Xem chi tiết ở v2 spec §10.

---

## 16. Running the System

Giữ nguyên từ v2. Xem chi tiết ở v2 spec §11.

---

## 17. Testing

### v3.2 Test Cases

| # | Test Case | Node | Input | Expected |
|---|---|---|---|---|
| 1 | Simple search — Intent Parser rule match | intent_parser | "Find telescopes" | intent=search, confidence ≥0.8, rule path |
| 2 | Ambiguous query — Intent Parser LLM fallback | intent_parser | "I want to see stuff" | intent determined by LLM, confidence <0.8 |
| 3 | Single tool DAG | task_graph_builder | "Find telescopes under $200" with intent=search | DAG: 1 node (search), no edges |
| 4 | Multi-tool DAG with parallel | task_graph_builder | "Review tent and recommend" | DAG: search → [review, recommend] song song |
| 5 | DAG with conditional | task_graph_builder | "Find Nike shoes $50-$150" | DAG: search with `condition: {"on":"total","==0":"ask_user"}` |
| 6 | Empty plan (denied action) | task_graph_builder | "Place order" | DAG: empty nodes, confidence=0 |
| 7 | DAG parallel execution | tool_executor | DAG: n0(search) → n1(review), n2(recommend) | n1, n2 chạy song song (asyncio.gather) |
| 8 | Conditional branching — 0 results → ask_user | tool_executor | DAG node with `condition: {"on":"total","==0":"ask_user"}` | Pause, trả về pending_action |
| 9 | Conditional branching — continue | tool_executor | DAG node with `condition: {"on":"total","==0":"ask_user"}`, total=5 | Tiếp tục execution |
| 10 | $first() helper — list has items | tool_executor | `$first(steps[n0].products, default=null)` | Returns first product |
| 11 | $first() helper — empty list | tool_executor | `$first(steps[n0].products, default=null)` | Returns null (không crash) |
| 12 | $safe_index() — index exists | tool_executor | `$safe_index(steps[n0].products, 0, default=null)` | Returns product[0] |
| 13 | $safe_index() — index out of bounds | tool_executor | `$safe_index(steps[n0].products, 99, default=null)` | Returns default (null) |
| 14 | $exists() — field exists | tool_executor | `$exists(steps[n0].products[0].id)` | Returns True |
| 15 | Tool execution with normalization | tool_executor | search_products_v2 raw output | Normalized with `price: "$99.99"` |
| 16 | Write confirmation pause | tool_executor | add_to_cart_tool returns pending | Pause, return token |
| 17 | Resume after confirm | tool_executor | state.confirmed=True | Executes gRPC AddItem |
| 18 | L3 blocks invalid tool | tool_executor | Unknown tool name | error in tool_results |
| 19 | Cache hit | tool_executor | Same query repeated | Returns cached, no gRPC |
| 20 | **Reflection PASS** — no issues | reflection | All tools OK, no errors | reflection_result="pass" |
| 21 | **Reflection REPLAN** — zero result | reflection | search returns total=0 | reflection_result="replan", issue type="zero_result" |
| 22 | **Reflection REPLAN** — tool errors | reflection | ≥2 tool errors | reflection_result="replan" |
| 23 | **Reflection limit reached** | reflection | replan_count≥2, still errors | reflection_result="pass" (force) |
| 24 | **Partial replan** — chỉ sửa node lỗi | task_graph_builder + tool_executor | DAG 3 node, node 2 lỗi | TGB sinh 1 node mới, executor chỉ chạy node đó |
| 25 | **Template-First** — cart | response_verifier (template) | get_cart_tool result | Template response, không LLM call |
| 26 | **Template-First** — shipping | response_verifier (template) | get_shipping_quote result | Template response, không LLM call |
| 27 | **Template-First** — currency | response_verifier (template) | convert_currency result | Template response, không LLM call |
| 28 | **Template-First** — reviews | response_verifier (template) | get_product_reviews result | Template response, không LLM call |
| 29 | **LLM path** — search >3 items | response_verifier (LLM) | search returns 5 products | LLM summarize, temperature=0.3 |
| 30 | **LLM path** — multi-tool complex | response_verifier (LLM) | review + recommend combined | LLM compare/explain, temperature=0.4-0.6 |
| 31 | Semantic hallucination check | hallucination_guard | Answer says "phù hợp chuyên gia" but description says "cho người mới" | semantic violation → groundedness <0.80 |
| 32 | Entity hallucination — wrong product | hallucination_guard | Answer says "Dell laptop" but DB only has "Telescope" | entity violation → fallback |
| 33 | Entity grounded — correct | hallucination_guard | Answer says "Telescope $99.99" and DB has it | No violation → PASS |
| 34 | Semantic gate catches meaning-drift | semantic_hallucination_gate | Claim passes rule-based but reinterprets tool fact | Nova Lite → NO → fallback |
| 35 | Gate timeout fallback | gate_node | Bedrock call times out | DEFAULT_DECISION, request not blocked |
| 36 | Planner memory — carry context | task_graph_builder | User says "review cái đó" after search | TGB dùng `planner_memory.last_product_id` |
| 37 | Low confidence → ask_user | tool_executor | plan_confidence=0.3 | Route sang ask_user |

---

## 18. Operating Costs

### Model dùng trong hệ thống

| Vai trò | Model | Nguồn giá tham chiếu |
|---|---|---|
| Intent Parser (LLM fallback) | LLM chính (Groq API) | ~20-100 tokens, rất nhỏ |
| Task Graph Builder | LLM chính (Groq API) | Giá theo provider Groq |
| Response Verifier (LLM path) | LLM chính (Groq API) | Chỉ khi complexity > 0.5 |
| **Semantic Decision Gates (§10.6)** | **Amazon Nova Lite** (`amazon.nova-lite-v1:0`) | AWS Bedrock on-demand: **$0.06 / 1M input tokens, $0.24 / 1M output tokens** |

### Per-Request Cost (v3.2, template-first + gate layer)

| Path | LLM/Gate Calls | Tokens | Cost | Latency |
|---|---|---|---|---|
| Template path: cart/shipping/currency/review | 1 (TGB, ~150 tokens) | ~150 | **~$0.00001** | **~300ms** (template <1ms) |
| Simple search (1-3 items) | 1 TGB + template search | ~250 | **~$0.00002** | ~500ms |
| Complex search (>3 items) | 1 TGB + 1 verifier (LLM) | ~600 | ~$0.00004 | ~1000ms |
| Multi-tool (3 tools, template) | 1 TGB + template ghép | ~350 | ~$0.00003 | ~800ms |
| Multi-tool (3 tools, LLM) | 1 TGB + 1 verifier (LLM) | ~800 | ~$0.00006 | ~1500ms |
| Multi-tool + gates typical | + semantic_hallucination_gate (1-2 claim) | +~270 (Nova Lite) | **+$0.00002 → tổng ~$0.00008** | +150-300ms |
| Multi-tool + reflection replan | + 1 partial TGB + 1 executor | +~500 | +$0.00004 | +500-1000ms |
| Worst case (replan + gates) | TGB→exec→refl→TGB(partial)→exec→verifier+gates | ~2000 | **~$0.00015** | ~2500ms |

**Tác động của Template-First**: ~60% request (cart, shipping, currency, reviews, search ≤3 items) không cần LLM cho response → giảm cost và latency đáng kể so với v3.1.

### Prompt Caching (Bedrock)

Khi dùng Amazon Bedrock, system prompt của TGB (phần `ToolRegistry.get_all_schemas_text()` ~1500 tokens) được **cache tự động** (Contextual Caching). Từ request thứ 2 trở đi:

- Input cost giảm ~75% (chỉ tính tokens khác biệt giữa session)
- Latency giảm ~30% (cache hit → skip encoding)
- Chi phí thực tế cho query lặp gần như bằng $0

Gate Layer cũng hưởng lợi tương tự.

### DAG parallel execution benefit

| Path | Sequential | Parallel (DAG) |
|---|---|---|
| Review + recommend (2 tools sau search) | search(500ms) → review(300ms) → recommend(300ms) = **1100ms** | search(500ms) → review/recommend song song(300ms) = **800ms** |
| 3 independent tools | 3 × 300ms = **900ms** | **300ms** (chạy đồng thời) |

### Trade-off tổng

| Điểm | v3.2 |
|---|---|
| **Cost giảm** so với v3.1 | Template-First (~60% request) không cần LLM response → tiết kiệm ~$0.00002-0.00004/request |
| **Latency giảm** so với v3.1 | DAG parallel: 20-40% nhanh hơn sequential cho multi-tool |
| **Coverage tăng** | Reflection + partial replan bắt được case tool lỗi/0 kết quả |
| **Rủi ro vận hành** | Reflection thêm 1 node rule-based ($0), replan thêm 1 TGB call (có kiểm soát replan_count) |

---

## 19. Limitations & Roadmap

### Known Limitations

| # | Limitation | Impact | Plan |
|---|---|---|---|
| 1 | ~~Planner chỉ support sequential plan~~ | ~~Không chạy tool song song~~ | ✅ Đã giải quyết ở v3.2 — DAG + parallel execution (§8) |
| 2 | Rate limiter per-pod | User bypass qua replicas | Valkey/Redis global limiter (Phase 3) |
| 3 | ~~Session/cache in-memory~~ | ~~Mất khi pod restart~~ | ✅ Đã thiết kế — Redis cache strategy (§13) + migration plan (§13.12). Triển khai ở Phase 3 |
| 4 | Price normalization manual | Tool phải gọi format_price() | Auto-normalize interceptor (Phase 3) |
| 5 | LLM dependency | TGB/Verifier cùng LLM | Separate smaller LLM for TGB (Phase 4) |
| 6 | No retry for write tools | add_to_cart fail = mất confirm token | Retry queue for write actions (Phase 4) |
| 7 | ~~HallucinationGuard chỉ rule-based~~ | ~~Không phát hiện hallucination ngữ nghĩa tinh vi~~ | ✅ Đã giải quyết — rule-based + semantic claim check (§10.5) + semantic_hallucination_gate (§10.6) |
| 8 | ~~Fallback template cứng~~ | ~~Thiếu tự nhiên so với LLM answer~~ | ✅ Đã giải quyết — Template-First strategy (§10): cart/shipping/currency/review dùng template, search/recommend dùng LLM khi cần summarize |
| 9 | Gate Layer chạy tuần tự | Worst case cộng dồn latency >1s | Chạy song song gate độc lập bằng `asyncio.gather` (Phase 4) |
| 10 | Gate Layer thêm external dependency | Nova Lite/Bedrock lỗi có thể ảnh hưởng critical path | Đã có `DEFAULT_DECISION` fallback (§10.6) + circuit breaker (Phase 3) |
| 11 | Chưa có metric theo dõi false positive/negative của Gate | Không biết Nova Lite quyết định sai bao nhiêu % | Log `reason` + sample review định kỳ, xây dashboard |
| 12 | Partial replan chỉ support 1 lần | Nếu replan vẫn lỗi → force pass | Multi-step replan với backtracking (v4.0) |
| 13 | Intent Parser rule set hữu hạn | Pattern match có thể miss query mới | Update rule set định kỳ từ log miss |

### Roadmap

**Phase 1 — 2-Layer Planner + DAG Core (Week 1) 🔄 In Progress**
- ⏳ `graph/nodes/intent_parser.py` — Layer 1: Rule-based + LLM fallback
- ⏳ `graph/nodes/task_graph_builder.py` — Layer 2: LLM chọn tool + nối edge
- ⏳ `graph/nodes/tool_executor.py` — DAG runner (parallel, conditional, variable helpers)
- ⏳ `graph/nodes/reflection.py` — Post-execution check → partial replan
- ⏳ `graph/nodes/response_verifier.py` — Template-First + LLM fallback
- ⏳ Update `graph/main_graph.py` — New DAG-centric edges + reflection routing
- ⏳ Update `graph/state.py` — Add tool_history, dependency_graph, confidence, planner_memory, ...
- ⏳ `llm/prompt.py` — TGB prompt + Verifier prompt (updated)

**Phase 2 — Hallucination Guard + Gate Layer (Week 2)**
- ⏳ `graph/nodes/hallucination_guard.py` — Rule-based + semantic claim check
- ⏳ `graph/nodes/fallback_generator.py` — Template fallback
- ⏳ `graph/gates/gate_node.py` — Shared Gate Node (Nova Lite)
- ⏳ `semantic_hallucination_gate`, `plan_validity_gate`, `confirm_parse_gate`, `replan_gate`
- ⏳ Template set hoàn chỉnh (cart, shipping, currency, reviews, search, confirm)
- ⏳ Integration tests (intent_parser → TGB → executor → reflection → verifier → guard)
- ⏳ 37 test cases từ §17

**Phase 3 — Production (Week 3)**
- ⏳ `memory/redis_store.py` — Redis-backed CacheStore implementation (§13)
- ⏳ Valkey/Redis for rate limiter + session store
- ⏳ Cache invalidation via Redis Pub/Sub (§13.10)
- ⏳ Enforce resource limits trong ToolExecutor (§13a): max tool calls, DAG depth, parallel nodes, timeout
- ⏳ OpenTelemetry metrics cho cache hit rate + resource limit counters (§13b)
- ⏳ Load test P95 < 5s (§13a.8)
- ⏳ Circuit breaker cho Nova Lite Gate calls
- ⏳ Partial replan multi-step (nếu replan vẫn lỗi → backtrack)

**Phase 4 — Optimization (v3.3, sau khi có traffic thật)**
- ⏳ Chạy song song các gate độc lập (`asyncio.gather`)
- ⏳ Bedrock prompt caching cho TGB system prompt + gate instructions
- ⏳ Dashboard: template hit rate, replan trigger distribution, gate false positive/negative
- ⏳ Cân nhắc downgrade một số gate ít rủi ro sang Nova Micro

---

> **Author:** AIO02 — TF3 | **Date:** 2026-07-17
> **Architecture Change:** v2 (Intent + Workflow) → v3 (Planner-Centric) → v3.2 (2-Layer Planner + DAG + Reflection + Template-First)
> **References:** `docs/design/langgraph_design.md` (deprecated — replaced by this spec)
> Keep this document updated when architecture changes or modules are added.