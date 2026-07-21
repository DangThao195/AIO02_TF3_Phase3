# 🚀 HƯỚNG DẪN CÀI ĐẶT, CẤU HÌNH & CHẠY THỬ NGHIỆM AIOPS ENGINE

Tài liệu này hướng dẫn chi tiết từng bước cho các lập trình viên hoặc kỹ sư SRE mới khi **clone dự án này về** cách cài đặt môi trường, cấu hình file `.env`, chạy các bộ test case và vận hành hệ thống Sandbox giả lập cục bộ (Local Simulation Sandbox).

---

## 📋 1. Các Yêu Cầu Cài Đặt Ban Đầu (Prerequisites)

Trước khi bắt đầu, hãy đảm bảo máy tính của bạn đã cài đặt các công cụ sau:
* **Python 3.10+** (đã cấu hình trong biến PATH).
* **Git** (để quản lý phiên bản).
* **PowerShell** (nếu dùng Windows) hoặc **Bash** (nếu dùng Linux/macOS).
* Quyền truy cập internet (để tải thư viện và gọi API AWS Bedrock).

---

## 📥 2. Cài Đặt Môi Trường Cục Bộ (Environment Setup)

Sau khi clone repo về, hãy mở terminal tại thư mục gốc của dự án và làm theo các bước sau:

### Bước 2.1: Di chuyển vào thư mục Engine
```bash
cd aiops-engine
```

### Bước 2.2: Tạo môi trường ảo (Virtual Environment)
* **Trên Windows:**
  ```powershell
  python -m venv venv
  .\venv\Scripts\activate
  ```
* **Trên Linux/macOS:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### Bước 2.3: Cài đặt các thư viện phụ thuộc (Dependencies)
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ 3. Cấu Hình File Môi Trường (`.env`)

Tạo file `.env` nằm trực tiếp trong thư mục `aiops-engine/` (`aiops-engine/.env`). File này chứa toàn bộ cấu hình hoạt động của hệ thống.

Copy nội dung mẫu dưới đây và điền thông tin của bạn:

```bash
# =========================================================================
# 🚨 CẤU HÌNH ĐỊA CHỈ SLACK WEBHOOK (NHẬN THẺ RCA TƯƠNG TÁC)
# =========================================================================
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK

# =========================================================================
# ⚙️ CHẾ ĐỘ HOẠT ĐỘNG (true: Chạy Sandbox Giả lập | false: Chạy Live EKS)
# =========================================================================
AIOPS_SIMULATION_MODE=true

# --- Cấu hình Sandbox Giả lập (Khi AIOPS_SIMULATION_MODE=true) ---
# Tự động trỏ các cổng giám sát về server local FastAPI để nạp Fixtures logs/traces
JAEGER_URL=http://localhost:8000/mock-jaeger
PROMETHEUS_URL=http://localhost:8000/mock-prometheus
OPENSEARCH_URL=http://localhost:8000/mock-opensearch
SIMULATION_SERVER_URL=http://localhost:8000

# --- Cấu hình EKS Live Cluster (Khi AIOPS_SIMULATION_MODE=false) ---
# JAEGER_URL=http://localhost:8080/jaeger/ui
# PROMETHEUS_URL=http://localhost:8080/grafana/api/datasources/proxy/uid/webstore-metrics
# OPENSEARCH_URL=http://localhost:9200

# =========================================================================
# ☁️ CẤU HÌNH THÔNG TIN KẾT NỐI AWS (GỌI API BEDROCK LLM)
# =========================================================================
# Model ID sử dụng thế hệ mô hình siêu nhanh siêu rẻ amazon.nova-micro-v1:0
BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
EXTERNAL_AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
EXTERNAL_AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
EXTERNAL_AWS_REGION=us-east-1
```

> [!IMPORTANT]
> **Bảo mật thông tin:** File `.env` chứa AWS Access Key cá nhân và Slack Webhook. Nó đã được đưa vào file `.gitignore` để đảm bảo không bị push công khai lên GitHub. Tuyệt đối không commit file này.

---

## 🏃 4. Khởi Động Máy Chủ AIOps Engine (Local Server)

Đảm bảo bạn vẫn đang ở trong thư mục `aiops-engine/` và môi trường ảo `venv` đã được kích hoạt:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

* **Kết quả mong đợi:** 
  * Cửa sổ terminal hiện log khởi động của `uvicorn` và thông báo:
    `[INFO] AIOpsEngine.Main: Starting Active Metrics Polling Loop (Mode B)...`
  * Máy chủ API chạy tại địa chỉ: `http://localhost:8000`.

