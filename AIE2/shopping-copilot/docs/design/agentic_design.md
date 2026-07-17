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
7. [Planner Node](#7-planner-node)
8. [Tool Executor Loop](#8-tool-executor-loop)
9. [Write + Confirm Flow](#9-write--confirm-flow)
10. [Response Verifier](#10-response-verifier)
10.6. [Semantic Decision Gate Layer (Nova Lite)](#106-semantic-decision-gate-layer-nova-lite)
11. [System Prompt Design](#11-system-prompt-design)
12. [State Design](#12-state-design)
13. [Memory & Caching](#13-memory--caching)
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
│   └── store.py                     # In-memory TTL + LRU
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

Dưới đây là `ToolSpec` đầy đủ cho tất cả tool — được thiết kế độc lập, không phụ thuộc vào output gRPC/REST hiện tại. Tool sẽ được implement lại dựa trên schema này.

#### `search_products_v2`

```python
_search_spec = ToolSpec(
    name="search_products_v2",
    description=(
        "Tìm kiếm sản phẩm theo từ khóa. "
        "Có thể lọc theo category, khoảng giá. "
        "Trả về danh sách sản phẩm khớp."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Từ khóa tìm kiếm (tiếng Việt hoặc tiếng Anh)",
            },
            "category": {
                "type": "string",
                "description": "Lọc theo danh mục (optional)",
            },
            "min_price": {
                "type": "string",
                "description": "Giá thấp nhất dạng '100' (optional)",
            },
            "max_price": {
                "type": "string",
                "description": "Giá cao nhất dạng '500' (optional)",
            },
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "empty", "error"],
                "description": "Kết quả tìm kiếm",
            },
            "total": {
                "type": "integer",
                "description": "Tổng số sản phẩm tìm thấy",
            },
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Product ID"},
                        "name": {"type": "string"},
                        "price": {"type": "string", "description": "Giá dạng '$99.99'"},
                        "description": {"type": "string"},
                        "image": {"type": "string", "description": "Tên file ảnh (tool ghép base URL)"},
                        "categories": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "DB lưu comma-separated string → tool split thành array",
                        },
                    },
                    "required": ["id", "name", "price"],
                },
            },
        },
        "required": ["status", "total", "products"],
    },
    is_write=False,
    examples=[
        {
            "query": "tìm kính thiên văn dưới 200 đô",
            "plan": [
                {"tool": "search_products_v2", "args": {"query": "kính thiên văn dưới 200 đô"}},
            ],
        },
        {
            "query": "giày thể thao Nike giá từ 50 tới 150 đô",
            "plan": [
                {
                    "tool": "search_products_v2",
                    "args": {
                        "query": "Nike giày thể thao",
                        "min_price": "50",
                        "max_price": "150",
                    },
                },
            ],
        },
    ],
    retry_config={"max_retries": 2},
)
```

**DB mapping:** `products` table. `id`, `name`, `description`, `picture→image` (filename, tool prepends CDN base URL), `price_units+price_nanos→price`, `categories` (comma-separated TEXT → tool splits to array). Computed fields: `total`, `status`.

#### `get_product_details_tool`

```python
_details_spec = ToolSpec(
    name="get_product_details_tool",
    description=(
        "Lấy thông tin chi tiết của một sản phẩm theo ID. "
        "Dùng khi user hỏi chi tiết cụ thể về sản phẩm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "ID của sản phẩm",
            },
        },
        "required": ["product_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "not_found", "error"],
            },
            "product": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "price": {"type": "string", "description": "Giá dạng '$99.99'"},
                    "description": {"type": "string"},
                    "image": {"type": "string", "description": "Tên file ảnh (tool ghép base URL)"},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "DB lưu comma-separated string → tool split thành array",
                    },
                    "rating": {"type": "number", "description": "Tính từ AVG(score) trong productreviews"},
                    "review_count": {"type": "integer", "description": "Đếm từ productreviews"},
                },
                "required": ["id", "name", "price"],
            },
        },
        "required": ["status"],
    },
    is_write=False,
    examples=[
        {
            "product_id": "prod_123",
            "plan": [
                {"tool": "get_product_details_tool", "args": {"product_id": "prod_123"}},
            ],
        },
    ],
    retry_config={"max_retries": 2},
)
```

**DB mapping:** `products` table + optional aggregate from `productreviews`. Removed `original_price`, `stock_status`, `attributes` (không tồn tại trong DB). `rating` và `review_count` cần JOIN/aggregate từ `productreviews`.

#### `get_product_reviews_tool`

```python
_reviews_spec = ToolSpec(
    name="get_product_reviews_tool",
    description=(
        "Lấy đánh giá của người dùng cho một sản phẩm. "
        "Bao gồm điểm số, nội dung, và thống kê."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "ID của sản phẩm",
            },
            "limit": {
                "type": "integer",
                "description": "Số lượng review tối đa (mặc định 10)",
            },
            "sort": {
                "type": "string",
                "enum": ["newest", "highest", "lowest"],
                "description": "Cách sắp xếp review",
            },
        },
        "required": ["product_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "error", "empty"],
            },
            "product_id": {"type": "string"},
            "product_name": {"type": "string", "description": "Cần JOIN với products table"},
            "average_score": {"type": "number", "description": "AVG(score) trong productreviews"},
            "total_reviews": {"type": "integer", "description": "COUNT(*) trong productreviews"},
            "distribution": {
                "type": "object",
                "properties": {
                    "1": {"type": "integer"},
                    "2": {"type": "integer"},
                    "3": {"type": "integer"},
                    "4": {"type": "integer"},
                    "5": {"type": "integer"},
                },
                "description": "Phân bố điểm — GROUP BY ROUND(score) trên productreviews",
            },
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "review_id": {"type": "integer", "description": "DB: id INTEGER AUTOINCREMENT"},
                        "username": {"type": "string", "description": "DB: username VARCHAR(64)"},
                        "score": {"type": "number", "description": "DB: NUMERIC(2,1) — vd 4.5, 3.0"},
                        "body": {"type": "string", "description": "DB: description VARCHAR(1024)"},
                    },
                    "required": ["review_id", "username", "score"],
                },
            },
        },
        "required": ["status", "product_id", "average_score", "total_reviews"],
    },
    is_write=False,
    examples=[
        {
            "product_id": "prod_123",
            "plan": [
                {"tool": "get_product_reviews_tool", "args": {"product_id": "prod_123"}},
            ],
        },
        {
            "product_id": "prod_456",
            "plan": [
                {
                    "tool": "get_product_reviews_tool",
                    "args": {"product_id": "prod_456", "limit": 5, "sort": "newest"},
                },
            ],
        },
    ],
    retry_config={"max_retries": 2},
)

**DB mapping:** `reviews.productreviews` table. Loại bỏ `title` và `created_at` (không tồn tại trong DB). `score` là NUMERIC(2,1) nên kiểu `number` thay vì `integer`. `review_id` là `integer` (DB auto-increment). `product_name` cần JOIN với `catalog.products`.

#### `add_to_cart_tool` (WRITE)

```python
_add_cart_spec = ToolSpec(
    name="add_to_cart_tool",
    description=(
        "Thêm sản phẩm vào giỏ hàng. "
        "CẦN CONFIRM — sẽ trả về status='pending' kèm confirmation token."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "ID sản phẩm cần thêm",
            },
            "quantity": {
                "type": "integer",
                "minimum": 1,
                "description": "Số lượng (mặc định 1)",
            },
        },
        "required": ["product_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "confirmed", "denied", "error"],
                "description": "pending = chờ user xác nhận",
            },
            "token": {
                "type": "string",
                "description": "HMAC confirmation token (khi status=pending)",
            },
            "message": {
                "type": "string",
                "description": "Thông báo cho user",
            },
            "item": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "name": {"type": "string", "description": "Tool JOIN với products table để lấy name"},
                    "price": {"type": "string", "description": "Tool JOIN với products table để lấy price"},
                    "quantity": {"type": "integer"},
                },
                "description": "Chi tiết item đã thêm (khi status=confirmed)",
            },
        },
        "required": ["status"],
    },
    is_write=True,
    examples=[
        {
            "product_id": "prod_123",
            "plan": [
                {"tool": "add_to_cart_tool", "args": {"product_id": "prod_123", "quantity": 2}},
            ],
        },
    ],
    retry_config={"max_retries": 1},
)

**DB mapping:** `cart` table (chỉ có `user_id`, `product_id`, `quantity`). `name` và `price` trong output cần JOIN với `products`. Cart table không có price — tool phải tự lookup.

#### `get_cart_tool`

```python
_cart_spec = ToolSpec(
    name="get_cart_tool",
    description=(
        "Xem giỏ hàng hiện tại. "
        "Trả về danh sách items và tổng tiền."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "empty", "error"],
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "name": {"type": "string", "description": "JOIN với products table"},
                        "price": {"type": "string", "description": "JOIN với products table"},
                        "quantity": {"type": "integer"},
                        "image": {"type": "string", "description": "picture từ products table"},
                    },
                    "required": ["product_id", "name", "price", "quantity"],
                },
            },
            "subtotal": {"type": "string", "description": "SUM(price*quantity) — computed"},
            "item_count": {"type": "integer"},
        },
        "required": ["status", "items"],
    },
    is_write=False,
    examples=[
        {
            "query": "xem giỏ hàng của tôi",
            "plan": [
                {"tool": "get_cart_tool", "args": {}},
            ],
        },
    ],
    retry_config={"max_retries": 2},
)
```

**DB mapping:** `cart` table (chỉ có `user_id`, `product_id`, `quantity`). `name`, `price`, `image` cần JOIN với `products`. `subtotal` = SUM(price*quantity). Loại bỏ `shipping`, `tax`, `total` — không có dữ liệu nguồn trong DB (shipping quote cần tool riêng).

#### `get_recommendations_tool`

```python
_rec_spec = ToolSpec(
    name="get_recommendations_tool",
    description=(
        "Gợi ý sản phẩm dựa trên sản phẩm hiện tại hoặc context. "
        "Nếu không có product_id, trả về gợi ý chung (popular products)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "Gợi ý dựa trên sản phẩm này (optional)",
            },
            "context": {
                "type": "string",
                "description": "Gợi ý theo chủ đề (optional, vd: 'thể thao', 'gia đình')",
            },
            "limit": {
                "type": "integer",
                "description": "Số lượng gợi ý (mặc định 5)",
            },
        },
        "required": [],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "empty", "error"],
            },
            "reason": {
                "type": "string",
                "description": "Lý do gợi ý (vd: 'Based on your interest in telescopes')",
            },
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "string", "description": "Giá dạng '$99.99'"},
                        "description": {"type": "string"},
                        "image": {"type": "string"},
                        "rating": {"type": "number", "description": "JOIN với productreviews"},
                    },
                    "required": ["id", "name", "price"],
                },
            },
        },
        "required": ["status", "products"],
    },
    is_write=False,
    examples=[
        {
            "product_id": "prod_123",
            "plan": [
                {
                    "tool": "get_recommendations_tool",
                    "args": {"product_id": "prod_123"},
                },
            ],
        },
    ],
    retry_config={"max_retries": 2},
)

**DB mapping:** Không có bảng recommendations riêng. Chiến lược implement: (1) `product_id` → same-category products (WHERE categories LIKE), (2) context → full-text search, (3) fallback → popular products. Các field SELECT từ `products` table + AVG(score) từ `productreviews`.

#### `convert_currency_tool`

```python
_currency_spec = ToolSpec(
    name="convert_currency_tool",
    description=(
        "Chuyển đổi tiền tệ. "
        "Dùng khi user hỏi giá theo VND, JPY, EUR, v.v."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "amount": {
                "type": "number",
                "description": "Số tiền cần chuyển đổi",
            },
            "from": {
                "type": "string",
                "description": "Mã tiền tệ gốc (vd: 'USD')",
            },
            "to": {
                "type": "string",
                "description": "Mã tiền tệ đích (vd: 'VND')",
            },
        },
        "required": ["amount", "from", "to"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "error"],
            },
            "from": {"type": "string", "description": "Mã tiền tệ gốc"},
            "to": {"type": "string", "description": "Mã tiền tệ đích"},
            "original_amount": {"type": "number"},
            "converted_amount": {"type": "number"},
            "rate": {"type": "number", "description": "Tỷ giá"},
            "formatted": {
                "type": "string",
                "description": "Kết quả dạng '120,000 VND'",
            },
        },
        "required": ["status", "from", "to", "converted_amount", "rate"],
    },
    is_write=False,
    examples=[
        {
            "amount": 99.99,
            "from": "USD",
            "to": "VND",
            "plan": [
                {
                    "tool": "convert_currency_tool",
                    "args": {"amount": 99.99, "from": "USD", "to": "VND"},
                },
            ],
        },
    ],
    retry_config={"max_retries": 2},
)

