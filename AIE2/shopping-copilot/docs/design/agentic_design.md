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
7.3. [Multi-Turn Reference Resolution (Inline trong Tool Executor)](#73-multi-turn-reference-resolution-inline-trong-tool-executor)
7.4. [Reference Resolver Node (inline trong Tool Executor)](#74-reference-resolver-node-inline-trong-tool-executor)
7.5. [Reference Table](#75-reference-table)
7.6. [Reference Priority Chain](#76-reference-priority-chain)
7.7. [Query Rewriter](#77-query-rewriter)
8. [Tool Executor (DAG Runner)](#8-tool-executor-dag-runner)
8.4. [Reference Updater (cập nhật Table/Stack/Registry sau tool execution)](#85-reference-updater-inline-trong-tool-executor)
8.6. [Reflection Node](#86-reflection-node)
9. [Write + Confirm Flow](#9-write--confirm-flow)
10. [Response Verifier (Template-First)](#10-response-verifier-template-first)
10.5. [HallucinationGuard & FallbackGenerator](#105-hallucinationguard--fallbackgenerator)
10.6. [Semantic Decision Gate Layer (Nova Lite)](#106-semantic-decision-gate-layer-nova-lite)
11. [System Prompt Design](#11-system-prompt-design)
12. [State Design](#12-state-design)
13. [Cache Strategy (Redis)](#13-cache-strategy-redis)
13.12. [CacheManager — 2-Layer Architecture](#1312-cachemanager--2-layer-architecture)
13.13. [Global Rate Limiter (Redis)](#1313-global-rate-limiter-redis)
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
               │  │            REFERENCE_RESOLVER            │   │ │
               │  │                  │                       │   │ │
               │  │       ROUTING_GATE (fast path?)          │   │ │
               │  │    ┌─── yes (template) → RESPONSE_VERIFIER→END│ │
               │  │    └── no → TASK_GRAPH_BUILDER           │   │ │
               │  │                  │ (LLM chọn tool + edge)│   │ │
               │  │       PLAN_VALIDITY_GATE                 │   │ │
               │  │    ├── pass → TOOL_EXECUTOR (DAG runner) │   │ │
                │  │    │   ┌───► parallel node ────┐         │   │ │
                │  │    │   │    └► parallel node ←──┤        │   │ │
                │  │    │   └────► sequential node    │        │   │ │
                │  │    │               │             │        │   │ │
                │  │    │     REFERENCE_UPDATER       │        │   │ │
                │  │    │       (update Table/        │        │   │ │
                │  │    │        Stack/Registry)      │        │   │ │
                │  │    │               │             │        │   │ │
                │  │    │          REFLECTION          │        │ │
               │  │    │       ├── pass ───────────── │        │ │
               │  │    │       └── replan ──► REPLAN_GATE     │ │
               │  │    │              /   ├── replan → TGB    │ │
               │  │    │             /    └── skip → VERIFIER │ │
               │  │    │    pause? (write confirm)             │ │
               │  │    │      RESPONSE_VERIFIER                │ │
               │  │    │  (template ── LLM theo complexity)    │ │
               │  │    │      │                                │ │
               │  │    │   HALLUCINATION_GUARD                 │ │
               │  │    │  ├── pass (≥80%)                      │ │
               │  │    │  │    → SEMANTIC_HALLUCINATION_GATE   │ │
               │  │    │  │    ├── PASS → answer → END         │ │
               │  │    │  │    └── FAIL → FALLBACK → END       │ │
               │  │    │  └── fail (<80%)                      │ │
               │  │    │       → FALLBACK_GENERATOR            │ │
               │  │    │            → answer_generator → END   │ │
               │  │    └── fail (invalid plan)                 │ │
               │  │         → ask_user / template              │ │
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
├── src/
│   ├── __init__.py
│   │
│   ├── main.py                      # FastAPI server entry point
│   │
│   ├── graph/                       # LangGraph StateGraph
│   │   ├── __init__.py
│   │   ├── main_graph.py            # build_graph() — planner-centric flow
│   │   ├── state.py                 # ShoppingState (updated v3)
│   │   ├── edges.py                 # route_after_input_guard
│   │   │
│   │   ├── nodes/                   # Graph nodes
│   │   │   ├── __init__.py
│   │   │   ├── input_guard.py       # L1 + L2a + L2b
│   │   │   ├── task_graph_builder.py # 2-Layer Planner: rule-based intent parsing + LLM DAG builder (§7)
│   │   │   ├── tool_executor.py     # DAG runner (parallel, conditional, cache, confirm, retry, reference resolve inline) (§8)
│   │   │   ├── reflection.py        # Post-execution check → partial replan signal (§8.6)
│   │   │   ├── response_verifier.py # Template-first + LLM fallback, temperature động (§10)
│   │   │   ├── hallucination_guard.py # Rule-based exact checks (price/entity/count/score/action) → semantic claim sang Gate (§10.5)
│   │   │   ├── fallback_generator.py # Template fallback khi hallucination detected (§10.5)
│   │   │   ├── answer_generator.py  # L5 + format
│   │   │   └── confirmation.py      # HMAC confirmation handler
│   │   │
│   │   ├── gates/                   # Semantic Decision Gate Layer (Nova Lite)
│   │   │   ├── __init__.py
│   │   │   ├── gate_node.py         # Shared Gate Node interface
│   │   │   ├── plan_validity_gate.py # DAG validity check
│   │   │   ├── semantic_hallucination_gate.py # Semantic hallucination check
│   │   │   ├── confirm_parse_gate.py # Natural language confirm parse
│   │   │   └── replan_gate.py       # Replan decision gate
│   │   │
│   │   ├── schemas/                 # Graph schemas
│   │   │   └── __init__.py
│   │   │
│   │   └── workflows/               # ❌ ĐÃ XOÁ (v3 planner-centric)
│   │
│   ├── guardrails/                  # ✅ 6 security layers — GIỮ NGUYÊN
│   │   ├── __init__.py
│   │   ├── rate_limiter.py          # L1: Per-pod → Redis global rate limiting
│   │   ├── input_filter.py          # L2: Regex (38+ patterns) + Bedrock
│   │   ├── tool_validator.py        # L3: Allow-list + isolation + bounds
│   │   ├── confirmation.py          # L4: HMAC stateless confirmation tokens
│   │   ├── output_filter.py         # L5: PII & system info redaction
│   │   └── fallback.py              # L6: Never-crash exception handler
│   │
│   ├── tools/                       # LangChain tools → EKS gRPC
│   │   ├── __init__.py              # Imports all tools (triggers registry)
│   │   ├── registry.py              # ✅ ToolRegistry + ToolSpec (đăng ký tập trung)
│   │   ├── cart_tool.py             # add_to_cart_tool, update_cart_item_tool, get_cart_tool, check_cart_item_tool
│   │   ├── review_tool.py           # get_product_reviews_tool
│   │   ├── recommendation_tool.py   # get_recommendations_tool
│   │   ├── currency_tool.py         # convert_currency_tool
│   │   ├── shipping_tool.py         # get_shipping_quote_tool (REST)
│   │   ├── catalog_tool.py          # get_categories, get_all_products
│   │   ├── product_tool.py          # get_product_details_tool
│   │   ├── product_id_tool.py       # get_product_id (Read)
│   │   └── search/                  # ✅ Multi-strategy search module v3
│   │       ├── __init__.py          # search_products_v2
│   │       ├── orchestrator.py      # SearchOrchestrator (dual-flow)
│   │       ├── models.py            # SearchToolResponse, ScoredProduct, etc.
│   │       ├── reranker.py          # Merge + dedup + score
│   │       ├── tracer.py            # SearchTracer
│   │       ├── schema_loader.py     # DB schema loader
│   │       ├── synonym_cache.py     # EN/VI synonym expansion
│   │       ├── flow1/               # SQL matching
│   │       │   ├── __init__.py
│   │       │   ├── entity_extractor.py
│   │       │   ├── sql_builder.py
│   │       │   └── sql_executor.py
│   │       └── flow2/               # Bedrock RAG semantic search
│   │           ├── __init__.py
│   │           ├── kb_client.py
│   │           └── prompt_rewriter.py
│   │
│   ├── llm/                         # LLM abstraction layer
│   │   ├── __init__.py
│   │   ├── llm.py                   # LLMClient (Bedrock Nova Lite) + MockLLMClient
│   │   └── prompt.py                # System prompt (planner prompt)
│   │
│   ├── memory/                      # Session & cache storage
│   │   ├── __init__.py
│   │   ├── cache_manager.py         # CacheManager 2-layer (Redis + in-memory fallback)
│   │   ├── redis_store.py           # Redis cache client (production)
│   │   └── store.py                 # In-memory TTL + LRU (dev fallback)
│   │
│   ├── agent/                       # Agent wrappers
│   │   ├── __init__.py
│   │   ├── copilot_agent.py         # Thin wrapper for CLI/benchmarks
│   │   └── response_formatter.py    # LLM restructure + rule-based fallback
│   │
│   ├── database/                    # PostgreSQL connection
│   │   ├── __init__.py
│   │   └── connect.py               # ThreadedConnectionPool
│   │
│   ├── evaluation/                  # Benchmark & eval
│   │   ├── __init__.py
│   │   ├── shopping_benchmark.py
│   │   └── trust_safety.py
│   │
│   └── protos/                      # gRPC protobuf (compiled)
│       ├── demo.proto
│       ├── demo_pb2.py
│       └── demo_pb2_grpc.py
│
├── server-test/                     # Mock EKS gRPC server (local dev)
│
├── tests/                           # Test suite
│   ├── conftest.py
│   ├── test_api_e2e.py
│   ├── test_cart_tool.py
│   ├── test_interactive.py
│   ├── ...
│   └── test_search/
│
├── docs/                            # Design & ADR documents
│   ├── design/
│   │   ├── agentic_design.md
│   │   ├── ... (all design docs)
│   └── ADR/
│       └── ADR1.md
│
├── static/
│   └── chatbot.html                 # Chatbot UI
│
├── scripts/                         # Utility scripts
│   ├── run_eval_suite.py
│   ├── cron_sync_and_sync_kb.py
│   ├── start_port_forwards.py
│   └── ...
│
├── .env
├── requirements.txt
└── README.md
```

### Build Status (v3.2)

| Module | Status | Notes |
|---|---|---|
| `guardrails/` | ✅ Built | All 6 layers, importable |
| `memory/store.py` | ✅ Built | SessionStore + InMemoryCacheStore |
| `memory/cache_manager.py` | ✅ Built | CacheManager 2-layer (Redis + in-memory fallback, circuit breaker) |
| `memory/redis_store.py` | ✅ Built | RedisCacheStore — 3 logical DBs |
| `main.py` | ✅ Built | FastAPI with 4 endpoints |
| `protos/` | ✅ Built | Compiled protobuf |
| `tools/registry.py` | ✅ Built | ToolRegistry + ToolSpec (singleton) |
| `tools/__init__.py` | ✅ Built | All tools exported + auto-register vào registry |
| `tools/search/` | ✅ Built | Multi-strategy search |
| `tools/cart_tool.py` | ✅ Built | add_to_cart_tool, update_cart_item_tool, get_cart_tool, check_cart_item_tool |
| `tools/catalog_tool.py` | ✅ Built | get_categories, get_all_products |
| `tools/product_tool.py` | ✅ Built | get_product_details_tool |
| `tools/product_id_tool.py` | ✅ Built | get_product_id |
| `tools/review_tool.py` | ✅ Built | get_product_reviews_tool (⚠️ missing ToolRegistry.register()) |
| `llm/llm.py` | ✅ Built | Bedrock Nova Lite + MockLLMClient |
| `llm/prompt.py` | ✅ Built | SYSTEM_PROMPT, PLANNER_PROMPT, VERIFIER_PROMPT, GATE prompts |
| `graph/nodes/input_guard.py` | ✅ Built | Kept from v2 |
| `graph/nodes/answer_generator.py` | ✅ Built | Kept from v2 |
| `graph/nodes/confirmation.py` | ✅ Built | Kept from v2 |
| `graph/nodes/task_graph_builder.py` | ✅ Built | 2-Layer Planner: rule-based intent parsing (§7.1) + LLM DAG builder (§7.2) |
| `graph/nodes/tool_executor.py` | ✅ Built | DAG runner (parallel, conditional, cache, retry, variable reference resolve, reference updater inline) |
| `graph/nodes/reflection.py` | ✅ Built | 4 trigger checks → partial replan |
| `graph/nodes/response_verifier.py` | ✅ Built | Template-first + LLM fallback |
| `graph/nodes/hallucination_guard.py` | ✅ Built | 6 deterministic checks |
| `graph/nodes/fallback_generator.py` | ✅ Built | Template fallback on hallucination |
| `graph/gates/` | ✅ Built | 6 gate files (gate_node + 5 gates) |
| `graph/main_graph.py` | ✅ Built | DAG-centric topology, 11 nodes, conditional edges |
| `graph/state.py` | ✅ Built | ShoppingState v3.2 (⚠️ missing 6 reference fields — see §12) |
| `graph/edges.py` | ✅ Built | 5 routing functions |

> **⚠️ Known gaps:** `review_tool.py` chưa register `get_product_reviews_tool` vào ToolRegistry; `state.py` thiếu 6 fields cho reference resolution (`last_tool_outputs`, `reference_table`, `reference_stack`, `entity_registry`, `resolved_query`, `resolved_entities`).

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
  Step 4 → INTENT_PARSER: extract intent + entities (rule-based → LLM fallback)
  Step 5 → REFERENCE_RESOLVER: detect referential tokens ("nó", "cái đầu tiên", "cái cuối"...) → resolve via reference_table / reference_stack / entity_registry → rewrite query → update state.entities
  Step 6 → PLANNER: LLM sinh plan dựa trên query đã rewrite + tool output schemas
               Example plan: [{"tool": "get_cart_tool", "args": {"user_id": "..."}}]
  Step 7 → TOOL_EXECUTOR_LOOP: iterate plan
               a. [L3] validate tool call (allow-list, bounds, user isolation)
               b. Cache check (read tools only)
               c. Execute tool → gRPC call
               d. Normalize output (price formatting, schema validation)
               e. REFERENCE_UPDATER: update reference_table, reference_stack, entity_registry từ tool output
               f. Append result to state.tool_results
  Step 8 → response_verifier: từ tool_results + user query
               a. Tính complexity score
               b. Chọn temperature (0.1-0.6)
               c. LLM sinh câu trả lời grounded
  Step 9 → answer_generator: [L5] output filter + format
  Step 10 → Return { reply, session_id } to user
```

### Add-to-Cart Flow (Write + Confirm)

```
POST /api/chat
  Body: { message: "add 2 telescopes to my cart", ... }
  
  Steps 1-3: Same as read flow
  Step 4-6: INTENT_PARSER → REFERENCE_RESOLVER → PLANNER (resolve references, rewrite query)
  Step 7: PLANNER sinh plan:
               [{"tool": "search_products_v2", ...},
                {"tool": "add_to_cart_tool", ...}]
  Step 8: TOOL_EXECUTOR_LOOP
               a. search_products_v2 → tìm product_id
               b. REFERENCE_UPDATER cập nhật reference_table/stack
               c. add_to_cart_tool → [L4] confirmation gate
               d. Tool returns {status: "pending", token: "eyJ..."}
               e. Loop PAUSES → graph checkpoint
               f. Return token to user
  Step 9: User clicks "Confirm" → POST /api/confirm
  Step 10: Resume graph → execute AddItem gRPC
  Step 11: response_verifier → "Đã thêm 2 telescope vào giỏ!"
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
|---|---|---|---|
| `search_products_v2` | `tools/search/__init__.py` | ProductCatalog | Read |
| `get_product_details_tool` | `tools/product_tool.py` | ProductCatalog | Read |
| `get_product_reviews_tool` | `tools/review_tool.py` | ProductReview | Read |
| `add_to_cart_tool` | `tools/cart_tool.py` | Cart | **Write** |
| `update_cart_item_tool` | `tools/cart_tool.py` | Cart | **Write** |
| `get_cart_tool` | `tools/cart_tool.py` | Cart | Read |
| `check_cart_item_tool` | `tools/cart_tool.py` | Cart | Read |
| `get_recommendations_tool` | `tools/recommendation_tool.py` | Recommendation | Read |
| `convert_currency_tool` | `tools/currency_tool.py` | Currency | Read |
| `get_shipping_quote_tool` | `tools/shipping_tool.py` | Shipping | Read |
| `get_categories` | `tools/catalog_tool.py` | ProductCatalog (SQL) | Read |
| `get_all_products` | `tools/catalog_tool.py` | ProductCatalog (SQL) | Read |
| `get_product_id` | `tools/product_id_tool.py` | ProductCatalog (SQL) | Read |

### 6.1 Tool Registry

**File:** `tools/registry.py` (NEW)

Tool Registry là nguồn truth duy nhất cho tất cả tool metadata — schema đầu vào, schema đầu ra, mô tả, examples. Planner đọc từ registry để xây prompt động; Executor đọc để resolve tool function.

#### ToolSpec

```python
# tools/registry.py

from __future__ import annotations
from typing import Any, Optional
from dataclasses import dataclass, field
import json


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
| `update_cart_item_tool` | `tools/cart_tool.py` | Cart | **Write** | `product_id` (str), `quantity` (int) | `status` (pending/confirmed/denied/error), `token`, `message` | `cart` (user_id, product_id, quantity) | Dùng AddItem gRPC (upsert); quantity=0 để xoá item |
| `get_cart_tool` | `tools/cart_tool.py` | Cart | Read | (none) | `status`, `items[]` (product_id, name, price, quantity, image), `subtotal`, `item_count` | `cart` + JOIN `products` | subtotal = SUM(price × quantity) |
| `check_cart_item_tool` | `tools/cart_tool.py` | Cart | Read | `user_id` (str), `product_id` (str) | Kiểm tra SP có trong giỏ không, trả về số lượng nếu có | `cart` | Dùng GetCart rồi filter |
| `get_recommendations_tool` | `tools/recommendation_tool.py` | Recommendation | Read | `product_id` (str, opt), `context` (str, opt), `limit` (int, opt) | `status`, `reason`, `products[]` (id, name, price, desc, image, rating) | Không có bảng riêng: (1) same-category, (2) full-text search, (3) popular | |
| `convert_currency_tool` | `tools/currency_tool.py` | Currency | Read | `amount` (num), `from` (str), `to` (str) | `status`, `from`, `to`, `original_amount`, `converted_amount`, `rate`, `formatted` | Không có DB — gọi external API hoặc hardcode mapping | |
| `get_shipping_quote_tool` | `tools/shipping_tool.py` | Shipping | Read | `zip_code` (str), `items_count` (int, opt), `cart_total` (str, opt) | `status`, `destination`, `options[]` (provider, cost, delivery_days, delivery_window, description) | Business rules (free >$100, flat rate) | cost dùng units/nanos pattern |
| `get_categories` | `tools/catalog_tool.py` | ProductCatalog | Read | (none) | Danh sách category duy nhất | `products.categories` | DISTINCT categories, parse comma-separated |
| `get_all_products` | `tools/catalog_tool.py` | ProductCatalog | Read | (none) | Danh sách đầy đủ sản phẩm (id, name, price, desc, categories) | `products` | Chỉ dùng khi thực sự cần (liệt kê/xuất kho) |
| `get_product_id` | `tools/product_id_tool.py` | ProductCatalog | Read | `product_name` (str) | Product ID string | `products` | Tra ID từ tên, fallback qua SQLite |

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

Các write tool (`add_to_cart_tool`, `update_cart_item_tool`) có `is_write=True` — Executor Loop tự động:

1. Gọi tool → nhận `{"status": "pending", "token": "...", "message": "..."}`
2. PAUSE execution → chờ user confirm/reject
3. User confirm → gọi lại với token → `{"status": "confirmed", ...}`

Chi tiết ở [§9 Write + Confirm Flow](#9-write--confirm-flow).

---

## 7. 2-Layer Planner

**Files:** `graph/nodes/task_graph_builder.py` (2-Layer Planner — intent parsing + DAG building)

> **Lưu ý kiến trúc:** Spec thiết kế 3 node riêng (`intent_parser`, `reference_resolver`, `reference_updater`), nhưng codebase hiện tại gộp intent parsing vào `task_graph_builder.py` (rule-based extract entities + LLM DAG builder) và reference resolution/update inline trong `tool_executor.py`. Các node riêng sẽ được tách sau (Phase 4).

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

### 7.1 Layer 1: Intent Parser (Rule-based + LLM fallback)

**Implementation:** Nhúng trong `graph/nodes/task_graph_builder.py` — hàm `_extract_entities()` và `_build_system_prompt()`.

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

Task Graph Builder là module duy nhất cho Planner — nó thực hiện cả Layer 1 (intent parsing) và Layer 2 (DAG building):

1. **Intent parsing** (rule-based, zero-cost): regex patterns cho intent + entity extraction
2. **LLM fallback**: nếu rule không đủ tự tin (confidence < 0.8)
3. **DAG building**: LLM chọn tool + nối edge dependency

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
    "last_product_name": str,    # Tên sản phẩm vừa xem
    "last_results_ids": list,    # [P001, P005, ...] thứ tự search results
    "mentioned_products": list,  # [P001, P005] tất cả SP từng mention
    "current_cart_items": int,   # Số items trong giỏ
    "last_intent": str,          # Intent của lượt trước
}
```

Điều này giúp TGB không cần lập kế hoạch từ đầu mỗi lượt — VD: user hỏi "review cái đó" sau khi search → TGB biết `product_id` từ memory thay vì phải search lại.

### 7.3 Multi-Turn Reference Resolution (Inline trong Tool Executor)

> **Implementation:** Reference resolution hiện tại inline trong `graph/nodes/tool_executor.py` (hàm `_resolve_args`, `_resolve_value`). Thiết kế dưới đây mô tả kiến trúc mục tiêu — các node `reference_resolver` và `reference_updater` sẽ được tách riêng trong Phase 4.

#### Vấn đề
User nói "review nó", "thêm cái đầu tiên vào giỏ", "cho tôi xem cái thứ hai" — Intent Parser / TGB không biết "nó"/"cái đầu tiên"/"cái thứ hai" là sản phẩm nào nếu không có context từ lượt trước. Giải pháp cũ (dùng LLM để resolve) tốn cost, thêm latency, và có thể hallucinate.

**Giải pháp mới:** Tách reference resolution thành node riêng (`reference_resolver`) đặt giữa `intent_parser` và `routing_gate`, với 4 cơ chế deterministic phối hợp:

```
intent_parser
    │
    ▼
reference_resolver
    ├── Intent Detection     — phát hiện query có chứa tham chiếu không
    ├── Reference Resolver   — resolve bằng Reference Table → Stack → Entity Registry
    ├── Query Rewriter       — thay "cái đầu tiên" → "Dell XPS 13"
    └── Reference Updater    — (chạy sau tool_executor) cập nhật Table/Stack/Registry
    │
    ▼
routing_gate → task_graph_builder
```

#### 4 cơ chế core

| # | Cơ chế | Chi phí | Mô tả |
|---|---|---|---|
| 1 | **Reference Table** (§7.5) | $0, ~10μs | Map "first"/"second"/"last"/"1"/"2" → item cụ thể từ kết quả tool gần nhất |
| 2 | **Reference Stack** (§7.4) | $0, ~5μs | Stack các kết quả tool qua nhiều lượt — hỗ trợ "quay lại cái trước" |
| 3 | **Entity Registry** (§7.4) | $0, ~5μs | Lưu entity đã mention (VD: `iphone16: {id:P123, type:product}`) — "nó" → iPhone 16 |
| 4 | **Reference Priority Chain** (§7.6) | $0, ~20μs | Thứ tự resolve deterministic: Explicit Name → Entity Registry → Reference Table → Reference Stack → History → LLM Guess |

#### Luồng tích hợp vào graph

```
START → input_guard → intent_parser
    │
    ▼
reference_resolver (MỚI)
    ├── detect_referential_intent()     — kiểm tra "nó", "cái đó", "đầu tiên", "cuối", ...
    ├── resolve_via_priority_chain()    — Reference Table → Stack → Entity Registry → History
    ├── rewrite_query()                 — thay "cái đầu tiên" → "Dell XPS 13" hoặc inject product_id
    └── update_state()                  — ghi resolved entities + query vào state
    │
    ▼
routing_gate → task_graph_builder
```

Sau tool_executor, `reference_updater` (MỚI) cập nhật:

```
tool_executor → reference_updater (MỚI)
    ├── build_reference_table()         — từ tool output, tạo "first"/"1"/"2"/"last" mapping
    ├── push_reference_stack()          — push current result lên stack
    ├── update_entity_registry()        — lưu entity mới
    └── update_last_tool_outputs()      — lưu structured output với index/type/items
    │
    ▼
reflection / confirmation
```

#### Cost

| Layer | Cost/request | Latency |
|---|---|---|
| Reference Resolver node | $0 (deterministic, không LLM) | ~50μs |
| Reference Updater node | $0 (ghi dict) | ~10μs |
| LLM fallback (rare, <5%) | 1 LLM call ngắn | ~200ms |
| **P50 path** | **$0** | **~60μs** |

---

### 7.4 Reference Resolver Node (inline trong Tool Executor)

**Implementation:** Nhúng trong `graph/nodes/tool_executor.py` — hàm `_resolve_value()` và `_resolve_args()`.

> **Lưu ý:** Spec thiết kế node riêng, codebase hiện tại đặt resolve logic inline trong executor (resolve variable references `$steps[...]`, `$session.*`, `$input.entities.*` tại runtime). Tách thành node riêng ở Phase 4.

#### Vị trí trong graph

```
intent_parser → REFERENCE_RESOLVER → routing_gate → task_graph_builder
```

Đặt giữa `intent_parser` và `routing_gate` — sau khi đã có intent + entities từ parser, trước khi quyết định fast path (template) hay TGB.

#### Interface

```python
# graph/nodes/reference_resolver.py

async def reference_resolver_node(state: ShoppingState) -> dict:
    """
    Node chính — detect referential tokens, resolve bằng priority chain,
    rewrite query, update state.
    
    Output:
        resolved_query: str          # Query đã rewrite (hoặc giữ nguyên)
        resolved_entities: dict      # Entities đã bổ sung product_id từ resolve
        references: list[dict]       # [{source, original, resolved, type}]
        node_durations: dict
    """
```

#### Pipeline

```
reference_resolver_node(state)
    │
    ├── 1. detect_referential_intent(query, entities)
    │       → bool: có tham chiếu không?
    │       → tokens: ["cái đầu tiên", "nó", ...]
    │
    ├── 2. resolve_via_priority_chain(tokens, state)
    │       → resolved: dict[token → concrete value]
    │       (xem Reference Priority Chain §7.6)
    │
    ├── 3. rewrite_query(query, resolved)
    │       → new_query: thay "cái đầu tiên" → "Dell XPS 13"
    │       → new_entities: inject product_id = "P001"
    │
    └── 4. update_state(resolved, new_query, new_entities)
```

#### Fallback

Nếu toàn bộ priority chain không resolve được → **LLM fallback** (gọi LLM với prompt ngắn <100 tokens, temperature=0.0): "User nói '{query}', context gần nhất là {context}. Hãy resolve reference: output JSON {{resolved: string, entity_id: string|null, confidence: float}}".

Nếu LLM cũng không chắc (confidence < 0.5) → giữ nguyên query, không inject.

---

### 7.5 Reference Table

**Mục đích:** Map các ordinal references ("first", "second", "last", "1", "2", "3") đến item cụ thể trong kết quả tool gần nhất.

#### Cấu trúc

```python
# Trong ShoppingState
reference_table: dict = {
    # Ordinal ánh xạ
    "first": {"id": "P001", "name": "Dell XPS 13", "price": "$999", "index": 0},
    "second": {"id": "P002", "name": "Dell Inspiron", "price": "$699", "index": 1},
    "third": {"id": "P003", "name": "Dell Latitude", "price": "$849", "index": 2},
    "last": {"id": "P005", "name": "Asus Zenbook", "price": "$1299", "index": 4},
    
    # Number alias
    "1": {"id": "P001", "name": "Dell XPS 13", ...},
    "2": {"id": "P002", ...},
    "3": {"id": "P003", ...},
    "4": {"id": "P004", ...},
    "5": {"id": "P005", ...},
}
```

#### Thuật toán build

```python
def build_reference_table(tool_output: dict) -> dict:
    """
    Tạo reference table từ tool output.
    Support: product_list, product_detail, review_list, cart_items.
    """
    items = _extract_items(tool_output)  # [{id, name, ...}, ...]
    if not items:
        return {}
    
    table = {}
    ordinals = ["first", "second", "third", "fourth", "fifth"]
    
    for i, item in enumerate(items[:5]):
        entry = {"id": item.get("id"), "name": item.get("name"),
                 "index": i}
        # Ordinal key
        if i < len(ordinals):
            table[ordinals[i]] = entry
        # Number key
        table[str(i + 1)] = entry
    
    # "last" = item cuối cùng (có thể ≠ item thứ 5)
    if items:
        last = items[-1]
        table["last"] = {"id": last.get("id"), "name": last.get("name"),
                         "index": len(items) - 1}
    
    return table
```

#### Giới hạn

| Key | Giới hạn | Lý do |
|---|---|---|
| Ordinal | first → fifth (5 items) | Hiếm khi user nói "cái thứ 6" |
| Number | 1 → 20 | Tối đa items trong 1 tool output |
| "last" | Luôn có nếu items không rỗng | Item cuối cùng của danh sách |

#### Vòng đời

1. **Build** — sau mỗi tool result, `reference_updater` gọi `build_reference_table()`
2. **Read** — `reference_resolver` tra cứu `reference_table.get(token)`
3. **Replace** — turn mới ghi đè table (không accumulate vô hạn)

---

### 7.6 Reference Priority Chain

**Mục đích:** Resolve reference deterministic, chỉ dùng LLM khi tất cả các tầng dưới đều fail.

#### Priority (từ cao đến thấp)

```
1. Explicit Name/ID
   Query đã có sẵn tên sản phẩm hoặc ID rõ ràng
   → Skip toàn bộ resolve
   
2. Named Entity Registry
   "iPhone 16" → entity_registry["iphone16"].id
   VD: user nói "nó" → lookup entity_registry gần nhất
   
3. Reference Table (§7.5)
   "cái đầu tiên" → reference_table["first"].id
   "cái thứ 2" → reference_table["2"].id
   "cái cuối" → reference_table["last"].id

4. Reference Stack
   "quay lại cái trước" → stack[-1] (pop)
   "kết quả trước đó" → stack[-2] (peek)

5. Planner Memory (planner_memory.last_*)
   "sản phẩm kia" → planner_memory.last_product_id
   "review đó" → planner_memory.last_product_id

6. tool_history (turn gần nhất)
   Duyệt tool_history[-1] tìm product_id đầu tiên

7. LLM Guess (fallback)
   Gọi LLM với prompt ngắn, chỉ khi 1-6 đều fail
```

#### Implementation

```python
async def resolve_via_priority_chain(
    query: str,
    tokens: list[str],      # VD: ["cái đầu tiên", "nó"]
    state: ShoppingState,
) -> dict[str, Any]:         # {token: resolved_value}
    
    resolved = {}
    
    for token in tokens:
        value = None
        
        # Priority 2: Entity Registry
        if token in ("nó", "cái này", "cái đó"):
            value = _resolve_entity_registry(state.entity_registry)
        
        # Priority 3: Reference Table
        if value is None:
            ordinal_key = _normalize_ordinal(token)  # "cái đầu tiên" → "first"
            if ordinal_key:
                value = state.reference_table.get(ordinal_key)
        
        # Priority 4: Reference Stack
        if value is None and token in ("cái trước", "quay lại", "trước đó"):
            value = _pop_reference_stack(state.reference_stack)
        
        # Priority 5: Planner Memory
        if value is None:
            value = _resolve_memory(token, state.planner_memory)
        
        # Priority 6: tool_history
        if value is None:
            value = _resolve_history(token, state.tool_history)
        
        # Priority 7: LLM fallback
        if value is None:
            value = await _llm_guess(token, query, state)
            if value and value.confidence < 0.5:
                value = None
        
        resolved[token] = value
    
    return resolved
```

#### Token normalization helpers

| Input token | Normalized key | Target structure |
|---|---|---|
| "cái đầu tiên", "đầu tiên", "first", "cái thứ 1" | `"first"` | reference_table |
| "cái thứ hai", "thứ hai", "second", "cái thứ 2" | `"second"` | reference_table |
| "cái thứ ba", "thứ ba", "third", "cái thứ 3" | `"third"` | reference_table |
| "cái cuối", "cuối cùng", "last" | `"last"` | reference_table |
| "nó", "cái này", "cái đó", "sản phẩm này", "sản phẩm đó" | — | entity_registry → memory → stack → tool_history |
| "cái trước", "quay lại", "trước đó" | — | reference_stack |

---

### 7.7 Query Rewriter

**Mục đích:** Thay thế tokens mơ hồ trong query bằng tên/ID cụ thể trước khi đưa vào agent, giúp LLM planner không phải suy luận.

#### Cơ chế

```python
def rewrite_query(
    query: str,
    resolved: dict[str, Any],
) -> tuple[str, dict]:
    """
    Input:  "Cho tôi xem cái đầu tiên"
    Output: "Cho tôi xem Dell XPS 13"
            entities = {product_id: "P001", resolved_query: "Cho tôi xem Dell XPS 13"}
    """
    new_query = query
    entities_override = {}
    
    for token, value in resolved.items():
        if not value:
            continue
        
        # CASE 1: Token là ordinal → thay bằng tên sản phẩm
        if isinstance(value, dict) and value.get("name"):
            new_query = new_query.replace(token, value["name"])
            entities_override["product_id"] = value["id"]
            entities_override["product_name"] = value["name"]
        
        # CASE 2: Token là entity ID → inject into entities
        elif isinstance(value, dict) and value.get("id"):
            entities_override["product_id"] = value["id"]
            # Không rewrite query text (giữ "nó")
        
        # CASE 3: Token resolve thành scalar (e.g. quantity)
        elif isinstance(value, (str, int, float)):
            entities_override["product_id"] = str(value)
    
    return new_query, entities_override
```

#### Ví dụ

| User query | Resolved token | Query sau rewrite | entities bổ sung |
|---|---|---|---|
| "Cho tôi xem cái đầu tiên" | `first → {id:P001, name:Dell XPS 13}` | "Cho tôi xem Dell XPS 13" | `product_id=P001` |
| "Thêm nó vào giỏ" | `nó → {id:P005, name:Telescope}` | "Thêm Telescope vào giỏ" | `product_id=P005` |
| "Review cái thứ hai" | `second → {id:P002, name:Inspiron}` | "Review Inspiron" | `product_id=P002` |
| "Cái cuối cùng có màu gì?" | `last → {id:P008, name:Zenbook}` | "Zenbook có màu gì?" | `product_id=P008` |
| "Quay lại cái trước" | stack pop → `{id:P003, name:Latitude}` | (giữ nguyên, inject entities) | `product_id=P003` |

#### Lợi ích

- LLM planner thấy "Dell XPS 13" thay vì "cái đầu tiên" → không cần suy luận
- Tool Executor nhận `product_id=P001` → resolve chính xác
- Giảm hallucination do LLM đoán sai tham chiếu
- Agent không cần đọc lại lịch sử chat để hiểu "nó" là gì

---

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
7. **Reference Updater**: gọi `reference_updater` với normalized output → cập nhật `reference_table`, `reference_stack`, `entity_registry`, `last_tool_outputs` trong state (xem §7.3)

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
| Write tool (add_to_cart) | 1 | Không retry write tool — tránh ghi đúp dữ liệu |

Output normalization: gọi `normalize_product()` trên từng item trong `products`/`items` array — gộp price units/nanos → price string.

### 8.5 Reference Updater (inline trong Tool Executor)

**Implementation:** Nhúng trong `graph/nodes/tool_executor.py` — hàm `_update_planner_memory()`.

Node này chạy **sau mỗi tool execution** và **trước khi reflection**. Nó không quyết định luồng (không routing) — chỉ cập nhật state phục vụ reference resolution ở turn sau.

#### Interface

```python
async def reference_updater_node(state: ShoppingState) -> dict:
    """
    Cập nhật reference structures sau mỗi tool execution.
    
    Output:
        last_tool_outputs: list   # Append tool output mới
        reference_table: dict     # Rebuild từ tool output mới nhất
        reference_stack: list     # Push current result lên stack
        entity_registry: dict     # Merge entities mới
        node_durations: dict
    """
```

#### Pipeline

```
reference_updater_node(state)
    │
    ├── 1. tool_output = state.tool_results mới nhất
    ├── 2. build_reference_table(tool_output)
    │       → state.reference_table = new_table
    ├── 3. push_reference_stack(tool_output)
    │       → state.reference_stack.append(tool_output)
    │       → Giới hạn stack depth = 10
    ├── 4. update_entity_registry(tool_output)
    │       → Extract entities (product names, IDs)
    │       → Merge vào state.entity_registry (không ghi đè)
    └── 5. update_last_tool_outputs(tool_output)
            → state.last_tool_outputs = [tool_output] + old[:4]
            → Giữ tối đa 5 outputs gần nhất
```

#### Trigger conditions

| Condition | Hành động |
|---|---|
| Tool output có `products[]` hoặc `items[]` | Build reference_table + push stack |
| Tool output có product ID | Update entity_registry |
| Tool output rỗng (error/pending) | Skip — không cập nhật |
| Multiple nodes trong 1 DAG | Chạy sau **tất cả** nodes (sau tool_executor hoàn thành toàn bộ DAG) |

---

### 8.6 Reflection Node

**File:** `graph/nodes/reflection.py`

#### Vai trò

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

#### Khi nào trigger replan?

| Trigger | Điều kiện | Hành động |
|---|---|---|
| **0 kết quả** | Node search/review/recommend trả `total=0` hoặc empty list | Replan: thử query khác, bỏ filter, hoặc thông báo user |
| **Tool lỗi liên tục** | ≥2 tool errors trong cùng 1 DAG run | Replan: chọn tool fallback hoặc đơn giản hoá plan |
| **Confidence thấp** | `plan_confidence < 0.5` sau execution | Replan: xác nhận lại intent với user |
| **Missing dependency** | Node A cần output node B nhưng B lỗi | Replan: bỏ node phụ thuộc, chạy alternative path |
| **Semantic gate fail** | `semantic_hallucination_detected = True` | Replan: yêu cầu TGB sinh plan mới với tool khác |

Tất cả trigger đều có threshold riêng và được kiểm soát bởi `replan_gate` (Nova Lite, §10.6) — không replan mù.

#### Partial Replan (không restart full DAG)

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

#### Thuật toán

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

#### Graph edges với Reflection

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

#### Cost

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

### Các kiểu claim check (L1 — Exact)

HallucinationGuard chỉ phụ trách các check exact deterministic. Mọi nghi ngờ semantic/entity đẩy xuống **Semantic Hallucination Gate** (Nova Lite, §10.6).

| Check | Pattern / Cơ chế | Nguồn (tool_results) | Hard Rule | Trọng số |
|---|---|---|---|---|
| **Price** | `\$\d+(?:\.\d{2})?` hoặc `\d+\s*USD` | `products[].price`, `items[].price`, `total` | Mọi price trong answer phải exact match | 0.15 |
| **Entity** | List intersection: set answer token {product_name, category} ∩ known_set | `products[].name`, `categories`, `items[].name` | Mọi entity token không trong known set → violation. Nếu total=0, mọi mention đều violation | **0.40** |
| **Count** | `"(\d+)\s*(sản phẩm\|kết quả\|đánh giá\|món)"` | `total`, `len(reviews)`, `len(products)` | Exact number match | 0.15 |
| **Score** | `"(\d+\.?\d*)\s*[/\\]\s*5"` hoặc `"(\d+\.?\d*)\s*sao"` | `average_score` | Match với ±0.1 tolerance | 0.15 |
| **Action confirm** | `"đã thêm"`, `"đã xoá"`, `"đã cập nhật"` | `pending_action` status, `confirmed` field | Chỉ cho phép nếu action đã confirm | 0.15 |
| **Semantic (attribute claim)** | ❌ ĐÃ XOÁ — chuyển sang Semantic Hallucination Gate (§10.6) | — | — | — |

> **Lưu ý:** Entity check dùng **list intersection**, không dùng "token viết hoa" — tiếng Việt không viết hoa danh từ chung. Các claim semantic attribute (chất liệu, tính năng, phù hợp...) được chuyển hoàn toàn sang Semantic Hallucination Gate (Nova Lite) vì regex không đáng tin.

### Groundedness Score — Thuật toán

1. **Input**: `answer` (string từ ResponseVerifier), `tool_results`, `pending_action`
2. **Kiểm tra lần lượt các claim type** — mỗi violation trừ penalty khỏi groundedness score (bắt đầu từ 1.0, clamp [0, 1]):

| Check | Phương pháp | Penalty |
|---|---|---|
| **Price** | Regex `\$\d+(?:\.\d{2})?` → từng price phải exact match với tool_results | -0.15 |
| **Entity** | List intersection: set answer token ∩ known_set; nếu total=0 → mọi mention đều violation (-0.50) | -0.40 |
| **Count** | Regex `(\d+)\s*(sản phẩm\|kết quả\|đánh giá\|món)` → exact number match với tool data | -0.15 |
| **Score** | Regex `(\d+\.?\d*)\s*/?\s*5` → match ±0.1 tolerance | -0.15 |
| **Action confirm** | Regex `(đã thêm\|đã xoá\|đã cập nhật)` → chỉ cho phép nếu action đã confirm | -0.15 |
| **Semantic attribute** | ❌ ĐÃ XOÁ — Semantic Hallucination Gate (§10.6) | — |

3. **Entity Verification (List Intersection)**:
   - Build `known_set` từ `tool_results`: gom `products[].name`, `products[].categories`, `items[].name`
   - Extract candidate tokens từ answer: danh từ, cụm danh từ (regex: `\b[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]{2,}\b`)
   - Loại stop words (và, của, các, the, a, an...)
   - Token nào không trong `known_set` → entity violation
   - Nếu `known_set` rỗng và `total>0` → skip (không có đối chiếu)
4. **Quyết định**:
   - `groundedness_score >= 0.8` → PASS → chuyển sang Semantic Hallucination Gate (per-claim)
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
                       ├── không còn claim nghi ngờ → AnswerGenerator → END
                       └── còn N claims cần kiểm tra ngữ nghĩa
                            → asyncio.gather(semantic_hallucination_gate(c1..cN))
                                 → tất cả PASS → AnswerGenerator → END
                                 → bất kỳ FAIL → semantic_hallucination_detected
                                               → FALLBACK_GENERATOR → AnswerGenerator → END
                       ↓ fail (groundedness < 0.8)
                  FALLBACK_GENERATOR → AnswerGenerator → END
```

> `semantic_hallucination_gate` dùng Amazon Nova Lite, timeout 2s, cost ~$0.000019/claim. Chi tiết xem §10.6.

### Cost

| Item | Cost | Latency | Trigger rate |
|---|---|---|---|
| HallucinationGuard | **$0** (rule-based regex) | <3ms | ~40% request (LLM path) |
| Semantic Hallucination Gate | ~$0.000019/claim (Nova Lite) | ~150ms | ~3-5 claims, ~20% request |
| FallbackGenerator | **$0** (template render) | <1ms | ~5% request |

### Skip Conditions

| Condition | Hành động |
|---|---|
| Không có tool_results | Auto PASS (score=1.0, không claims để check) |
| Answer trống | Auto PASS (giữ nguyên) |
| Fallback cũng fail | Không thể — template là static, đã grounded |
| Confirmation pending | Fallback dùng template confirm, không check |
| Guardrail violation trước đó | Giữ nguyên message guardrail |
| known set rỗng + total>0 | Entity check không có đối chiếu → no entity violations |
| known set rỗng + total=0 | Mọi entity token trong answer → entity_zero_result violation |
| HallucinationGuard PASS nhưng còn claim semantic | Đẩy sang Semantic Hallucination Gate (§10.6) |

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

Nova Lite là điểm cân bằng: đắt hơn Micro ~1.7x nhưng vẫn rẻ hơn Bedrock Claude 10-100 lần, trong khi độ tin cậy phân loại nhị phân tốt hơn rõ rệt so với Micro theo benchmark public của Bedrock.

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
| `plan_validity_gate` | Sau Planner, trước Tool Executor | "Plan này có đủ step để trả lời intent gốc, không thiếu dependency?" | Có | Luôn chạy nếu `len(plan) > 1` (plan đơn bước bỏ qua) |
| `semantic_hallucination_gate` | Sau HallucinationGuard §10.5, chỉ khi **pass** rule-based | "Claim '<X>' có thực sự được suy ra từ tool output này, hay là LLM tự suy diễn?" | Có | Chỉ chạy trên **claim còn lại sau rule-based** (không phải toàn bộ answer) — xem §10.6.1 |
| `confirm_parse_gate` | `confirmation.py`, khi resume | "Phản hồi của user có phải là đồng ý xác nhận hành động không?" | Không | Thay cho parse cứng "ừ/ok/được" — bắt được biến thể ngôn ngữ tự nhiên |
| `replan_gate` | Reflection (sau Tool Executor, khi có lỗi/0 kết quả) | "Kết quả hiện tại có đạt được goal ban đầu không, hay cần replan?" | Có | Chỉ chạy khi tool trả `total=0` hoặc lỗi liên tục ≥2 lần |

> **Ghi chú:** Routing gate (fast path detection) không tồn tại dưới dạng file riêng — logic fast path được xử lý inline trong `response_verifier.py` thông qua Strategy Decision Tree (§10).

Nguyên tắc chung: **Gate chỉ chạy khi rule-based không đủ tự tin xử lý** — không thay thế L1-L6 hay HallucinationGuard, mà là lớp bổ sung phía sau, giữ nguyên "zero-cost path" cho phần lớn request (Design Principle #3).

### 10.6.1 Semantic gate không thay HallucinationGuard — chạy tiếp nối

Rule-based (§10.5) chạy trước, **miễn phí**, loại được phần lớn hallucination surface-level (giá sai, entity không tồn tại). Semantic gate chỉ chạy trên phần **claim đã pass rule-based** để bắt loại hallucination tinh vi hơn — claim đúng từ khoá nhưng sai ý nghĩa (VD: tool ghi "phù hợp người mới bắt đầu", answer diễn giải thành "tốt nhất cho chuyên gia thiên văn"). Vì vậy số lượng claim đưa vào semantic gate luôn nhỏ hơn hoặc bằng số claim ban đầu, giữ cost thấp.

### Cost per Gate call (Nova Lite, tính theo pricing thực tế ở trên)

| Gate | Input tokens (ước tính) | Output tokens | Cost/call |
|---|---|---|---|
| `plan_validity_gate` | ~400 (plan JSON + tool schema tóm tắt) | ~20 (có reason) | ~$0.000029 |
| `semantic_hallucination_gate` | ~250/claim (claim + tool snippet) | ~18 (có reason) | ~$0.000019/claim |
| `confirm_parse_gate` | ~100 (user reply + instruction) | 1 | ~$0.000006 |
| `replan_gate` | ~350 (goal + tool_results tóm tắt) | ~18 (có reason) | ~$0.000025 |

**Worst case per request** (plan_validity + 2 semantic claims + replan, tất cả cùng trigger — hiếm gặp): `0.000029 + 2×0.000019 + 0.000025 ≈ $0.000092` — vẫn nhỏ hơn 1 lần gọi ResponseVerifier sinh câu trả lời tự do (~$0.0002-0.0006 tuỳ độ dài, xem §18).

**Typical case** (chỉ `semantic_hallucination_gate` chạy trên 1-2 claim, các gate khác skip vì rule đã đủ tự tin): **~$0.00002-0.00004/request** — tăng chưa tới 0.05₫ mỗi request so với v3 hiện tại.

### Trade-off

| Điểm | Được | Mất |
|---|---|---|
| **Coverage** | Bắt được hallucination ngữ nghĩa mà regex không thấy (claim đúng từ khoá, sai ý) | Nova Lite vẫn có thể đoán sai ở case mơ hồ ranh giới (không phải oracle) — cần theo dõi false positive/negative qua log `reason` |
| **Cost** | Rẻ hơn 5-20x so với gọi lại full LLM answer để re-verify | Vẫn là chi phí cộng thêm so với rule-based thuần ($0 trước đây) |
| **Latency** | 1 Gate call Nova Lite thường 150-400ms — nhanh hơn nhiều so với 1 lần sinh answer đầy đủ | Nếu 3-4 gate trigger cùng lúc và chạy tuần tự, cộng dồn latency đáng kể → nên chạy song song (`asyncio.gather`) các gate độc lập (VD: `plan_validity_gate` và `confirm_parse_gate` không phụ thuộc nhau) |
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

    # ── Reflection (§8.6) ──
    reflection_result: str             # "pass" | "replan"
    reflection_issues: list            # [{"type": "zero_result", "node": "n0", ...}]

    # ─️─ Confidence ──
    confidence: float                  # 0.0-1.0 — overall confidence của cả lượt
    retry_count: int                   # Số lần retry (accumulated)

    # ── Planner Memory (ngắn hạn, §7) ──
    planner_memory: dict               # {"last_search": "...", "last_product_id": "...", "current_cart_items": 0, "last_intent": "..."}

    # ── Reference Resolution (§7.3-§7.7) ──
    last_tool_outputs: list            # [{"type": "product_list", "items": [{"index":1, "id":"P001", "name":"Dell XPS 13", ...}], "tool_name": "search_products_v2"}]
    reference_table: dict              # {"first": {"id":"P001","name":"Dell XPS 13"}, "second": {...}, "1": {...}, "last": {...}}
    reference_stack: list              # Stack các recent tool outputs — pop() cho "quay lại cái trước"
    entity_registry: dict              # {"iphone16": {"id":"P123","type":"product"} — cross-turn entity mapping
    resolved_query: str                # Query đã rewrite bởi Reference Resolver (hoặc giữ nguyên)
    resolved_entities: dict            # Entities đã bổ sung sau khi resolve (ghi đè entities gốc nếu cần)

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
    errors: Annotated[list, accumulate_errors]   # [{node: node_id, error: message}]

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
| `last_tool_outputs` | — | ✅ New | Structured tool output với index/type/items (§7.3) |
| `reference_table` | — | ✅ New | Ordinal mapping "first"/"1"/"last" → item (§7.5) |
| `reference_stack` | — | ✅ New | Stack các recent tool outputs (§7.4) |
| `entity_registry` | — | ✅ New | Cross-turn entity mapping (§7.4) |
| `resolved_query` | — | ✅ New | Query đã rewrite bởi Reference Resolver (§7.7) |
| `resolved_entities` | — | ✅ New | Entities sau khi resolve (§7.7) |
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
3. Không phải write tool (`add_to_cart_tool`, `update_cart_item_tool`)
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

### 13.12 CacheManager — 2-Layer Architecture

**File:** `memory/cache_manager.py` (MỚI)

CacheManager bọc cả Redis (primary) và in-memory (fallback). Redis unavailable → tự động fallback local, không throw exception.

```
CacheManager:
  Layer 1 (primary): Redis — global cache, cluster-wide
  Layer 2 (fallback): In-memory (OrderedDict LRU) — local fallback khi Redis down
  
  Circuit breaker: 2 lần health check fail liên tiếp → mở circuit 30s
                   → HALF-OPEN → OK → CLOSED; Fail → OPEN lại 30s
```

### Migration từ in-memory sang Redis

| Giai đoạn | Cache | Layer 1 (primary) | Layer 2 (fallback) |
|---|---|---|---|
| Dev/Test | Tool cache | In-memory (`InMemoryCacheStore`) | — |
| Production | Planner + Tool | Redis DB0 + DB1 | In-memory (khi Redis down) |
| Production | Session | Redis DB2 | In-memory (khi Redis down) |

```
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHE_ENABLED = env("CACHE_ENABLED", "true")
```

File mới: `memory/cache_manager.py` + `memory/redis_store.py`.

### 13.13 Global Rate Limiter (Redis)

Rate limiter hiện tại: in-memory per-pod. Production chuyển global dùng Redis sorted set, fallback per-pod khi Redis down.

```
Key: ratelimit:{user_id}:{date}
Score: timestamp
Query: ZCOUNT key now-60 +inf → count > MAX_PER_MINUTE → block
Fallback → in-memory per-pod (hiện tại) khi Redis unavailable
```

Chi tiết cache: `cache_design.md`.

---

## 13a. Resource Limits & Production Guardrails

Các giới hạn cứng (hard limits) để đảm bảo hệ thống ổn định trong production, ngăn DAG mở rộng quá mức, LLM lặp lại nhiều lần, hoặc backend bị quá tải.

### 13a.1 Max Tool Calls

Một request tối đa **≤ 8 tool calls** (tổng số node trong DAG).

```
Ví dụ hợp lệ: search → product → review → recommend → currency → shipping → cart
```

Nếu vượt: Planner phải ưu tiên hoặc hỏi user, không execute mù.

### 13a.2 Max DAG Depth

**≤ 5 levels** (độ sâu tối đa của dependency chain).

Nếu sâu hơn: Planner phải chia nhỏ.

### 13a.3 Max Parallel Nodes

**≤ 4** nodes chạy đồng thời trong một batch `asyncio.gather`.

Lý do: tránh 20+ gRPC call cùng lúc đến backend (EKS microservices không có connection pool đủ lớn).

### 13a.4 Replan Limit

**Max Replan = 2** mỗi request. Sau 2 lần replan, dù kết quả thế nào cũng force pass.

Implementation trong `reflection.py`: nếu `replan_count >= 2` → force `reflection_result = "pass"`.

### 13a.5 Retry Strategy

| Loại tool | Retry | Ghi chú |
|---|---|---|
| Read tool (search, product, review, recommend, currency) | **2 lần** | Exponential backoff (0.5s, 1s) |
| Write tool (add_to_cart, update_cart_item) | **1 lần** | Retry tối đa 1 lần nếu timeout/network error; không retry nếu đã confirm thành công — tránh ghi đúp |
| Checkout | **0 lần** | Fail → báo user, không retry mù |

### 13a.6 LLM Timeout

| LLM Call | Timeout | Hành động khi timeout |
|---|---|---|
| Planner (Task Graph Builder) | **5s** | Fallback → template response |
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

### 13a.9 Conversation History & Sliding Reference Window

Không gửi toàn bộ lịch sử cho LLM. Giới hạn:
- **6 lượt gần nhất** (kế thừa từ `SessionStore._SESSION_MAX_MESSAGES`)
- Hoặc **2000 token** (whichever comes first)
- **Sliding Reference Window**: lưu **last 5 assistant outputs** + **last 3 tool outputs** cho Reference Resolver tra cứu
  - >90% tham chiếu ("nó", "cái đó", "cái đầu tiên", "cái cuối") nằm trong vài lượt gần nhất
  - Không cần quét toàn bộ session history

### 13a.10 Planner Memory

Giới hạn dung lượng: **20 KB** mỗi session.

Memory gồm các field cố định: `last_search`, `last_product_id`, `current_cart_items`, `last_intent`, và các field reference (`last_tool_outputs`, `reference_table`, `reference_stack`, `entity_registry`).

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
| 31 | Semantic hallucination check | semantic_hallucination_gate | Answer says "phù hợp chuyên gia" but description says "cho người mới" | Nova Lite → NO → fallback template |
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
| Intent Parser (LLM fallback) | LLM chính (Bedrock Nova Lite) | ~20-100 tokens, rất nhỏ |
| Task Graph Builder | LLM chính (Bedrock Nova Lite) | AWS Bedrock on-demand: **$0.06 / 1M input tokens, $0.24 / 1M output tokens** |
| Response Verifier (LLM path) | LLM chính (Bedrock Nova Lite) | Chỉ khi complexity > 0.5 |
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
| 2 | ~~Rate limiter per-pod~~ | ~~User bypass qua replicas~~ | ✅ Đã giải quyết — Redis-backed global rate limiter + in-memory per-pod fallback. Chi tiết `cache_design.md` Global Rate Limiter |
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
| 14 | ~~Reference resolution embedded trong Planner~~ | ~~LLM phải suy luận "nó"/"cái đầu tiên" — tốn token, dễ hallucinate~~ | ✅ Đã giải quyết — Reference Resolver node riêng (§7.4) + Reference Table (§7.5) + Priority Chain (§7.6) + Query Rewriter (§7.7) |

### Roadmap

**Phase 1 — 2-Layer Planner + DAG Core (Week 1) ✅ Complete**
- ✅ `graph/nodes/task_graph_builder.py` — 2-Layer Planner: rule-based intent parsing + LLM DAG builder
- ✅ `graph/nodes/tool_executor.py` — DAG runner (parallel, conditional, variable helpers, reference resolve inline)
- ✅ `graph/nodes/reflection.py` — Post-execution check → partial replan
- ✅ `graph/nodes/response_verifier.py` — Template-First + LLM fallback
- ✅ `graph/main_graph.py` — DAG-centric topology, 11 nodes + conditional edges
- ✅ `graph/state.py` — ShoppingState v3.2 (⚠️ thiếu 6 reference fields — cần bổ sung)
- ✅ `llm/prompt.py` — TGB prompt + Verifier prompt + Gate prompts
- ❌ Tách `reference_resolver` + `reference_updater` thành node riêng (design ready, code đang inline trong executor)

**Phase 2 — Hallucination Guard + Gate Layer (Week 2) ✅ Complete**
- ✅ `graph/nodes/hallucination_guard.py` — Rule-based exact checks (price/entity/count/score/action)
- ✅ `graph/nodes/fallback_generator.py` — Template fallback
- ✅ `graph/gates/` — gate_node (Nova Lite) + 4 gates (plan_validity, semantic_hallucination, confirm_parse, replan)
- ✅ Template set hoàn chỉnh (cart, shipping, currency, reviews, search, confirm)
- ✅ Integration tests (TGB → executor → reflection → verifier → guard)

**Phase 3 — Production (Week 3) 🔄 In Progress**
- ✅ `memory/redis_store.py` — RedisCacheStore implementation (§13)
- ✅ `memory/cache_manager.py` — 2-layer CacheManager (Redis + in-memory fallback, circuit breaker)
- ⏳ Valkey/Redis for rate limiter + session store
- ⏳ Cache invalidation via Redis Pub/Sub (§13.10)
- ⏳ Enforce resource limits trong ToolExecutor (§13a): max tool calls, DAG depth, parallel nodes, timeout
- ⏳ OpenTelemetry metrics cho cache hit rate + resource limit counters (§13b)
- ⏳ Load test P95 < 5s (§13a.8)
- ⏳ Circuit breaker cho Nova Lite Gate calls

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