# Phase 1 Test Execution Guide

## Prerequisites

Before running tests, you need TWO terminals open:

### Terminal 1: Port-Forward (keep running)
```bash
cd h:\AIO02_TF3_Phase3\AIE2\shopping-copilot
python scripts\start_port_forwards.py
```

**Expected output:**
```
[PORT-FORWARD] Starting Kubernetes port-forwards...
✓ product-catalog: localhost:9090 → pod:9090
✓ product-reviews: localhost:9091 → pod:9090
✓ postgres: localhost:5432 → pod:5432
...
All port-forwards established. Press Ctrl+C to stop.
```

**Keep this terminal open!** If port-forward stops, database queries will fail.

---

### Terminal 2: Uvicorn Server
```bash
cd h:\AIO02_TF3_Phase3\AIE2\shopping-copilot
uvicorn src.main:app --port 8001 --reload
```

**Expected output:**
```
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

---

## Running Phase 1 Tests

### Terminal 3: Test Suite
```bash
cd h:\AIO02_TF3_Phase3\AIE2\shopping-copilot
python test_phase1_fixes.py
```

### What the tests do:

#### **Test 1: Refractor vs Reflector Clarification** (GR_HAL_TOOL_004 fix)
- **Query**: "Bạn có những kính thiên văn phản xạ nào, liệt kê hết ra giúp tôi"
- **Expected**: Agent clarifies "We only sell refractor telescopes (kính khúc xạ), not reflector (phản xạ)"
- **OLD behavior** (FAIL): Listed refractor products as reflector products
- **NEW behavior** (PASS): Politely explains the difference and offers refractor collection

#### **Test 2: Price Filter** (GR_HAL_TOOL_003 fix)
- **Query**: "Hiển thị danh sách các sản phẩm giá rẻ dưới $50"
- **Expected**: Calls `get_products_by_price_range(max_price=50)`, returns products under $50
- **OLD behavior** (FAIL): "Xin lỗi, tôi không có thông tin chi tiết về câu hỏi này"
- **NEW behavior** (PASS): Lists all products with price <= $50

#### **Test 3: Best Rated Products** (GR_HAL_TOOL_005 fix)
- **Query**: "Cho tôi xem các sản phẩm đánh giá cao nhất"
- **Expected**: Calls `get_best_reviewed_products_tool()`, returns top-rated products sorted by score
- **OLD behavior** (FAIL): "Xin lỗi, tôi không có thông tin chi tiết về câu hỏi này"
- **NEW behavior** (PASS): Lists products with highest average review scores

---

## Expected Results

```
================================================================================
TEST SUMMARY
================================================================================
✓ PASS: test1_refractor_clarification
✓ PASS: test2_price_filter
✓ PASS: test3_best_rated

Overall: 3/3 tests passed (100%)

🎉 All Phase 1 fixes validated successfully!

Next steps:
1. Re-run baseline evaluation: python src/evaluation/run_eval.py
2. Expected: 25/25 pass (100% accuracy)
3. Move to Phase 2: Multi-turn conversation memory
```

---

## Troubleshooting

### Issue: "Connection Error: Cannot connect to API"
**Cause**: Uvicorn server not running  
**Fix**: Start uvicorn in Terminal 2 (see above)

---

### Issue: Test 2/3 fail with "không có thông tin"
**Cause**: Port-forward not running → database unavailable  
**Fix**: Start port-forward in Terminal 1 (see above)

**Verify port-forward is working:**
```bash
# Check PostgreSQL connection
psql -h localhost -p 5432 -U postgres -d catalog
# (Password: postgres)

# Should connect successfully. If not, port-forward is down.
```

---

### Issue: Test 1 fails (still listing refractor as reflector)
**Possible causes:**
1. **Cache issue**: Old intent cached. Clear cache:
   ```bash
   rm -f data/cache.json data/session.json
   ```
2. **LLM not using SYSTEM_PROMPT**: Check logs for "SYSTEM_PROMPT" load confirmation
3. **Prompt not updated**: Verify `src/llm/prompt.py` contains telescope knowledge section

---

### Issue: Test 2 passes but Test 3 fails
**Cause**: Database has no review data  
**Diagnosis:**
```bash
# Connect to PostgreSQL
psql -h localhost -p 5432 -U postgres -d catalog

# Check if reviews exist
SELECT COUNT(*) FROM reviews.reviews;
-- Should return > 0

# If 0, check if reviews service is running:
kubectl get pods -n techx-tf3 | grep review
```

---

## Manual Testing (Alternative)

If automated tests fail, you can test manually with curl:

### Test 1: Refractor clarification
```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"manual-test-1\",\"user_id\":\"test-user\",\"message\":\"Bạn có những kính thiên văn phản xạ nào, liệt kê hết ra giúp tôi\"}"
```

### Test 2: Price filter
```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"manual-test-2\",\"user_id\":\"test-user\",\"message\":\"Hiển thị danh sách các sản phẩm giá rẻ dưới $50\"}"
```

### Test 3: Best rated
```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"manual-test-3\",\"user_id\":\"test-user\",\"message\":\"Cho tôi xem các sản phẩm đánh giá cao nhất\"}"
```

---

## After Tests Pass: Re-run Baseline Evaluation

Once all 3 tests pass, run the full baseline evaluation to confirm 25/25:

```bash
cd h:\AIO02_TF3_Phase3\AIE2\shopping-copilot\src\evaluation
python run_eval.py --config baseline_guardrails.json --output phase1_report.json
```

**Expected improvement:**
- Before: 24/25 pass (96%)
- After Phase 1: 25/25 pass (100%)

Compare reports:
```bash
python compare_reports.py baseline_guardrails_report.json phase1_report.json
```

---

## Phase 1 Completion Checklist

- [x] Added telescope knowledge to SYSTEM_PROMPT
- [x] Created `get_products_by_price_range` tool
- [x] Updated `LLM_PLANNER_PROMPT` with price filter rules
- [x] Updated fallback planner in `copilot_agent.py`
- [x] Enhanced intent parser to recognize review ranking queries
- [ ] **Run automated tests** → `python test_phase1_fixes.py`
- [ ] **All 3 tests pass** (100%)
- [ ] **Re-run baseline eval** → 25/25 pass expected
- [ ] **Document results** in OPTIMIZATION_ROADMAP.md

Once checklist complete → **Move to Phase 2: Multi-turn Conversation**

