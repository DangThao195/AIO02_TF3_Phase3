# Báo Cáo Nộp Bài: AI Mandate #15 - Độ Tin Cậy Phát Hiện Sự Cố

- **Trạng thái**: Sẵn sàng đánh giá (Ready for Evaluation)
- **Đội ngũ thực hiện**: Task Force 3 (Team AIO02)
- **Hạn nộp #7b**: Thứ Bảy 25/07/2026

---

## 🎫 1. Thông Tin Ticket Jira

* **Summary:** `AI MANDATE #15`
* **Labels:** `ai-mandate`, `m15`
* **Priority:** `High`

---

## 💬 2. Nội Dung Comment Bằng Chứng (Evidence Comment)

*(Copy toàn bộ phần bên dưới để paste vào comment của Jira Ticket)*

---

### 🔗 1. Link PR / Commit (Code đã merge vào trunk)

* **Repository:** `https://github.com/Baronger23/Capstone03`
* **Detector core (anomaly_detector.py):**
  `https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/anomaly_detector.py`
* **Engine main (main.py + /simulate/replay endpoint):**
  `https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/main.py`
* **Bộ test case có nhãn (test_ml_anomaly.py):**
  `https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/tests/test_ml_anomaly.py`
* **Bộ kịch bản labeled scenarios:**
  `https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/datametric/labeled_scenarios.json`
* **Dữ liệu baseline EKS thực tế (datametric/):**
  `https://github.com/Baronger23/Capstone03/tree/main/aiops-engine/datametric`

---

### 📋 2. Phân Tích Metrics & Baseline (Mandate #7a — implement + phân tích)

Tài liệu phân tích đầy đủ ≥ 3 metrics trọng yếu, với mỗi metric ghi rõ:
- Lý do lựa chọn
- Baseline "bình thường" đo từ EKS thực tế ngày 14/07/2026
- Ngưỡng bất thường
- Phương pháp phát hiện

**Link tài liệu:**
`https://github.com/Baronger23/Capstone03/blob/main/docs/Baseline_metric.md`

**Tóm tắt 3 metrics trọng yếu được chọn:**

| Metric | Service | Baseline (EKS thực tế) | Ngưỡng bất thường |
|---|---|---|---|
| **Error Rate** | checkout | 0.0 errors/s | > 0.001 errors/s kéo dài 2 chu kỳ |
| **Latency P90** | frontend | 0.0s (sub-ms, idle) | `latency_deviation > 2.0` |
| **CPU Usage** | checkout | 0.003 cores | > 0.02 cores (gấp ~7×) |

> Lưu ý: Cluster EKS thu thập data ở giai đoạn idle/staging (14/07). Model IF học baseline này và phát hiện dựa trên **độ lệch tương đối**, không phải ngưỡng tuyệt đối.

---

### 📝 3. ADR Ký Tên

Chi tiết quyết định kiến trúc, các phương án đã xem xét (Z-Score vs Static Threshold vs Supervised ML vs Isolation Forest) và lý do từ chối:

**ADR-008 (Anomaly Detection Baseline):**
`https://github.com/Baronger23/Capstone03/blob/main/docs/adr/ADR-008-anomaly-detection-baseline.md`

* **Ký tên phê duyệt:** Hảo — Leader team AIOps (Task Force 3)
* **Ngày ký:** 17/07/2026 (cập nhật 20/07/2026)

---

### 🚪 4. Cửa Replay Gateway (Nhận Kịch Bản Từ Ngoài)

Mentor/BTC có thể bơm bất kỳ time-series payload nào vào endpoint để đánh giá:

```bash
# Bơm kịch bản ẩn từ bên ngoài vào Engine
curl -X POST "http://localhost:8000/simulate/replay" \
  -H "Content-Type: application/json" \
  -d '{
    "service": "checkout",
    "data": [
      {"timestamp": "2026-07-20T10:00:00Z", "rps": 0.25, "cpu_usage": 0.003,
       "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0,
       "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-20T10:05:00Z", "rps": 0.25, "cpu_usage": 0.020,
       "memory_usage": 0.188, "latency_p90": 0.95, "error_rate": 0.08,
       "client_error_rate": 0.0, "kafka_lag": 45.0, "label": -1}
    ]
  }'
```

