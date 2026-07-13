# 🚀 End-to-End Testing Guide

## Prerequisites

✅ Hoàn thành:
- [x] Multi-strategy search module (`tools/search/`)
- [x] All 16 unit tests passing
- [x] LLM client (Groq integration)
- [x] Query analyzer + synonym expansion

## Setup (Chi tiết từng bước)

### Step 1: Tạo `.env` file từ template

```bash
cd H:\Phase3-TF3-Infra-Sentinel\shopping-copilot

# Copy .env.example → .env
cp .env.example .env
```

### Step 2: Set GROQ_API_KEY

**Option A: Set trong .env file**
```
# .env
GROQ_API_KEY=gsk_your_actual_api_key_here
```

**Option B: Set via PowerShell (tạm thời cho session này)**
```powershell
$env:GROQ_API_KEY="gsk_your_actual_api_key_here"
```

**Option C: Set permanent Windows environment variable**
```powershell
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "gsk_...", "User")
```

### Step 3: Setup gRPC Port-Forward (nếu product-catalog trên EKS)

**Open terminal mới:**
```bash
kubectl port-forward svc/product-catalog 3550:3550
```

**Output sẽ như:**
```
Forwarding from 127.0.0.1:3550 -> 3550
Forwarding from [::1]:3550 -> 3550
Handling connection for 3550
```

**Giữ terminal này mở** trong lúc test.

### Step 4: Cài dependency (nếu chưa)

```bash
pip install python-dotenv
```

---

## Running Tests

### Mode 1: Single Query Test

```bash
# Test Vietnamese query
python tools/search/test_e2e.py "kính thiên văn dưới 100 đô"

# Test English query
python tools/search/test_e2e.py "telescope under 100"

# Test price filter
python tools/search/test_e2e.py "từ 50 đến 200 đô"
```

### Mode 2: Batch Test (Multiple Queries)

```bash
python tools/search/test_e2e.py --batch
```

Chạy 6 queries predefined:
1. "kính thiên văn"
2. "kính thiên văn dưới 100 đô"
3. "ống nhòm rẻ nhất"
4. "sách từ 20 đến 50 đô"
5. "đèn pin"
6. "telescope dưới 500"

### Mode 3: Custom Batch

```bash
python tools/search/test_e2e.py "query1" "query2" "query3"
```

---

## Expected Output

### Success Case (with real gRPC)

```
================================================================================
QUERY: kính thiên văn dưới 100 đô
================================================================================

[Phase 1] QUERY PARSING
  ✓ Category: telescopes
  ✓ Keywords EN: ['100']
  ✓ Keywords VN: ['kính', 'thiên', 'văn', 'dưới', 'đô']
  ✓ Price: $0 - $100
  ✓ Sort: relevance
  ✓ Intent: search
  ✓ Is Complex: True

[Phase 2] SYNONYM EXPANSION
  ✓ Expanded keywords: ['telescope']

[Phase 3] SEARCH STRATEGIES
  ✓ Strategies used: ['FullCatalogStrategy', 'SynonymExpansionStrategy']
  ✓ Found 23 products

[Phase 4] TOP RESULTS
  1. [  98.0] Professional Telescope Set 1000x
     Price: $89.99 | Category: ['telescopes', 'optics']
     Strategy: SynonymExpansionStrategy
  2. [  96.0] Beginner Telescope with Stand
     Price: $45.50 | Category: ['telescopes', 'beginner']
     Strategy: SynonymExpansionStrategy
  3. [  94.0] Refractor Telescope 70mm
     Price: $65.00 | Category: ['telescopes', 'optics']
     Strategy: FullCatalogStrategy
  ...
```

### Fallback Case (gRPC unavailable)

```
[Phase 3] SEARCH STRATEGIES
❌ Search failed: _InactiveRpcError: [Unavailable] failed to connect to all addresses

[Fallback] SHOWING PARSE RESULT
  Query parse successful, but gRPC call failed.
  Category: telescopes
  Price filter: $0 - $100
```

---

## Troubleshooting

### ❌ Error: GROQ_API_KEY not set

**Fix:**
```bash
# Check if set
echo $env:GROQ_API_KEY

# If empty, set it
$env:GROQ_API_KEY="gsk_your_key"

# Or create .env file
GROQ_API_KEY=gsk_your_key
```

### ❌ Error: Cannot connect to product-catalog

**Symptoms:**
```
_InactiveRpcError: [Unavailable] failed to connect to all addresses
```

**Fix:**
1. Check port-forward is running: `kubectl port-forward svc/product-catalog 3550:3550`
2. Verify service is accessible: `telnet localhost 3550`
3. Check EKS cluster is accessible: `kubectl get pods -n techx-tf3`

### ❌ Error: ModuleNotFoundError

**Fix:**
```bash
# Reinstall dependencies
pip install -r requirements.txt

# Or specific packages
pip install groq rapidfuzz python-dotenv
```

### ❌ LLM errors (timeout, rate limit)

**This is normal for mock/test mode.** LLM errors are caught and fallback to regex parsing.

---

## Test Scenarios

| Scenario | Query | Expected Behavior |
|----------|-------|-------------------|
| **Simple search** | "kính thiên văn" | Regex detects category=telescopes |
| **Price filter** | "dưới 100 đô" | Regex extracts price_max=100 |
| **Price range** | "từ 50 đến 200" | Regex extracts price_min=50, price_max=200 |
| **Sort order** | "rẻ nhất" | Regex detects sort=price_asc |
| **Complex query** | "kính thiên văn dưới 100 đô rẻ nhất" | is_complex=True, triggers LLM rerank |
| **No results** | "product không tồn tại xyzabc" | Returns empty result, caches for 30m |
| **English query** | "telescope under 100" | Works same as Vietnamese |

---

## Performance Metrics

After running batch tests, you'll see:

- **Query Parse**: <10ms (regex)
- **Synonym Expand**: <5ms (cache)
- **gRPC Call**: 100-500ms (network latency to product-catalog)
- **LLM Parse**: 200-800ms (Groq API call, cached 24h)
- **LLM Rerank**: 300-1000ms (only if is_complex=True AND pool>5)

**Total latency per query**: 100-1500ms (depending on cache hits)

---

## Next Steps

1. ✅ Run single query test
2. ✅ Run batch test
3. ✅ Verify search results accuracy
4. ✅ Monitor LLM token usage (Groq dashboard)
5. ➜ Deploy to staging environment
6. ➜ Collect user feedback
7. ➜ Production deployment

---

## Debug Mode

For more detailed logs, set:

```python
import logging
logging.getLogger("tools.search").setLevel(logging.DEBUG)
logging.getLogger("llm").setLevel(logging.DEBUG)
```

Or run with verbose:

```bash
python tools/search/test_e2e.py "query" --debug
```

---

## Contact

Questions? 📧 AIO02 team (TF3 Phase 3)

Documentation:
- [tools/search/README.md](tools/search/README.md) — Architecture
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) — Integration guide
- [search_design.md](shopping-copilot/spec/search_design.md) — Full specification
