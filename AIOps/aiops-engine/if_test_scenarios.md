# 🧪 KỊCH BẢN KIỂM THỬ ISOLATION FOREST NÂNG CAO (AIOPS ENGINE)

Tài liệu này tổng hợp **9 kịch bản kiểm thử (Test Scenarios)** nâng cao dành cho mô hình Isolation Forest (IF) của cụm TechX-Corp, chỉ rõ dịch vụ mục tiêu (Target Service), hành vi metric, mục tiêu chẩn đoán và liên kết đến tệp dữ liệu CSV tương ứng.

---

## 📊 Tổng quan 9 Kịch bản Kiểm thử

| ID | Kịch bản Kiểm thử | Dịch vụ Mục tiêu | Kiểu Test | Đặc trưng chính quyết định | Tệp dữ liệu CSV tương ứng |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SCN-A** | Drain Node (Bảo trì) | **`frontend`** | FP resistance | `rps_delta`, `latency_deviation` | [frontend_test_scn_a.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/frontend_test_scn_a.csv) |
| **SCN-B** | Prompt Injection DoS | **`product-reviews`** | TP detection | `rps` $\times$ `cpu` $\times$ `latency` | [product-reviews_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/product-reviews_test.csv) |
| **SCN-C** | Rò rỉ RAM âm thầm | **`payment`** | TP detection | `memory_growth` | [payment_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/payment_test.csv) |
| **SCN-D** | HTTP 4xx Spam | **`recommendation`** | TP detection | `client_error_ratio` | [recommendation_test_scn_d.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/recommendation_test_scn_d.csv) |
| **SCN-E** | Mất gói tin mạng | **`product-catalog`** | TP detection | `latency_deviation`, `rps_delta` | [product-catalog_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/product-catalog_test.csv) |
| **SCN-F** | Cascading Failure (Lỗi dây chuyền) | **`checkout`** | TP detection | `error_ratio`, `kafka_lag_growth` | [checkout_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/checkout_test.csv) |
| **SCN-G** | Thundering Herd | **`frontend`** | FP resistance | `is_high_traffic_period` | [frontend_test_scn_g.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/frontend_test_scn_g.csv) |
| **SCN-H** | SLO Erosion (Độ trễ tăng chậm) | **`shipping`** | TP detection | `latency_deviation` trượt dài | [shipping_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/shipping_test.csv) |
| **SCN-I** | Noisy Neighbor CPU Steal | **`recommendation`** | TP detection | `cpu_per_rps` tăng vọt | [recommendation_test_scn_i.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/recommendation_test_scn_i.csv) |

---

## 📝 Chi tiết 9 Kịch bản Kiểm thử

### 1. SCN-A · Drain Node (Bảo trì rút node)
* **Dịch vụ mục tiêu:** **`frontend`** (Cổng đón nhận traffic đầu vào).
* **Bối cảnh:** SRE chạy lệnh `kubectl drain node` để bảo trì định kỳ. Pod của frontend được tái khởi động trên node mới.
* **Biến đổi Metric:** RPS giảm 25% tạm thời, CPU usage vọt nhẹ (1.4x), Latency P90 vọt nhẹ (1.8x) ở những request đầu tiên do chưa warm-up cache, các loại lỗi bằng 0.
* **Mục tiêu của IF:** Kiểm tra tính **kháng báo động giả (FP resistance)**. IF cần nhận diện đây là biến động tải lành mạnh và duy trì nhãn Normal (`1`).
* **Dữ liệu CSV:** [frontend_test_scn_a.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/frontend_test_scn_a.csv)

### 2. SCN-B · Prompt Injection DoS (Spam truy vấn AI)
* **Dịch vụ mục tiêu:** **`product-reviews`** (Chứa tính năng tóm tắt đánh giá bằng LLM).
* **Bối cảnh:** Kẻ xấu liên tục spam các prompt cực dài và mã độc chèn lệnh làm tê liệt LLM Gateway.
* **Biến đổi Metric:** RPS vọt 6x, CPU vọt (>90%), Latency vọt (>5.0s), lỗi 5xx tăng nhẹ.
* **Mục tiêu của IF:** Phát hiện bất thường đa biến tương quan (TP). Nhận diện sự kết hợp RPS-CPU-Latency cực đại để cảnh báo tấn công ứng dụng.
* **Dữ liệu CSV:** [product-reviews_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/product-reviews_test.csv)

### 3. SCN-C · Rò rỉ RAM âm thầm (Memory Leak)
* **Dịch vụ mục tiêu:** **`payment`** (Dịch vụ thanh toán chạy các tác vụ Statefull).
* **Bối cảnh:** Deploy phiên bản mới có bug rò rỉ RAM âm thầm, bộ nhớ tăng liên tục mỗi chu kỳ.
* **Biến đổi Metric:** Chỉ số RAM tăng tuyến tính liên tục qua từng chu kỳ cho đến khi chạm ngưỡng 99%, các chỉ số CPU/RPS/Latency hoàn toàn bình thường.
* **Mục tiêu của IF:** Nhận biết sự cố dựa trên tốc độ tăng trưởng của đặc trưng `memory_growth` trước khi container bị Kernel giết do OOM-killer.
* **Dữ liệu CSV:** [payment_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/payment_test.csv)

