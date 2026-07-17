# Tài liệu Đặc tả Cấu trúc Dữ liệu Giám sát (Data Metric Schema)

Tài liệu này mô tả chi tiết cấu trúc dữ liệu giám sát (schemas) được thu thập từ cụm EKS thông qua Prometheus và được xử lý đặc trưng (feature engineering) trước khi đưa vào huấn luyện mô hình học máy **Isolation Forest** phát hiện bất thường chủ động.

---

## 📊 1. Các chỉ số gốc thu thập từ Prometheus (Golden Signals)

Mỗi dịch vụ (service) trong cụm được thu thập định kỳ các chỉ số cơ bản sau:

| Tên Chỉ số (Metric) | Nguồn Truy vấn Prometheus (PromQL) | Ý nghĩa SRE |
| :--- | :--- | :--- |
| **rps** | `sum(rate(traces_span_metrics_calls_total{service_name="{service}", span_kind="SPAN_KIND_SERVER"}[5m]))` | Lưu lượng truy vấn (Requests Per Second) |
| **error_rate** | `sum(rate(traces_span_metrics_calls_total{service_name="{service}", span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}[5m]))` | Tốc độ phát sinh lỗi server-side |
| **client_error_rate**| Lấy mặc định là `0.0` (dành cho lỗi 4xx client-side) | Tốc độ phát sinh lỗi client-side |
| **latency_p90** | `histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="{service}", span_kind="SPAN_KIND_SERVER"}[5m])) by (le))` | Độ trễ phân vị 90 (miliseconds) |
| **cpu_usage** | `sum(rate(container_cpu_usage_seconds_total{container="{service}"}[5m]))` | Mức tiêu thụ tài nguyên CPU |
| **memory_usage** | `sum(container_memory_working_set_bytes{container="{service}"}) / sum(container_spec_memory_limit_bytes{container="{service}"})` | Tỷ lệ sử dụng Memory thực tế so với Limit |
| **kafka_lag** | `sum(kafka_consumer_records_lag{service_name="{service}"})` | Độ trễ xử lý tin nhắn trong Kafka queue |

---

## 🛠️ 2. Các đặc trưng được tính toán bổ sung (Feature Engineering)

Để tăng độ nhạy và chính xác cho mô hình phát hiện bất thường chủ động, Engine sinh thêm các đặc trưng động từ chỉ số gốc:

1. **error_ratio:** Tỷ lệ lỗi trên tổng request (`error_rate / rps`).
2. **client_error_ratio:** Tỷ lệ lỗi client-side trên tổng request (`client_error_rate / rps`).
3. **latency_deviation:** Độ lệch độ trễ so với mức cơ sở.
4. **rps_delta:** Sự biến động lưu lượng giữa chu kỳ hiện tại và chu kỳ trước.
5. **cpu_per_rps:** Hiệu năng sử dụng CPU trên mỗi đơn vị request (`cpu_usage / rps`).
6. **memory_growth:** Tốc độ tăng trưởng bộ nhớ.
7. **kafka_lag_growth:** Tốc độ tăng trưởng hàng đợi tin nhắn.
8. **hour_of_day:** Giờ trong ngày (0-23) - Giúp học quy luật thời gian.
9. **day_of_week:** Ngày trong tuần (0-6) - Giúp phân biệt ngày thường và cuối tuần.
10. **is_business_hours:** Cờ đánh dấu giờ làm việc hành chính (8h - 18h).
11. **is_high_traffic_period:** Cờ đánh dấu giờ cao điểm mua sắm (11h-13h và 19h-22h).

---

## 📁 3. Danh sách các tệp dữ liệu huấn luyện (CSV) tại máy local
Thư mục [datametric/](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric) chứa đầy đủ dữ liệu huấn luyện mẫu của 7 dịch vụ chính:

* [checkout_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/checkout_train.csv)
* [frontend_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/frontend_train.csv)
* [payment_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/payment_train.csv)
* [product-catalog_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/product-catalog_train.csv)
* [product-reviews_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/product-reviews_train.csv)
* [recommendation_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/recommendation_train.csv)
* [shipping_train.csv](file:///d:/Xbrain/Read_Capstone03/aiops-engine/datametric/shipping_train.csv)

Mỗi tệp CSV bao gồm đầy đủ dòng dữ liệu thời gian (5-minute step) với đầy đủ cấu trúc cột mô tả ở phần 2 kèm theo cột `label` (1: Normal, 0: Anomaly) dùng để làm tập mẫu kiểm thử chất lượng mô hình.
