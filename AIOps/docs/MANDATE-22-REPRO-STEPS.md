# 📋 REPRO STEPS — Mandate #22 Closed-Loop Mitigation
# Hướng dẫn tái tạo (Reproduction Guide) cho BTC & Evaluators

**Đội:** Task Force 3 (Team AIO02)
**Mandate:** #22 — Closed-loop Mitigation
**Môi trường:** Local Simulation Sandbox HOẶC EKS Cluster `techx-corp-tf3`

---

## 🚀 1. Khởi Động Môi Trường Giả Lập Local (Simulation Mode)

### Bước 1: Cài đặt thư viện phụ thuộc

```powershell
cd D:\AWS\AIO23\AIO02_TF3_Phase3\AIOps\aiops-engine
pip install -r requirements.txt
```

### Bước 2: Thiết lập biến môi trường chạy Simulation

```powershell
# Trên Windows PowerShell:
$env:AIOPS_SIMULATION_MODE = "true"
$env:PYTHONIOENCODING = "utf-8"

# Trên Linux/macOS Bash:
export AIOPS_SIMULATION_MODE="true"
export PYTHONIOENCODING="utf-8"
```

### Bước 3: Khởi động AIOps Engine Server

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Server sẽ lắng nghe tại `http://localhost:8000`. Truy cập Swagger UI tại `http://localhost:8000/docs` để xem tài liệu API.

---

## 🎮 2. Cách Bơm Lỗi (Có 2 Phương Pháp)

### Phương Pháp 1: Dùng Bảng Điều Khiển Trực Quan (Chaos Control Panel)
1. Mở file `AIOps/chaos-engine/chaos-control-panel.html` trên trình duyệt (Chrome/Edge).
2. Bấm nút **"Bật lỗi"** ở cờ bất kỳ (ví dụ `productCatalogFailure` hoặc `paymentFailure`).
3. Panel sẽ tự động gửi signal sang Engine tại `http://localhost:8000/simulate/inject`.

### Phương Pháp 2: Dùng cURL / PowerShell API Call
Bơm kịch bản lỗi trực tiếp qua REST API (xem danh sách 11 kịch bản bên dưới).

---

## 🔥 3. Kịch Bản A: Tự Dập Sự Cố Thành Công (Happy Path)

> **Mục tiêu:** Chứng minh hệ thống Detect ➔ Safety Check ➔ Act ➔ Verify ➔ Resolution.

### Bước 1: Bơm sự cố `inc1` (`product-catalog` DB pool exhaustion)

* **Windows PowerShell:**
  ```powershell
  Invoke-RestMethod -Method POST -Uri "http://localhost:8000/simulate/inject?scenario=inc1"
  ```
* **Linux/macOS Bash:**
  ```bash
  curl -X POST "http://localhost:8000/simulate/inject?scenario=inc1"
  ```

### Bước 2: Đặt trạng thái giả lập đã sửa lỗi (Remediated = True)

```powershell
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/simulate/remediate"
```

### Bước 3: Duyệt thực thi hành động khắc phục

```powershell
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/simulate/approve"
```

**Kỳ vọng log Engine:**
```text
[1] DETECT:     AnomalyDetector phát hiện bất thường trên product-catalog
[2] EVIDENCE:   EvidenceCollector thu thập log + trace (từ fixtures mock)
[3] DIAGNOSIS:  LLMDiagnostician phân tích RCA → đề xuất action "scale" / "restart"
[4] SAFETY:     validate_action() → PASSED (whitelisted, no dangerous keywords)
[5] DRY-RUN:    execute_k8s_command(dry_run=True) → PASSED
[6] ACT:        [SIMULATION] Executing command: kubectl scale deploy/product-catalog --replicas=2
[7] VERIFY:     Starting SRE 5-minute Hybrid Verification...
                Verification cycle passed (5/5). Z-score: 0.00, ML: Normal
                Verification Success!
[8] CLOSE:      Incident resolved. Audit log written.
```

---

## 🔄 4. Kịch Bản B: Ép Lỗi Sai & Tự Rollback (Unhappy / Rollback Path)

> **Mục tiêu:** Chứng minh hệ thống tự lùi lệnh (Rollback) khi verification bị thất bại.

### Bước 1: Bơm sự cố

```powershell
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/simulate/inject?scenario=inc1"
```

### Bước 2: Duyệt hành động (NHƯNG KHÔNG gọi /simulate/remediate)

```powershell
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/simulate/approve"
```

**Kỳ vọng log Engine (Sau 5 phút timeout verification):**
```text
WARNING: Verification cycle failed. Z-score passed: False, ML passed: False
WARNING: Verification Timeout! Service product-catalog is still anomalous after 5 minutes.
WARNING: Remediation verification failed. Triggering rollback for INC-SIM-...
INFO:    Executing rollback command: kubectl -n techx-tf3 scale deploy/product-catalog --replicas=1
[SIMULATION] Bypassing actual command execution (rollback)
```

---

## 📡 5. Cổng Replay Gateway (Nhận kịch bản ngoài từ BTC)

BTC nạp kịch bản time-series kiểm thử từ ngoài qua Endpoint:

* **Windows PowerShell:**
  ```powershell
  Invoke-RestMethod -Method POST -Uri "http://localhost:8000/simulate/replay" -ContentType "application/json" -InFile "D:\AWS\AIO23\AIO02_TF3_Phase3\AIOps\datametric\labeled_scenarios.json"
  ```
* **Linux/macOS Bash:**
  ```bash
  curl -X POST "http://localhost:8000/simulate/replay" \
    -H "Content-Type: application/json" \
    -d @AIOps/datametric/labeled_scenarios.json
  ```

---

## 🗂️ 6. Danh Sách 11 Kịch Bản Bơm Lỗi Có Sẵn

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

## 📑 7. Vị Trí Các Tài Liệu Nghiệm Thu Trong Repo

- **ADR-022 Ký tên:** [ADR-022-closed-loop-safe-mitigation.md](file:///D:/AWS/AIO23/AIO02_TF3_Phase3/AIOps/docs/adr/ADR-022-closed-loop-safe-mitigation.md)
- **Báo cáo nộp bài:** [MANDATE-22-EVIDENCE-SUBMISSION.md](file:///D:/AWS/AIO23/AIO02_TF3_Phase3/AIOps/docs/MANDATE-22-EVIDENCE-SUBMISSION.md)
- **Bảng MTTR Before/After:** [MANDATE-22-MTTR-ANALYSIS.md](file:///D:/AWS/AIO23/AIO02_TF3_Phase3/AIOps/docs/MANDATE-22-MTTR-ANALYSIS.md)
- **Audit Log (JSONL):** [AIOps/aiops-engine/audit_log.jsonl](file:///D:/AWS/AIO23/AIO02_TF3_Phase3/AIOps/aiops-engine/audit_log.jsonl)