**DB mapping:** Không có bảng exchange rates trong DB. Tool cần gọi external API (hoặc hardcode mapping USD→VND, USD→JPY, v.v.) vì products chỉ có price_currency_code='USD'. Output schema giữ nguyên như design.

#### `get_shipping_quote_tool`

```python
_shipping_spec = ToolSpec(
    name="get_shipping_quote_tool",
    description=(
        "Tính phí vận chuyển và thời gian giao hàng dự kiến."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "zip_code": {
                "type": "string",
                "description": "Mã vùng giao hàng",
            },
            "items_count": {
                "type": "integer",
                "description": "Số lượng items (optional)",
            },
            "cart_total": {
                "type": "string",
                "description": "Giá trị đơn hàng dạng '$199.99' (optional)",
            },
        },
        "required": ["zip_code"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "error", "unavailable"],
            },
            "destination": {"type": "string", "description": "Khu vực giao hàng"},
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "cost": {"type": "string", "description": "Phí dạng '$15.00' (units/nanos → format_price)"},
                        "delivery_days": {
                            "type": "integer",
                            "description": "Số ngày giao hàng dự kiến",
                        },
                        "delivery_window": {
                            "type": "string",
                            "description": "Khung giờ (vd: '2-4 ngày')",
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["provider", "cost", "delivery_days"],
                },
            },
        },
        "required": ["status", "options"],
    },
    is_write=False,
    examples=[
        {
            "zip_code": "70000",
            "cart_total": "$227.97",
            "plan": [
                {
                    "tool": "get_shipping_quote_tool",
                    "args": {"zip_code": "70000", "cart_total": "$227.97"},
                },
            ],
        },
    ],
    retry_config={"max_retries": 2},
)

**DB mapping:** Không có bảng shipping quotes. `shipping` table chỉ ghi lại shipment sau khi đặt hàng. Tool implement bằng business rules (vd: free ship > $100, flat rate $15 theo zip). Cost format dùng `shipping_cost_units/nanos` pattern giống products.

#### `checkout_tool` (WRITE)

```python
_checkout_spec = ToolSpec(
    name="checkout_tool",
    description=(
        "Tiến hành thanh toán đơn hàng. "
        "CẦN CONFIRM — yêu cầu user xác nhận toàn bộ đơn hàng trước khi thực hiện."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shipping_address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                    "zip": {"type": "string"},
                    "country": {"type": "string"},
                },
                "required": ["street", "city", "zip", "country"],
                "description": "Địa chỉ giao hàng đầy đủ",
            },
            "shipping_provider": {
                "type": "string",
                "description": "Hãng vận chuyển đã chọn từ shipping options",
            },
            "note": {
                "type": "string",
                "description": "Ghi chú cho đơn hàng (optional)",
            },
        },
        "required": ["shipping_address", "shipping_provider"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "confirmed", "denied", "error"],
                "description": "pending = chờ user xác nhận thanh toán",
            },
            "token": {
                "type": "string",
                "description": "HMAC confirmation token (khi status=pending)",
            },
            "order_id": {
                "type": "string",
                "description": "Mã đơn hàng (khi status=confirmed) — DB: order.order_id",
            },
            "total": {
                "type": "string",
                "description": "Tổng thanh toán dạng '$227.97' — computed từ orderitem",
            },
            "summary": {
                "type": "object",
                "properties": {
                    "items_count": {"type": "integer"},
                    "subtotal": {"type": "string", "description": "SUM item_cost từ orderitem"},
                    "shipping": {"type": "string", "description": "Từ shipping.shipping_cost_units/nanos"},
                    "total": {"type": "string", "description": "subtotal + shipping"},
                    "estimated_delivery": {"type": "string", "description": "Từ shipping quote (không lưu DB)"},
                },
                "description": "Tóm tắt đơn hàng trước khi xác nhận",
            },
        },
        "required": ["status"],
    },
    is_write=True,
    examples=[
        {
            "shipping_provider": "FastShip",
            "plan": [
                {"tool": "get_cart_tool", "args": {}},
                {"tool": "get_shipping_quote_tool", "args": {"zip_code": "70000"}},
                {
                    "tool": "checkout_tool",
                    "args": {
                        "shipping_address": $steps[0].shipping_address,
                        "shipping_provider": "FastShip",
                    },
                },
            ],
        },
    ],
    retry_config={"max_retries": 1},
)

**DB mapping:** INSERT INTO `accounting.order`(order_id), `accounting.orderitem`(product_id, quantity, item_cost_units/nanos), `accounting.shipping`(shipping_tracking_id, cost, address). Output `order_id` là primary key. `total` và `summary` computed từ orderitem + shipping. Không có `order_status` column — cần thêm migration nếu muốn tracking (hiện tại `order` table chỉ có `order_id`). `estimated_delivery` lấy từ quote response, không persist.

#### `get_order_status_tool`

Chỉ dùng field có sẵn trong DB. `order` table chỉ có `order_id` — không có status, carrier, timeline.

```python
_order_spec = ToolSpec(
    name="get_order_status_tool",
    description=(
        "Tra cứu đơn hàng đã đặt. "
        "Trả về danh sách sản phẩm, tổng tiền, tracking number (nếu đã giao cho ship)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "Mã đơn hàng",
            },
        },
        "required": ["order_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "not_found", "error"],
            },
            "order_id": {"type": "string", "description": "DB: accounting.order.order_id"},
            "total": {"type": "string", "description": "Computed: SUM(orderitem.item_cost_units/nanos)"},
            "tracking_number": {"type": "string", "description": "DB: shipping.shipping_tracking_id (nếu có)"},
            "shipping_address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                    "zip": {"type": "string"},
                    "country": {"type": "string"},
                },
                "description": "DB: shipping table",
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string", "description": "DB: orderitem.product_id"},
                        "name": {"type": "string", "description": "JOIN với products.name"},
                        "quantity": {"type": "integer", "description": "DB: orderitem.quantity"},
                        "price": {"type": "string", "description": "DB: orderitem.item_cost_units/nanos → format_price"},
                    },
                    "required": ["product_id", "name", "quantity", "price"],
                },
            },
        },
        "required": ["status", "order_id"],
    },
    is_write=False,
    examples=[
        {
            "order_id": "ORD-20240715-1234",
            "plan": [
                {"tool": "get_order_status_tool", "args": {"order_id": "ORD-20240715-1234"}},
            ],
        },
    ],
    retry_config={"max_retries": 2},
)
```

**DB mapping:** `accounting.order` (order_id), `accounting.orderitem` (product_id, quantity, item_cost_units/nanos), `accounting.shipping` (shipping_tracking_id, address). **Loại bỏ:** `order_status`, `carrier`, `estimated_delivery`, `items[].status`, `timeline` — không column nào tồn tại trong DB hiện tại.

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

Mỗi tool file tự đăng ký với `ToolSpec` (đã define ở trên) khi import:

```python
# tools/search/__init__.py
from tools.registry import ToolRegistry

# _search_spec được define ngay trong file này
ToolRegistry.register(_search_spec, fn=search_products_v2)
```

```python
# tools/cart_tool.py
from tools.registry import ToolRegistry

ToolRegistry.register(_add_cart_spec, fn=add_to_cart_tool)
```

Không cần import `ToolSpec` ở mỗi file — `ToolSpec` instances là global trong module đó.

#### Lợi ích

| Trước (TOOL_OUTPUT_SCHEMAS static) | Sau (ToolRegistry) |
|---|---|
| Schema hardcode trong dict | Mỗi tool tự đăng ký bằng `ToolSpec` |
| Thêm tool → sửa `tools/__init__.py` + prompt | Thêm tool → chỉ cần register — prompt tự cập nhật |
| Planner đọc từ global dict | Planner đọc `ToolRegistry.get_all_schemas_text()` |
| Không có input_schema → planner tự guess args | Input schema rõ ràng → planner biết chính xác args |
| Không có examples gắn với tool | Mỗi tool tự mang examples → few-shot chất lượng hơn |



### Price Normalization

Mọi tool output đều phải gộp `price_units` + `price_nanos` thành `price` string (được đảm bảo bởi `ToolExecutor._normalize_output`):