---

## 🧪 5. Chạy Các Bài Test Đơn Vị & Tích Hợp (Automated Tests)

Chúng tôi đã viết sẵn bộ test tự động kiểm tra E2E luồng xử lý từ chẩn đoán đến gửi Slack card. Bạn mở một terminal mới và chạy:

```bash
cd aiops-engine
# Kích hoạt môi trường ảo (venv) trước khi chạy
pytest -v
```

* **Bộ Test chính bao gồm:**
  * `test_anomaly_detection.py`: Kiểm tra logic Z-score và phát hiện SLO burn-rate vỡ.
  * `test_e2e_with_fixtures.py`: Tự động nạp fixtures giả lập và chạy E2E RCA.
  * `test_incident_flow.py`: Kiểm tra luồng phê duyệt từ Slack interactive webhook.

---

## 🔴 6. Kiểm Thử Vận Hành Bằng Tay (Manual Sandbox Verification)

Khi máy chủ uvicorn đang chạy trên máy của bạn, bạn có thể chủ động **bơm lỗi (Inject Fault)** để kiểm tra hành vi chẩn đoán của LLM và thẻ duyệt lỗi Slack.

### Bước 6.1: Bơm lỗi giả lập (Fault Injection)
Mở một terminal mới và chạy lệnh gọi API tương ứng với kịch bản lỗi bạn muốn thử nghiệm:

* **Sử dụng PowerShell (Windows):**
  ```powershell
  # Bơm lỗi kịch bản LLM Saturation (INC-4)
  Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/inject?scenario=inc4"
  ```
* **Sử dụng cURL (Linux/macOS):**
  ```bash
  curl -X POST "http://localhost:8000/simulate/inject?scenario=inc4"
  ```

#### 📂 Danh sách các kịch bản có sẵn để bơm (`?scenario=...`):
| Kịch bản | Dịch vụ thủ phạm | Loại lỗi chính | Lệnh đề xuất | Rủi ro |
| :--- | :--- | :--- | :--- | :--- |
| **`inc1`** | `postgresql` | DB Connection Pool cạn kiệt | `scale deploy/product-catalog` | `MEDIUM` |
| **`inc2`** | `cart` (Valkey) | OOM / Single-replica SPOF | `none` (Không được restart pod) | `LOW` |
| **`inc3`** | `fraud-detection` | flagd EventStream timeout (gRPC status 4) | `cache-flush` | `LOW` |
| **`inc4`** | `llm` | AWS Bedrock API Rate Limit 429 | `toggle-tf-flag` (Tắt AI Feature) | `MEDIUM` |
| **`inc5`** | `accounting` | Kafka Consumer Lag lớn | `scale deploy/accounting` | `MEDIUM` |
| **`inc6`** | `recommendation` | Memory Pressure / GC latency | `restart deployment/recommendation`| `MEDIUM` |
| **`inc7`** | `product-reviews`| Circuit Breaker bị kẹt OPEN | `breaker-force` (Ép đóng) | `LOW` |
| **`inc8`** | `currency` | Trễ do Cold Start / Warming Cache | `none` (Hệ thống tự phục hồi) | `LOW` |

### Bước 6.2: Kiểm tra tin nhắn Slack
* Sau khi bơm lỗi, hãy đợi khoảng **30 giây** để luồng Polling tick kích hoạt.
* Hệ thống sẽ tự động gửi một **Interactive Slack Card** vào kênh Slack của bạn.
* Báo cáo này hiển thị theo định dạng Bullet Points chi tiết:
  * **Hiện tượng** & **Nguyên nhân gốc rễ**.
  * **Bằng chứng** (chỉ rõ span Jaeger và log Drain3 cụ thể).
  * **Vùng ảnh hưởng (Blast Radius)**.

### Bước 6.3: Phê duyệt sửa lỗi (Approval & Verify Loop)
1. Trên Slack Card, bạn nhấn nút **`✅ Approve (Duyệt chạy)`**.
2. Hệ thống sẽ nhận payload interactive và tiến hành:
   * **Thực thi lệnh** (ở chế độ Sandbox, hệ thống sẽ gọi ngầm `/simulate/remediate` để chuyển đổi trạng thái `remediated = True`).
   * **Chạy vòng lặp kiểm chứng (Verify Loop) trong 5 phút**: Cứ mỗi 30 giây, hệ thống quét lại Prometheus Z-Score. Do trạng thái đã được remediated, Z-Score sẽ phục hồi về `< 2.0` và hệ thống thông báo sửa lỗi thành công!
