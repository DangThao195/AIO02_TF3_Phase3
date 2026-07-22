# Hướng Dẫn Chạy Thực Tế Sub-task 2.4: Đo Lường Cost/Latency Caching

Tài liệu này hướng dẫn chi tiết từng bước để chạy migration database, khởi chạy server và thực hiện đo đạc các chỉ số Cost và Latency của cache (Cold Cache vs Hot Cache) trên máy local.

---

## 📋 Yêu Cầu Chuẩn Bị Trước Khi Chạy

1. **Docker Desktop** phải được bật và chạy bình thường.
2. Đảm bảo các service phụ trợ (**PostgreSQL** và **Redis**) đã được start (thông thường chạy qua `docker compose` của hệ thống).

---

## 🛠️ Quy Trình Thực Hiện Từng Bước

### Bước 1: Khởi động Database Migration & Quét dữ liệu cũ

Mở một cửa sổ Terminal (PowerShell hoặc Bash) tại thư mục gốc của dự án `AIE1` và chạy lệnh sau:

```bash
# Thực thi migration.sql và chạy batch quét dữ liệu reviews cũ bằng Regex Guardrails
techx-corp-platform/.venv/bin/python techx-corp-platform/src/product-reviews/db_migration_worker.py
```

> [!NOTE]
> Khi có thông báo `Migration scan completed!`, cột bảo mật `is_safe` và bảng log kiểm toán `reviews.fidelity_audit` đã được khởi tạo và cập nhật dữ liệu thành công trong database.

---

### Bước 2: Khởi chạy Product Reviews Server

Trong chính terminal ở **Bước 1**, chạy lệnh sau để khởi động gRPC server:

```bash
# Khởi chạy gRPC Server (Lắng nghe cổng 8085)
techx-corp-platform/.venv/bin/python techx-corp-platform/src/product-reviews/product_reviews_server.py
```

> [!IMPORTANT]
> Hãy giữ nguyên terminal này hoạt động để duy trì dịch vụ gRPC của server.

---

### Bước 3: Đo đạc chỉ số Cold Cache (Cache Miss)

Mở một **cửa sổ Terminal thứ hai** tại thư mục gốc `AIE1` và chạy lệnh benchmark đo lường lần thứ nhất:

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

> [!NOTE]
> Lần chạy này đo lường trường hợp **Cache Miss** (Cold Cache), hệ thống sẽ tốn chi phí gọi LLM và ghi kết quả audit log.

---

### Bước 4: Đo đạc chỉ số Hot Cache (Cache Hit)

Trong **Terminal thứ hai**, tiếp tục chạy lại lệnh đo đạc lần thứ hai để ghi nhận hiệu quả khi có Cache Hit:

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

> [!TIP]
> Do toàn bộ 6 câu hỏi này đã được lưu vào Redis ở Bước 3, lần chạy này sẽ có tỉ lệ **Cache Hit 100%**, Latency sẽ đạt mức tối ưu (< 10ms) và cost/token tiêu hao sẽ bằng 0.

---

## 📊 Báo cáo kết quả

Sau khi chạy xong, hãy kiểm tra 2 tệp kết quả trong thư mục `repro/artifacts/`:
1. `cost_latency_cold_cache.json`
2. `cost_latency_hot_cache.json`

Hãy gửi cho tôi các số liệu chính của 2 tệp trên (đặc biệt là mục `runtime_summary.latency_seconds_end_to_end_after` p50, p95 và `after_candidate_plus_judge.total_tokens`). Tôi sẽ lập tức xử lý và tạo tệp đối chiếu so sánh tổng hợp giúp bạn kết thúc Sub-task 2.4!