```python
# src/tools/_normalize.py

def format_price(units: int, nanos: int, currency: str = "USD") -> str:
    """
    DB stores price as (units BIGINT, nanos INT) = ($101, 960000000) → $101.96.
    nanos = 960_000_000 means 96 cents (nanos // 10_000_000).
    Truncate to 2 decimal places for display.
    """
    if currency == "USD":
        return f"${units}.{nanos // 10_000_000:02d}"
    return f"{units}.{nanos // 10_000_000:02d} {currency}"


def normalize_product(raw: dict) -> dict:
    """
    Map DB columns → API output.
    DB column name → output field:
      price_units (BIGINT) + price_nanos (INT) → price (string)
      picture (filename) → image (tool prepends CDN base URL)
      categories (comma-separated TEXT) → categories (array)
    """
    units = raw.get("price_units", 0) or raw.get("units", 0)
    nanos = raw.get("price_nanos", 0) or raw.get("nanos", 0)
    categories_raw = raw.get("categories", "")
    categories = categories_raw.split(",") if isinstance(categories_raw, str) else list(categories_raw)

    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "price": format_price(int(units), int(nanos)),
        "description": raw.get("description", ""),
        "image": raw.get("picture", ""),            # filename → image (API consumer ghép base URL)
        "categories": categories,                    # "telescopes,travel" → ["telescopes", "travel"]
    }


def normalize_cost(raw: dict) -> str:
    """Normalize shipping_cost_units + shipping_cost_nanos → price string."""
    units = raw.get("shipping_cost_units", 0)
    nanos = raw.get("shipping_cost_nanos", 0)
    currency = raw.get("shipping_cost_currency_code", "USD")
    return format_price(int(units), int(nanos), currency)
```

Không expose `price_units`, `price_nanos` hay `price_usd.units` trong output string.

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

```python
# graph/nodes/intent_parser.py

import re
import json
import logging
from typing import Optional

logger = logging.getLogger("graph.nodes.intent_parser")

# ── Rule patterns (đơn giản, zero-cost) ──
PATTERNS = {
    "cart_view":    re.compile(r"(?:xem|giỏ|cart|co.*giỏ)", re.IGNORECASE),
    "cart_add":     re.compile(r"(?:thêm|add|cho.*vào|bỏ.*vào)", re.IGNORECASE),
    "search":       re.compile(r"(?:tìm|search|kiếm|find)", re.IGNORECASE),
    "review":       re.compile(r"(?:review|đánh giá|nhận xét|sao)", re.IGNORECASE),
    "recommend":    re.compile(r"(?:gợi ý|recommend|suggest|tương tự)", re.IGNORECASE),
    "currency":     re.compile(r"(?:VND|JPY|EUR|đổi.*tiền|convert|giá.*VN)", re.IGNORECASE),
    "shipping":     re.compile(r"(?:ship|vận chuyển|giao.*hàng|phí.*ship)", re.IGNORECASE),
    "checkout":     re.compile(r"(?:thanh toán|checkout|mua|đặt.*hàng|order)", re.IGNORECASE),
    "greeting":     re.compile(r"^(?:hi|hello|chào|hey|ok|có.*giúp)", re.IGNORECASE),
}


class IntentParser:
    """
    Layer 1: Rule-based parser với LLM fallback.
    - Fast path: regex match → confidence ≥ 0.8 → dùng ngay.
    - Slow path: regex ambiguous → LLM classify (prompt ngắn, <100 tokens).
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from src.llm.llm import llm_model
            self._llm = llm_model
        return self._llm

    async def __call__(self, state) -> dict:
        t0 = time.monotonic_ns()
        user_query = self._get_user_query(state.get("messages", []))

        # Bước 1: Rule-based match
        intent_scores = {}
        entities = self._extract_entities_rule(user_query)

        for intent, pattern in PATTERNS.items():
            m = pattern.search(user_query)
            if m:
                intent_scores[intent] = 1.0 if m.group(0) == user_query.strip() else 0.8

        if intent_scores:
            best_intent = max(intent_scores, key=intent_scores.get)
            best_score = intent_scores[best_intent]
            if best_score >= 0.8:
                logger.info("[INTENT_PARSER] rule match | intent=%s | score=%.2f", best_intent, best_score)
                return {
                    "intent": best_intent,
                    "entities": entities,
                    "confidence": best_score,
                    "node_durations": {"IntentParser": _ms(t0)},
                }

        # Bước 2: LLM fallback (chỉ khi rule không đủ tự tin)
        llm = self._get_llm()
        prompt = (
            "Phân loại ý định người dùng từ câu sau. "
            "Chỉ trả về JSON: {\"intent\": \"...\", \"entities\": {...}, \"confidence\": 0.0-1.0}\n"
            f"Intents: {list(PATTERNS.keys())}\n"
            f"Query: {user_query}\n"
            f"History: {self._format_history(state.get('messages', []))}\n"
        )
        response = llm.invoke(prompt, temperature=0.0, max_tokens=200,
                              response_format={"type": "json_object"})
        result = json.loads(response.content)

        return {
            "intent": result.get("intent", "unknown"),
            "entities": {**entities, **result.get("entities", {})},
            "confidence": result.get("confidence", 0.5),
            "node_durations": {"IntentParser": _ms(t0)},
        }

    @staticmethod
    def _extract_entities_rule(query: str) -> dict:
        """Rule-based entity extraction: số lượng, price range, category."""
        entities = {}
        # Quantity: "2 cái", "3 tents"
        qty = re.search(r"(\d+)\s*(cái|chiếc|tents?|items?)", query, re.IGNORECASE)
        if qty:
            entities["quantity"] = int(qty.group(1))
        # Price range: "dưới $200", "under $200", "từ $50 tới $150"
        price_range = re.search(r"(?:dưới|under|<|nhỏ.*hơn)\s*\$?(\d+)", query, re.IGNORECASE)
        if price_range:
            entities["max_price"] = price_range.group(1)
        price_min = re.search(r"(?:trên|over|>|lớn.*hơn)\s*\$?(\d+)", query, re.IGNORECASE)
        if price_min:
            entities["min_price"] = price_min.group(1)
        return entities

    @staticmethod
    def _get_user_query(messages) -> str:
        if not messages:
            return ""
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)

    @staticmethod
    def _format_history(messages) -> str:
        return "; ".join(
            m.content[:100] for m in messages[-4:] if hasattr(m, "content")
        )
```

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

#### Implementation

```python
class TaskGraphBuilder:
    """
    LLM nhận intent + entities → sinh DAG plan.
    Chỉ chọn tool + nối edge — không fill argument.
    """

    TGB_PROMPT = """..."""  # Xem §11 (đã cập nhật)

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from src.llm.llm import llm_model
            self._llm = llm_model
        return self._llm

    async def __call__(self, state) -> dict:
        t0 = time.monotonic_ns()
        user_query = self._get_user_query(state.get("messages", []))
        intent = state.get("intent", "unknown")
        entities = state.get("entities", {})
        planner_memory = state.get("planner_memory", {})

        # Đọc schema động từ ToolRegistry
        from tools.registry import ToolRegistry

        llm = self._get_llm()
        prompt = self._build_tgb_prompt(
            user_query=user_query,
            intent=intent,
            entities=entities,
            planner_memory=planner_memory,
            registry=ToolRegistry,
        )

        response = llm.invoke(
            prompt,
            temperature=0.2,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        dag = self._parse_dag(response.content)

        # Validate: tool names trong registry + depends_on IDs tồn tại
        node_ids = {n["id"] for n in dag["nodes"]}
        for node in dag["nodes"]:
            assert ToolRegistry.get_spec(node["tool"]) is not None, \
                f"Unknown tool: {node['tool']}"
            for dep in node.get("depends_on", []):
                assert dep in node_ids, \
                    f"Node {node['id']} depends on {dep} — not found"
                assert dep != node["id"], \
                    f"Node {node['id']} self-reference"

        # Confidence check: nếu overall < threshold → không execute, hỏi user
        overall_confidence = sum(n.get("confidence", 0.5) for n in dag["nodes"]) / max(len(dag["nodes"]), 1)
        dag["overall_confidence"] = overall_confidence
        dag["current_goal"] = intent

        logger.info("[TGB] session=%s | intent=%s | nodes=%d | conf=%.2f",
                     state.get("session_id"), intent, len(dag["nodes"]), overall_confidence)

        return {
            "plan": dag,                     # DAGPlan — replaces list[PlanStep]
            "plan_step_index": 0,
            "current_goal": intent,
            "planner_reasoning": dag.get("reasoning", ""),
            "plan_confidence": overall_confidence,
            "node_durations": {"TaskGraphBuilder": _ms(t0)},
        }

    @staticmethod
    def _parse_dag(content: str) -> dict:
        """Parse LLM JSON output → DAGPlan."""
        data = json.loads(content) if isinstance(content, str) else content
        return {
            "nodes": data.get("nodes", []),
            "edges": data.get("edges", []),
            "reasoning": data.get("reasoning", ""),
            "overall_confidence": data.get("overall_confidence", 0.5),
        }

    @staticmethod
    def _get_user_query(messages) -> str:
        if not messages:
            return ""
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)

    def _build_tgb_prompt(self, user_query, intent, entities, planner_memory, registry):
        """Build prompt với schema động từ ToolRegistry."""
        schemas_text = registry.get_all_schemas_text()
        memory_text = self._format_memory(planner_memory)

        return TGB_PROMPT.format(
            tool_schemas_text=schemas_text,
            user_query=user_query,
            intent=intent,
            entities=json.dumps(entities, ensure_ascii=False),
            planner_memory=memory_text,
        )

    @staticmethod
    def _format_memory(memory: dict) -> str:
        if not memory:
            return "(không có dữ liệu phiên trước)"
        parts = []
        if "last_search" in memory:
            parts.append(f"Tìm kiếm gần đây: {memory['last_search']}")
        if "current_cart_items" in memory:
            parts.append(f"Sản phẩm trong giỏ: {len(memory['current_cart_items'])}")
        if "last_product_id" in memory:
            parts.append(f"Product ID gần đây: {memory['last_product_id']}")
        return "; ".join(parts) if parts else "(không có dữ liệu phiên trước)"
```

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

