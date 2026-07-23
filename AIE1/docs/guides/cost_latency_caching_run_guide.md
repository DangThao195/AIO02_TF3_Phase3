# Hướng Dẫn Chạy Thực Tế Sub-task 2.4: Đo Lường Cost/Latency Caching

Tài liệu này hướng dẫn chi tiết từng bước để chạy migration database, khởi chạy server và thực hiện đo đạc các chỉ số Cost và Latency của cache (Cold Cache vs Hot Cache) trên máy local sử dụng các Terminal khác nhau (WSL/Git Bash, PowerShell hoặc CMD).

---

## 📋 Yêu Cầu Chuẩn Bị Trước Khi Chạy

> [!TIP]
> Tài liệu này được thiết kế bổ trợ dựa trên tài liệu chuẩn [docs/guides/TEST_SERVICES_GUIDE.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/guides/TEST_SERVICES_GUIDE.md).

1. **Docker Desktop** phải được bật và chạy bình thường.
2. Khởi động đầy đủ các dịch vụ phụ trợ nền (**PostgreSQL, Product Catalog, Flagd, OpenTelemetry Collector** và **Valkey/Redis**) từ thư mục `techx-corp-platform`:
   ```bash
   cd techx-corp-platform
   docker compose up -d postgresql product-catalog flagd otel-collector valkey-cart
   cd ..
   ```

> [!CAUTION]
> **Lỗi thường gặp: `Connection refused` đến cổng 5432 hoặc 6379 (đặc biệt khi dùng WSL)**
> 
> Nếu chạy lệnh ở Bước 1 gặp lỗi `Failed to connect to database: Connection refused`, có các nguyên nhân chính:
> 1. Dịch vụ Docker Postgresql/Valkey chưa khởi chạy (hãy chạy lệnh `docker compose up -d postgresql valkey-cart` như trên).
> 2. Cổng dịch vụ bị thay đổi trên máy host: Hãy kiểm tra bằng `docker compose ps` để xem các container đang chạy trên cổng nào. Nếu chúng được map ra cổng ngẫu nhiên (ví dụ Postgres map ra `50319`, Catalog ra `50333`), bạn hãy cập nhật lại biến môi trường `DB_CONNECTION_STRING` với cổng tương ứng (Xem chi tiết tại [TEST_SERVICES_GUIDE.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/guides/TEST_SERVICES_GUIDE.md)).
> 3. WSL 2 không phân giải được `localhost` tới Windows Host.
>    * **Cách khắc phục nhanh nhất**: Mở terminal **PowerShell** hoặc **CMD** trực tiếp trên Windows để chạy thay vì WSL.
>    * **Cách khắc phục triệt để trên WSL**: Mở **Docker Desktop Settings** -> **Resources** -> **WSL integration** -> Bật kích hoạt cho Distro WSL của bạn rồi restart Terminal.

---

## 🛠️ Quy Trình Thực Hiện Từng Bước

### Bước 1: Khởi động Database Migration & Quét dữ liệu cũ

> [!IMPORTANT]
> Vì script migration chạy các lệnh `ALTER TABLE` và `CREATE TABLE` trên schema `reviews`, bạn cần kết nối bằng tài khoản quản trị (**user=root**) để tránh lỗi `must be owner of table productreviews`. Lịch sử thực thi sau đó sẽ tự động phân quyền truy cập cho user thường (`otelu`).

Mở cửa sổ Terminal tại thư mục gốc của dự án `AIE1` và chạy các lệnh dưới đây để di chuyển vào thư mục dịch vụ, kích hoạt môi trường ảo và chạy migration:

#### 💻 Lựa chọn A: Nếu dùng Git Bash / WSL (Khuyến nghị)
```bash
cd techx-corp-platform/src/product-reviews/
source .venv/bin/activate
DB_CONNECTION_STRING="host=localhost user=root password=otel dbname=otel port=5432" python db_migration_worker.py
```

#### 💻 Lựa chọn B: Nếu dùng Windows PowerShell
```powershell
cd techx-corp-platform\src\product-reviews\
.\.venv\Scripts\Activate.ps1
$env:DB_CONNECTION_STRING="host=localhost user=root password=otel dbname=otel port=5432"
python db_migration_worker.py
Remove-Item Env:\DB_CONNECTION_STRING
```

