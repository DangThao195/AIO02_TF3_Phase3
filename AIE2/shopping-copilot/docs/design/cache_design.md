# Cache Strategy — Redis 3 DB

> **Phase 3 — Integration & Production** | *Files: `memory/cache_manager.py`, `memory/redis_store.py`*

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
| L4 External | Currency rate, shipping quote, recommendation | 5-60 phút (tuỳ loại) | DB1 | `currency:{from}:{to}`, `shipping:{sha256(zip+total)[:16]}`, `recommend:{id}:{limit}` |
| L5 Session | Planner memory (last_search, current_cart, history) | 30 phút | DB2 | `session:{session_id}` |

## Redis Configuration

| DB | Purpose | Eviction Policy | Maxmemory |
|---|---|---|---|
| DB0 | Planner | `noeviction` | 256 MB |
| DB1 | Tool | `allkeys-lru` | 2 GB |
| DB2 | Session | `volatile-ttl` | 512 MB |

## CacheManager — 2-Layer Architecture

**File:** `memory/cache_manager.py` (MỚI)

CacheManager bọc cả Redis (primary) và in-memory (fallback). Redis luôn được ưu tiên; nếu Redis unavailable → tự động fallback về in-memory mà không throw exception.

```python
class CacheManager:
    """
    2-layer Cache Manager:
    - Layer 1 (primary): Redis — dùng cho production, global state
    - Layer 2 (fallback): In-memory — local fallback khi Redis down
    Cả 2 layer luôn khởi tạo; Redis health check quyết định layer nào dùng.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._redis = RedisCacheStore(redis_url) if redis_url else None
        self._local = InMemoryCacheStore()   # Luôn available
        self._circuit_open = False            # Circuit breaker state
        self._circuit_failures = 0
        self._last_health_check = 0.0

    async def _redis_healthy(self) -> bool:
        """Kiểm tra Redis health với circuit breaker."""
        now = time.time()
        if self._circuit_open and now - self._last_health_check < 30:
            return False                       # Circuit open, skip ping
        if now - self._last_health_check < 5:
            return not self._circuit_open      # Dùng cache health gần nhất
        self._last_health_check = now
        if self._redis:
            try:
                await asyncio.wait_for(self._redis.ping(), timeout=1.0)
                self._circuit_open = False
                self._circuit_failures = 0
                return True
            except Exception:
                self._circuit_failures += 1
                if self._circuit_failures >= 2:
                    self._circuit_open = True  # Mở circuit sau 2 lần fail liên tiếp
                return False
        return False

    async def get(self, key: str, db_type: str) -> Optional[Any]:
        if await self._redis_healthy():
            return await self._redis.get(key, db_type)
        return self._local.get(key)

    async def set(self, key: str, value: Any, db_type: str, ttl: int) -> None:
        # Luôn ghi vào local (backup)
        self._local.set(key, value, db_type, ttl)
        if await self._redis_healthy():
            await self._redis.set(key, value, db_type, ttl)

    async def delete(self, key: str, db_type: str) -> None:
        self._local.delete(key)
        if await self._redis_healthy():
            await self._redis.delete(key, db_type)
```

### RedisCacheStore (primary)

**File:** `memory/redis_store.py` — giữ nguyên thiết kế cũ

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

### InMemoryCacheStore (fallback)

**File:** `memory/store.py` — giữ nguyên `CacheStore` hiện tại, thêm interface `get(key, db_type)` / `set(key, value, db_type, ttl)`. Dùng `OrderedDict` LRU, max entries tuỳ DB type.

### Circuit Breaker State Machine

```
CLOSED (Redis hoạt động)
  └── 2 lần health check fail liên tiếp
       → OPEN (30s không gọi Redis)
            └── Sau 30s → HALF-OPEN (thử 1 ping)
                 ├── OK → CLOSED
                 └── Fail → OPEN lại 30s
```

### Migration từ In-Memory

| Giai đoạn | Cache | Layer 1 (primary) | Layer 2 (fallback) |
|---|---|---|---|
| Dev/Test | Tool cache | In-memory (`CacheStore`) | — |
| Production | Planner + Tool | Redis DB0 + DB1 | In-memory (khi Redis down) |
| Production | Session | Redis DB2 | In-memory (khi Redis down) |

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

## Global Rate Limiter (Redis)

**File:** `guardrails/rate_limiter.py` (mở rộng)

Rate limiter hiện tại dùng in-memory per-pod — dễ bị bypass qua multi-replica. Chuyển global rate limiter dùng Redis sorted set, fallback về per-pod khi Redis down.

### Redis-backed rate limiter

```python
class RedisRateLimiter:
    """
    Global rate limiter dùng Redis sorted set.
    Fallback: in-memory per-pod (hiện tại) khi Redis unavailable.
    """
    
    def __init__(self, redis: Optional[RedisClient]):
        self._redis = redis
        self._local = InMemoryRateLimiter()  # fallback

    async def check(self, user_id: str) -> RateLimitResult:
        if self._redis and await self._redis.healthy():
            return await self._check_redis(user_id)
        return self._local.check(user_id)    # fallback per-pod
    
    async def _check_redis(self, user_id: str) -> RateLimitResult:
        now = int(time.time())
        key = f"ratelimit:{user_id}:{now // 86400}"
        pipe = self._redis.pipeline()
        # Thêm timestamp hiện tại
        pipe.zadd(key, {now: now})
        # Xoá entries cũ hơn 60s
        pipe.zremrangebyscore(key, 0, now - 60)
        # Đếm số request trong 60s
        pipe.zcard(key)
        # Set TTL 24h cho key
        pipe.expire(key, 86400)
        _, _, count, _ = await pipe.execute()
        
        if count > MAX_PER_MINUTE:
            return RateLimitResult(blocked=True, reason="Quá nhiều tin nhắn trong 1 phút")
        # Kiểm tra daily limit (hash riêng)
        # ...
```

### Fallback behavior

| Redis status | Rate limiter | Ghi chú |
|---|---|---|
| Available | Global (Redis sorted set) | Chính xác, multi-replica |
| Unavailable | Per-pod (in-memory) | User có thể gửi N×replicas req/phút — acceptable trong thời gian ngắn |
| Recovered | Global (Redis) | Auto-detect qua circuit breaker |
