# 📋 REPRO STEPS — Mandate #22 Closed-Loop Mitigation
# Hướng dẫn tái tạo (Reproduction Guide) cho BTC chấm điểm

**Đội:** Task Force 3 (Team AIO02)
**Mandate:** #22 — Closed-loop Mitigation
**Môi trường:** EKS Cluster `techx-corp-tf3` HOẶC Local Simulation Sandbox

---

## 🚀 Cách 1: Chạy trên Local Simulation (Không cần EKS)

### Bước 1: Cài đặt môi trường

```powershell
cd D:\AWS\AIO23\AIO02_TF3_Phase3\AIOps\aiops-engine
pip install -r requirements.txt
```

### Bước 2: Thiết lập biến môi trường

```powershell
$env:AIOPS_SIMULATION_MODE = "true"
$env:PYTHONIOENCODING = "utf-8"
```

### Bước 3: Khởi động AIOps Engine

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Engine sẽ chạy tại `http://localhost:8000`. Xác nhận bằng cách truy cập `http://localhost:8000/docs` (Swagger UI).

---

## 🔥 Kịch bản A: Tự Dập Sự Cố End-to-End (Happy Path)

> **Mục tiêu:** Chứng minh hệ thống detect → safety check → act → verify → đóng incident tự động.

### Bước 1: Bơm sự cố `productCatalogFailure` (inc1)

```bash
curl -X POST "http://localhost:8000/simulate/inject?scenario=inc1"
```

**Kỳ vọng:**
- Response: `{"status": "injected", "scenario": "inc1"}`
- Engine log: `[SIMULATION] Injected scenario: inc1`
- Background task tự động chạy `process_incident_background()`

### Bước 2: Theo dõi log Engine

Trong terminal chạy uvicorn, sẽ thấy tuần tự:

```
[1] DETECT:     AnomalyDetector phát hiện bất thường trên product-catalog
[2] EVIDENCE:   EvidenceCollector thu thập log + trace (từ fixtures mock)
[3] DIAGNOSIS:  LLMDiagnostician phân tích RCA → đề xuất action "restart"
[4] SAFETY:     validate_action("restart") → PASSED (whitelisted)
[5] DRY-RUN:    execute_k8s_command(dry_run=True) → PASSED
[6] ACT:        [SIMULATION] Bypassing actual command execution
[7] VERIFY:     Starting SRE 5-minute Hybrid Verification...
                Gate 1 (Z-Score): passing...
                Gate 2 (ML Isolation Forest): Normal...
                Verification Success!
[8] CLOSE:      Incident resolved. Audit log written.
```

### Bước 3: Kiểm tra trạng thái

```bash
curl -X GET "http://localhost:8000/simulate/state"
```

**Kỳ vọng:** `{"scenario": "inc1", "remediated": true}`

---

## 🔄 Kịch bản B: Rollback Khi Verify Thất Bại (Unhappy Path)

> **Mục tiêu:** Chứng minh hệ thống tự rollback/escalate khi hành động sai.

### Bước 1: Bơm sự cố

```bash
curl -X POST "http://localhost:8000/simulate/inject?scenario=inc1"
```

### Bước 2: Phê duyệt hành động (thủ công)

```bash
curl -X POST "http://localhost:8000/simulate/approve"
```

### Bước 3: Ngay lập tức reset trạng thái (ép verify fail)

```bash
# Reset remediated=false để verification gate thấy hệ thống VẪN LỖI
curl -X POST "http://localhost:8000/simulate/inject?scenario=inc1"
```

**Kỳ vọng log:**
```
WARNING: Verification cycle failed. Z-score passed: False, ML passed: False
WARNING: Verification Timeout! Service product-catalog is still anomalous after 5 minutes.
WARNING: Remediation verification failed. Triggering rollback for INC-SIM-...
INFO:    Executing rollback command: kubectl rollout undo deployment/product-catalog -n techx-tf3
[SIMULATION] Bypassing actual command execution (rollback)
```

---

## 🔍 Kịch bản C: Kiểm Tra Safety Gate (Chặn Hành Động Nguy Hiểm)

> **Mục tiêu:** Chứng minh hệ không "bấm bừa" — chặn lệnh ngoài whitelist.

Safety gate tự động chặn trong code:
- Lệnh chứa `rm`, `delete`, `bash` → bị block
- Action ngoài whitelist (`scale`, `restart`, `toggle-tf-flag`, `cache-flush`, `breaker-force`) → bị block
- Vượt quá 3 lần/incident/giờ → bị block

---

## 📊 Kiểm Tra Audit Log

Audit log append-only được ghi tại:
- **Console log**: Toàn bộ output trong terminal uvicorn
- **File log**: `audit_log.jsonl` (nếu được cấu hình)
- **Structured format**: JSON per-line với đầy đủ: `incident_id`, `action`, `verify_result`, `rollback_triggered`

---

## 📡 Cổng Replay Gateway (Nhận kịch bản từ BTC)

BTC có thể bơm bất kỳ kịch bản time-series nào:

```bash
curl -X POST "http://localhost:8000/simulate/replay" \
  -H "Content-Type: application/json" \
  -d @datametric/labeled_scenarios.json
```

**Response mẫu:**
```json
{
  "status": "evaluated",
  "service": "checkout",
  "metrics": {
    "precision": 1.0,
    "recall": 1.0,
    "lead_time_cycles": 0,
    "confusion_matrix": {
      "true_positives": 3,
      "false_positives": 0,
      "false_negatives": 0,
      "true_negatives": 3
    }
  }
}
```

---

## 🗂️ Danh Sách 11 Kịch Bản Inject Có Sẵn

| Scenario | Culprit Service | Loại sự cố |
|----------|----------------|-------------|
| `inc1` | product-catalog | PostgreSQL Connection Pool Exhaustion |
| `inc2` | cart | Valkey/Cart OOM / Single Point of Failure |
| `inc3` | payment | fraud-detection gRPC Timeout |
| `inc4` | product-reviews | Bedrock LLM Rate Limit 429 |
| `inc5` | shipping | Kafka Consumer Lag |
| `inc6` | recommendation | Stateless Memory Pressure |
| `inc7` | fraud-detection | Circuit Breaker Stuck OPEN |
| `inc8` | frontend | Cold Start Cache Warming |
| `incnew` | product-catalog | General DB Connection Pool |
| `ml_proactive` | product-reviews | Proactive ML Warning |
| `stable` | — | Hệ thống bình thường (baseline) |

---

## 🔧 Troubleshooting

| Vấn đề | Giải pháp |
|--------|----------|
| `ModuleNotFoundError` | Chạy `pip install -r requirements.txt` |
| `AWS credentials error` | Set `AIOPS_SIMULATION_MODE=true` — engine sẽ bypass AWS calls cho một số flow |
| Unicode error trên Windows | Set `$env:PYTHONIOENCODING="utf-8"` |
| Port 8000 đã bị chiếm | Dùng `--port 8001` và cập nhật curl URL tương ứng |