```python
# graph/nodes/tool_executor.py

import re
import json
import asyncio
import logging
from collections import defaultdict
from typing import Optional

import grpc

from tools.registry import ToolRegistry
from guardrails.tool_validator import validate_tool_call
from guardrails.fallback import with_fallback
from memory.store import cache_store

logger = logging.getLogger("graph.nodes.tool_executor")

WRITE_TOOLS = frozenset({"add_to_cart_tool"})

# ── Variable reference patterns ──
STEPS_REF = re.compile(r"^\$steps\[([a-zA-Z_]\w*)\]\.(.+)$")           # $steps[node_id].path
SESSION_REF = re.compile(r"^\$session\.(.+)$")
INPUT_REF = re.compile(r"^\$input\.entities\.(.+)$")
MEMORY_REF = re.compile(r"^\$memory\.(.+)$")
FIRST_HELPER = re.compile(r"^\$first\(steps\[([a-zA-Z_]\w*)\]\.(.+),\s*default=(.+)\)$")
EXISTS_HELPER = re.compile(r"^\$exists\(steps\[([a-zA-Z_]\w*)\]\.(.+)\)$")
SAFE_INDEX_HELPER = re.compile(
    r"^\$safe_index\(steps\[([a-zA-Z_]\w*)\]\.(.+),\s*(\d+),\s*default=(.+)\)$"
)


class ToolExecutor:
    """
    DAG-based tool executor. Chạy node theo topological order,
    song song các node không có dependency.
    """

    MAX_RETRIES = {
        "search_products_v2": 2,
        "get_product_reviews_tool": 1,
        "get_recommendations_tool": 1,
        "convert_currency_tool": 2,
        "get_shipping_quote_tool": 2,
        "get_cart_tool": 1,
        "add_to_cart_tool": 1,
    }

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()
        dag = state.get("plan", {})
        nodes = dag.get("nodes", [])
        if not nodes:
            return {"node_durations": {"ToolExecutor": _ms(t0)}}

        node_map = {n["id"]: n for n in nodes}
        done: set[str] = set()
        node_outputs: dict[str, dict] = {}
        errors: dict[str, str] = {}

        # Build dependency graph
        in_degree: dict[str, set[str]] = {}
        for n in nodes:
            nid = n["id"]
            in_degree[nid] = set(n.get("depends_on", []))

        while len(done) < len(nodes):
            # Tìm node ready (all dependencies done)
            ready_ids = [
                nid for nid in in_degree
                if nid not in done and in_degree[nid].issubset(done)
            ]
            if not ready_ids:
                # Deadlock
                logger.error("[TOOL_EXECUTOR] Deadlock detected | done=%s", done)
                break

            # Chạy song song các node ready
            coros = [
                self._execute_node(
                    node_map[nid], node_outputs, node_map, state, errors
                )
                for nid in ready_ids
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for nid, result in zip(ready_ids, results):
                if isinstance(result, Exception):
                    errors[nid] = str(result)
                    logger.error("[TOOL_EXECUTOR] node=%s exception=%s", nid, result)
                    done.add(nid)
                    continue
                if result is None:
                    done.add(nid)
                    continue

                result_data, node_status = result

                # Conditional branching
                node = node_map[nid]
                if node.get("condition"):
                    branch = self._evaluate_condition(result_data, node["condition"])
                    if branch == "ask_user":
                        return {
                            "tool_results": node_outputs,
                            "errors": errors,
                            "pending_action": {
                                "action": "ask_user",
                                "node_id": nid,
                                "message": node["condition"].get("ask_message",
                                    "Tôi cần bạn xác nhận thêm thông tin."),
                            },
                        }
                    elif branch == "stop":
                        done.add(nid)
                        continue

                done.add(nid)
                node_outputs[nid] = result_data

        return {
            "tool_results": node_outputs,
            "errors": errors,
            "node_durations": {"ToolExecutor": _ms(t0)},
        }

    async def _execute_node(
        self,
        node: dict,
        node_outputs: dict[str, dict],
        node_map: dict[str, dict],
        state: "ShoppingState",
        errors: dict[str, str],
    ):
        tool_name = node["tool"]
        nid = node["id"]
        raw_args = node.get("args", {})

        # 1. Resolve variable references với helpers an toàn
        resolved_args = self._resolve_args(raw_args, node_outputs, state)
        if resolved_args is None:
            logger.warning("[TOOL_EXECUTOR] %s args resolve failed", nid)
            return None

        # 2. L3 Validate
        validation = validate_tool_call(tool_name, resolved_args, state.user_id)
        if not validation.is_valid:
            logger.warning("[TOOL_EXECUTOR] %s L3 blocked: %s", nid, validation.blocked_reason)
            errors[nid] = validation.blocked_reason
            return None

        # 3. Cache check (read-only)
        if tool_name not in WRITE_TOOLS:
            cache_key = (tool_name, str(resolved_args))
            cached = cache_store.get(*cache_key)
            if cached is not None:
                return (json.loads(cached), "cached")

        # 4. Execute tool with retry
        raw = await self._execute_with_retry(tool_name, resolved_args)
        if raw is None:
            errors[nid] = f"{tool_name} failed after retries"
            return None

        # 5. Normalize output
        normalized = self._normalize_output(tool_name, raw)
        parsed = json.loads(normalized) if isinstance(normalized, str) else normalized

        # 6. Cache set (read-only)
        if tool_name not in WRITE_TOOLS:
            cache_store.set(*cache_key, normalized)

        return (parsed, "grpc")

    # ──────────────────────────────────────────────────────────────
    # 8.2 Variable Reference Resolver (với helpers an toàn)
    # ──────────────────────────────────────────────────────────────

    def _resolve_args(self, args: dict, node_outputs: dict, state: "ShoppingState") -> Optional[dict]:
        resolved = {}
        for key, value in args.items():
            resolved[key] = self._resolve_value(value, node_outputs, state)
            if resolved[key] is None and self._is_ref(value):
                logger.warning("[RESOLVE] arg '%s' = '%s' → None", key, value)
                return None
        return resolved

    def _resolve_value(self, value, node_outputs: dict, state: "ShoppingState"):
        if isinstance(value, dict):
            return {k: self._resolve_value(v, node_outputs, state) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(v, node_outputs, state) for v in value]
        if not isinstance(value, str):
            return value

        # Helper: $first(steps[nid].path, default=val)
        m = FIRST_HELPER.match(value)
        if m:
            nid, path, default = m.group(1), m.group(2), m.group(3)
            if nid not in node_outputs:
                return self._parse_default(default)
            val = self._get_by_path(node_outputs[nid], path)
            if val is None or (isinstance(val, list) and len(val) == 0):
                return self._parse_default(default)
            return val[0] if isinstance(val, list) else val

        # Helper: $exists(steps[nid].path)
        m = EXISTS_HELPER.match(value)
        if m:
            nid, path = m.group(1), m.group(2)
            if nid not in node_outputs:
                return False
            return self._get_by_path(node_outputs[nid], path) is not None

        # Helper: $safe_index(steps[nid].path, idx, default=val)
        m = SAFE_INDEX_HELPER.match(value)
        if m:
            nid, path, idx, default = m.group(1), m.group(2), int(m.group(3)), m.group(4)
            if nid not in node_outputs:
                return self._parse_default(default)
            arr = self._get_by_path(node_outputs[nid], path)
            if not isinstance(arr, (list, tuple)) or idx >= len(arr):
                return self._parse_default(default)
            return arr[idx]

        # $steps[node_id].path
        m = STEPS_REF.match(value)
        if m:
            nid, path = m.group(1), m.group(2)
            if nid not in node_outputs:
                logger.error("[RESOLVE] node %s not executed yet", nid)
                return None
            return self._get_by_path(node_outputs[nid], path)

        # $session.*
        m = SESSION_REF.match(value)
        if m:
            return state.get(m.group(1)) or state.get("user_id", "")

        # $input.entities.*
        m = INPUT_REF.match(value)
        if m:
            return state.get("entities", {}).get(m.group(1))

        # $memory.*
        m = MEMORY_REF.match(value)
        if m:
            return state.get("planner_memory", {}).get(m.group(1))

        return value

    @staticmethod
    def _parse_default(default_str: str):
        """Parse default value từ syntax helper."""
        if default_str == "null" or default_str == "None":
            return None
        if default_str == "true":
            return True
        if default_str == "false":
            return False
        try:
            return int(default_str)
        except ValueError:
            pass
        try:
            return float(default_str)
        except ValueError:
            pass
        return default_str

    @staticmethod
    def _is_ref(value) -> bool:
        return isinstance(value, str) and value.startswith("$")

    @staticmethod
    def _get_by_path(data: dict, path: str):
        parts = re.split(r"\.(?![^\[]*\])", path)
        current = data
        for part in parts:
            array_match = re.match(r"^(\w+)\[(\d+)\]$", part)
            if array_match:
                key = array_match.group(1)
                idx = int(array_match.group(2))
                if isinstance(current, dict) and key in current:
                    arr = current[key]
                    if isinstance(arr, (list, tuple)) and idx < len(arr):
                        current = arr[idx]
                    else:
                        return None
                else:
                    return None
            else:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                    if isinstance(current, (list, tuple)) and len(current) > 0:
                        current = current[0]
                else:
                    return None
        return current

    # ──────────────────────────────────────────────────────────────
    # 8.3 Conditional Branching
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _evaluate_condition(result: dict, condition: dict) -> str:
        """
        Evaluate conditional branching dựa trên result của node.
        Condition format:
          {"on": "result.count", "==0": "ask_user", ">1": "ask_choose", "default": "continue"}
        """
        on_path = condition.get("on", "")
        actual = ToolExecutor._get_by_path(result, on_path)

        for cond_key, action in condition.items():
            if cond_key in ("on", "default"):
                continue
            if ToolExecutor._eval_single_cond(actual, cond_key):
                return action

        return condition.get("default", "continue")

    @staticmethod
    def _eval_single_cond(actual, cond_key: str) -> bool:
        """Evaluate 1 condition key like '==0', '>1', '!=null'."""
        if cond_key.startswith("=="):
            expected = cond_key[2:]
            try:
                return float(actual) == float(expected)
            except (ValueError, TypeError):
                return str(actual) == expected
        if cond_key.startswith("!="):
            expected = cond_key[2:]
            try:
                return float(actual) != float(expected)
            except (ValueError, TypeError):
                return str(actual) != expected
        if cond_key.startswith(">"):
            try:
                return float(actual) > float(cond_key[1:])
            except (ValueError, TypeError):
                return False
        if cond_key.startswith("<"):
            try:
                return float(actual) < float(cond_key[1:])
            except (ValueError, TypeError):
                return False
        if cond_key == "null":
            return actual is None
        if cond_key == "not_null":
            return actual is not None
        return False

    # ──────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────

    async def _execute_with_retry(self, tool_name: str, args: dict) -> Optional[str]:
        max_retries = self.MAX_RETRIES.get(tool_name, 1)
        for attempt in range(max_retries):
            try:
                tool_fn = ToolRegistry.get_fn(tool_name)
                if tool_fn is None:
                    logger.error("[TOOL_EXECUTOR] %s not in registry", tool_name)
                    return None
                return await tool_fn.ainvoke(args)
            except (grpc.RpcError, Exception) as e:
                if attempt == max_retries - 1:
                    logger.error("[TOOL_EXECUTOR] %s failed after %d retries: %s",
                                 tool_name, max_retries, str(e)[:200])
                    return None
                await asyncio.sleep(0.5 * (attempt + 1))
        return None

    def _normalize_output(self, tool_name: str, raw: str) -> str:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return raw
        if tool_name == "search_products_v2" and "products" in data:
            data["products"] = [normalize_product(p) for p in data["products"]]
        elif tool_name == "get_cart_tool" and "items" in data:
            data["items"] = [normalize_product(i) for i in data["items"]]
        return json.dumps(data, ensure_ascii=False)


def normalize_product(raw: dict) -> dict:
    from src.tools._normalize import format_price
    units = raw.get("price_units", 0) or raw.get("units", 0)
    nanos = raw.get("price_nanos", 0) or raw.get("nanos", 0)
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "price": format_price(int(units), int(nanos)),
        "description": raw.get("description", ""),
        "categories": raw.get("categories", []),
    }
```

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

