# ADR-006: Kiểm Chứng Phục Hồi Lai Hai Cổng (Hybrid Double-Gate Remediation Verification)

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-15
- **Tác giả / Ký tên**: Hảo (Leader team AIOps)
- **Phạm vi tác động**: AI Engine (`aiops-engine`), Auto-Healing & Remediation

---

## 1. Bối cảnh (Context)

Luồng kiểm tra sau khắc phục lỗi tự động (Remediation Verification) ban đầu sử dụng Z-score của chỉ số chung `http_server_active_requests` làm thước đo phục hồi. Điều này gặp 3 rủi ro SRE lớn:
1. **Lỗi Cold Start:** Trên cụm EKS mới, 7 ngày lịch sử trống trơn dẫn đến `stddev = 0`. Z-score trả về `0.0` và lập tức báo phục hồi thành công giả tạo (False Positive) ngay chu kỳ đầu tiên.
2. **Thiếu tính đa chiều:** Chỉ kiểm tra 1 metric lỗi sẽ bỏ qua các lỗi phụ nảy sinh sau remediation (ví dụ: vá lỗi thành công nhưng làm CPU vọt lên 100% hoặc latency tăng gấp 10 lần).
3. **Hiện tượng Flapping:** Hệ thống vừa hồi phục có thể dao động nhẹ, việc chỉ kiểm tra 1-2 lần đơn lẻ dễ đưa ra quyết định sai lầm.

---

## 2. Quyết Định Kiến Trúc (Decisions)

### **A. Thiết lập Cổng Kiểm Chứng Lai Song Song (Hybrid Double-Gate)**
* Để xác minh một lệnh sửa lỗi thành công, hệ thống phải vượt qua đồng thời **2 cổng bảo vệ**:
  * **Cổng 1 (Z-Score):** Theo dõi trực tiếp tỷ lệ lỗi gRPC/HTTP của riêng dịch vụ lỗi gốc (`culprit_service`).
  * **Cổng 2 (Isolation Forest):** Quét toàn bộ 18 chỉ số sức khỏe hệ thống (CPU, Memory, Latency, RPS...) để đảm bảo dịch vụ không gặp bất kỳ tác dụng phụ nào sau sửa lỗi.

### **B. Giải quyết bài toán Cold Start**
* Chuyển cửa sổ tính Z-score từ `7d` về `1d` để phản ánh đúng baseline thực tế của cụm mới dựng.
* Thiết lập logic fallback thông minh khi `stddev == 0`:
  * Nếu giá trị lỗi hiện tại bằng `0`, trả về `0.0` (Thành công).
  * Nếu giá trị lỗi hiện tại $> 0$ (vẫn phát sinh lỗi mới), trả về `999.0` (Lỗi nặng).

### **C. Cửa sổ chống rung ổn định (Dampening Window 5 chu kỳ)**
* Yêu cầu cả 2 Cổng Z-score và Isolation Forest phải vượt qua đồng thời liên tục trong **5 chu kỳ quét (tương đương 2.5 phút)**.
* Chỉ cần có 1 chu kỳ thất bại, bộ đếm sẽ lập tức reset về 0 và đếm lại từ đầu.
* Nếu hết 5 phút giới hạn mà không tích lũy đủ 5 chu kỳ thành công liên tiếp, hệ thống sẽ tự động kích hoạt **Rollback Plan** để đưa cụm về trạng thái cũ an toàn.

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
* Tránh tuyệt đối các trường hợp "Thành công giả" làm treo cụm hoặc che giấu lỗi thực tế.
* Bảo vệ cụm khỏi các tác dụng phụ sau khi chạy lệnh scale/restart.

### **Đánh đổi**:
* Thời gian xác minh lâu hơn (tối thiểu 2.5 phút thay vì chỉ 30 giây như trước). Tuy nhiên, đây là sự đánh đổi hoàn toàn xứng đáng để đổi lấy tính ổn định và an toàn cho môi trường Production.
