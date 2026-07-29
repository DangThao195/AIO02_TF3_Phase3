# CẨM NANG VẬN HÀNH & CÀI ĐẶT AIOPS ENGINE (TF3)

Tài liệu này được biên soạn dành riêng cho đội ngũ **AIOps (TF3)** để hướng dẫn cài đặt, vận hành hệ thống **AIOps Engine** (FastAPI-based CMDR Pipeline) và bộ **Chaos Validation Suite** (Offline Simulation).

---

## 🗺️ 1. Tổng quan Kiến trúc Vận hành

Hệ thống hoạt động theo mô hình khép kín **Closed-Loop Auto-Remediation (CMDR)**:

```mermaid
graph TD
    subgraph Thu thập & Giám sát (Collect & Monitor)
        A[SLO Burn-rate Monitor] -->|Vỡ SLO / Error Budget| C[Alert Correlator]
        B[Z-Score & Isolation Forest] -->|Bất thường CPU/RAM/Lag| C
    end

    subgraph Chẩn đoán (Diagnose)
        C -->|Topology Map: services.json| D[RCA Assistant]
        D -->|Query Telemetry / Logs| E[Bedrock LLM: Nova Lite]
        E -->|Xác định Culprit| F[Remediation Policy]
    end

    subgraph Khắc phục (Remediate)
        F -->|Safety Gate & Risk Assessment| G{Phân loại Risk}
        G -->|Risk LOW| H[Auto-Execute]
        G -->|Risk MEDIUM| I[Slack SRE Approval]
        H & I -->|Thực thi lệnh| J[Verification Gate: 5 Phút]
        J -->|SLI bình thường| K[Ghi Audit Trail - Success]
        J -->|SLI vẫn lỗi| L[Rollback Plan & Escalate]
    end
```

---

## 🛠️ 2. Hướng dẫn Cài đặt & Chuẩn bị Môi trường

### 2.1 Yêu cầu tiên quyết
*   **Python:** Phiên bản `3.11` trở lên.
*   **AWS CLI:** Đã cài đặt và kiểm tra kết nối với AWS Account.

### 2.2 Các bước thiết lập thư viện (Cục bộ)
Mở terminal tại thư mục gốc `AIOps/chaos-engine/ai-engine` và chạy:

```powershell
# 1. Khởi tạo môi trường ảo
python -m venv .venv
.venv\Scripts\activate   # Trên Windows
# source .venv/bin/activate # Trên Linux/macOS

# 2. Nâng cấp pip & cài đặt dependencies
python -m pip install -U pip
python -m pip install -e .           # Dependencies lõi (FastAPI, boto3, httpx...)
python -m pip install -e ".[ml,dev]" # Cài đặt thêm scikit-learn & pytest phục vụ test ML
```

### 2.3 Cấu hình AWS Credentials
Đảm bảo Profile AWS (`default` hoặc `kietbe`) trên máy có quyền đọc/ghi S3 Bucket `tf3-aiops-models-197826770971` và quyền invoke model Bedrock `amazon.nova-lite-v1:0` ở region `us-east-1`.

Cấu hình mẫu tại tệp `~/.aws/credentials`:
```ini
[default]
aws_access_key_id = YOUR_AWS_ACCESS_KEY_ID
aws_secret_access_key = YOUR_AWS_SECRET_ACCESS_KEY
region = ap-southeast-1
```

---

## ⚙️ 3. Cấu hình biến môi trường (Environment Variables)

Hệ thống có thể chạy ở 2 chế độ: **Simulation Mode** (Giả lập ngoại tuyến, không cần cụm EKS) và **Live EKS Mode** (Kết nối trực tiếp tới K8s).

