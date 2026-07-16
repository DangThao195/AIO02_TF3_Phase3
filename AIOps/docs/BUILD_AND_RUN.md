# BUILD & RUN — AIOps CMDR Engine

> Tài liệu tổng hợp: kiến trúc hệ thống, yêu cầu cài đặt, các bước setup đầy đủ, lệnh chạy server, lệnh chạy test, và danh sách những gì còn thiếu để chạy được trên local.

---

## 1. Hệ Thống Này Là Gì?

**AIOps CMDR Engine** là một pipeline SRE tự động hoá khép kín, viết bằng Python/FastAPI, để phát hiện, chẩn đoán và sửa lỗi sự cố cho một hệ thống microservices e-commerce chạy trên AWS EKS.

Tên **CMDR** là viết tắt của 4 giai đoạn xử lý cốt lõi:

```
Correlate → Monitor → Diagnose → Remediate
```

### Luồng xử lý đầy đủ (khi có sự cố):

```
[Prometheus Metrics / Alertmanager]
          |
          v
[1. AnomalyDetector]  ← SLO Burn-rate + Isolation Forest (ML)
          |
          v
[2. AlertCorrelator]  ← Union-Find topology clustering (services.json)
          |
          v
[3. RCAEngine]        ← Jaeger DAG traversal → tìm culprit service
          |
          v
[4. EvidenceCollector] ← OpenSearch logs → Drain3 clustering → templates
          |
          v
[5. LLMDiagnostician]  ← Hybrid RAG + AWS Bedrock (Nova/Claude/Llama)
          |
          v
[6. RemediationHandler] ← Safety gate → Risk classification → kubectl
          |
          v
[Slack Interactive Card]  ← Approve / Reject button
          |
          v
[Verify Loop 5 phút]    ← Z-Score + Isolation Forest → Rollback nếu thất bại
```

---

## 2. Kiến Trúc Các Module

| Module | File | Vai trò |
|---|---|---|
| **AnomalyDetector** | `anomaly_detector.py` | Layer 1: SLO Burn-rate (PromQL, ngưỡng K=14.4). Layer 2: Isolation Forest (18 features, 7 models `.joblib`). Fallback Z-Score khi thiếu model |
| **AlertCorrelator** | `alert_correlator.py` | Dedup fingerprint + BFS/Union-Find theo topology graph `services.json`. Chọn culprit xa frontend nhất |
| **RCAEngine** | `rca_engine.py` | Kéo trace Jaeger API, duyệt DAG tìm span lỗi (`error=true`) sâu nhất để định vị service thủ phạm |
| **EvidenceCollector** | `evidence_collector.py` | Query OpenSearch `otel-logs-*`, chạy Drain3 gom 100+ log thô → ~5 log templates đặc trưng |
| **LLMDiagnostician** | `llm_diagnostician.py` | RAG từ `playbooks_vector_index.json` (local cosine) hoặc Bedrock KB (cloud). Gọi Amazon Nova/Claude/Llama qua Bedrock. Fallback: pattern matcher cứng INC-1..8 |
| **RemediationHandler** | `remediation_handler.py` | Whitelist actions, namespace injection, dry-run gate, risk classification, verify loop 5 phút (Z-Score + IF), auto rollback |
| **SlackNotifier** | `slack_notifier.py` | Gửi Block Kit card với nút Approve/Reject. Fallback in ra console nếu không có webhook |
| **FastAPI Server** | `main.py` | Orchestrator. Hai background loop: polling 30s + graph reload 5 phút. Endpoints: `/webhook/alerts`, `/slack/interactive`, `/simulate/*`, `/readyz` |

### Các file dữ liệu quan trọng đã có sẵn trong repo:

| File/Thư mục | Nội dung |
|---|---|
| `services.json` | Đồ thị dependency giữa 14+ microservices (adjacency list) |
| `playbooks_vector_index.json` | Vector embedding của 8 incident playbooks (dùng cho local RAG) |
| `fixtures/incN_trace_response.json` | Mock Jaeger traces cho INC-1 → INC-8 + incnew |
| `fixtures/incN_logs.json` | Mock OpenSearch logs cho từng kịch bản |
| `models/*_iforest.joblib` | 7 Isolation Forest models đã train sẵn (checkout, frontend, payment, product-catalog, product-reviews, recommendation, shipping) |
| `data/` | CSV training/test data cho 7 services |

