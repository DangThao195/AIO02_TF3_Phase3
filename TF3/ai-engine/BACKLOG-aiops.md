# AIOps Engine — Priority Backlog (TF3 / AIO02)

> **Nguồn sự thật duy nhất** cho backlog AIOps. Merge từ bản của nhóm + đối chiếu với **code
> thật đã build và test** (cột Trạng thái). Dùng cho pitch + Ops Review.
>
> Priority Score = Risk (Probability × Severity) × Business Impact, mỗi tiêu chí thang 1-5.
> Score 1-125: **75-125 Tối ưu tiên · 40-74 Cao · 20-39 Trung bình · 1-19 Thấp**.
>
> **Bối cảnh thật (đã sửa 3 điểm sai):** hệ thống TechX Corp có **~18 microservice** (không phải
> 200+), `llm` hiện là **mock** OpenAI-compatible (chưa cắm model thật/Bedrock). SLO: checkout
> ≥99%, browse ≥99.5%, cart ≥99.5%, p95<1s.

---

## 📋 Danh sách Backlog Ưu Tiên

| Mã | Hạng mục | Prob | Sev | Business | Score | Ưu tiên | Tuần | **Trạng thái code** |
|---|---|:---:|:---:|:---:|:---:|---|---|---|
| **AIOps-01** | Anomaly + Burn-rate SLO (Alertmanager fallback) | 4 | 5 | 5 | **100** | Tối ưu tiên | T1 | ✅ **DONE** (test) |
| **AIOps-06** | Approval Gate (Slack/webhook) — Human-in-loop (C6) | 4 | 4 | 5 | **80** | Tối ưu tiên | T1-T2 | 🟡 **đang làm** (bước này) |
| **AIOps-04** | Safety Gate + Dry-run (whitelist, chặn INC-2) | 3 | 5 | 5 | **75** | Tối ưu tiên | T1-T3 | 🟡 **đang làm** (bước này) |
| **AIOps-02** | RCA định vị nguyên nhân (topology) | 4 | 4 | 4 | **64** | Cao | T1 | ✅ **DONE** (topology tĩnh)¹ |
| **AIOps-03** | Đóng gói bằng chứng + phân cụm log | 5 | 3 | 4 | **60** | Cao | T1-T2 | 🟡 **một phần**² |
| **AIOps-05** | Container hóa + deploy EKS | 3 | 4 | 4 | **48** | Cao | T2-T3 | ⏳ chờ C1 CDO |
| **AIOps-07** | Chống báo động giả (multiwindow) | 5 | 3 | 3 | **45** | Cao | T1 | ✅ **DONE** (multiwindow)³ |
| **AIOps-08** | Blast Radius (dependency graph) | 2 | 4 | 4 | **32** | Trung bình | T2 | ✅ **DONE** |
| **AIOps-09** | Chaos/flagd fire-drill (đo detection latency) | 4 | 4 | 4 | **64** | Cao | T3 | ⏳ chờ cluster |
| **AIOps-10** | ADR mọi lỗi Tuần 2 (ký tên) | 3 | 3 | 3 | **27** | Trung bình | T3 | ⏳ |

**Ghi chú sửa 3 điểm sai (đối chiếu code thật):**
- ¹ **AIOps-02 RCA:** code dùng **topology tĩnh** (DEPENDENCY_MAP từ ARCHITECTURE.md) + correlated
  signals, KHÔNG duyệt Jaeger DAG đệ quy. Với ~18 service, static map đủ + giải thích được +
  không phụ thuộc Jaeger sống. Jaeger DAG đệ quy là **over-engineering** — đưa vào "nice-to-have".
- ² **AIOps-03:** hiện dùng OpenSearch terms-aggregation (top-5 error signature). **Drain3** (gom
  log template) là nâng cấp khi bật LLM-augment RCA — chưa làm, không hứa ở pitch.
- ³ **AIOps-07:** cơ chế thật là **multiwindow multi-burn-rate** (long+short cùng cháy mới page,
  Google SRE) — đạt đúng mục tiêu "bỏ transient spike <5m" nhưng KHÁC cơ chế "5 chu kỳ quét".
  Kể một cách thống nhất: "chống báo giả bằng multiwindow", không nói "5 cycle".