#### 💻 Lựa chọn C: Nếu dùng Windows Command Prompt (CMD)
```cmd
cd techx-corp-platform\src\product-reviews\
.\.venv\Scripts\activate.bat
set DB_CONNECTION_STRING=host=localhost user=root password=otel dbname=otel port=5432
python db_migration_worker.py
set DB_CONNECTION_STRING=
```

> [!NOTE]
> Khi có thông báo `Migration scan completed!`, cột bảo mật `is_safe` và bảng log kiểm toán `reviews.fidelity_audit` đã được khởi tạo, phân quyền và quét dữ liệu cũ thành công trong database.

---

### Bước 2: Khởi chạy Product Reviews Server

Trong chính terminal ở **Bước 1** (nơi môi trường ảo đã được kích hoạt sẵn), chạy lệnh sau để khởi động gRPC server. 

> [!IMPORTANT]
> **Cấu hình Cổng Redis/Valkey (Tránh bị đơ/chậm do chờ timeout kết nối):**
> 
> Căn cứ vào file `docker-compose.yml`, dịch vụ `valkey-cart` được ánh xạ (map) ra một cổng ngẫu nhiên trên máy Host (ví dụ: `57215` như hiển thị trong `docker ps`).
> Nếu không khai báo cổng thực tế này, server sẽ mặc định kết nối tới cổng `6379`, dẫn đến lỗi kết nối và kích hoạt vòng lặp chờ khóa (Lock Stampede polling) gây đơ/chậm tiến trình (mất khoảng 30s mỗi request).
> 
> 1. Kiểm tra cổng thực tế đang chạy của `valkey-cart` bằng lệnh:
>    ```bash
>    docker ps | grep valkey-cart
>    ```
>    *(Tìm phần cổng bên trái dấu `->6379/tcp`, ví dụ: `0.0.0.0:57215->6379/tcp` tức là cổng `57215`)*.
> 
> 2. Chạy server truyền kèm biến môi trường `REDIS_PORT` tương ứng:
> 
> * **WSL / Git Bash**:
>   ```bash
>   REDIS_PORT=<cổng_thực_tế> python product_reviews_server.py
>   ```
> * **Windows PowerShell**:
>   ```powershell
>   $env:REDIS_PORT="<cổng_thực_tế>"
>   python product_reviews_server.py
>   ```
> * **Windows CMD**:
>   ```cmd
>   set REDIS_PORT=<cổng_thực_tế>
>   python product_reviews_server.py
>   ```

> [!IMPORTANT]
> Hãy giữ nguyên terminal này hoạt động để duy trì dịch vụ gRPC của server (lắng nghe cổng 8085).

---

### Bước 3: Đo đạc chỉ số Cold Cache (Cache Miss)

Mở một **cửa sổ Terminal thứ hai** tại thư mục gốc `AIE1`, **kích hoạt môi trường ảo** rồi mới chạy lệnh benchmark đo lường lần thứ nhất:

#### 🔌 Kích hoạt môi trường ảo ở Terminal thứ hai:
* **WSL / Git Bash**:
  ```bash
  source techx-corp-platform/src/product-reviews/.venv/bin/activate
  ```
* **Windows PowerShell**:
  ```powershell
  .\techx-corp-platform\src\product-reviews\.venv\Scripts\Activate.ps1
  ```
* **Windows CMD**:
  ```cmd
  .\techx-corp-platform\src\product-reviews\.venv\Scripts\activate.bat
  ```

#### 💻 Lựa chọn A: Nếu dùng Git Bash / WSL (Khuyến nghị)
```bash
python repro/run_eval_guardrail.py \
  --dataset repro/datasets/dataset.jsonl \
  --case-types normal \
  --max-cases 6 \
  --grpc-addr localhost:8085 \
  --grpc-timeout-seconds 60 \
  --workers 1 \
  --candidate-provider bedrock \
  --candidate-model amazon.nova-lite-v1:0 \
  --judge-provider bedrock \
  --judge-model amazon.nova-micro-v1:0 \
  --expected-cases 6 \
  --min-products 3 \
  --out repro/artifacts/cost_latency_cold_cache.json
```

#### 💻 Lựa chọn B: Nếu dùng Windows PowerShell hoặc CMD
```powershell
python repro\run_eval_guardrail.py `
  --dataset repro\datasets\dataset.jsonl `
  --case-types normal `
  --max-cases 6 `
  --grpc-addr localhost:8085 `
  --grpc-timeout-seconds 60 `
  --workers 1 `
  --candidate-provider bedrock `
  --candidate-model amazon.nova-lite-v1:0 `
  --judge-provider bedrock `
  --judge-model amazon.nova-micro-v1:0 `
  --expected-cases 6 `
  --min-products 3 `
  --out repro\artifacts\cost_latency_cold_cache.json