| Tên biến | Chế độ Giả lập (Simulation) | Chế độ Live (EKS Cluster) | Vai trò |
|---|---|---|---|
| `AIOPS_SIMULATION_MODE` | `"true"` | `"false"` | Quyết định có bỏ qua việc call API K8s thật hay không. |
| `AIOPS_S3_BUCKET` | `"tf3-aiops-models-197826770971"` | `"tf3-aiops-models-197826770971"` | Bucket S3 chứa model ML Isolation Forest. |
| `BEDROCK_MODEL_ID` | `"amazon.nova-lite-v1:0"` | `"amazon.nova-lite-v1:0"` | Model sử dụng cho phân tích RCA chẩn đoán. |
| `AWS_DEFAULT_REGION` | `"ap-southeast-1"` | `"ap-southeast-1"` | Hệ thống tự động redirect Bedrock API sang `us-east-1`. |
| `PROMETHEUS_URL` | N/A | `"http://prometheus-server.techx-tf3.svc.cluster.local:9090"` | DNS Prometheus nội bộ cụm. |
| `JAEGER_URL` | N/A | `"http://jaeger-query.techx-tf3.svc.cluster.local:16686/jaeger/ui"` | DNS Jaeger query. |
| `OPENSEARCH_URL` | N/A | `"http://opensearch.techx-tf3.svc.cluster.local:9200"` | DNS Opensearch log. |

---

## 🏃‍♂️ 4. Quy trình Chạy & Kiểm chứng (Verification)

### 4.1 Chạy Chaos Validation Suite (Simulation Test)
Để kiểm tra xem hệ thống phát hiện và RCA đúng thủ phạm của 15 lỗi khác nhau hay không mà không cần hạ tầng EKS thực tế:

1. Chuyển sang thư mục: `AIOps/chaos-engine/ai-engine`
2. Chạy script:
   ```bash
   python scripts/chaos_validate.py
   ```
3. Kết quả in ra dạng **Scoreboard** (Bảng điểm) và ghi đè vào tệp `chaos/scoreboard.md`.

### 4.2 Chạy Unit Test kiểm tra Safety Gate
Kiểm tra xem hệ thống có tự động chặn các hành động phi-idempotent trên dịch vụ Tier-1 hoặc cho phép tăng limit trên dịch vụ Leaf-node hay không:
```bash
pytest tests/
```

### 4.3 Khởi động Engine FastAPI Server cục bộ
Chạy server tiếp nhận alert webhook và xử lý chẩn đoán:
```bash
# Chạy từ thư mục AIOps/aiops-engine
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🚢 5. Triển khai lên EKS Cluster (SRE / CDO)

Khi triển khai lên cụm EKS thật, thực hiện apply các tệp cấu hình trong thư mục `k8s/`:

```bash
# 1. Tạo Secrets chứa API keys
kubectl create secret opaque aiops-engine-secrets \
  --namespace=techx-tf3 \
  --from-literal=aws-access-key-id="YOUR_AWS_ACCESS_KEY_ID" \
  --from-literal=aws-secret-access-key="YOUR_AWS_SECRET_ACCESS_KEY" \
  --from-literal=slack-webhook-url="YOUR_SLACK_WEBHOOK_URL"

# 2. Tạo Priority Class (Hạ độ ưu tiên của job train ML định kỳ tránh giật lag cụm)
kubectl apply -f k8s/priority-class.yaml

# 3. Deploy Engine và Training Cronjob
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/training-cronjob.yaml
```

---

## 🛠️ 6. Xử lý sự cố thường gặp (Troubleshooting)

### 6.1 Lỗi "AWS Connection / Timeout"
*   **Nguyên nhân:** Cụm EKS ở chế độ Private Access. Bạn không thể chạy `kubectl` từ máy local.
*   **Cách xử lý:** Kết nối qua Bastion Host hoặc chạy gián tiếp thông qua AWS Systems Manager (SSM) CLI. Để kiểm tra pods thực tế trên node mà không có quyền kubectl:
    ```bash
    aws ssm send-command --instance-ids "<NODE_INSTANCE_ID>" --document-name "AWS-RunShellScript" --parameters "commands=['ls /var/log/pods']"
    ```

### 6.2 Lỗi "Fail-Closed" trong kiểm tra ML khi verify
*   **Mô tả:** Hệ thống tự động rollback mặc dù dịch vụ đã hồi phục.
*   **Xử lý:** Kiểm tra xem các mô hình Isolation Forest trong S3 (`tf3-aiops-models-197826770971`) đã được sinh đầy đủ hay chưa. Chạy hot reload để nạp lại model mà không cần restart server:
    ```bash
    curl -X POST http://aiops-engine.techx-tf3.svc.cluster.local/reload-models
    ```
