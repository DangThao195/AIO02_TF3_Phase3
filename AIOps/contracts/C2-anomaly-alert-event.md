# C2 — Anomaly / Alert Event Contract

| Trường | Giá trị |
|---|---|
| Version | 1.0.0 |
| Producer | **AIO02** (AI engine — detection + correlation) |
| Consumer | **CDO on-call** (bất kỳ ai đang trực, mọi trụ) |
| Kênh giao | Webhook JSON (format tương thích Alertmanager) → kênh chat TF3 + dashboard |
| Trạng thái | Draft — chờ CDO review |

## Mục đích

Chuẩn hóa **một loại sự kiện duy nhất** mà AI engine đẩy cho người trực. Người trực
(CDO hay AIO) nhìn một alert phải trả lời được ngay 3 câu: *cái gì đang đau, đau tới đâu,
làm gì tiếp* — không cần mở AI engine ra đọc.

Thiết kế chống alert-fatigue theo Google SRE Workbook (multiwindow multi-burn-rate:
chỉ page khi cả cửa sổ dài và ngắn cùng cháy) và nguyên tắc correlation của các nền tảng
AIOps (nhiều tín hiệu → một incident).

---

## INPUT — thứ AI engine tiêu thụ để sinh alert

- Telemetry theo [C1](C1-telemetry-access.md) (Prometheus/OpenSearch/Jaeger).
- Bảng SLO trong `onboarding/SLO.md` (checkout ≥99%, browse ≥99.5%, p95 <1s, cart ≥99.5%).
- Bản đồ phụ thuộc service trong `onboarding/ARCHITECTURE.md` (để correlation).

CDO **không phải làm gì** ở phía input — mục này để CDO hiểu alert đến từ đâu.

## OUTPUT — Alert Event (thứ CDO nhận được)

### Schema (JSON, version hóa)

```json
{
  "schema_version": "1.0",
  "alert_id": "TF3-20260713-0042",
  "fingerprint": "checkout|availability|burnrate",
  "status": "firing",
  "severity": "critical",
  "source_layer": "slo-burnrate",
  "service": "checkout",
  "sli_impacted": "checkout_success_ratio",
  "slo_target": 0.99,
  "current_value": 0.941,
  "burn_rate": 14.4,
  "windows": { "long": "1h", "short": "5m" },
  "starts_at": "2026-07-13T09:41:00Z",
  "ends_at": null,
  "confidence": 0.98,
  "correlated_signals": [
    "payment p99 latency x8 vs baseline (anomaly layer)",
    "kafka consumer lag tăng từ 09:38"
  ],
  "probable_blast_radius": ["checkout", "payment", "accounting"],
  "evidence": {
    "promql": "1 - sli:checkout_success:ratio_rate5m",
    "grafana_panel": "http://<host>:8080/grafana/d/slo-checkout",
    "trace_ids": ["7c1f0e...", "a94b22..."],
    "log_query": "service:payment AND level:error AND @timestamp:[now-30m TO now]"
  },
  "suggested_action": "Kiểm tra payment trước (5xx tăng cùng lúc). Nếu payment nghẽn: xem runbook RB-PAY-01 (retry budget + fallback).",
  "runbook_link": "TF3/runbooks/RB-PAY-01.md",
  "requires_ack_within": "5m"
}
```

### Quy ước từng trường (CDO đọc kỹ mục này)

| Trường | Ý nghĩa cho người trực |
|---|---|
| `severity` | `critical` = page ngay, khách đang đau (burn-rate 14.4×/1h). `warning` = xử trong ca (6×/6h). `info` = ghi nhận, bàn ở Ops Review (1×/3d). **Chỉ tầng SLO burn-rate được phát critical**; tầng ML anomaly tối đa là warning |
| `source_layer` | `slo-burnrate` (deterministic, tin được) hay `ml-anomaly` (xác suất, cần người xác nhận) |
| `confidence` | Với `ml-anomaly`: điểm tin cậy của model. <0.7 sẽ không gửi — đã lọc ở engine |
| `correlated_signals` | Các tín hiệu phụ engine đã gom vào cùng incident — **một alert, không phải mười** |
| `evidence` | Copy-paste được ngay: PromQL, link Grafana, trace ID mở trong Jaeger, log query cho OpenSearch |
| `suggested_action` | Gợi ý — **người trực quyết định**, không phải lệnh. Mọi auto-action đi qua C6 |
| `requires_ack_within` | Critical: ack trong 5 phút, không thì escalate lên cả kênh TF |

### SLA của producer (AIO cam kết với CDO)

| Cam kết | Ngưỡng | Đo bằng |
|---|---|---|
| Detection latency (sự cố thật → alert critical) | ≤ 3 phút | So `starts_at` với mốc inject của BTC trong postmortem |
| Precision alert critical | ≥ 90% (mục tiêu; đo lại mỗi tuần) | Đếm critical đúng/sai ở Ops Review |
| Volume | ≤ 5 alert critical/ngày trong điều kiện thường; lặp fingerprint trong 15 phút bị gộp | Counter trên dashboard AI Engine Health |
| Resolve notice | Khi hết sự cố, gửi event `status: "resolved"` cùng `alert_id` | — |

### Nghĩa vụ của consumer (CDO cam kết lại)

- Ack alert critical trong 5 phút khi trực.
- Alert sai/nhiễu → gắn nhãn `false-positive` (một reaction/reply theo format thống nhất)
  — đây là **dữ liệu huấn luyện** để AIO chỉnh ngưỡng. Không label = không cải thiện được.
- Không mute nguồn alert; muốn đổi ngưỡng → đề xuất ở standup, chỉnh trong engine, ghi ADR.

## Failure modes

| Tình huống | Hành vi |
|---|---|
| AI engine chết | Alert rules burn-rate cơ bản vẫn chạy **trực tiếp trên Prometheus/Alertmanager** (lớp dự phòng do AIO viết, CDO host) — mất phần thông minh, không mất phần trực |
| Kênh chat chết | Alert vẫn xem được trên dashboard + Alertmanager UI |
| Bão alert (>20/giờ) | Engine tự chuyển chế độ digest: gộp thành 1 bản tin/10 phút, giữ nguyên critical |

## Tiêu chí nghiệm thu

- [ ] Fire-drill: bắn 1 alert giả lập đủ schema vào kênh, người trực CDO xác nhận đọc hiểu + tìm được evidence trong <5 phút.
- [ ] Lớp dự phòng Alertmanager hoạt động khi tắt engine (đã test).
- [ ] Dashboard đếm alert volume + precision đang chạy.
- [ ] ADR ký tên bởi AIO02 + đại diện CDO01, CDO02.