```

> [!NOTE]
> Lần chạy này đo lường trường hợp **Cache Miss** (Cold Cache), hệ thống sẽ tốn chi phí gọi LLM và ghi kết quả audit log.

---

### Bước 4: Đo đạc chỉ số Hot Cache (Cache Hit)

Trong **Terminal thứ hai**, tiếp tục chạy lại lệnh đo đạc lần thứ hai để ghi nhận hiệu quả khi có Cache Hit:

#### 💻 Lựa chọn A: Nếu dùng Git Bash / WSL (Khuyến nghị)
```bash
python repro/run_eval_guardrail.py \
  --dataset repro/datasets/dataset.jsonl \
  --case-types normal \
  --max-cases 6 \
  --grpc-addr localhost:8085 \
  --grpc-timeout-seconds 60 \
  --workers 1 \
  --candidate-provider bedrock \
  --candidate-model amazon.nova-lite-v1:0 \
  --judge-provider bedrock \
  --judge-model amazon.nova-micro-v1:0 \
  --expected-cases 6 \
  --min-products 3 \
  --out repro/artifacts/cost_latency_hot_cache.json
```

#### 💻 Lựa chọn B: Nếu dùng Windows PowerShell hoặc CMD
```powershell
python repro\run_eval_guardrail.py `
  --dataset repro\datasets\dataset.jsonl `
  --case-types normal `
  --max-cases 6 `
  --grpc-addr localhost:8085 `
  --grpc-timeout-seconds 60 `
  --workers 1 `
  --candidate-provider bedrock `
  --candidate-model amazon.nova-lite-v1:0 `
  --judge-provider bedrock `
  --judge-model amazon.nova-micro-v1:0 `
  --expected-cases 6 `
  --min-products 3 `
  --out repro\artifacts\cost_latency_hot_cache.json
```

> [!TIP]
> Do toàn bộ 6 câu hỏi này đã được lưu vào Redis ở Bước 3, lần chạy này sẽ có tỉ lệ **Cache Hit 100%**, Latency sẽ đạt mức tối ưu (< 10ms) và cost/token tiêu hao sẽ bằng 0.

---

## 🔍 Giám Sát Traces Bằng Jaeger UI

Để trực quan hóa các cuộc gọi API, luồng xử lý Cache (Hit/Miss) và kiểm toán Judge, bạn có thể sử dụng Jaeger UI để theo dõi bằng giao diện:

### 1. Nếu chạy local bằng Docker Compose:
* Truy cập địa chỉ: [http://localhost:16686](http://localhost:16686)
* Chọn Service: `product-reviews` trong ô tìm kiếm.
* Nhấn **Find Traces** để xem chi tiết timeline của các request. Bạn sẽ thấy rõ sự khác biệt:
  - **Cold Cache (Cache Miss)**: Luồng xử lý gọi LLM dài vài giây, hiển thị đầy đủ các span con của `get_ai_assistant_response`, candidate call, và judge call.
  - **Hot Cache (Cache Hit)**: Phản hồi siêu tốc trong vài mili-giây với thẻ tag `app.cache.hit = True` và không phát sinh bất kỳ cuộc gọi LLM/boto3 nào.

### 2. Nếu chạy trên Kubernetes (K8s) Cluster:
* Port-forward dịch vụ Jaeger hoặc truy cập qua `frontend-proxy`:
  ```bash
  kubectl -n <your-namespace> port-forward svc/jaeger 16686:16686
  ```
* Truy cập Jaeger UI tại: [http://localhost:16686](http://localhost:16686)

---

## 📊 Báo cáo kết quả

Sau khi chạy xong, hãy kiểm tra 2 tệp kết quả trong thư mục `repro/artifacts/`:
1. `cost_latency_cold_cache.json`
2. `cost_latency_hot_cache.json`

Hãy gửi cho tôi các số liệu chính của 2 tệp trên (đặc biệt là mục `runtime_summary.latency_seconds_end_to_end_after` p50, p95 và `after_candidate_plus_judge.total_tokens`). Tôi sẽ lập tức xử lý và tạo tệp đối chiếu so sánh tổng hợp giúp bạn kết thúc Sub-task 2.4!