### 4. SCN-D · HTTP 4xx Spam (Quét lỗ hổng / Scan API)
* **Dịch vụ mục tiêu:** **`recommendation`** (Dịch vụ gợi ý sản phẩm).
* **Bối cảnh:** Hacker chạy công cụ scan API tìm lỗ hổng bảo mật, sinh lượng lớn mã lỗi HTTP 404/403.
* **Biến đổi Metric:** RPS vọt 5x, lỗi 4xx vọt cao (`client_error_rate` từ 35% đến 65%), CPU/RAM/Latency bình thường.
* **Mục tiêu của IF:** Phát hiện bất thường ở tầng Client qua đặc trưng `client_error_ratio` và báo động nhưng **không trigger restart** vì phần cứng backend hoàn toàn khỏe mạnh.
* **Dữ liệu CSV:** [recommendation_test_scn_d.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/recommendation_test_scn_d.csv)

### 5. SCN-E · Mất gói tin mạng (Network Packet Loss)
* **Dịch vụ mục tiêu:** **`product-catalog`** (Dịch vụ danh mục sản phẩm).
* **Bối cảnh:** Hạ tầng mạng chập chờn gây mất gói tin ở mức 15% giữa Catalog và Frontend.
* **Biến đổi Metric:** Latency P90 vọt cao (2.5s - 4.0s) do TCP retry liên tục, RPS giảm nhẹ, CPU/RAM bình thường, error_rate = 0.
* **Mục tiêu của IF:** Phát hiện bất thường âm thầm (Silent Degradation) không kèm lỗi HTTP 5xx.
* **Dữ liệu CSV:** [product-catalog_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/product-catalog_test.csv)

### 6. SCN-F · Cascading Failure (Lỗi dây chuyền đa dịch vụ)
* **Dịch vụ mục tiêu:** **`checkout`** (Downstream kết nối hàng loạt dịch vụ).
* **Bối cảnh:** Lỗi cạn kết nối DB của checkout (INC-1) kéo theo nghẽn tin nhắn ở Kafka, gây chậm trễ lan truyền sang dịch vụ thanh toán và vận chuyển.
* **Biến đổi Metric:** checkout bị lỗi 5xx tăng vọt, latency tăng vọt; Kafka consumer lag tăng vọt liên tục; RPS của accounting/shipping bị kéo giảm 50%.
* **Mục tiêu của IF:** Khả năng tối ưu quan sát tương quan chéo (Cross-service Correlation). IF vượt trội Z-Score vì bắt được sự biến động dây chuyền này.
* **Dữ liệu CSV:** [checkout_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/checkout_test.csv)

### 7. SCN-G · Thundering Herd (Bầy đàn sấm sét sau deploy)
* **Dịch vụ mục tiêu:** **`frontend`**.
* **Bối cảnh:** Sau khi deploy phiên bản mới thành công, hàng vạn thiết bị client cùng lúc reconnect lại cụm gây vọt RPS trong 2-3 mẫu rồi tự phục hồi.
* **Biến đổi Metric:** RPS vọt 4x trong 15 phút đầu rồi tự hồi phục, CPU tăng tương ứng, lỗi = 0, latency tăng nhẹ không đáng kể.
* **Mục tiêu của IF:** FP resistance. IF cần nhận diện đây là lưu lượng burst tự nhiên (dựa trên đặc trưng `is_high_traffic_period` tự thích ứng) và không báo động rác.
* **Dữ liệu CSV:** [frontend_test_scn_g.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/frontend_test_scn_g.csv)

### 8. SCN-H · SLO Erosion (Độ trễ tăng chậm)
* **Dịch vụ mục tiêu:** **`shipping`** (Dịch vụ vận chuyển bất đồng bộ).
* **Bối cảnh:** Không có lỗi đột xuất, nhưng hiệu năng đĩa/mạng suy hao chậm rãi, khiến độ trễ tích lũy tăng 5-10% mỗi ngày trong 4 ngày.
* **Biến đổi Metric:** Latency P90 tăng dần qua từng ngày, các chỉ số RPS/CPU/RAM hoàn toàn bình thường, error_rate = 0.
* **Mục tiêu của IF:** Nhận dạng sự dịch chuyển chậm của baseline thông qua đặc trưng lệch rolling median (`latency_deviation`), lỗi mà Z-Score thuần túy sẽ bỏ sót do dịch chuyển mean.
* **Dữ liệu CSV:** [shipping_test.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/shipping_test.csv)

### 9. SCN-I · CPU Steal Noisy Neighbor (Cạnh tranh CPU node vật lý)
* **Dịch vụ mục tiêu:** **`recommendation`**.
* **Bối cảnh:** Một container của team khác chạy chung node vật lý ngốn sạch CPU chu kỳ, gây ra hiện tượng CPU Steal kéo tụt CPU allocation của Pod.
* **Biến đổi Metric:** CPU usage của container giảm bất thường do bị bóp nghẹt, RPS sụt giảm mạnh, Latency vọt cao, đặc trưng tỷ lệ `cpu_per_rps` tăng vọt bất thường.
* **Mục tiêu của IF:** Phát hiện tài nguyên bị tranh chấp âm thầm mà không phát sinh log Exception.
* **Dữ liệu CSV:** [recommendation_test_scn_i.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/data/recommendation_test_scn_i.csv)