---

## 3. Yêu Cầu Cài Đặt (Prerequisites)

### 3.1 Bắt buộc

| Công cụ | Phiên bản tối thiểu | Kiểm tra |
|---|---|---|
| **Python** | 3.10+ | `python --version` |
| **pip** | 23+ | `pip --version` |
| **Git** | bất kỳ | `git --version` |
| **Tài khoản AWS** | có quyền `bedrock:InvokeModel` ở `us-east-1` hoặc `ap-southeast-1` | — |

### 3.2 Cần thiết để nhận thông báo Slack (tuỳ chọn nhưng khuyến nghị)

- **Slack Workspace** + **Incoming Webhook URL** (tạo tại [api.slack.com/apps](https://api.slack.com/apps))
- Nếu không có webhook, hệ thống vẫn chạy bình thường — kết quả RCA sẽ in ra console thay vì gửi Slack.

### 3.3 Không cần cho chế độ Sandbox (AIOPS_SIMULATION_MODE=true)

Các công cụ dưới đây **chỉ cần** khi chuyển sang chế độ Live EKS:

- `kubectl` + `aws eks update-kubeconfig`
- AWS CLI + SSM Session Manager Plugin
- Kết nối tới cụm EKS `techx-capstone-eks` ở region `ap-southeast-1`

---

## 4. Cài Đặt Môi Trường Local

### Bước 4.1 — Di chuyển vào thư mục engine

```powershell
# Từ thư mục gốc của repo (AIO02_TF3_Phase3/AIOps/)
cd aiops-engine
```

### Bước 4.2 — Tạo và kích hoạt Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

> Dấu nhắc terminal sẽ đổi thành `(venv)` khi kích hoạt thành công.

### Bước 4.3 — Cài đặt dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Danh sách thư viện chính được cài đặt:

| Thư viện | Vai trò |
|---|---|
| `fastapi` + `uvicorn` | HTTP server framework |
| `boto3` | AWS SDK: Bedrock LLM, Bedrock KB, S3 |
| `drain3` | Log template mining (clustering) |
| `scikit-learn` + `joblib` | Isolation Forest inference |
| `pandas` + `numpy` | Feature engineering pipeline |
| `kubernetes` | K8s API client (dùng ở Live mode) |
| `requests` | HTTP calls tới Prometheus, Jaeger, OpenSearch, Slack |
| `pydantic` | Request/response validation |

### Bước 4.4 — Tạo file `.env`

Tạo file `aiops-engine/.env` với nội dung sau (thay các giá trị `YOUR_*`):

```bash
# =========================================================
# CHẾ ĐỘ HOẠT ĐỘNG
# true  = Sandbox giả lập local (không cần EKS, không cần Prometheus thật)
# false = Kết nối live EKS thật
# =========================================================
AIOPS_SIMULATION_MODE=true

# =========================================================
# SANDBOX MODE — trỏ về localhost (chính server FastAPI tự phục vụ)
# =========================================================
JAEGER_URL=http://localhost:8000/mock-jaeger
PROMETHEUS_URL=http://localhost:8000/mock-prometheus
OPENSEARCH_URL=http://localhost:8000/mock-opensearch
SIMULATION_SERVER_URL=http://localhost:8000

# =========================================================
# AWS BEDROCK — bắt buộc để gọi LLM thật
# Nếu để trống, hệ thống fallback sang local pattern matcher
# =========================================================
BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
EXTERNAL_AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
EXTERNAL_AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
EXTERNAL_AWS_REGION=us-east-1

# =========================================================
# SLACK — tuỳ chọn (để trống = in kết quả ra console)
# =========================================================
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK

# =========================================================
# BEDROCK KNOWLEDGE BASE — tuỳ chọn (để trống = dùng local RAG)
# =========================================================
# BEDROCK_KB_ID=GH3FUCYVOJ
```

> **Bảo mật:** File `.env` đã có trong `.gitignore`. Tuyệt đối không commit file này lên Git.

---

## 5. Khởi Động Server Local

Đảm bảo đang ở trong thư mục `aiops-engine/` và môi trường ảo `venv` đã được kích hoạt.

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Kết quả mong đợi trong terminal:**

```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     AIOpsEngine.AlertCorrelator: Successfully loaded service graph version g-xxxx (14 nodes, 18 edges)
INFO:     AIOpsEngine.AnomalyDetector: Loaded 7 Isolation Forest models into memory: [...]
INFO:     AIOpsEngine.Main: Starting Active Metrics Polling Loop (Mode B)...
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Kiểm tra server đã sẵn sàng:**

```powershell
# Windows PowerShell
Invoke-RestMethod -Uri "http://localhost:8000/readyz"

# Linux/macOS
curl http://localhost:8000/readyz
```

Kết quả trả về: `{"status":"ready","checks":{"topology_graph":"ok","local_kb":"ok"}}`

**Xem version và metadata đồ thị topology:**

```bash
curl http://localhost:8000/version
```

---

## 6. Chạy Test Tự Động

Mở một **terminal mới** (giữ nguyên server đang chạy ở terminal cũ), kích hoạt venv và chạy:

```bash
cd aiops-engine
# Windows
.\venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# Chạy toàn bộ test suite
pytest tests/ -v
```

### Mô tả từng test file:

| File | Loại test | Yêu cầu |
|---|---|---|
| `test_e2e_with_fixtures.py` | **Unit + Integration** — Chạy full pipeline với mock fixtures (inc1, inc2, inc3). Không cần AWS, không cần Prometheus. | Chỉ cần fixtures/ và models/ |
| `test_ml_anomaly.py` | **Unit** — Kiểm tra feature engineering (18 columns), simulation mode, Z-Score fallback khi thiếu model. | Không cần kết nối ngoài |
| `test_incident_flow.py` | **Integration** — Giả lập full CMDR flow với mock LLM (INC-3), risk classification, dry-run, Slack fallback. | Không cần AWS/Slack thật |
| `test_semantic_rag.py` | **Unit** — Cosine similarity math, local RAG từ `playbooks_vector_index.json` cho INC-1 và INC-4. | Không cần AWS |
| `test_anomaly_detection.py` | **Integration** — SLO burn-rate algorithm, Z-Score. Cần Prometheus đang chạy (dùng localhost:9090). | Cần port-forward Prometheus |
| `test_retrieval.py` | **Integration** — Kết nối live tới Jaeger và Prometheus qua localhost:8080. | Cần port-forward EKS |
| `test_bedrock_raw.py` | **Integration** — Gọi AWS Bedrock API thật để kiểm tra kết nối. | Cần AWS credentials hợp lệ |
| `test_opensearch_indices.py` | **Integration** — Liệt kê indices và kiểm tra `otel-logs-*` trên OpenSearch. | Cần port-forward OpenSearch |

### Chạy chỉ các test không cần kết nối ngoài (khuyến nghị để test local nhanh):

```bash
pytest tests/test_e2e_with_fixtures.py tests/test_ml_anomaly.py tests/test_incident_flow.py tests/test_semantic_rag.py -v
```

### Chạy test Bedrock (cần AWS credentials):

```bash
pytest tests/test_bedrock_raw.py -v -s
```

---

## 7. Kiểm Thử Thủ Công — Sandbox Fault Injection

Khi server đang chạy, bạn có thể bơm lỗi giả lập để xem toàn bộ luồng CMDR hoạt động.

### Bước 7.1 — Bơm lỗi vào hệ thống

**Windows PowerShell:**
```powershell
# Bơm kịch bản INC-4 (LLM Rate Limit)
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/inject?scenario=inc4"

# Kiểm tra trạng thái simulation hiện tại
Invoke-RestMethod -Uri "http://localhost:8000/simulate/state"
```

**Linux / macOS (cURL):**
```bash
curl -X POST "http://localhost:8000/simulate/inject?scenario=inc4"
curl "http://localhost:8000/simulate/state"
```

### Bước 7.2 — Đợi polling tick (khoảng 30 giây)

Server sẽ tự động phát hiện anomaly, chạy RCA, và gửi kết quả ra Slack (hoặc in ra console nếu không cấu hình webhook).

Theo dõi log server để xem từng giai đoạn:
```
[INFO] Active Polling Check: checking system SLO via Prometheus...
[WARNING] SLO Burn Rate breach detected via Active Polling!
[INFO] Triggering CMDR Pipeline for INC-... (Culprit: llm, Trace ID: mock-inc4)
[INFO] Step 1: Generating Evidence Pack...
[INFO] Step 2: Invoking LLM Bedrock Diagnostician...
[INFO] Action 'toggle-tf-flag' classified as MEDIUM RISK. Sending Slack card...
```

### Bước 7.3 — Phê duyệt sửa lỗi thủ công qua API

Nếu không dùng Slack, bạn có thể approve trực tiếp qua endpoint giả lập:

```powershell
# Windows
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/approve"

# Linux/macOS
curl -X POST "http://localhost:8000/simulate/approve"
```

### Danh sách kịch bản để inject:

| Scenario | Dịch vụ thủ phạm | Loại lỗi | Hành động đề xuất | Risk |
|---|---|---|---|---|
| `inc1` | `postgresql` | DB connection pool cạn | `scale deploy/product-catalog` | MEDIUM |
| `inc2` | `cart` (Valkey) | OOM / SPOF single replica | `none` (tuyệt đối không restart) | LOW |
| `inc3` | `fraud-detection` | gRPC EventStream timeout flagd | `cache-flush` (scale=1) | LOW |
| `inc4` | `llm` | Bedrock API Rate Limit 429 | `toggle-tf-flag` (tắt AI) | MEDIUM |
| `inc5` | `accounting` | Kafka consumer lag lớn | `scale deploy/accounting` | MEDIUM |
| `inc6` | `recommendation` | Memory pressure / GC latency | `restart deployment` | MEDIUM |
| `inc7` | `product-reviews` | Circuit Breaker kẹt OPEN | `breaker-force` | LOW |
| `inc8` | `currency` | Cold start / warming cache | `none` (tự phục hồi) | LOW |

### Bước 7.4 — Reset về trạng thái bình thường

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/inject?scenario=stable"
```

---

## 8. Những Gì Còn Thiếu Để Chạy Đầy Đủ Trên Local

Dưới đây là danh sách đầy đủ những gì **chưa có / cần bổ sung** để engine hoạt động ở từng mức độ.

### 8.1 Để chạy server + test cơ bản (Sandbox mode)

| Thiếu gì | Mức độ | Cách khắc phục |
|---|---|---|
| File `aiops-engine/.env` | **BẮT BUỘC** | Tạo theo mẫu ở Mục 4.4 |
| AWS credentials hợp lệ trong `.env` | **BẮT BUỘC** để gọi Bedrock LLM | Điền `EXTERNAL_AWS_ACCESS_KEY_ID` và `EXTERNAL_AWS_SECRET_ACCESS_KEY`. Nếu không có, hệ thống tự fallback sang `match_incident_locally()` — vẫn chạy được |
| Model `accounting_iforest.joblib` và `llm_iforest.joblib` | Không bắt buộc | Hiện `models/` chỉ có 7 model cho: checkout, frontend, payment, product-catalog, product-reviews, recommendation, shipping. Dịch vụ `accounting`, `llm`, `cart` sẽ fallback Z-Score — vẫn chạy được |

### 8.2 Để LLM Bedrock hoạt động đúng

| Thiếu gì | Ghi chú |
|---|---|
| AWS Access Key có quyền `bedrock:InvokeModel` | Model `amazon.nova-micro-v1:0` cần được enable trong Bedrock console tại region đã chọn (`us-east-1` hoặc `ap-southeast-1`) |
| Model access enabled trên AWS Bedrock console | Một số model mặc định bị khoá — cần vào AWS Console → Bedrock → Model access để bật |

> **Không có AWS credentials vẫn chạy được**: LLMDiagnostician sẽ tự gọi `match_incident_locally()` — một bộ pattern matcher tĩnh cho INC-1..8. Kết quả chẩn đoán vẫn chính xác cho 8 kịch bản đã biết.

### 8.3 Để nhận thông báo Slack

| Thiếu gì | Ghi chú |
|---|---|
| `SLACK_WEBHOOK_URL` trong `.env` | Nếu để trống, hệ thống in kết quả ra stdout thay vì gửi Slack — các test vẫn pass |
| Slack App với `Interactive Components` | Nếu muốn dùng nút Approve/Reject thật: cần cấu hình Request URL của Slack App trỏ về `http://your-public-url:8000/slack/interactive`. Không thể dùng localhost trực tiếp — cần dùng ngrok hoặc deploy lên server |

### 8.4 Để chạy Live EKS (Production mode)

Cần thêm tất cả các công cụ và quyền truy cập sau:

| Thiếu gì | Lệnh cài đặt / cấu hình |
|---|---|
| `kubectl` | [docs.aws.amazon.com/eks/latest/userguide/install-kubectl](https://docs.aws.amazon.com/eks/latest/userguide/install-kubectl.html) |
| AWS CLI v2 | [docs.aws.amazon.com/cli/latest/userguide/install-cliv2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| IAM quyền EKS SRE | Cần quyền `eks:DescribeCluster`, `eks:ListClusters` + kubeconfig |
| Kubeconfig cho cụm | `aws eks update-kubeconfig --region ap-southeast-1 --name techx-capstone-eks` |
| SSM Session Manager Plugin | Chỉ cần nếu EKS nằm trong Private VPC qua Bastion |
| Port-forward 3 terminal | Prometheus `:9090`, Jaeger `:16686`, OpenSearch `:9200` |
| K8s Secret `aiops-engine-secrets` | Chứa Slack webhook và AWS credentials — tạo bằng `kubectl create secret generic` |

### 8.5 Để chạy Slack Approval thật từ local (không phải EKS)

Slack cần một URL công khai để gửi payload Interactive khi user bấm nút. Giải pháp:

```bash
# Cài ngrok
ngrok http 8000
# Copy HTTPS URL từ ngrok (e.g. https://abc123.ngrok.io)
# Cấu hình trong Slack App: Interactivity & Shortcuts → Request URL
# → https://abc123.ngrok.io/slack/interactive
```

---

## 9. Cấu Trúc Thư Mục Đầy Đủ

```
AIOps/
├── aiops-engine/                        ← Toàn bộ source code Python
│   ├── main.py                          ← FastAPI app + CMDR orchestrator + polling loops
│   ├── config.py                        ← Đọc .env, map biến env, định nghĩa whitelist
│   ├── anomaly_detector.py              ← SLO burn-rate + Isolation Forest + Z-Score
│   ├── alert_correlator.py              ← Topology clustering + Union-Find dedup
│   ├── rca_engine.py                    ← Jaeger DAG traversal → culprit service
│   ├── evidence_collector.py            ← OpenSearch logs + Drain3 clustering
│   ├── llm_diagnostician.py             ← Bedrock LLM + Hybrid RAG + local fallback
│   ├── remediation_handler.py           ← Safety gate + kubectl + verify loop + rollback
│   ├── slack_notifier.py                ← Block Kit card + console fallback
│   ├── train_anomaly_model_local.py     ← Train Isolation Forest từ CSV local
│   ├── train_anomaly_model_eks.py       ← Train từ Prometheus live (dùng trên EKS)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── services.json                    ← Topology graph microservices
│   ├── playbooks_vector_index.json      ← Pre-embedded playbook vectors (local RAG)
│   ├── fixtures/                        ← Mock Jaeger traces + logs INC-1..8 + incnew
│   ├── models/                          ← 7 trained .joblib Isolation Forest models
│   ├── data/                            ← CSV training/test data
│   ├── tests/                           ← 8 pytest test files
│   ├── scripts/
│   │   ├── embed_playbooks.py           ← Tạo lại playbooks_vector_index.json
│   │   ├── deploy_bedrock_kb.py         ← Deploy incident history lên Bedrock KB
│   │   └── fire_webhook.py              ← Gửi mock Alertmanager webhook để test
│   └── k8s/
│       ├── deployment.yaml              ← K8s Deployment + ClusterIP Service
│       └── training-cronjob.yaml        ← Weekly retraining CronJob
├── contracts/                           ← Integration contracts C1-C6
└── docs/
    ├── ONBOARDING_AND_TESTING_GUIDE.md  ← Hướng dẫn gốc của dự án
    └── BUILD_AND_RUN.md                 ← File này
```

---

## 10. Thông Tin Đáng Chú Ý

### Hai chế độ vận hành:

| | Sandbox (AIOPS_SIMULATION_MODE=true) | Live EKS (false) |
|---|---|---|
| Prometheus | Mock endpoint `/mock-prometheus` trên chính server | Port-forward `svc/prometheus-server:9090` |
| Jaeger | Mock endpoint `/mock-jaeger` + fixture JSON | Port-forward `svc/jaeger-query:16686` |
| OpenSearch | Mock endpoint `/mock-opensearch` + fixture JSON | Port-forward `svc/opensearch:9200` |
| kubectl | Giả lập (gọi `/simulate/remediate`) | Thực thi thật trên namespace `techx-tf3` |
| LLM | Vẫn gọi Bedrock thật (nếu có credentials) | Như sandbox |

### Safety invariants (C6 contract) đã được cài cứng trong code:

- **Invariant 1**: Chỉ 5 action type được phép: `scale`, `restart`, `toggle-tf-flag`, `cache-flush`, `breaker-force`
- **Invariant 2**: Các keyword nguy hiểm bị chặn: `rm`, `delete`, `flagd-sync`, `token`, `mkfs`, `bash`
- **Invariant 3**: Namespace luôn được inject `-n techx-tf3` nếu thiếu
- **Invariant 4**: Tối đa 3 lần thực thi per incident per hour
- **Invariant 5**: Dry-run bắt buộc trước khi chạy thật (khi ở Live mode)

### Risk classification:

| Risk Level | Actions | Hành vi |
|---|---|---|
| LOW | `cache-flush`, `breaker-force` | Tự động thực thi ngay, không cần approve |
| MEDIUM | `scale`, `restart`, `toggle-tf-flag` | Gửi Slack card chờ approve |
| HIGH / Unknown | Bất kỳ action nào khác | Tự động từ chối |
| LOW nhưng confidence < 0.80 | — | Nâng lên MEDIUM để an toàn hơn |

### Về Isolation Forest models:

- 7 models đã được train sẵn và commit vào repo tại `models/`
- Các dịch vụ `accounting`, `cart`, `llm`, `currency` **chưa có model** → fallback về Z-Score tự động
- Để train lại model local: `python train_anomaly_model_local.py`
- Để nhúng lại playbook vectors (khi cập nhật INCIDENT_HISTORY.md): `python scripts/embed_playbooks.py`

### Về Local RAG vs Bedrock KB:

- Nếu `BEDROCK_KB_ID` **không được set**: dùng `playbooks_vector_index.json` (local cosine similarity, ngưỡng ≥ 0.35)
- Nếu `BEDROCK_KB_ID` **được set**: gọi `bedrock-agent-runtime` Retrieve API (cloud-native RAG)
- Nếu cả hai đều thất bại: đọc toàn bộ `INCIDENT_HISTORY.md` dưới dạng text thuần

---

## 11. Tóm Tắt Lệnh Nhanh (Quick Reference)

```powershell
# === SETUP (chạy 1 lần) ===
cd aiops-engine
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
# → Tạo file .env theo mẫu Mục 4.4

# === CHẠY SERVER ===
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# === KIỂM TRA SERVER ===
Invoke-RestMethod -Uri "http://localhost:8000/readyz"

# === CHẠY TEST (terminal mới, venv activated) ===
pytest tests/test_e2e_with_fixtures.py tests/test_ml_anomaly.py tests/test_incident_flow.py tests/test_semantic_rag.py -v

# === FAULT INJECTION ===
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/inject?scenario=inc4"
Invoke-RestMethod -Uri "http://localhost:8000/simulate/state"
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/approve"
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/simulate/inject?scenario=stable"

# === KIỂM TRA ANOMALY ML (test trực tiếp endpoint) ===
$body = '{"service":"frontend","rps":500,"cpu_usage":0.95,"memory_usage":0.9,"latency_p90":2.5,"error_rate":0.3}'
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/anomaly/predict" -Body $body -ContentType "application/json"
```
