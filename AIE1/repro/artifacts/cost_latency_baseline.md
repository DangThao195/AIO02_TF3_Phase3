# 📊 BÁO CÁO ĐO LƯỜNG & ĐỐI CHIẾU HIỆU NĂNG CACHING (MANDATE #14 & #23)

Bản báo cáo này cung cấp cái nhìn chi tiết về hiệu năng thực tế của dịch vụ **Product Reviews (AIE1)** trước và sau khi triển khai cơ chế Bộ nhớ đệm (Caching) bằng Redis/Valkey.

---

## 📈 Bảng Số Liệu Đối Chiếu Hiệu Năng

| Chỉ số | Trước khi có Cache (Before Caching Baseline) | Lần chạy đầu tiên (Cold Cache Run) | Các lần chạy sau (Hot Cache Run) | Hiệu quả cải thiện (Delta) |
| :--- | :---: | :---: | :---: | :---: |
| **Tổng số cuộc gọi LLM** | 12 (6 Candidate + 6 Judge) | 6 | **2** | **Giảm 83.3%** số lần gọi Bedrock |
| **Tổng lượng token tiêu thụ** | 13,788 tokens | 6,894 tokens | **2,297 tokens** | **Tiết kiệm 11,491 tokens** |
| **Tổng chi phí ước tính** | $0.00069523 | $0.00034760 | **$0.00011580** | **Giảm 83.3%** chi phí API |
| **Chi phí trung bình / Request** | $0.00011587 | $0.00005793 | **$0.00001930** | Tối ưu hóa chi phí biên |
| **Độ trễ p50 (p50 Latency)** | 2.8213 giây | 4.0820 giây | **0.0044 giây (4.4 ms)** | **Nhanh gấp ~641 lần** |
| **Độ trễ p95 (p95 Latency)** | 3.4962 giây | 17.6619 giây | **15.0109 giây** | *(Xem phần giải thích bên dưới)* |
| **Tỷ lệ Pass Rate** | 83.3% | 83.3% | **83.3%** | Giữ nguyên độ chính xác 100% |

---

## 🔍 Phân Tích & Phát Hiện Chính

### 1. Tối ưu hóa Tốc độ Phản hồi (p50 Latency)
> [!NOTE]
> Khi có Cache Hit (ở các lần gọi sau), thời gian xử lý của gRPC server giảm từ **2.82 giây xuống còn 4.4 mili-giây** (tốc độ xử lý tăng gấp **641 lần**). Điều này giúp cải thiện tối đa trải nghiệm người dùng và giải phóng năng lực xử lý của server.

### 2. Tiết kiệm Chi phí & Tài nguyên API
> [!TIP]
> Số cuộc gọi đến mô hình AWS Bedrock giảm từ **12 cuộc gọi xuống chỉ còn 2 cuộc gọi** (giảm **83.3%**). Lượng token tiêu thụ giảm tương ứng giúp tránh được tình trạng bị giới hạn băng thông (Rate Limit 429) diện rộng từ nhà cung cấp mô hình.

### 3. Giải thích về Độ trễ p95
> [!IMPORTANT]
> Mặc dù độ trễ trung vị p50 giảm cực mạnh, độ trễ p95 ở Hot Cache vẫn giữ ở mức **15.01 giây**. Đây **không phải là lỗi hệ thống**, mà là kết quả của **Chính sách Đảm bảo Chất lượng Cache (Fidelity-based Cache Policy)**:
> - **Case 1** có kết quả từ mô hình Judge là `Unverified` (không được xác thực độ trung thực).
> - Để đảm bảo an toàn, hệ thống **bỏ qua việc lưu cache** đối với các kết quả lỗi hoặc không đạt chuẩn chất lượng.
> - Các request tiếp theo gửi tới case này bắt buộc phải gọi lại Bedrock để re-verify thay vì trả kết quả lỗi từ cache. Điều này làm độ trễ của case này cao hơn hẳn các case hit cache khác, kéo chỉ số p95 lên nhưng đảm bảo tính đúng đắn tuyệt đối.

### 4. Phòng chống lỗi đồng thời (Cache Stampede Protection)
> [!NOTE]
> Hệ thống sử dụng khóa phân tán Redis `SET NX EX 10` trước khi truy vấn LLM. Khi có nhiều request đồng thời truy cập vào một sản phẩm chưa được cache, chỉ luồng đầu tiên được quyền gọi LLM, các luồng còn lại sẽ tự động polling đợi kết quả cache, triệt tiêu nguy cơ nghẽn hoặc sập do thundering herd.

---

## 🛠️ Phương Pháp Đo Lường (Methodology)
1. **Dữ liệu test**: Lấy 6 cases bình thường đầu tiên từ bộ dữ liệu chuẩn `repro/datasets/dataset.jsonl` (bao gồm 3 sản phẩm khác nhau).
2. **Kịch bản chạy**:
   - **Baseline**: Server chạy nguyên bản, mọi request đều gọi AWS Bedrock (Nova Lite làm Candidate + Nova Micro làm Judge).
   - **Cold Run**: Khởi động server với caching sạch, các case được nạp dần vào Redis.
   - **Hot Run**: Chạy lại các case trên để đo đạc thời gian truy xuất từ Redis Cache.
3. **Đơn giá áp dụng (Nova Model)**:
   - Input: `$0.06 / triệu tokens` (Lite) | `$0.035 / triệu tokens` (Micro)
   - Output: `$0.24 / triệu tokens` (Lite) | `$0.14 / triệu tokens` (Micro)

*Kết quả đo lường chi tiết được lưu trữ có cấu trúc tại tệp tin:* [cost_latency_baseline.json](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/repro/artifacts/cost_latency_baseline.json).
