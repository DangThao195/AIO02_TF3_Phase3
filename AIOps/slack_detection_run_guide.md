# HƯỚNG DẪN KẾT NỐI SLACK & CHẠY DETECTION PIPELINE (MOCK/LIVE)

Tài liệu này hướng dẫn chi tiết từng bước từ cấu hình Slack Webhook, cách dựng và kích hoạt sự cố giả lập đến lúc phát hiện (Detect) và khắc phục tự động trên cụm EKS hoặc môi trường Local.

---

## 🛠️ Bước 1: Kết nối & Cấu hình Slack Webhook

Hệ thống hỗ trợ gửi **Thẻ tương tác (Interactive Alerts Card)** qua Slack Block Kit để SRE duyệt hành động khắc phục nhanh.

1. **Tạo Incoming Webhook trên Slack:**
   - Truy cập trang quản trị App của Slack (`api.slack.com/apps`).
   - Tạo App mới và kích hoạt chức năng **Incoming Webhooks**.
   - Chọn kênh Slack để nhận thông báo (ví dụ: `#tf3-alerts-aiops`) và copy link Webhook URL (có dạng `https://hooks.slack.com/services/...`).

2. **Cấu hình vào AIOps Engine:**
   - Mở tệp `.env` đã tạo tại thư mục `AIOps/aiops-engine/.env`.
   - Điền link webhook vào biến:
     ```env
     SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000/B00000/XXXXXXXXXXXX
     ```
   > [!NOTE]
   > Nếu để trống `SLACK_WEBHOOK_URL`, AIOps Engine sẽ tự động chuyển sang chế độ **Console Fallback** — in nguyên cấu trúc Thẻ Alert + Phân tích RCA bằng Markdown ra màn hình Command Line, giúp bạn chạy thử không cần Slack.

---

## 🚀 Bước 2: Khởi động AIOps Engine FastAPI Server

Để tiếp nhận webhook và chạy vòng lặp phát hiện sự cố, khởi động FastAPI server cục bộ:

```powershell
# Chuyển tới thư mục engine
cd D:\AWS\AIO23\AIO02_TF3_Phase3\AIOps\aiops-engine

# Kích hoạt venv (Windows)
..\chaos-engine\ai-engine\.venv\Scripts\activate

# Chạy server Uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

*Bạn sẽ thấy log server hoạt động tại cổng `8000` (FastAPI Swagger UI khả dụng tại `http://localhost:8000/docs`).*

---

## 💥 Bước 3: Bơm sự cố giả lập (Inject Incident Scenario)

Trong chế độ chạy thử cục bộ (`AIOPS_SIMULATION_MODE=true` trong `.env`), bạn có thể chủ động bơm các kịch bản lỗi bằng các request REST API:

1. **Mở một Terminal mới và chạy lệnh cURL để bơm lỗi:**
   - **Kịch bản `inc1` (OOMKilled PostgreSQL/Catalog):**
     ```bash
     curl -X POST "http://localhost:8000/simulate/inject?scenario=inc1"
     ```
   - **Kịch bản `inc2` (Cart Valkey State loss):**
     ```bash
     curl -X POST "http://localhost:8000/simulate/inject?scenario=inc2"
     ```
   - **Kịch bản `inc3` (Payment gRPC Timeout):**
     ```bash
     curl -X POST "http://localhost:8000/simulate/inject?scenario=inc3"
     ```

2. **Kết quả trả về dự kiến:**
   ```json
   {"status": "injected", "scenario": "inc1"}
   ```

---

## 🔍 Bước 4: Xem Tiến trình Phát hiện (Detect & Analyze)

Sau khi bơm lỗi, vòng quét chủ động (Active Polling Loop) chạy ngầm mỗi 30s của Engine sẽ phát hiện trạng thái bất thường:

1. **Server Logs hoạt động:**
   ```text
   INFO:     [SIMULATION] Injected scenario: inc1
   INFO:     [Main] Running Active Polling Loop cycle...
   INFO:     [Main] Incident Detected! ID: INC-ML-20260723-XXXX
   INFO:     [RCAEngine] Building topology-aware candidates list for product-catalog
   INFO:     [LLMDiagnostician] Generating RCA via Bedrock Nova Lite...
   INFO:     [SlackNotifier] Sent interactive Slack card successfully.
   ```

2. **Kiểm tra trên Slack:**
   Kênh Slack của bạn sẽ nhận được một Card Alert dạng:
   - **Tiêu đề:** `🚨 AIOps Incident Alert: INC-ML-20260723-XXXX`
   - **Hiện tượng:** `Product Catalog service returned 500 Internal Server Errors.`
   - **Nguyên nhân:** `PostgreSQL connection pool exhausted due to peak traffic.`
   - **Action đề xuất:** `kubectl scale deployment/product-catalog --replicas=4`
   - Kèm 2 nút tương tác: **Approve (Duyệt chạy)** và **Reject (Từ chối)**.

---

## 🛡️ Bước 5: Phê duyệt Khắc phục (Approve & Remediate)

Bạn có hai cách để tiến hành phê duyệt chạy lệnh tự động vá lỗi:

*   **Cách A (Tương tác thật qua Slack):**
    Click trực tiếp vào nút **✅ Approve (Duyệt chạy)** trên thẻ thông báo Slack. Slack sẽ gửi webhook tương tác ngược về `/slack/interactive` để thực thi lệnh.
*   **Cách B (Mô phỏng bằng API):**
    Gửi request giả lập người dùng duyệt qua API:
    ```bash
    curl -X POST "http://localhost:8000/simulate/approve"
    ```

**Luồng xử lý sau khi Approve:**
1. Engine thực thi lệnh khắc phục (ví dụ: scale pods/patch limits) qua `remediation_handler.py`.
2. Chuyển trạng thái sang **Verification Gate (5 Phút)**: Quét Prometheus để kiểm tra SLO đã phục hồi và Isolation Forest xác minh tài nguyên sạch hay chưa.
3. Nếu thành công -> Ghi log Audit Trail.
4. Nếu thất bại -> Tự động chạy rollback và réo còi thông báo khẩn cấp (Escalate).
