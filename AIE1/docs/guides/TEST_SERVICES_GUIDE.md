# Hướng Dẫn Chạy & Thử Nghiệm Toàn Diện Dịch Vụ Product Reviews (Local Testing Guide)

Tài liệu này hướng dẫn chi tiết các bước thiết lập môi trường chạy thử nghiệm local (máy host) bằng cách sử dụng **cú pháp `export` (POSIX shell/Bash)**, tích hợp trực tiếp **AWS Bedrock (boto3)**, và phân định rõ ràng các câu lệnh chạy trên **WSL2 (Ubuntu) / Git Bash** hay **Windows PowerShell / CMD**.

---

## 📋 1. Chuẩn Bị Hạ Tầng Nền (Postgres, Catalog, Flagd)
> [!IMPORTANT]
> **Chạy ở Terminal 1 [WSL2 (Ubuntu) / Git Bash / Linux]** hoặc **Command Prompt / PowerShell** đều được:

Trước khi chạy service `product-reviews`, bạn cần dựng các service nền như Database PostgreSQL và Catalog Service bằng Docker Compose để có dữ liệu thử nghiệm:

```bash
# 1. Di chuyển vào thư mục chứa docker-compose
cd AIE1/techx-corp-platform/

# 2. Khởi động các container hạ tầng nền
docker compose up -d postgresql product-catalog flagd otel-collector
```
*(Tham số `-d` chạy ngầm, sau khi chạy xong container sẽ giải phóng terminal để bạn gõ tiếp).*

---

## 🛠️ 2. Các Phương Pháp Chạy Dịch Vụ product-reviews (Server)

### Cách A: Chạy Trực Tiếp Bằng Python Trên Máy Host (Khuyên dùng để Debug)

#### 1. Cài đặt thư viện dependencies và môi trường ảo
> [!IMPORTANT]
> **Chạy ở Terminal 1 [WSL2 (Ubuntu) / Git Bash / Linux]**:
> Nếu chạy trên WSL Ubuntu mới cài và báo lỗi `ensurepip` hoặc thiếu `pip3`, hãy chạy lệnh cài đặt nền trước:
> `sudo apt update && sudo apt install -y python3-pip python3-venv`

```bash
# Di chuyển vào thư mục nguồn của dịch vụ
cd src/product-reviews/

# Khởi tạo môi trường ảo (Dùng python3 trên Linux/WSL)
python3 -m venv venv

# Kích hoạt môi trường ảo
source venv/bin/activate

# Cài đặt các package (boto3, openai, psycopg2, grpcio, v.v.)
pip install -r requirements.txt
```

#### 2. Cấu hình biến môi trường và chạy Server
> [!NOTE]
> Với stack Docker local của repo này, database thực tế là `otel`, không phải `demo`.
> Nếu dùng PostgreSQL publish port khác `5432`, hãy thay thêm `port=<published_port>` trong `DB_CONNECTION_STRING`.

Bạn có thể lựa chọn 1 trong 2 cách thiết lập môi trường dưới đây tùy theo loại Terminal bạn đang sử dụng:

##### 👉 Lựa chọn A.2.1: Sử dụng lệnh `export` trực tiếp (Khuyên dùng cho WSL / Git Bash / macOS)
> [!IMPORTANT]
> **Chạy ở Terminal 1 [WSL2 (Ubuntu) / Git Bash / Linux]**:

```bash
# Kích hoạt venv nếu chưa kích hoạt
source venv/bin/activate

# Định tuyến LLM sang Bedrock trực tiếp
export LLM_PROVIDER="bedrock"
export LLM_MODEL="amazon.nova-lite-v1:0"
export AWS_REGION="us-east-1"

# Cấu hình AWS Credentials (nếu máy local chưa cấu hình ~/.aws/credentials)
export AWS_ACCESS_KEY_ID="AKIAxxxxxxxxxxxxxx"
export AWS_SECRET_ACCESS_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Cấu hình kết nối gRPC và Database local
export PRODUCT_REVIEWS_PORT="8085"
export DB_CONNECTION_STRING="host=localhost user=otelu password=otelp dbname=otel"
export PRODUCT_CATALOG_ADDR="localhost:8081"
export FLAGD_HOST="localhost"
export FLAGD_PORT="8013"
export LLM_HOST="localhost"
export LLM_PORT="8000"
export OTEL_SERVICE_NAME="product-reviews"

# Khởi chạy gRPC Server (giữ nguyên tab terminal này không tắt)
python3 product_reviews_server.py
```

##### 👉 Lựa chọn A.2.2: Sử dụng tệp `.env` cục bộ (Dành cho mọi Terminal kể cả cmd/powershell của Windows)
> [!IMPORTANT]
> **Chạy ở Terminal 1 [Windows PowerShell / CMD / VSCode Default Terminal]**:

1. Sao chép tệp cấu hình mẫu:
   ```bash
   cp .env.example .env
   ```
2. Mở tệp `.env` vừa tạo trong VSCode và điền đầy đủ thông tin AWS Credentials của bạn và cấu hình khác.
3. Khởi chạy gRPC Server trực tiếp (Dùng venv trên Windows):
   ```powershell
   # Kích hoạt venv trên Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   
   python product_reviews_server.py
   ```

---

### Cách B: Chạy Bằng Docker Compose (Chạy Đóng Gói)
> [!IMPORTANT]
> **Chạy ở Terminal 1 [WSL2 / Windows PowerShell / CMD]**:

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

## 🧪 3. Thực Thi Các Kịch Bản Kiểm Thử (Terminal 2 - Mới)
> [!IMPORTANT]
> **Mở Terminal 2 mới song song** (không chạy chung terminal đang chạy server ở trên).

### Kịch bản 1: Gọi lấy Tóm tắt AI qua Client Python mẫu
Sử dụng script **[test_client.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/test_client.py)** đã được tích hợp sẵn:

* **Phương án 1.1: Chạy trong WSL2 / Git Bash (Terminal 2 - WSL2)**:
  ```bash
  cd AIE1/techx-corp-platform/src/product-reviews/
  source venv/bin/activate
  
  # Cổng 8085 nếu chạy server trực tiếp bằng Python, 3551 nếu chạy bằng Docker
  python3 test_client.py 8085 
  ```
* **Phương án 1.2: Chạy trên Windows Host (Terminal 2 - PowerShell / CMD)**:
  *(Yêu cầu máy Windows của bạn đã cài python và cài thư viện: `pip install grpcio grpcio-tools`)*
  ```powershell
  cd AIE1/techx-corp-platform/src/product-reviews/
  
  # Cổng 8085 nếu chạy server trực tiếp bằng Python, 3551 nếu chạy bằng Docker
  python test_client.py 8085
  ```

---

### Kịch bản 2: Đánh giá chất lượng Độ trung thực (Fidelity Evaluation)
> [!IMPORTANT]
> **Chạy ở Terminal 2 [WSL2 (Ubuntu) / Git Bash]**:

Để chạy chấm điểm sự ảo giác (Hallucination) của AI Assistant dựa trên tập dữ liệu đánh giá thực tế trong Postgres:

```bash
cd repro/

# Cấu hình môi trường cho script đánh giá
export DB_CONNECTION_STRING="host=localhost user=otelu password=otelp dbname=otel port=5432"
export PRODUCT_REVIEWS_ADDR="localhost:8085"  # Đổi thành 3551 nếu chạy Docker

# Chạy chấm điểm Fidelity (Ví dụ: sử dụng Nova Lite làm Giám khảo)
python3 eval_fidelity.py --judge-model amazon.nova-lite-v1:0
```
> [!NOTE]
> Kết quả chấm điểm dạng JSON sẽ được lưu tự động trong thư mục `repro/artifacts/`.

