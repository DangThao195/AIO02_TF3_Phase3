# TF3 — AIOps Experience Playbook (đúc kết từ XBrain Learning Notes)

> Nguồn: [learning-notes-dz2.pages.dev/xbrain](https://learning-notes-dz2.pages.dev/xbrain/) — 9 bài W1–W3
> (Detection & Triage → RCA & Smart Response → Reliability Engineering & Postmortem).
> Tài liệu này đúc kết **tham số vận hành cụ thể** + **đối chiếu với hiện trạng ai-engine** + **backlog lấp gap**.
> Liên quan: [AIOPS-PROBLEM-STATEMENT.md](AIOPS-PROBLEM-STATEMENT.md) · [AI-ENGINE-ARCHITECTURE.md](AI-ENGINE-ARCHITECTURE.md) · [ai-engine/BACKLOG-aiops.md](ai-engine/BACKLOG-aiops.md)

---

## 1. Bảng tham số vận hành (cheat-sheet)

### 1.1 Detection (W1-D1)

| Tình huống | Phương pháp | Tham số |
|---|---|---|
| Metric ổn định, không seasonality (pool, memory) | Z-score / 3σ | rolling window 60–240 điểm; **không dùng full history** |
| Metric lệch phải (latency, throughput) | log-transform `log1p` rồi 3σ, hoặc IQR | IQR: `Q1−1.5·IQR`, `Q3+1.5·IQR` — 3σ thô trên latency cho ngưỡng âm (vô nghĩa) |
| Drift chậm (memory leak, degradation) | EWMA | α = 0.05–0.1 (trend); α = 0.3 default; spike thì dùng 3σ chứ đừng tăng α |
| Seasonality ngày/tuần | STL rồi detect trên residual | period = 1440 (1-min data, daily); verify bằng ACF peak; `robust=True` |
| ≥5 metric tương quan | IsolationForest | `n_estimators=200`, `contamination` 0.01–0.02 tune xuống; **bắt buộc** feature engineering (rolling mean/std, rate-of-change, lag) — raw series không đủ |

**KPI detection:** Recall > 0.8 (bỏ sót đắt hơn báo nhầm) · Precision > 0.7 · TTD < 5 phút · false-alarm < 1%/ngày.

### 1.2 Log mining (W1-D2)

- **Drain3**: similarity threshold **0.4–0.5**, tree depth 4. >0.8 → hàng triệu template vô dụng; <0.2 → over-group.
- **Merge multiline trước khi parse** (stack trace 10–50 dòng = 1 event) — không merge thì mỗi frame thành 1 template rác.
- 5 tín hiệu từ log: template-count spike (window 5 phút + 3σ/IF) · **template mới** (báo deploy/attack; cần grace period sau deploy) · sequence bất thường · parameter outlier · **inter-arrival** (template "im lặng" cũng là tín hiệu — count-based bỏ sót).
- Mục tiêu: 100–500 template/service, grouping F1 > 0.8.
- **Cross-signal workflow** (giảm TTD từ giờ → phút): metric alert → lọc log ±5 phút → template spike trùng thời điểm → drill parameter → đối chiếu deploy record.

### 1.3 Data layer (W1-D3)

- Điều tra theo chiều: **metric (what) → trace (where) → log (why)**.
- Tier storage: hot 0–7d / warm 7–30d / cold S3+Parquet — tiering tiết kiệm ~75% so với hot-only.
- Chuẩn hoá qua OTel Collector; scale TF3 (~25 services) **không cần** Kafka/feature-store riêng — SQL view + cache là đủ, chỉ nâng cấp khi >5 model ML.
- Mọi quyết định kiến trúc ảnh hưởng >1 nhóm → **ADR** (Context / Decision / Consequences / Alternatives).

### 1.4 Alert correlation (W2-D1)

4 tầng, **không tầng nào tự đủ**:
1. **Dedup** — fingerprint từ field bất biến `{service|sli|rule}` (loại timestamp/value); TTL eviction bắt buộc (chống memory leak).
2. **Time-window** — session gap **120–300s** (chọn p95 của gap intra-incident lịch sử), tốt hơn tumbling window cố định.
3. **Topology** — lỗi lan **ngược lên upstream** (callers); correlate khi khoảng cách ≤ **2 hop**.
4. **Semantic** (optional) — Jaccard/embedding bắt alert cùng nghĩa khác tên metric.

Bối cảnh: 67% engineer nhận >10 alert/ca; response time ×2.4 khi flood — correlation là điều kiện sống của on-call.

### 1.5 RCA (W2-D2)

- **Graph + temporal fusion**: `score = 0.6 × PageRank(reverse-graph) + 0.4 × timestamp-order` (alert sớm hơn = nghi phạm hơn). Đủ tốt cho topology ổn định như e-commerce; đừng vội causal inference.
- Cạm bẫy retry-storm: service hạ nguồn bắn **nhiều** alert hơn thủ phạm — rank theo alert count là sai; phải theo topology + thời gian. DB/cache alert *sau* app = nạn nhân, không phải thủ phạm.
- **LLM-augmented pipeline 5 bước**: retrieve K sự cố lịch sử tương tự → assemble context (cluster + top-3 graph candidates) → gọi LLM `temperature=0.2`, JSON schema, timeout 10s + 2 retry → **guardrail validate** (root cause phải ∈ cluster; class ∈ enum cố định; confidence ∈ [0,1]; actions ≠ rỗng) → **fallback = top-1 graph candidate** khi LLM fail/hallucinate.
- RAG scoring heuristic: +0.4 nếu service root-cause lịch sử ∈ cluster hiện tại; +0.2/service trùng (max +0.4); +0.2 trùng severity; ngưỡng ≥0.2 mới đưa vào prompt.
- **Ngưỡng confidence điều phối hành động**: >0.85 → auto-remediation (vẫn qua approve) · 0.6–0.85 → on-call điều tra · <0.6 → escalate senior.
- Kỳ vọng thực tế: **top-3 chứa đúng root cause >80%** là gold standard — đừng hứa 100% tự động.

### 1.6 Model serving (W2-D3)

- LLM chiếm ~91% latency pipeline → tối ưu ở đó: prompt cache (SHA256+TTL) · `asyncio.gather` · model rẻ (nova-micro/haiku-class) · **skip LLM khi graph confidence ≥0.9** → giảm ~90% call.
- **Mọi outbound call phải có timeout tường minh** — thiếu timeout = cạn connection pool = treo cả service.
- `/healthz` (liveness) tách khỏi `/readyz` (dependencies); **readyz không được phụ thuộc LLM provider** — provider sập không được kéo pod bị evict.
- Feature flag `USE_LLM=false` để degrade không cần redeploy.
- 4 metric tự giám sát: requests_total(status) · latency histogram · **llm_failures_total(reason)** · clusters_per_request. Log JSON, không `print()`.
- SLO của chính pipeline AIOps: availability 99.5% · p99 <10s · LLM failure <1% · top-3 precision >70%.
- Mock LLM trong test = đúng; mock trong production = cấm.

### 1.7 SLO & burn-rate (W3-D1)

- `burn_rate = error_rate / (1 − SLO)`; công thức ngưỡng `T = budget_fraction / window_fraction`.
- 3 tier chuẩn Google: **14.4× (1h/5m, page) · 6× (6h/30m, page) · 1× (3d/6h, ticket)** — chỉ fire khi **CẢ HAI** window vượt (long = đủ lớn, short = đang diễn ra; short window giúp alert tự tắt ~5 phút sau khi hết sự cố).
- SLI phải đo từ **trải nghiệm user**: 5xx + 429 = fail; 4xx loại ra (lỗi user/bot); **CPU không bao giờ là SLI**.
- Percentile: p99 cho user-facing; p95 báo cáo; p50 pipeline throughput.
- Chọn SLO = baseline hiện tại + ~0.5% buffer; mỗi số 9 thêm = chi phí ×3–10.
- Validation: MWMBR phải giảm ≥70% noise so với ngưỡng error-rate thô, MTTD không tệ hơn 60s. Tune sau ~2 tuần baseline, đừng tune vội.

### 1.8 Chaos engineering — validate chính pipeline AIOps (W3-D2)

- Chaos không phải để test app — để **đo pipeline detect/correlate/RCA**: confusion matrix (TP/FN/FP), MTTD, RCA-accuracy per experiment.
- **Acceptance: recall ≥70% · RCA accuracy ≥70% · ≤1 false alarm** trên bộ ≥10 experiment (network/resource/app/state), cooldown 120s giữa các lần.
- Experiment 5 trường bắt buộc: hypothesis đo được ("order_success_rate ≥99.5% trong 60s partition") · blast radius · rollback · measurement · abort condition.
- **External synthetic probe** (script ~20 dòng, query 5s/lần từ ngoài cluster, pass ≥99%/60s) = nguồn sự thật độc lập — internal metrics có thể tự dối (cache stale, 200-nhưng-sai-nội-dung).
- 5 failure mode phải chủ động test: detector miss vì noise floor (Roblox 2021) · correlator ghép nhầm 2 fault độc lập cùng lúc · RCA chọn nhầm victim trong retry storm · **LLM hallucination confidence cao** (bắt buộc evidence citation, reject citation rỗng) · **monitoring dependency loop** (stack quan sát không được phụ thuộc service bị quan sát).

### 1.9 Postmortem, ADR & cost model (W3-D3)

- Postmortem template Google SRE: summary · impact (%, revenue, budget SLO đã đốt) · **timeline UTC ≥8 event** · root cause · contributing factors · detection analysis · action items **có owner + due date**.
- **Blameless**: "pipeline config cho phép YAML sai lọt qua", không phải "X push config sai". Blame culture = giấu lỗi = outage to hơn.
- 5 Whys chỉ hợp single-chain; sự cố đa nguyên nhân (GitHub 2018: network blip 43s + failover logic + consistency-first) → **causal tree**.
- ADR Nygard: Status/Context/Decision/**≥2 Alternatives có pros-cons**/Consequences.
- Cost model: `Value = downtime_hours × MTTR_reduction% × cost_per_hour`; **ROI >1.5 mới đáng làm**; nhớ tính công engineer (thiếu là hụt 3–5×). E-commerce mid-tier: $5k–50k/giờ downtime.
- **Khi nào KHÔNG làm AIOps**: <30 services & <3 incident/tháng, downtime <$1k/h, chưa có SLO/log tập trung — đầu tư observability + on-call culture trước.

---

## 2. Đối chiếu hiện trạng ai-engine (gap analysis)

| Bài học XBrain | Hiện trạng TF3 (`ai-engine/src/ai_engine/aiops/`) | Trạng thái |
|---|---|---|
| MWMBR 3-tier 14.4/6/1, AND hai window | `detector_burnrate.py` — đúng chuẩn Google, tier (14.4, 1h, 5m) CRITICAL | ✅ |
| Robust z-score (median-based) cho latency | `detector_latency.py` + `detector_anomaly.py` (`robust_zscore`) | ✅ |
| IsolationForest multivariate | `detector_iforest.py` — 6 feature bắt buộc (value, roll mean/std, rate-of-change, lag-1, lag-12), n_estimators=200, contamination 0.02, wired vào `server.tick` | ✅ (bắt được pattern anomaly mà z-score điểm đơn bỏ sót — có test chứng minh) |
| Dedup fingerprint bất biến + TTL eviction | `correlator.py` — fingerprint `{service|sli|rule}`, dedup_window 900s, có evict | ✅ |
| Topology upstream ≤2 hop | `correlator.py` `_upstream_of` / `_blast_radius` | ✅ (xác nhận max-hop = 2) |
| RCA rank graph+temporal | `rca_assistant.score_candidates` — 0.6×structural + 0.4×timestamp; `Incident.first_seen` từ correlator | ✅ (chaos exp09 retry-storm: top-1 đúng thủ phạm) |
| LLM guardrail: root ∈ cluster, enum class, evidence citation | `rca_guardrail.py` — 5 rule cứng, fallback top-1 graph candidate, audit `method`+`violations` | ✅ |
| RAG grounding từ incident history | `kb_retriever.py` (bedrock-agent-runtime + heuristic +0.4/+0.2/+0.2, ngưỡng 0.2) nối vào `rca_assistant.build` | ✅ (cần `KNOWLEDGE_BASE_ID` từ terraform output) |
| Safety gate + human approve + verify + auto-rollback | `action_policy.py`, `approval.py`, `verify_loop.py` (fail-safe: telemetry mù = NOT recovered → rollback) | ✅ |
| Confidence tiers 0.85/0.6 điều phối auto-vs-manual | `action_policy.route_for_confidence` — auto-queue/investigate/escalate, wired vào `server.tick` | ✅ |
| Log mining Drain3 (template mới, inter-arrival) | `detector_logtemplate.py` — miner tự viết (sim 0.45, merge multiline), 3 tín hiệu: new-template + count-spike + **silence** (template đều đặn bỗng câm); wired vào `server.tick` qua OpenSearch 5m | ✅ |
| Chaos validation scoreboard (recall/MTTD/RCA-acc) | `scripts/chaos_validate.py` — 10 exp (INC-1..8 + retry-storm + multi-fault) + 2 control → `chaos/scoreboard.md` | ✅ PASS 100/100/0 |
| External synthetic probe độc lập | `scripts/synthetic_probe.py` — stdlib, ngoài cluster, steady-state 99%/60s, JSON-lines | ✅ |
| Skip-LLM khi confidence cao + prompt cache | `aie/gateway.py` (product path) + `rca_assistant` SKIP_LLM_SCORE=0.9: graph+temporal ≥0.9 → verdict deterministic `graph-high-confidence`, không gọi LLM | ✅ (~90% call reduction ở sự cố quen — W2-D3) |
| Cost model ROI cho AIOps | `cost_roi.py` — incident_roi (value = downtime × MTTR-reduction × cost/h, gồm công engineer), verdict 1.5/1.0 | ✅ |
| Postmortem + ADR template chuẩn | `onboarding/POSTMORTEM_TEMPLATE.md` (Google SRE, blameless, ≥8 event UTC) + `onboarding/ADR_TEMPLATE.md` (Nygard, ≥2 alternatives) | ✅ |

## 3. Backlog lấp gap (ưu tiên theo tuần thi)

> **Trạng thái 2026-07-14: TOÀN BỘ backlog P1–P4 đã triển khai** (146/146 test pass,
> chaos scoreboard PASS 100/100/0). Gap table trên: 11/11 dòng ✅. Việc còn lại là việc
> VẬN HÀNH, không phải code: deploy KB (terraform apply + ingestion), đo MTTD thật trên
> cluster thay số mô phỏng, và tune contamination/threshold sau 2 tuần baseline (§1.7).

**P1 — trước game-day (bảo vệ điểm sống sót):**
1. **Chaos harness + scoreboard** (`scripts/chaos_validate.py`): ≥10 experiment map theo INC-1..8 của `onboarding/INCIDENT_HISTORY.md` (pool exhaustion, pod kill valkey, 429 Bedrock, Kafka lag, memory pressure…), đo TP/FN/FP, MTTD, RCA-accuracy; acceptance ≥70/≥70/≤1. Chạy được là có **bằng chứng định lượng** cho Ops Review.
2. **External synthetic probe**: script 20 dòng ngoài cluster, 5s/lần vào frontend + product-detail; nguồn sự thật độc lập cho verify_loop (tránh monitoring dependency loop — failure mode #5).
3. **LLM guardrail validator** trong `rca_assistant.py`: root ∈ cluster services, class ∈ enum, confidence ∈ [0,1], actions ≠ rỗng, **evidence citation bắt buộc**; fallback top-1 graph candidate.

**P2 — nâng chất RCA:**
4. Thêm **timestamp-order 0.4** vào rank hypotheses (chống retry-storm rank nhầm); DB/cache alert-sau = victim.
5. Nối Bedrock KB `retrieve` vào prompt RCA theo scoring heuristic (+0.4/+0.2/+0.2, ngưỡng 0.2).
6. Ngưỡng confidence 0.85/0.6 trong `action_policy.py` để phân tầng auto-queue vs investigate vs escalate.

**P3 — mở rộng tín hiệu & hồ sơ:**
7. Drain3 log-template detector (threshold 0.45, depth 4, merge multiline): 2 tín hiệu rẻ nhất trước — **template mới** + template-count spike.
8. Cost model ROI (`cost_report.py` mở rộng): downtime/h × MTTR-reduction vs chi phí engine — số liệu cho Service Health Readout & BUDGET.md.
9. Template postmortem (Google SRE, blameless) + ADR (Nygard, ≥2 alternatives) vào `onboarding/` — deliverable bắt buộc theo RULES.md.

---

*Nguyên tắc xuyên suốt (từ cả 9 bài): đo trước khi tối ưu · recall trước precision · mọi ngưỡng phải suy từ công thức chứ không bốc · pipeline AIOps cũng là một service — nó cần SLO, self-metrics, và chaos test cho chính nó.*
