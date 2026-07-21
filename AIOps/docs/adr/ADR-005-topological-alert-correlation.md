# ADR-005: Gom Nhóm Tương Quan Cảnh Báo Topo Trong Luồng ML (Topological Alert Correlation & Culprit Selection)

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-15
- **Tác giả / Ký tên**: Hảo (Leader team AIOps)
- **Phạm vi tác động**: AI Engine (`aiops-engine`), Alerting & Correlation

---

## 1. Bối cảnh (Context)

Ban đầu, module tương quan và lọc trùng cảnh báo (Union-Find, Graph distance) chỉ được cấu hình chạy ở webhook nhận tin từ Prometheus Alertmanager (`/webhook/alerts`). 

Trong khi đó, luồng quét chủ động **ML Isolation Forest** trong `main.py` lại hoàn toàn bỏ qua module này. Khi quét thấy cả `checkout` và `frontend` cùng bất thường, nó gửi độc lập 2 cảnh báo về Slack, dẫn đến hiện tượng spam tin nhắn hàng loạt và gây ra Alert Fatigue cho đội ngũ SRE.

---

## 2. Quyết Định Kiến Trúc (Decisions)

### **A. Tích hợp AlertCorrelator vào luồng ML Proactive Loop**
* Khi Isolation Forest phát hiện danh sách các dịch vụ bất thường, hệ thống không gửi Slack ngay, mà đóng gói chúng thành các mock alerts và đẩy qua hàm `correlator.correlate_alerts`.
* Thuật toán **Union-Find** sẽ gom các dịch vụ nằm gần nhau trên đồ thị cấu trúc liên kết mạng lưới (topo $\le 2$ hops) thành một cụm sự cố duy nhất.

### **B. Tự động tính toán lỗi gốc (Culprit Selection)**
* Với mỗi cụm sự cố, hệ thống tự động tìm dịch vụ đóng vai trò nguyên nhân gốc (**Culprit**) dựa trên khoảng cách tô-pô mạng lưới xa `frontend` nhất (ví dụ: `checkout` cách `frontend` 1 hop, `payment` cách `frontend` 2 hops $\rightarrow$ ưu tiên chọn `payment` hoặc `checkout` làm culprit và ẩn `frontend`).
* Hệ thống **chỉ gửi 1 cảnh báo duy nhất đại diện cho Culprit** lên Slack.
* Các cảnh báo triệu chứng (như `frontend`) sẽ bị triệt tiêu hoàn toàn khỏi kênh thông báo để tránh gây trôi tin nhắn.

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
* **Chống Alert Fatigue:** Giảm thiểu tới 80% số lượng tin nhắn rác trên Slack khi có sự cố dây chuyền xảy ra.
* **Xác định lỗi nhanh hơn:** SRE tập trung trực tiếp vào dịch vụ lỗi gốc thay vì phải tự lần mò từ các dịch vụ gateway thượng nguồn.

### **Đánh đổi**:
* Nếu cấu trúc liên kết topo mạng lưới (`service_graph`) trong `alert_correlator.py` bị cấu hình sai lệch hoặc lỗi thời khi deploy dịch vụ mới, thuật toán gom nhóm có thể hoạt động không chính xác. Do đó, đồ thị topo này cần được đồng bộ và cập nhật thường xuyên khi có thay đổi kiến trúc hạ tầng.