### Implementation

```python
# graph/nodes/reflection.py

import json
import logging

logger = logging.getLogger("graph.nodes.reflection")

REPLAN_TRIGGERS = {
    "zero_result": {"max_count": 1},       # Allow 1 zero before replan
    "tool_error": {"max_count": 2},
    "low_confidence": {"threshold": 0.5},
}


class Reflection:
    """
    Post-execution check. Quyết định pass / replan dựa trên tool_results.
    """

    REPLAN_COUNT_KEY = "replan_count"

    async def __call__(self, state) -> dict:
        t0 = time.monotonic_ns()
        tool_results = state.get("tool_results", {})
        errors = state.get("errors", {})
        plan_confidence = state.get("plan_confidence", 1.0)
        replan_count = state.get("replan_count", 0)

        issues = []

        # Trigger 1: Zero result
        for nid, result in tool_results.items():
            if isinstance(result, dict):
                total = result.get("total", -1)
                if total == 0:
                    issues.append({"type": "zero_result", "node": nid})
                products = result.get("products", result.get("items", []))
                if isinstance(products, list) and len(products) == 0:
                    total_field = result.get("total", 0)
                    if total_field != 0:
                        pass  # Có other fields, not zero
                    else:
                        issues.append({"type": "zero_result", "node": nid, "detail": "empty list"})

        # Trigger 2: Tool errors
        error_count = len(errors)
        if error_count >= REPLAN_TRIGGERS["tool_error"]["max_count"]:
            issues.append({"type": "tool_error", "count": error_count})

        # Trigger 3: Low confidence
        if plan_confidence < REPLAN_TRIGGERS["low_confidence"]["threshold"]:
            issues.append({"type": "low_confidence", "score": plan_confidence})

        # Trigger 4: Semantic hallucination
        if state.get("semantic_hallucination_detected"):
            issues.append({"type": "semantic_hallucination", "detail": "gate rejected claim"})

        if not issues:
            logger.info("[REFLECTION] PASS | no issues | errors=%d", error_count)
            return {
                "reflection_result": "pass",
                "replan_count": replan_count,
                "node_durations": {"Reflection": _ms(t0)},
            }

        # Check replan limit
        if replan_count >= 2:
            logger.warning("[REFLECTION] replan limit reached | count=%d", replan_count)
            return {
                "reflection_result": "pass",  # Force pass, không replan nữa
                "replan_count": replan_count,
                "reflection_issues": issues,
                "node_durations": {"Reflection": _ms(t0)},
            }

        logger.info("[REFLECTION] REPLAN | issues=%s", json.dumps(issues))
        return {
            "reflection_result": "replan",
            "replan_count": replan_count + 1,
            "reflection_issues": issues,
            "node_durations": {"Reflection": _ms(t0)},
        }
```

### Graph edges với Reflection

```python
# graph/main_graph.py — Reflection edges

# ToolExecutor → Reflection
builder.add_edge("tool_executor", "reflection")

# Reflection → conditional
builder.add_conditional_edges(
    "reflection",
    route_after_reflection,
    {
        "pass": "response_verifier",
        "replan": "task_graph_builder",  # partial replan
    },
)

# graph/edges.py
def route_after_reflection(state) -> str:
    return state.get("reflection_result", "pass")
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

Khi user confirm, graph resume từ checkpoint:

```python
# ToolExecutor Loop — resume logic
if state.get("confirmed") and state.pending_action:
    action = state.pending_action
    # Execute actual gRPC call
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    stub.AddItem(demo_pb2.AddItemRequest(
        user_id=action["params"]["user_id"],
        item=demo_pb2.CartItem(
            product_id=action["params"]["product_id"],
            quantity=action["params"]["quantity"],
        ),
    ))
    state.pending_action = None
    state.tool_results["confirmed"] = {"result": "success"}
```

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

### Selection Logic

```python
def select_response_strategy(tool_results: dict, user_query: str) -> dict:
    """
    Chọn strategy: template hay LLM dựa trên tool types và complexity.
    Returns: {"strategy": "template" | "llm", "template_key": str | None}
    """
    tool_types = set()
    for call_id in tool_results:
        for known in ["get_cart_tool", "get_shipping_quote_tool",
                       "convert_currency_tool", "get_product_reviews_tool",
                       "search_products_v2", "add_to_cart_tool",
                       "get_recommendations_tool"]:
            if known in call_id:
                tool_types.add(known)

    # Deterministic paths → luôn template
    if tool_types == {"get_cart_tool"}:
        return {"strategy": "template", "template_key": "cart"}
    if tool_types == {"get_shipping_quote_tool"}:
        return {"strategy": "template", "template_key": "shipping"}
    if tool_types == {"convert_currency_tool"}:
        return {"strategy": "template", "template_key": "currency"}
    if tool_types == {"get_product_reviews_tool"}:
        return {"strategy": "template", "template_key": "reviews"}

    # Search: single + ≤3 items → template, else → LLM
    if tool_types == {"search_products_v2"}:
        data = _first_result(tool_results)
        total = data.get("total", 0)
        if total <= 3 and total > 0:
            return {"strategy": "template", "template_key": "search_single"}
        return {"strategy": "llm"}

    # Multi-tool: complexity decides
    complexity = compute_complexity(user_query, tool_results)
    if complexity > 0.5:
        return {"strategy": "llm"}
    return {"strategy": "template", "template_key": "multi"}
```

### Complexity Scoring (cho path dùng LLM)

```python
def compute_complexity(user_query: str, tool_results: dict) -> float:
    """
    Tính complexity score 0.0 → 1.0.
    Chỉ dùng cho path cần LLM (template path không cần tính).
    """
    score = 0.0
    
    # Factor 1: Query length
    word_count = len(user_query.split())
    if word_count > 20: score += 0.2
    elif word_count > 10: score += 0.1
    
    # Factor 2: Số tool được gọi
    tool_count = len(tool_results)
    score += min(tool_count * 0.1, 0.3)
    
    # Factor 3: Result size
    total_items = sum(
        len(r.get("products", [])) +
        len(r.get("reviews", [])) +
        len(r.get("items", []))
        for r in tool_results.values() if isinstance(r, dict)
    )
    if total_items > 10: score += 0.2
    elif total_items > 5: score += 0.1
    
    # Factor 4: Write action
    if any("pending" in str(r) for r in tool_results.values()):
        score += 0.1
    
    return min(score, 1.0)


def select_temperature(complexity: float) -> float:
    if complexity < 0.2: return 0.1
    if complexity < 0.5: return 0.3
    if complexity < 0.8: return 0.4
    return 0.6
```

### Implementation

```python
# graph/nodes/response_verifier.py

class ResponseVerifier:
    """
    Tạo câu trả lời từ tool results + user query.
    Temperature động dựa trên complexity.
    """

    VERIFIER_PROMPT = """..."""  # Xem §11

    def _get_llm(self):
        if self._llm is None:
            from src.llm.llm import llm_model
            self._llm = llm_model
        return self._llm

    async def __call__(self, state: ShoppingState) -> dict:
        t0 = time.monotonic_ns()
        user_query = self._get_user_query(state.get("messages", []))
        tool_results = state.get("tool_results", {})
        entities = state.get("entities", {})

        # Compute complexity → temperature
        complexity = compute_complexity(user_query, tool_results)
        temperature = select_temperature(complexity)

        # Build prompt
        prompt = self._build_verifier_prompt(
            user_query=user_query,
            tool_results=tool_results,
            entities=entities,
        )

        # Invoke LLM
        llm = self._get_llm()
        response = llm.invoke(prompt, temperature=temperature, max_tokens=1024)
        answer = response.content.strip() if response.content else ""

        # Verify: check answer claims vs tool_results
        # (future: cross-check PII, hallucination)

        logger.info(
            "[VERIFIER] complexity=%.2f | temp=%.1f | answer=%d chars",
            complexity, temperature, len(answer)
        )

        return {
            "final_answer": answer,
            "node_durations": {"ResponseVerifier": _ms(t0)},
        }
```

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

### Groundedness Score

```python
# hallucination_guard.py

import re
import json
import logging
from typing import Optional

logger = logging.getLogger("graph.nodes.hallucination_guard")

GROUNDEDNESS_THRESHOLD = 0.8  # configurable

# ── Regex patterns ──
PRICE_RE = re.compile(r'\$\d+(?:\.\d{2})?')
COUNT_RE = re.compile(r'(\d+)\s*(sản phẩm|kết quả|đánh giá|món|items?|products?)', re.IGNORECASE)
SCORE_RE = re.compile(r'(\d+\.?\d*)\s*[/\/]\s*5|(\d+\.?\d*)\s*sao', re.IGNORECASE)
CONFIRM_ACTION_RE = re.compile(r'(đã thêm|đã xoá|đã cập nhật|đã hủy)', re.IGNORECASE)


class GroundingResult:
    def __init__(self, score: float, total: int, violations: list):
        self.score = score
        self.total_claims = total
        self.violations = violations
        self.is_grounded = score >= GROUNDEDNESS_THRESHOLD or total == 0


