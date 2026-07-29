# Chaos Validation Scoreboard — TF3 AIOps pipeline

> Harness: `scripts/chaos_validate.py` (offline replay, deterministic). Acceptance: recall ≥ 70% · RCA top-3 ≥ 70% · false alarm ≤ 1.

| Exp | Kịch bản | Detect | MTTD (mô phỏng) | RCA top-3 | Ghi chú |
|---|---|---|---|---|---|
| exp01 | INC-1: PostgreSQL pool exhaustion (checkout ← product-catalog) | ✅ | 30s | ✅ | H1=product-catalog là nguyên nhân gốc (downstream của checkout,… (score 1.0) |
| exp02 | INC-2: Valkey cart state loss (cart ← valkey-cart, KHÔNG resta | ✅ | 30s | ✅ | H1=valkey-cart là nguyên nhân gốc (downstream của cart, cùng bấ… (score 1.0) |
| exp03 | INC-3: gRPC EventStream timeout lúc deploy (fraud-detection ←  | ✅ | 30s | ✅ | H1=kafka là nguyên nhân gốc (downstream của fraud-detection, cù… (score 1.0) |
| exp04 | INC-4: Bedrock 429 rate limit (product-reviews ← llm) | ✅ | 30s | ✅ | H1=llm là nguyên nhân gốc (downstream của product-reviews, cùng… (score 1.0) |
| exp05 | INC-5: Kafka consumer lag (accounting ← kafka) | ✅ | 30s | ✅ | H1=kafka là nguyên nhân gốc (downstream của accounting, cùng bấ… (score 1.0) |
| exp06 | INC-6: Memory pressure + GC (frontend ← recommendation) | ✅ | 30s | ✅ | H1=recommendation là nguyên nhân gốc (downstream của frontend, … (score 1.0) |
| exp07 | INC-7: Circuit breaker kẹt OPEN (product-reviews chính chủ) | ✅ | 30s | ✅ | H1=Sự cố được inject qua flagd vào product-reviews hoặc downstr… (score 0.8) |
| exp08 | INC-8: Cold start currency (checkout ← currency, self-heal) | ✅ | 30s | ✅ | H1=currency là nguyên nhân gốc (downstream của checkout, cùng b… (score 1.0) |
| exp09 | RETRY-STORM: Retry storm: payment (victim) ồn hơn product-catalog (c | ✅ | 30s | ✅ | H1=product-catalog là nguyên nhân gốc (downstream của checkout,… (score 1.0) |
| exp10 | MULTI-FAULT: 2 fault độc lập cùng lúc → phải ra 2 incident, không gộ | ✅ | 30s | ✅ | H1=Sự cố được inject qua flagd vào checkout hoặc downstream… (score 0.8) |
| ctrl01 | CONTROL: No fault: telemetry sạch → 0 incident | — | — | — | 0 incident(s) |
| ctrl02 | CONTROL: Dup storm: cùng burn signal 3 tick → dedup fold về 1 in | — | — | — | 1 incident(s) |

## Tổng kết
- **Recall: 100%** (10 TP / 0 FN trên 10 fault) — ngưỡng 70%
- **RCA top-3 accuracy: 100%** (10 incident chấm) — ngưỡng 70%
- **False alarms: 0** (control runs) — ngưỡng ≤ 1
- MTTD p50 mô phỏng: 30s (tick 30s — con số thật đo lại trên cluster)
- Multi-fault tách incident đúng: ✅

## VERDICT: ✅ PASS