**Response trả về:**
```json
{
  "status": "evaluated",
  "service": "checkout",
  "metrics": {
    "precision": 1.0,
    "recall": 1.0,
    "lead_time_cycles": 0,
    "lead_time_seconds": 0.0,
    "slo_breaches_detected": 1,
    "confusion_matrix": {
      "true_positives": 1,
      "false_positives": 0,
      "false_negatives": 0,
      "true_negatives": 1
    }
  }
}
```

---

### 🚀 5. Hướng Dẫn Tái Tạo (Repro Steps)

#### Cách A: Chạy unit test tự động (đo Precision/Recall trên 3 kịch bản có nhãn)
```bash
cd aiops-engine
python tests/test_ml_anomaly.py
```

**Kết quả mong đợi:**
```
[TEST] Replay Scenario 'checkout_incident'  -> Precision: 1.00, Recall: 1.00, Lead-time: 0 cycles
[TEST] Replay Scenario 'masking_incident'   -> Precision: 1.00, Recall: 1.00, Lead-time: 0 cycles
[TEST] Replay Scenario 'high_load_healthy'  -> Precision: 1.00, FP: 0, SLO Breaches: 0

Ran 5 tests in ~170s
OK
```

#### Cách B: Gọi API Replay trực tiếp trên EKS Pod
```bash
curl -X POST "http://aiops-engine.techx-tf3.svc.cluster.local/simulate/replay" \
  -H "Content-Type: application/json" \
  -d @aiops-engine/datametric/labeled_scenarios.json
```

---

### 📊 6. Bộ Sự Cố Có Nhãn Commit Trong Repo

Tập `labeled_scenarios.json` thiết kế dựa trên baseline EKS thực tế (không dùng số synthetic):

| Kịch bản | Service | Mô tả | Nhãn anomaly |
|---|---|---|---|
| `checkout_incident` | checkout | DB bottleneck: latency vọt 0.95s–1.2s, error_ratio 32–48% | 3 dòng cuối = -1 |
| `masking_incident` | checkout | RPS tăng 7× + lỗi nhẹ 4% âm ỉ | 3 dòng cuối = -1 |
| `high_load_healthy` | checkout | RPS tăng 6× nhưng error=0, latency=0 | Tất cả = 1 |

---

### ⏱️ 7. MTTD Before vs After

| | Trước (Traditional Alertmanager) | Sau (AIOps Engine) |
|---|---|---|
| **Cơ chế** | Ngưỡng tĩnh PromQL alert rules | IF 18-feature scan + SLO Burn Rate |
| **MTTD** | 10–50 phút | 30–35 giây |
| **Tỷ lệ giảm** | Baseline | **> 95%** |
| **Đo từ** | Alert rule firing delay lịch sử | Lead-time = 0 cycles trên labeled scenarios |

---

### 🟢 8. Bằng Chứng Detector Chạy Liên Tục Trong Cụm

```bash
kubectl get pods -n techx-tf3 -l app=aiops-engine

NAME                            READY   STATUS    RESTARTS   AGE
aiops-engine-5d5c7964c6-q4ff5   1/1     Running   0          5m
```

Engine quét chủ động Isolation Forest mỗi **30 giây** qua vòng lặp `active_metrics_polling_loop()`. Chạy 24/7 dưới dạng K8s Deployment với readiness/liveness probe tại `/readyz`.

---

### 🚨 9. Ví Dụ Incident Summary Tự Sinh (Mandate #15 — Auto-generate)

Khi phát hiện anomaly, Engine gọi Bedrock LLM và đẩy Slack alert:

```
🚨 AIOps Incident Alert: INC-ML-1784270453
• Hiện tượng: Vỡ SLO latency — checkout latency P90 vọt lên 1.2s
• Nguyên nhân: DB connection pool exhausted, timeout cascade
  (Nguồn: INC-1 từ Bedrock Knowledge Base)
• Bằng chứng: Jaeger Trace ID 9bd4b5..., error_ratio = 48%,
  kafka_lag tăng từ 0 → 120 messages
• Vùng ảnh hưởng: checkout → payment → shipping (dây chuyền)
```