class HallucinationGuard:
    """
    Rule-based fact-checking: đối chiếu từng claim trong answer với tool_results.
    Không gọi LLM — zero cost, <3ms latency.
    """

    async def __call__(self, state) -> dict:
        t0 = time.monotonic_ns()
        answer = state.get("final_answer", "")
        tool_results = state.get("tool_results", {})
        pending_action = state.get("pending_action")

        if not answer or not tool_results:
            return {"node_durations": {"HallucinationGuard": _ms(t0)}}

        result = self._check_groundedness(answer, tool_results, pending_action)

        if result.is_grounded:
            logger.info(
                "[HALLUCINATION_GUARD] PASS | score=%.2f | claims=%d",
                result.score, result.total_claims,
            )
            return {
                "groundedness_score": result.score,
                "node_durations": {"HallucinationGuard": _ms(t0)},
            }

        # Hallucination detected → fallback
        logger.warning(
            "[HALLUCINATION_GUARD] FAIL | score=%.2f | violations=%s",
            result.score, result.violations,
        )
        return {
            "groundedness_score": result.score,
            "hallucination_detected": True,
            "final_answer": None,  # signal FallbackGenerator
            "node_durations": {"HallucinationGuard": _ms(t0)},
        }

    # ── Weight penalties per violation type ──
    PENALTY = {
        "price": 0.15,
        "entity": 0.40,
        "entity_zero_result": 0.50,
        "count": 0.15,
        "score": 0.15,
        "action": 0.15,
        "semantic": 0.25,      # Attribute claim không grounded
    }

    # ── Semantic claim patterns ──
    SEMANTIC_CLAIM_PATTERNS = [
        re.compile(r'(?:phù hợp|dành cho|thích hợp)\s+(.+?)(?:,|\.|$)', re.IGNORECASE),
        re.compile(r'(?:chất liệu|làm từ|bằng)\s+(.+?)(?:,|\.|$)', re.IGNORECASE),
        re.compile(r'(?:tính năng|có|sở hữu|được trang bị)\s+(.+?)(?:,|\.|$)', re.IGNORECASE),
        re.compile(r'(?:nặng|nhẹ|cân nặng|trọng lượng)\s+(.+?)(?:,|\.|$)', re.IGNORECASE),
        re.compile(r'(?:màu|có màu|màu sắc)\s+(.+?)(?:,|\.|$)', re.IGNORECASE),
        re.compile(r'(?:công dụng|dùng để|sử dụng cho)\s+(.+?)(?:,|\.|$)', re.IGNORECASE),
    ]

    def _check_groundedness(
        self, answer: str, tool_results: dict, pending_action: Optional[dict],
    ) -> GroundingResult:
        violations = []

        # ── Price check ──
        answer_prices = set(PRICE_RE.findall(answer))
        actual_prices = self._extract_prices(tool_results)
        for p in answer_prices:
            if p not in actual_prices:
                violations.append({"type": "price", "claim": p, "actual": list(actual_prices)})

        # ── Entity Grounding check ──
        known_products, known_categories, any_zero_total = self._extract_known_entities(tool_results)
        noun_phrases = self._extract_noun_phrases(answer, known_products, known_categories)
        for phrase, is_known in noun_phrases:
            if not is_known:
                if any_zero_total and len(known_products) == 0:
                    # Zero-result: mọi entity mention đều violation nặng
                    violations.append({
                        "type": "entity_zero_result",
                        "claim": phrase,
                        "reason": "Không có kết quả tìm kiếm nhưng answer vẫn đề cập sản phẩm",
                    })
                else:
                    violations.append({
                        "type": "entity",
                        "claim": phrase,
                        "reason": "Không tồn tại trong kho dữ liệu",
                    })

        # ── Count check ──
        for match in COUNT_RE.finditer(answer):
            claimed_num = int(match.group(1))
            actual_num = self._infer_count(match.group(2), tool_results)
            if actual_num is not None and claimed_num != actual_num:
                violations.append({
                    "type": "count",
                    "claim": f"{claimed_num} {match.group(2)}",
                    "actual": actual_num,
                })

        # ── Score check ──
        for match in SCORE_RE.finditer(answer):
            claimed_score = float(match.group(1) or match.group(2))
            actual_score = self._extract_avg_score(tool_results)
            if actual_score is not None and abs(claimed_score - actual_score) > 0.1:
                violations.append({
                    "type": "score",
                    "claim": claimed_score,
                    "actual": actual_score,
                })

        # ── Action confirm check ──
        if CONFIRM_ACTION_RE.search(answer):
            is_confirmed = (
                pending_action is None
                and tool_results.get("confirmed")
            )
            if not is_confirmed:
                violations.append({
                    "type": "action",
                    "claim": "Hành động chưa confirm nhưng answer nói đã thực hiện",
                })

        # ── Semantic attribute claim check ──
        description_text = self._extract_descriptions(tool_results)
        for pattern in self.SEMANTIC_CLAIM_PATTERNS:
            for match in pattern.finditer(answer):
                claim = match.group(0)
                # Nếu claim attribute không xuất hiện trong description của bất kỳ product nào
                if description_text and claim.lower() not in description_text:
                    violations.append({
                        "type": "semantic",
                        "claim": claim.strip(),
                        "reason": "Attribute claim không có trong product description",
                    })

        # ── Weighted groundedness score ──
        score = 1.0
        for v in violations:
            penalty = self.PENALTY.get(v["type"], 0.15)
            score -= penalty
        score = max(score, 0.0)  # clamped [0, 1]

        total_claims = len(violations)  # for logging only
        return GroundingResult(score=score, total=total_claims, violations=violations)

    # ──────────────────────────────────────────────────────────────
    # Entity Grounding
    # ──────────────────────────────────────────────────────────────

    def _extract_known_entities(self, tool_results: dict) -> tuple[set, set, bool]:
        """
        Trích xuất danh sách tên sản phẩm + category đã biết từ tool_results.
        Returns: (known_products, known_categories, any_zero_total)
        """
        known_products: set[str] = set()
        known_categories: set[str] = set()
        any_zero_total = False

        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(data, dict):
                continue

            # Total = 0?
            if data.get("total") == 0:
                any_zero_total = True

            # Products / items
            for p in data.get("products", []) + data.get("items", []):
                name = p.get("name", "").lower().strip()
                if name:
                    known_products.add(name)

                for cat in p.get("categories", []):
                    c = cat.lower().strip()
                    if c:
                        known_categories.add(c)

            # Categories list riêng (search category view)
            for cat in data.get("categories", []):
                c = cat.lower().strip()
                if c:
                    known_categories.add(c)

        return known_products, known_categories, any_zero_total

    @staticmethod
    def _extract_noun_phrases(
        answer: str, known_products: set, known_categories: set,
    ) -> list[tuple[str, bool]]:
        """
        Tách câu trả lời thành các noun phrase tiềm năng.
        Trả về list (phrase, is_known) — is_known=True nếu phrase
        tồn tại trong known_products hoặc known_categories.

        Strategy: lấy các token viết hoa (danh từ riêng) + bigram
        xuất hiện trong known set.
        """
        import re

        results: list[tuple[str, bool]] = []
        seen = set()

        # Strategy 1: Token viết hoa (Potential product name)
        # VD: "Tôi thấy Telescope rất tốt" → "Telescope"
        capitalized = re.findall(r'\b[A-ZÀ-Ỹ][a-zà-ỹ]+\b', answer)
        for token in capitalized:
            t = token.lower().strip()
            if t not in seen and len(t) > 2:
                seen.add(t)
                is_known = t in known_products or t in known_categories
                results.append((token, is_known))

        # Strategy 2: Bigram xuất hiện trong known set
        # VD: "Camping Stove" là 2 từ nhưng là 1 entity
        words = re.findall(r'\b[a-zA-ZÀ-ỹà-ỹ]+\b', answer)
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}".lower().strip()
            if bigram not in seen and len(bigram) > 3:
                seen.add(bigram)
                if bigram in known_products or bigram in known_categories:
                    results.append((f"{words[i]} {words[i+1]}", True))

        # Strategy 3: Nếu có danh mục trong known, check answer có nhắc tới không
        for cat in known_categories:
            if cat in answer.lower() and cat not in seen:
                seen.add(cat)
                results.append((cat, True))

        return results

    def _extract_prices(self, tool_results: dict) -> set:
        prices = set()
        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(data, dict):
                for product in data.get("products", []) + data.get("items", []):
                    price_str = product.get("price", "")
                    if price_str:
                        prices.add(price_str)
                if "total" in data:
                    prices.add(data["total"])
        return prices

    def _infer_count(self, keyword: str, tool_results: dict) -> Optional[int]:
        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(data, dict):
                if "sản phẩm" in keyword.lower() or "product" in keyword.lower():
                    if "total" in data:
                        return data["total"]
                    if "products" in data:
                        return len(data["products"])
                if "đánh giá" in keyword.lower() or "review" in keyword.lower():
                    if "reviews" in data:
                        return len(data["reviews"])
                if "món" in keyword.lower() or "item" in keyword.lower():
                    if "items" in data:
                        return len(data["items"])
        return None

    def _extract_avg_score(self, tool_results: dict) -> Optional[float]:
        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(data, dict) and "average_score" in data:
                try:
                    return float(data["average_score"])
                except (ValueError, TypeError):
                    pass
        return None

    @staticmethod
    def _extract_descriptions(tool_results: dict) -> str:
        """Gộp tất cả description từ tool results để semantic check."""
        texts = []
        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(data, dict):
                for product in data.get("products", []) + data.get("items", []):
                    desc = product.get("description", "")
                    if desc:
                        texts.append(desc.lower())
                    name = product.get("name", "")
                    if name:
                        texts.append(name.lower())
        return " ".join(texts)
```

### FallbackGenerator

Khi groundedness < 80%, FallbackGenerator dùng **template** thay vì LLM để tạo câu trả lời — đảm bảo 100% grounded vì template lấy dữ liệu trực tiếp từ `tool_results`.

Nguyên tắc:
- **Không technical terms**: không JSON, không error raw, không tool name
- **Tiếng Việt tự nhiên**: câu văn thông thường, có ngữ điệu
- **Grounded**: mọi số liệu đều từ tool_results

```python
# graph/nodes/fallback_generator.py