3. Nếu bạn muốn kiểm tra luồng **Rollback tự động**:
   * Bạn không duyệt chạy lệnh, hoặc cấu hình giả lập trả về thất bại sau 5 phút. Hệ thống sẽ tự động phát lệnh Rollback tương ứng để khôi phục cấu hình cũ an toàn.

---

## 📈 7. Hướng Dẫn Kết Nối & Chạy Live Trên Cụm EKS Thật (Production Mode)

Khi đã kiểm thử thành công trên Sandbox và muốn chuyển sang bắt lỗi live trên cụm EKS thực tế, hãy thực hiện theo các bước chi tiết sau:

### Bước 7.1: Thiết lập cấu hình kết nối EKS (Kubeconfig)
Đảm bảo bạn đã cấu hình AWS CLI cục bộ và có quyền SRE trên cụm. Chạy lệnh sau để cập nhật kubeconfig nhằm kết nối kubectl tới cụm EKS:
```bash
aws eks update-kubeconfig --region ap-southeast-1 --name techx-capstone-eks
```
Kiểm tra kết nối bằng cách liệt kê các Pods hoạt động trong namespace dự án:
```bash
kubectl get pods -n techx-tf3
```

### Bước 7.2: Mở SSM Tunnel bảo mật (Nếu chạy qua AWS Bastion Host)
Trong trường hợp cụm EKS hoặc các API giám sát nằm trong mạng Private VPC và yêu cầu kết nối bảo mật qua SSM Session Manager (Bastion host):
* **On Windows:**
  ```powershell
  $env:PATH += ";C:\Program Files\Amazon\SessionManagerPlugin\bin"
  aws ssm start-session --target i-0abcd1234efgh5678 --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["80"],"localPortNumber":["8080"]}'
  ```
* **On Linux/macOS:**
  ```bash
  aws ssm start-session --target i-0abcd1234efgh5678 --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["80"],"localPortNumber":["8080"]}'
  ```

### Bước 7.3: Mở Port-Forwarding cho bộ ba giám sát (Telemetry Services)
Để AIOps Engine có thể lấy dữ liệu thật từ Prometheus, Jaeger và OpenSearch, bạn cần mở **3 tab terminal mới** để thực hiện port-forward các service tương ứng về local máy cá nhân:

* **Tab 1: Ánh xạ Prometheus (Cổng 9090)**
  ```bash
  kubectl -n techx-tf3 port-forward svc/prometheus-server 9090:80
  ```
  *(Cho phép Engine truy cập Prometheus để tính toán SLO burn-rate và Z-Score hạ tầng)*

* **Tab 2: Ánh xạ Jaeger Query (Cổng 16686)**
  ```bash
  kubectl -n techx-tf3 port-forward svc/jaeger-query 16686:16686
  ```
  *(Cho phép Engine truy cập Jaeger API để phân tích cấu trúc vết lỗi cuộc gọi Trace DAG)*

* **Tab 3: Ánh xạ OpenSearch (Cổng 9200)**
  ```bash
  kubectl -n techx-tf3 port-forward svc/opensearch 9200:9200
  ```
  *(Cho phép Engine truy cập Elasticsearch/OpenSearch để kéo log thô phục vụ Drain3)*

### Bước 7.4: Kiểm tra kết nối tới các dịch vụ live
Trước khi chạy Engine, hãy đảm bảo các cổng cục bộ đã thông suốt bằng cách chạy thử cURL:
```bash
# Kiểm tra Prometheus Live API
curl http://localhost:9090/api/v1/query?query=up

# Kiểm tra OpenSearch Live API
curl http://localhost:9200
```

### Bước 7.5: Cập nhật biến môi trường và chạy Engine
Mở file `aiops-engine/.env` và đổi cấu hình từ Sandbox sang Live EKS:
1. Tắt chế độ giả lập:
   ```bash
   AIOPS_SIMULATION_MODE=false
   ```
2. Cập nhật các đường dẫn URL trỏ về cổng port-forward thực tế:
   ```bash
   JAEGER_URL=http://localhost:16686
   PROMETHEUS_URL=http://localhost:9090
   OPENSEARCH_URL=http://localhost:9200
   ```
3. Khởi động lại máy chủ Engine:
   ```bash
   python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

Hệ thống sẽ lập tức quét chỉ số trực tiếp từ EKS thật, vẽ đồ thị RCA và tự động gửi cảnh báo thẻ duyệt sự cố live về Slack của bạn!
