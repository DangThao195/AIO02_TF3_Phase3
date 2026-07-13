# Hướng Dẫn Chạy & Thử Nghiệm Toàn Diện Dịch Vụ Product Reviews (Real LLM & Fidelity Eval)

Tài liệu này hướng dẫn chi tiết các bước thiết lập môi trường chạy thử nghiệm thực tế (Real LLM) thông qua proxy LiteLLM kết nối AWS Bedrock, đo đạc chỉ số (Latency, Token) và chạy bộ kiểm toán Fidelity Evaluation.

---

## BƯỚC 1: Khởi động hạ tầng cơ sở và Database (Terminal 1 - WSL2)

Mở **Terminal 1 (WSL2)**, di chuyển vào thư mục dự án và khởi động các container nền:

```bash
cd "/mnt/c/Users/ASUS/OneDrive/Obsidian Vault/XBrain-Phase3/techx-corp-platform"

# 1. Khai báo ánh xạ cổng Postgres ra máy host vật lý phục vụ script eval chạy bên ngoài
export POSTGRES_PORT="5432:5432"

# 2. Khởi động các dịch vụ hạ tầng cốt lõi
docker compose up -d postgresql product-catalog otel-collector flagd
```

---

## BƯỚC 2: Thiết lập Bedrock Proxy (Terminal 2 - PowerShell)

Mở **Terminal 2 (PowerShell)** để khởi chạy LiteLLM làm proxy dịch mã OpenAI API sang Bedrock Converse API, đồng thời xử lý các tham số không tương thích:

```powershell
cd "C:\Users\ASUS\OneDrive\Obsidian Vault\XBrain-Phase3\repro"

# Khởi chạy LiteLLM Proxy với file cấu hình định tuyến cho AWS Bedrock
litellm --config litellm_config.yaml --port 4000
```
> [!NOTE]
> Giữ nguyên terminal này chạy ẩn để duy trì dịch vụ proxy.

---

## BƯỚC 3: Cấu hình và chạy Dịch Vụ gRPC (Terminal 1 - WSL2)

Quay lại **Terminal 1 (WSL2)** để cấu hình cho container `product-reviews` gọi LLM thông qua LiteLLM proxy ở máy host:

```bash
# Trỏ base URL về máy Windows host thông qua Docker Gateway
export LLM_BASE_URL="http://host.docker.internal:4000/v1"
export LLM_MODEL="amazon.nova-lite-v1:0" # Hoặc "amazon.nova-micro-v1:0" / "meta.llama3-3-70b-instruct-v1:0"
export OPENAI_API_KEY="dummy"

# Khởi động dịch vụ product-reviews
docker compose up -d product-reviews
```

---

## BƯỚC 4: Tiến hành các Kịch Bản Kiểm Thử (Terminal 3 - PowerShell)

Mở một **Terminal 3 (PowerShell) mới** để chạy các script Python kiểm thử:

```powershell
cd "C:\Users\ASUS\OneDrive\Obsidian Vault\XBrain-Phase3\repro"
```

### 1. Gọi lấy Tóm tắt AI đơn lẻ
Chạy script **[repro/get_summary.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/get_summary.py)** để in nhanh phản hồi của AI Assistant:
```powershell
python get_summary.py
```

### 2. Đo đạc lượng Token tiêu thụ thực tế
Chạy script **[repro/check_tokens.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/check_tokens.py)** để thống kê chi tiết số Input/Output tokens qua 2 lượt gọi RAG:
```powershell
# Thiết lập biến môi trường kết nối proxy cho PowerShell hiện tại
$env:LLM_BASE_URL="http://localhost:4000/v1"
$env:LLM_MODEL="amazon.nova-lite-v1:0" # Đổi tên model tương ứng khi cần test
$env:OPENAI_API_KEY="dummy"

python check_tokens.py
```

### 3. Đo đạc Baseline Hiệu năng (Latency & Error Rate)
Chạy script **[repro/benchmark.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/benchmark.py)** gửi dồn dập 20 requests liên tục:
```powershell
python benchmark.py 20
```

### 4. Đánh giá kiểm toán Độ trung thực (Fidelity Evaluation)
Chạy script **[repro/eval_fidelity.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/eval_fidelity.py)** để kéo reviews gốc từ database Postgres, gọi gRPC lấy tóm tắt candidate, và đối chiếu chấm điểm Fidelity 1-5 bằng LLM Judge:
```powershell
# Cấu hình kết nối Database và LLM Judge
$env:DB_CONNECTION_STRING="host=localhost user=otelu password=otel dbname=otel port=5432"
$env:PRODUCT_REVIEWS_ADDR="localhost:3551"
$env:OPENAI_API_KEY="dummy"

# Chạy chấm điểm Fidelity (sử dụng Nova Lite làm Giám khảo)
python eval_fidelity.py --judge-model amazon.nova-lite-v1:0 --judge-base-url http://localhost:4000/v1
```
*Kết quả chi tiết dạng JSON của phiên chạy sẽ được lưu tự động trong thư mục `repro/artifacts/`.*