class FallbackGenerator:
    """
    Sinh câu trả lời từ template khi HallucinationGuard detect hallucination.
    Không gọi LLM — zero cost, <1ms.

    Mỗi tool type có 3-4 biến thể template — random chọn để tránh robotic.
    """

    async def __call__(self, state) -> dict:
        t0 = time.monotonic_ns()
        tool_results = state.get("tool_results", {})
        pending_action = state.get("pending_action")

        # Xác định tool type từ tool_results keys
        tool_types = self._detect_tool_types(tool_results)

        if pending_action and pending_action.get("status") == "pending":
            # Write tool pending — dùng template confirm
            answer = self._template_confirm(pending_action)
        elif len(tool_types) == 1:
            # Single tool — dùng template tương ứng
            answer = self._template_single(tool_types[0], tool_results)
        else:
            # Multi tool — dùng template tổng hợp
            answer = self._template_multi(tool_types, tool_results)

        logger.info(
            "[FALLBACK_GENERATOR] tools=%s | answer=%d chars",
            tool_types, len(answer),
        )

        return {
            "final_answer": answer,
            "fallback_used": True,
            "node_durations": {"FallbackGenerator": _ms(t0)},
        }

    def _detect_tool_types(self, tool_results: dict) -> list[str]:
        types = set()
        for call_id in tool_results:
            for known_type in [
                "search_products_v2", "get_cart_tool",
                "get_product_reviews_tool", "get_recommendations_tool",
                "convert_currency_tool", "get_shipping_quote_tool",
                "add_to_cart_tool",
            ]:
                if known_type in call_id:
                    types.add(known_type)
        return list(types)

    # ── Templates ──

    def _get_products(self, tool_results: dict) -> list:
        """Lấy danh sách sản phẩm từ tool_results (đã normalized)."""
        products = []
        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(data, dict):
                for p in data.get("products", []) + data.get("items", []):
                    name = p.get("name", "")
                    price = p.get("price", "")
                    products.append(f"{name} ({price})" if price else name)
        return products

    def _template_single(self, tool_type: str, tool_results: dict) -> str:
        import random
        products = self._get_products(tool_results)
        tool_data = self._first_result(tool_results)

        if tool_type == "search_products_v2":
            n = tool_data.get("total", len(products))
            if n == 0:
                return random.choice([
                    "Tôi không tìm thấy sản phẩm nào phù hợp với yêu cầu của bạn.",
                    "Rất tiếc, không có sản phẩm nào khớp với những gì bạn cần.",
                    "Hiện tại chưa tìm thấy sản phẩm bạn muốn. Bạn thử tìm bằng từ khóa khác nhé?",
                ])
            product_list = ", ".join(products[:5])
            if n > 5:
                return random.choice([
                    f"Tôi tìm thấy {n} sản phẩm phù hợp, trong đó có {product_list}. Bạn muốn xem thêm sản phẩm nào không?",
                    f"Có {n} sản phẩm đáp ứng yêu cầu của bạn, ví dụ: {product_list}. Bạn quan tâm đến sản phẩm nào?",
                ])
            return random.choice([
                f"Tôi tìm thấy {n} sản phẩm: {product_list}.",
                f"Đây là {n} sản phẩm tôi tìm được: {product_list}.",
            ])

        if tool_type == "get_cart_tool":
            if not products:
                return random.choice([
                    "Giỏ hàng của bạn hiện đang trống.",
                    "Bạn chưa có sản phẩm nào trong giỏ hàng.",
                ])
            items_text = ", ".join(products)
            total = tool_data.get("total", "")
            if total:
                return random.choice([
                    f"Giỏ hàng của bạn có {len(products)} món: {items_text}. Tổng cộng {total}.",
                    f"Bạn đang có {len(products)} sản phẩm trong giỏ: {items_text}. Tạm tính {total}.",
                ])
            return random.choice([
                f"Giỏ hàng của bạn có {len(products)} món: {items_text}.",
                f"Trong giỏ có {len(products)} sản phẩm: {items_text}.",
            ])

        if tool_type == "get_product_reviews_tool":
            reviews = tool_data.get("reviews", [])
            avg = tool_data.get("average_score", "")
            if not reviews:
                return random.choice([
                    "Sản phẩm này chưa có đánh giá nào.",
                    "Hiện tại chưa có ai đánh giá sản phẩm này.",
                ])
            top = reviews[0]
            top_review = f'{top.get("username", "Một người dùng")} nhận xét: "{top.get("description", "")[:100]}"'
            if avg:
                return random.choice([
                    f"Sản phẩm được đánh giá {avg}/5 sao với {len(reviews)} lượt nhận xét. {top_review}",
                    f"Sản phẩm đạt {avg}/5 sao từ {len(reviews)} đánh giá. {top_review}",
                ])
            return random.choice([
                f"Có {len(reviews)} đánh giá. {top_review}",
                f"Sản phẩm có {len(reviews)} nhận xét. {top_review}",
            ])

        if tool_type == "get_recommendations_tool":
            if not products:
                return random.choice([
                    "Hiện tại chưa có gợi ý nào dành cho bạn.",
                    "Rất tiếc, tôi chưa tìm được gợi ý phù hợp cho bạn.",
                ])
            return random.choice([
                f"Gợi ý dành cho bạn: {', '.join(products[:5])}.",
                f"Có thể bạn sẽ thích: {', '.join(products[:5])}.",
            ])

        if tool_type == "convert_currency_tool":
            return random.choice([
                f"{tool_data.get('amount')} {tool_data.get('from')} tương đương khoảng {tool_data.get('result')} {tool_data.get('to')} (tỷ giá {tool_data.get('rate')}).",
                f"{tool_data.get('amount')} {tool_data.get('from')} hiện tại đổi được {tool_data.get('result')} {tool_data.get('to')}.",
            ])

        if tool_type == "get_shipping_quote_tool":
            return random.choice([
                f"Phí vận chuyển ước tính {tool_data.get('cost')} {tool_data.get('currency')}, giao trong {tool_data.get('delivery_days', 'vài')} ngày qua {tool_data.get('provider', 'đơn vị vận chuyển')}.",
                f"Dự kiến phí ship {tool_data.get('cost')} {tool_data.get('currency')}, thời gian giao {tool_data.get('delivery_days', 'vài')} ngày ({tool_data.get('provider', 'đơn vị vận chuyển')}).",
            ])

        return random.choice([
            "Xin lỗi, tôi không thể tổng hợp câu trả lời ngay lúc này. Bạn có thể thử hỏi lại với cách khác được không?",
            "Rất tiếc, tôi chưa thể trả lời câu hỏi này. Bạn vui lòng thử lại nhé?",
            "Hiện tại tôi không có đủ thông tin để trả lời. Bạn có thể hỏi theo cách khác không?",
        ])

    def _template_confirm(self, pending_action: dict) -> str:
        params = pending_action.get("params", {})
        qty = params.get("quantity", 1)
        # product name có thể lấy từ entities hoặc params
        product_name = params.get("product_name", params.get("product_id", "sản phẩm"))
        return f"Vui lòng xác nhận: thêm {qty} {product_name} vào giỏ hàng."

    def _template_multi(self, tool_types: list, tool_results: dict) -> str:
        parts = []
        for t in tool_types:
            template = self._template_single(t, {k: v for k, v in tool_results.items() if t in k})
            parts.append(template)
        return " ".join(parts) + " Bạn cần hỗ trợ thêm gì không?"

    @staticmethod
    def _first_result(tool_results: dict) -> dict:
        """Lấy kết quả tool đầu tiên trong tool_results."""
        for call_id, r in tool_results.items():
            data = r.get("result", {})
            if isinstance(data, str):
                try:
                    return json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    return {}
            if isinstance(data, dict):
                return data
        return {}
```

### Graph Edge Update

```python
# graph/main_graph.py — thêm HallucinationGuard + FallbackGenerator

builder.add_node("response_verifier", ResponseVerifier())
builder.add_node("hallucination_guard", HallucinationGuard())
builder.add_node("fallback_generator", FallbackGenerator())
builder.add_node("answer_generator", AnswerGenerator())

# response_verifier → hallucination_guard
builder.add_edge("response_verifier", "hallucination_guard")

# hallucination_guard → conditional: pass → generator, fail → fallback
builder.add_conditional_edges(
    "hallucination_guard",
    route_after_grounding,  # function: state → str
    {
        "pass": "answer_generator",
        "fail": "fallback_generator",
    }
)

builder.add_edge("fallback_generator", "answer_generator")
builder.add_edge("answer_generator", END)

# Blocked path cũng qua hallucination_guard
builder.add_edge("input_guard", "hallucination_guard")
```

```python
# graph/edges.py

def route_after_grounding(state) -> str:
    if state.get("hallucination_detected"):
        return "fail"
    return "pass"
```

### State changes

```python
# Thêm vào ShoppingState
groundedness_score: float          # 0.0-1.0 (set bởi HallucinationGuard)
hallucination_detected: bool       # True nếu cần fallback
fallback_used: bool                # True nếu FallbackGenerator đã chạy
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

### Gate Node — interface dùng chung

```python
# graph/gates/gate_node.py

class GateResult(TypedDict):
    decision: bool          # True = Yes, False = No
    reason: Optional[str]   # chỉ set cho gate rủi ro cao (xem bảng dưới)
    latency_ms: float
    tokens: dict            # {"input": int, "output": int}

class GateNode:
    """
    Node dùng chung cho mọi quyết định nhị phân cần suy luận ngữ nghĩa.
    Luôn ép output = "YES" hoặc "NO" (+ optional 1 dòng reason).
    """
    MODEL_ID = "amazon.nova-lite-v1:0"

    async def __call__(self, question: str, context: str, want_reason: bool = False) -> GateResult:
        system = (
            "Bạn là bộ phân loại nhị phân. Chỉ trả lời đúng 1 từ: YES hoặc NO."
            + (" Sau đó xuống dòng, thêm 1 câu lý do ngắn (<15 từ)." if want_reason else " Không thêm gì khác.")
        )
        response = await bedrock_invoke(
            model_id=self.MODEL_ID,
            system=system,
            prompt=f"{question}\n\nContext:\n{context}",
            max_tokens=25 if want_reason else 3,
            temperature=0.0,   # deterministic — đây là classification, không phải generation
        )
        text = response.text.strip()
        decision = text.upper().startswith("YES")
        reason = text.split("\n", 1)[1].strip() if want_reason and "\n" in text else None
        return GateResult(
            decision=decision, reason=reason,
            latency_ms=response.latency_ms,
            tokens=response.usage,
        )
```

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

```python
try:
    result = await gate_node(question, context, want_reason=True)
except (TimeoutError, BedrockError):
    logger.warning("[GATE] timeout/error — fallback to rule-based default")
    result = GateResult(decision=DEFAULT_DECISION[gate_name], reason="gate_unavailable", ...)
```

Mỗi gate có `DEFAULT_DECISION` riêng, thiên về hướng an toàn hơn (VD: `semantic_hallucination_gate` timeout → mặc định `decision=False` tức fallback template, thà an toàn hơn là risk hallucination lọt qua).

---

## 11. System Prompt Design

### 11.1 Task Graph Builder Prompt