---

## 🛠️ Chi tiết hạng mục (đồng bộ mô tả với code)

### AIOps-01 · Anomaly + Burn-rate SLO ✅ DONE
- **Đã build:** [detector_burnrate.py] (multiwindow 14.4×/6×/1×) + [detector_anomaly.py]
  (robust z-score median+MAD, focus checkout/payment/cart/kafka/email theo INC-history) +
  [burnrate_alerts.yaml] (lớp dự phòng chạy thẳng Alertmanager khi engine chết).
- **DoD đạt:** burn-rate là nguồn page duy nhất; anomaly ≤warning; test spike→fire, normal→silent.
- **Metric:** SLO violation detection; anomaly confidence<0.7 bị lọc.

### AIOps-06 · Approval Gate — Human-in-loop (C6) 🟡 đang làm
- **Mục tiêu:** card duyệt/từ chối (Slack Block Kit hoặc webhook generic) → callback → thực thi.
  `approval.by` phải là người thật (C6 invariant).
- **Thực dụng:** làm **framework-agnostic** — core approval logic không cứng phụ thuộc Slack/ALB;
  Slack chỉ là 1 adapter. Chạy + test không cần hạ tầng AWS.
- **DoD:** click Approve → thực thi action; Reject → ghi record `rejected`, không thực thi.

### AIOps-04 · Safety Gate + Dry-run 🟡 đang làm
- **Mục tiêu:** whitelist action (scale/restart/cache-flush/breaker-force/toggle-tf-flag),
  dry-run trước khi thực thi, **hard-block flagd/flag BTC** + chặn action phá hủy single-replica
  (bài học INC-2). Rate-limit 3 action/incident/h.
- **DoD:** chặn 100% action ngoài whitelist; chặn action đụng flagd; mọi record có rollback_plan.

### AIOps-02 · RCA topology ✅ DONE (tĩnh)
- **Đã build:** [rca_assistant.py] — topology walk trên DEPENDENCY_MAP + causal-by-time,
  ≥2 hypothesis (anti-anchor), fail-graceful. Evidence Pack markdown ≤30m.
- **Không làm:** Jaeger DAG đệ quy (over-engineering ở 18 service).

### AIOps-03 · Bằng chứng + phân cụm log 🟡 một phần
- **Đã có:** OpenSearch terms-agg top-5 error signature trong Evidence Pack.
- **Chưa:** Drain3 template mining (đưa vào khi bật LLM-augment RCA).

### AIOps-05 · Deploy EKS ⏳ chờ C1
- Dockerfile + K8s manifest + ServiceAccount/IRSA read-only. Chờ observability CDO lên.

### AIOps-07 · Chống báo giả ✅ DONE (multiwindow)
- Multiwindow: chỉ page khi long+short cùng cháy → transient spike <5m tự loại. Dedup fingerprint 15m.

### AIOps-08 · Blast Radius ✅ DONE
- [correlator.py] `_blast_radius`: service + upstream phụ thuộc, từ dependency graph.

### AIOps-09 · Chaos/flagd fire-drill ⏳ T3
- Bật từng flag trên docker-compose local → đo detection latency ≤3m + precision. Số cho Ops Review.

### AIOps-10 · ADR ⏳ T3
- Mọi lỗi Tuần 2: lỗi gì + solution + why, ký tên.

---

## Phụ thuộc block (cần CDO)
- **C1 observability** (Prometheus/OpenSearch/Jaeger) → block AIOps-05/09.
- **Change log #tf3-changes** → nuôi RCA (AIOps-02/03).
- **Cluster + fire-drill window** → AIOps-09.

## 3 quyết định cần chốt
1. Anomaly nghiêm trọng (kafka lag/OOM) nâng critical có điều kiện? → AIOps-01 threshold.
2. Slack thật hay webhook generic cho approval? → AIOps-06 adapter.
3. Bật Drain3 + LLM-augment RCA (cost/hallucination) hay giữ deterministic? → AIOps-03.
