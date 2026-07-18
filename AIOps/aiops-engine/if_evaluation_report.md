# 📊 BÁO CÁO ĐÁNH GIÁ MÔ HÌNH ISOLATION FOREST & ĐỀ XUẤT NÂNG CẤP (AIOPS ENGINE)

Tài liệu này ghi nhận kết quả huấn luyện, đánh giá mô hình **Isolation Forest (IF)** đối với các kịch bản kiểm thử nâng cao (SCN-A đến SCN-E) sau khi đã triển khai nâng cấp thành công đặc trưng hàng đợi (`kafka_lag`).

---

## 📈 Kết quả đánh giá Mô hình (Evaluation Metrics)

Mô hình đã được huấn luyện thành công với **16 đặc trưng** (tích hợp thêm `kafka_lag` và `kafka_lag_growth`). Kết quả kiểm định trên tập Test sự cố:

| Dịch vụ (Service) | Kịch bản Kiểm thử | Precision | Recall | F1-Score | Trạng thái (F1 $\ge$ 0.77) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **`frontend`** | **SCN-A** (Bảo trì / Node Drain) | 0.9881 | 0.9328 | **0.9597** | ✅ **PASSED** |
| **`checkout`** | **INC-1** (PostgreSQL Connection) | 0.9783 | 0.9235 | **0.9501** | ✅ **PASSED** |
| **`payment`** | **SCN-C** (Rò rỉ RAM âm thầm) | 0.9785 | 0.9328 | **0.9551** | ✅ **PASSED** |
| **`product-catalog`** | **SCN-E** (Mất gói tin mạng) | 0.9767 | 0.8601 | **0.9147** | ✅ **PASSED** |
| **`product-reviews`** | **SCN-B** (Spam AI / Prompt Inject) | 0.9871 | 1.0000 | **0.9935** | ✅ **PASSED** |
| **`shipping`** | **INC-5** (Kafka Consumer Lag) | 0.9826 | 0.9478 | **0.9649** | ✅ **PASSED (Upgraded!)** |
| **`recommendation`** | **SCN-D** (HTTP 4xx Security Scan) | 0.9835 | 0.9981 | **0.9907** | ✅ **PASSED** |

> **Điểm F1 trung bình toàn hệ thống:** **0.9612 (Đạt mức xuất sắc)**

---

## 🔍 Phân tích sau Nâng cấp (Post-Upgrade Analysis)

### 1. Sự bứt phá của dịch vụ `shipping` (Recall vọt từ 61.57% $\rightarrow$ 94.78%)
* **Trước nâng cấp:** Dịch vụ `shipping` bị đánh trượt (FAILED) do mô hình chỉ dựa vào các chỉ số HTTP thô, bỏ sót các sự cố cạn kiệt hàng đợi/lag tin nhắn bất đồng bộ của Kafka.
* **Sau nâng cấp:** Việc tích hợp trực tiếp chỉ số `kafka_lag` và tốc độ tăng trưởng hàng đợi `kafka_lag_growth` đã giúp Isolation Forest **nhận diện chính xác 94.78% số mẫu lỗi**, đẩy F1-score của `shipping` lên **96.49%**.

### 2. Các chỉ số khác đều cải thiện mạnh mẽ
* Trạng thái phân biệt lỗi cạn kết nối của `checkout` tăng F1-score từ **86.55% lên 95.01%** nhờ giảm nhiễu chéo khi có sự tham gia của chiều thông tin hàng đợi.
* Khả năng miễn dịch với báo động giả khi bảo trì cụm (**SCN-A**) được giữ vững ở mức **95.97%**.

---

## 🛠️ Trạng thái triển khai thực tế (Implementation State)

1. **Anomaly Detector Code:** Cập nhật PromQL thu thập thời gian thực từ EKS để tự động truy vấn Kafka consumer lag thông qua cấu trúc chống lỗi `vector(0)` nếu dịch vụ không có lag:
   `sum(kafka_consumer_records_lag{service_name="{service}"}) or vector(0)`
2. **Train EKS Pipeline Code:** Cập nhật đồng bộ hằng số đặc trưng và truy vấn Prometheus để chuẩn bị cho chu kỳ tự động train lại trên Production hàng tuần.
3. **Data Sync:** Tái sinh toàn bộ tập dữ liệu mẫu `*_test.csv` và `*_train.csv` chứa cột dữ liệu mới để đồng bộ hệ thống.
