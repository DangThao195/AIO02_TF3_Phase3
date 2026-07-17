# Cache Strategy — Redis 3 DB

> **Phase 3 — Integration & Production** | *File: `memory/redis_store.py`*

## Architecture

```
                    LangGraph
                        │
                 Cache Manager
                        │
          ┌─────────────┼─────────────┐
     Planner Cache   Tool Cache    Session Cache
     (DB0)           (DB1)         (DB2)
     DAG Plans       Search/       Planner Memory
                     Product/
                     Currency/
                     Shipping/
                     Recommend
```

## Cache Types

| Cache | Data | TTL | Redis DB | Key Pattern |
|---|---|---|---|---|
| L1 Planner | DAG plan (nodes + edges) | 5 phút | DB0 | `planner:{sha256(query)[:16]}` |
| L2 Search | Top N Product IDs | 10 phút | DB1 | `search:{sha256(lang+query+price+cat)[:16]}` |
| L3 Product | Product detail (name, price, description, rating, image) | 30 phút | DB1 | `product:{product_id}` |
| L4 External | Currency rate, shipping quote, recommendation | 30-60 phút | DB1 | `currency:{from}:{to}`, `shipping:{sha256(zip+total)[:16]}`, `recommend:{id}:{limit}` |
| L5 Session | Planner memory (last_search, current_cart, history) | 30 phút | DB2 | `session:{session_id}` |

## Redis Configuration

| DB | Purpose | Eviction Policy | Maxmemory |
|---|---|---|---|
| DB0 | Planner | `noeviction` | 256 MB |
| DB1 | Tool | `allkeys-lru` | 2 GB |
| DB2 | Session | `volatile-ttl` | 512 MB |

## Cache Manager Interface

**File:** `memory/redis_store.py`

```python
class RedisCacheStore:
    def __init__(self, redis_url: str):
        self._redis = redis.from_url(redis_url)

    # ── Planner Cache ──
    async def get_plan(self, query: str) -> Optional[dict]: ...
    async def set_plan(self, query: str, plan: dict, confidence: float) -> None:
        """Chỉ cache nếu confidence >= 0.9"""
        ...

    # ── Tool Cache ──
    async def get_tool(self, tool_name: str, params: dict) -> Optional[Any]: ...
    async def set_tool(self, tool_name: str, params: dict, result: Any) -> None:
        """Chỉ cache read tools, không cache write"""
        ...

    # ── Session Cache ──
    async def get_session(self, session_id: str) -> Optional[dict]: ...
    async def set_session(self, session_id: str, data: dict) -> None: ...
    async def update_planner_memory(self, session_id: str, memory: dict) -> None: ...

    # ── Cache Invalidation ──
    async def invalidate_product(self, product_id: str) -> None:
        """Xoá product:{id} + flush search:* + recommend:*"""
        ...
```

## Cache Conditions

**Chỉ cache sau khi:**
1. Tool thành công (`status = success`)
2. Output hợp lệ theo schema
3. Không phải write tool (`add_to_cart_tool`, `checkout_tool`)
4. Cache planner: `plan_confidence >= 0.9`
5. Không cache plan rỗng/denied

## Key Conventions

| Cache | Key | Example |
|---|---|---|
| Planner | `planner:{sha256(query)}` | `planner:a1b2c3d4e5f6g7h8` |
| Search | `search:{sha256(lang+query+price_range+cat)}` | `search:f9e8d7c6b5a4` |
| Product | `product:{id}` | `product:P001` |
| Currency | `currency:{from}:{to}` | `currency:USD:VND` |
| Shipping | `shipping:{sha256(zip+cart_total)}` | `shipping:abc123` |
| Recommend | `recommend:{product_id}:{limit}` | `recommend:P001:5` |
| Session | `session:{session_id}` | `session:550e8400-e29b-...` |

Hash toàn bộ query/params bằng SHA256, lấy 16 ký tự đầu.

## Cache Invalidation

**Passive:** TTL tự động hết hạn — đủ cho hầu hết use case.

**Event-driven (khi admin sửa sản phẩm):**
```
ProductUpdated Event → Redis Pub/Sub → xoá:
  - product:{product_id}
  - search:* (flush search cache)
  - recommend:* (flush recommend cache)
```

## Migration từ In-Memory

| Giai đoạn | Cache | Storage |
|---|---|---|
| Dev/Test | Tool cache | In-memory (`CacheStore` hiện tại) |
| Production | Planner + Tool | Redis DB0 + DB1 |
| Production | Session | Redis DB2 |

```python
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHE_ENABLED = env("CACHE_ENABLED", "true")
```

## Cost & Performance

| Cache | Est. Hit Rate | Latency Saved |
|---|---|---|
| Planner | > 50% | ~150ms (1 LLM call) |
| Search | > 60% | ~200ms (1 gRPC call) |
| Product | > 80% | ~100ms (1 gRPC call) |
| Currency/Shipping | > 70% | ~100-300ms |