```python
# llm/prompt.py

TGB_PROMPT = """Bạn là Task Graph Builder của Shopping Copilot — trợ lý mua sắm AI của TechX Corp.
Nhiệm vụ của bạn là chọn tool cần gọi và nối edge dependency giữa chúng.

## Tool Output Schemas

Mỗi tool khi gọi sẽ trả về dữ liệu có cấu trúc cố định như sau:

{tool_schemas_text}

## DAG Format

Trả về JSON object với cấu trúc:
{{
  "reasoning": "Giải thích ngắn gọn tại sao chọn các tool này",
  "overall_confidence": 0.95,
  "nodes": [
    {{
      "id": "n0",
      "tool": "tool_name",
      "description": "tại sao gọi tool này",
      "depends_on": [],
      "condition": null,
      "confidence": 0.95
    }}
  ],
  "edges": [["n0", "n1"], ["n0", "n2"]]
}}

## Quy tắc

1. KHÔNG fill argument/entity — chỉ chọn tool và nối edge.
2. Node không có dependency → depends_on: [] → Executor chạy song song.
3. Node B cần output node A → depends_on: ["A_id"].
4. Nếu quantity không được chỉ định, entity extractor đã parse — không cần bạn guess.
5. add_to_cart_tool là write tool → cần user confirm sau.
6. Không chọn tool cho: place order, charge, empty cart — empty plan = từ chối.
7. Đánh giá confidence 0.0-1.0 cho mỗi node dựa trên độ chắc chắn.

## Planner Memory (ngữ cảnh phiên trước)

{planner_memory}

## Ví dụ (Few-shot)

### Ví dụ 1: Tìm sản phẩm (1 tool, không dependency)
User: "tìm kính thiên văn dưới 200 đô"
Intent: search | Entities: {{"max_price": "200"}}
DAG:
{{
  "reasoning": "User muốn tìm sản phẩm theo từ khóa + giá → search_products_v2",
  "overall_confidence": 0.98,
  "nodes": [
    {{ "id": "n0", "tool": "search_products_v2", "description": "tìm kính thiên văn", "depends_on": [], "condition": null, "confidence": 0.98 }}
  ],
  "edges": []
}}

### Ví dụ 2: Thêm vào giỏ (2 tools, dependency)
User: "thêm 2 cái lều vào giỏ"
Intent: cart_add | Entities: {{"quantity": 2}}
DAG:
{{
  "reasoning": "Cần search product_id trước, sau đó add_to_cart",
  "overall_confidence": 0.95,
  "nodes": [
    {{ "id": "n0", "tool": "search_products_v2", "description": "tìm product_id lều", "depends_on": [], "condition": null, "confidence": 0.95 }},
    {{ "id": "n1", "tool": "add_to_cart_tool", "description": "thêm lều vào giỏ", "depends_on": ["n0"], "condition": null, "confidence": 0.90 }}
  ],
  "edges": [["n0", "n1"]]
}}

### Ví dụ 3: Review + gợi ý (3 tools, parallel sau search)
User: "review cái bếp camping và gợi ý sản phẩm tương tự"
Intent: review | Entities: {{}}
DAG:
{{
  "reasoning": "Search lấy product_id → review + recommend chạy song song (không phụ thuộc nhau)",
  "overall_confidence": 0.95,
  "nodes": [
    {{ "id": "n0", "tool": "search_products_v2", "description": "tìm bếp camping", "depends_on": [], "condition": null, "confidence": 0.95 }},
    {{ "id": "n1", "tool": "get_product_reviews_tool", "description": "lấy review", "depends_on": ["n0"], "condition": null, "confidence": 0.90 }},
    {{ "id": "n2", "tool": "get_recommendations_tool", "description": "gợi ý sản phẩm tương tự", "depends_on": ["n0"], "condition": null, "confidence": 0.90 }}
  ],
  "edges": [["n0", "n1"], ["n0", "n2"]]
}}

### Ví dụ 4: Conditional — search, hỏi user nếu 0 kết quả
User: "tìm giày Nike giá từ 50 tới 150 đô"
Intent: search | Entities: {{"min_price": "50", "max_price": "150"}}
DAG:
{{
  "reasoning": "Search với filter, nếu 0 kết quả thì hỏi user có muốn thử lại không",
  "overall_confidence": 0.92,
  "nodes": [
    {{
      "id": "n0", "tool": "search_products_v2",
      "description": "tìm giày Nike theo giá",
      "depends_on": [],
      "condition": {{"on": "total", "==0": "ask_user", "default": "continue"}},
      "confidence": 0.92
    }}
  ],
  "edges": []
}}

## Format output

Trả về JSON object như format ở trên.
Nếu không cần gọi tool nào, trả về {{"nodes": [], "edges": [], "overall_confidence": 0.0, "reasoning": "..."}} và trả lời thẳng.

User query: {user_query}
Intent: {intent}
Entities: {entities}
Planner memory: {planner_memory}

DAG:"""
```

### 11.2 Response Verifier Prompt

```python
# llm/prompt.py (continued)

VERIFIER_PROMPT = """Bạn là trợ lý bán hàng của TechX Corp, đang trò chuyện trực tiếp với khách hàng.
Nhiệm vụ của bạn là trả lời khách hàng dựa trên dữ liệu thật từ hệ thống.

## Dữ liệu nhận được

Tool results: {tool_results_text}

## Quy tắc

1. CHỈ dùng thông tin có trong tool results — KHÔNG thêm chi tiết không có.
2. Nếu không có thông tin hoặc có lỗi: "Tôi không tìm thấy..." — không bịa.
3. Giữ nguyên giá cả (giữ format "$99.99"), tên sản phẩm, số lượng.
4. KHÔNG dùng markdown, không emoji, không technical terms.
5. Nếu là kết quả của write action (đã thêm vào giỏ): xác nhận ngắn gọn.
6. Nếu cần confirm (status=pending): nói "Vui lòng xác nhận..." và mô tả hành động.
7. Xưng hô: "tôi" — "bạn", lịch sự, gần gũi.
8. Trả lời bằng tiếng Việt. KHÔNG thêm thuộc tính, công dụng, đánh giá không có trong tool results.

Khách hàng hỏi: {user_query}

Trả lời:"""
```

### 11.2 Response Verifier Prompt

```python
# llm/prompt.py (continued)

VERIFIER_PROMPT = """Bạn là trợ lý bán hàng của TechX Corp, đang trò chuyện trực tiếp với khách hàng.
Nhiệm vụ của bạn là trả lời khách hàng dựa trên dữ liệu thật từ hệ thống.

## Dữ liệu nhận được

Tool results: {tool_results_text}

## Quy tắc

1. CHỈ dùng thông tin có trong tool results — KHÔNG thêm chi tiết không có.
2. Nếu không có thông tin hoặc có lỗi: "Tôi không tìm thấy..." — không bịa.
3. Giữ nguyên giá cả (giữ format "$99.99"), tên sản phẩm, số lượng.
4. KHÔNG dùng markdown, không emoji, không technical terms.
5. Nếu là kết quả của write action (đã thêm vào giỏ): xác nhận ngắn gọn.
6. Nếu cần confirm (status=pending): nói "Vui lòng xác nhận..." và mô tả hành động.
7. Xưng hô: "tôi" — "bạn", lịch sự, gần gũi.
8. Trả lời bằng tiếng Việt.

Khách hàng hỏi: {user_query}

Trả lời:"""
```

### 11.3 System Prompt Injection (Dynamic Tool Schemas)

Cả TGB prompt và Verifier prompt đều được build động với tool schemas từ `ToolRegistry`. Thêm tool mới → chỉ cần register → prompt tự cập nhật.

```python
def _build_tgb_prompt(
    user_query: str,
    intent: str,
    entities: dict,
    planner_memory: dict,
    registry: "ToolRegistry",
) -> str:
    schemas_text = registry.get_all_schemas_text()
    memory_text = _format_memory(planner_memory)
    return TGB_PROMPT.format(
        tool_schemas_text=schemas_text,
        user_query=user_query,
        intent=intent,
        entities=json.dumps(entities, ensure_ascii=False),
        planner_memory=memory_text,
    )


def _build_verifier_prompt(
    user_query: str,
    tool_results_text: str,
) -> str:
    return VERIFIER_PROMPT.format(
        tool_results_text=tool_results_text,
        user_query=user_query,
    )
```

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

## 13. Memory & Caching

Giữ nguyên từ v2. Xem chi tiết ở v2 spec §8.

### CacheStore Updates

Cập nhật TTL map cho v3:

```python
_CACHE_TTL_MAP = {
    "search_products_v2":        300,   # 5 minutes
    "get_product_reviews_tool":  300,   # 5 minutes
    "get_recommendations_tool":  300,   # 5 minutes
    "convert_currency_tool":      60,   # 1 minute
    "get_shipping_quote_tool":   300,   # 5 minutes
    # get_cart_tool và add_to_cart_tool không cache
}
```

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

### main.py — Graph Invocation

```python
# main.py — gọi graph planner-centric

@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    graph = _get_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    result = await graph.ainvoke({
        "messages": [HumanMessage(content=req.message)],
        "session_id": req.session_id,
        "user_id": req.user_id,
        "trace_id": str(uuid.uuid4()),
    }, config=config)

    # Pending confirmation
    if result.get("pending_action"):
        return ChatResponse(
            status="pending",
            reply=result["pending_action"]["message"],
            token=result["pending_action"]["token"],
            session_id=req.session_id,
        )

    # Guardrail violation
    if result.get("guardrail_violations"):
        violation = result["guardrail_violations"][0]
        return ChatResponse(
            status="error",
            reply=violation.get("detail", "Yêu cầu bị từ chối."),
            session_id=req.session_id,
        )

    return ChatResponse(
        status="ok",
        reply=result.get("final_answer", ""),
        session_id=req.session_id,
    )


@app.post("/api/confirm", response_model=ConfirmResponse)
async def api_confirm(req: ConfirmRequest):
    graph = _get_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    is_valid, action_data = verify_confirmation_token(req.token)
    if not is_valid:
        return ConfirmResponse(status="error", reply="Token không hợp lệ.")

    result = await graph.ainvoke(
        Command(resume={"confirmed": True}),
        config=config,
    )

    return ConfirmResponse(
        status=result.get("status", "ok"),
        reply=result.get("final_answer", "Đã xác nhận."),
    )
```

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
| 3 | Session/cache in-memory | Mất khi pod restart | Valkey session store (Phase 3) |
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
- ⏳ Valkey/Redis for rate limiter + session store
- ⏳ OpenTelemetry metrics (đặc biệt: template vs LLM ratio, replan rate, gate accuracy)
- ⏳ Load test P95 < 2s
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