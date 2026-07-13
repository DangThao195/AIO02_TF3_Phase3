# Hướng Dẫn Chạy & Thử Nghiệm Toàn Diện Dịch Vụ Product Reviews (Local Testing Guide)

Tài liệu này hướng dẫn chi tiết các bước thiết lập môi trường chạy thử nghiệm local (máy host) bằng cách sử dụng **cú pháp `export` (POSIX shell/Bash)**, tích hợp trực tiếp **AWS Bedrock (boto3)** mà không cần qua proxy trung gian LiteLLM, và cách chạy các kịch bản kiểm thử (Fidelity Eval).

---

## 📋 1. Chuẩn Bị Hạ Tầng Nền (Postgres, Catalog, Flagd)

Trước khi chạy service `product-reviews`, bạn cần dựng các service nền như Database PostgreSQL và Catalog Service bằng Docker Compose để có dữ liệu thử nghiệm:

```bash
# 1. Di chuyển vào thư mục chứa docker-compose
cd AIE1/techx-corp-platform/

# 2. Khởi động các container hạ tầng
docker compose up -d postgresql product-catalog flagd otel-collector
```

---

## 🛠️ 2. Các Phương Pháp Chạy Dịch Vụ product-reviews

### Cách A: Chạy Trực Tiếp Bằng Python Trên Máy Host (Khuyên dùng để Debug)

Phương pháp này giúp bạn sửa đổi mã nguồn trực tiếp trong IDE mà không cần build lại Docker container liên tục.

#### 1. Cài đặt thư viện dependencies
```bash
# Di chuyển vào thư mục nguồn của dịch vụ
cd src/product-reviews/

# (Tùy chọn) Khởi tạo và kích hoạt môi trường ảo
python -m venv venv
source venv/bin/activate

# Cài đặt các package (boto3, openai, psycopg2, grpcio, v.v.)
pip install -r requirements.txt
```

#### 2. Cấu hình biến môi trường và chạy Server

Bạn có thể lựa chọn 1 trong 2 cách thiết lập môi trường dưới đây tùy theo thói quen và loại Terminal:

##### 👉 Cách A.1: Sử dụng tệp `.env` cục bộ (Tự động & Khuyên dùng trên VSCode Terminal)
Để tránh các lỗi cú pháp lệnh môi trường khác nhau giữa các shell của VSCode Terminal (như PowerShell, CMD, hay Bash), dịch vụ hiện tại hỗ trợ tự động tải biến môi trường từ tệp `.env` cục bộ:
1. Sao chép tệp cấu hình mẫu:
   ```bash
   cp .env.example .env
   ```
2. Mở tệp `.env` vừa tạo trong VSCode và điền đầy đủ thông tin AWS Credentials của bạn và cấu hình khác.
3. Khởi chạy gRPC Server trực tiếp:
   ```bash
   python product_reviews_server.py
   ```

##### 👉 Cách A.2: Sử dụng lệnh `export` trực tiếp (Dành cho Bash / WSL / Git Bash)
Nếu terminal của bạn hỗ trợ lệnh `export` (như Git Bash, Ubuntu terminal, hoặc WSL), bạn chạy các lệnh sau:
```bash
# Định tuyến LLM sang Bedrock trực tiếp
export LLM_PROVIDER="bedrock"
export LLM_MODEL="amazon.nova-lite-v1:0"
export AWS_REGION="us-east-1"

# Cấu hình AWS Credentials (nếu máy local chưa cấu hình ~/.aws/credentials)
export AWS_ACCESS_KEY_ID="AKIAxxxxxxxxxxxxxx"
export AWS_SECRET_ACCESS_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Cấu hình kết nối gRPC và Database local
export PRODUCT_REVIEWS_PORT="8085"
export DB_CONNECTION_STRING="host=localhost user=otelu password=otelp dbname=demo"
export PRODUCT_CATALOG_ADDR="localhost:8081"
export FLAGD_HOST="localhost"
export FLAGD_PORT="8013"
export LLM_HOST="localhost"
export LLM_PORT="8000"
export OTEL_SERVICE_NAME="product-reviews"

# Khởi chạy gRPC Server
python product_reviews_server.py
```

---

### Cách B: Chạy Bằng Docker Compose (Chạy Đóng Gói)

Nếu bạn muốn chạy dịch vụ bên trong môi trường container khép kín:

1. Thêm cấu hình môi trường vào tệp `.env.override` tại thư mục **[techx-corp-platform](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform)**:
   ```ini
   LLM_PROVIDER=bedrock
   LLM_MODEL=amazon.nova-lite-v1:0
   AWS_REGION=us-east-1
   AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxx
   AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

2. Thực hiện build lại Docker image và khởi chạy container:
   ```bash
   docker compose build product-reviews
   docker compose up -d product-reviews
   ```

---

## 🧪 3. Thực Thi Các Kịch Bản Kiểm Thử (Terminal Mới)

Mở một tab terminal mới để bắt đầu gọi và kiểm tra dịch vụ AI:

### Kịch bản 1: Gọi lấy Tóm tắt AI qua Client Python mẫu
Sử dụng script **[test_client.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/test_client.py)** đã được tích hợp sẵn:

* **Nếu chạy Cách A (Python trên Host - cổng 8085)**:
  ```bash
  python test_client.py 8085
  ```
* **Nếu chạy Cách B (Docker Compose - cổng 3551)**:
  ```bash
  python test_client.py 3551
  ```

### Kịch bản 2: Đánh giá chất lượng Độ trung thực (Fidelity Evaluation)
Để chạy chấm điểm sự ảo giác (Hallucination) của AI Assistant dựa trên tập dữ liệu đánh giá thực tế trong Postgres:

```bash
cd repro/

# Cấu hình môi trường cho script đánh giá
export DB_CONNECTION_STRING="host=localhost user=otelu password=otelp dbname=demo port=5432"
export PRODUCT_REVIEWS_ADDR="localhost:8085"  # Đổi thành 3551 nếu chạy Docker

# Chạy chấm điểm Fidelity (Ví dụ: sử dụng Nova Lite làm Giám khảo)
python eval_fidelity.py --judge-model amazon.nova-lite-v1:0
```
> [!NOTE]
> Kết quả chấm điểm dạng JSON sẽ được lưu tự động trong thư mục `repro/artifacts/`.
