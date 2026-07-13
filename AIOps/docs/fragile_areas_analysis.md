# Phân Tích Điểm Yếu Hệ Thống (Fragile Areas) Từ Lịch Sử Sự Cố

Tài liệu này phân tích các vùng mỏng manh (fragile areas) của hệ thống dựa trên 3 sự cố lịch sử (INC-1, INC-2, INC-3) và cách **AIOps CMDR Pipeline** được thiết kế để bảo vệ, phát hiện và khắc phục các điểm yếu này.

---

## 🔍 Tổng quan về các vùng mỏng manh của hệ thống

Qua 3 sự cố quá khứ, chúng ta xác định được 3 vùng mỏng manh cốt lõi sau:
1. **Database & Resource Saturation (Vùng tài nguyên cơ sở dữ liệu)** - Sự cố cạn kiệt Connection Pool (INC-1).
2. **State & Single Point of Failure (Điểm chết đơn lẻ và dữ liệu trong bộ nhớ)** - Sự cố mất giỏ hàng Valkey (INC-2).
3. **Deployment Gating & Traffic Routing (Luồng phát hành và định tuyến lưu lượng)** - Sự cố thiếu probe lúc rollout (INC-3).

---

## 🛠️ Chi tiết phân tích và Giải pháp bảo vệ từ AIOps Engine

### 📊 1. VÙNG MỎNG MANH 1: DATABASE & RESOURCE SATURATION (INC-1)
* **Điểm yếu**: Số lượng kết nối (Connection Pool) tới CSDL (`postgresql`) là hữu hạn. Khi tải vọt lên, các service xếp hàng chờ và gây ra lỗi dây chuyền (Cascading Timeout) lên tận `checkout` và `frontend`.
* **Cách AIOps Engine giải quyết**:
  - **Phát hiện (Giai đoạn 1)**: Dùng thuật toán Z-Score sửa đổi giám sát độ trễ p95 của checkout. Phát hiện sớm bất thường về Latency trước khi hệ thống sập hoàn toàn.
  - **RCA (Giai đoạn 2)**: Duyệt Jaeger Trace DAG. Khi `frontend` báo lỗi, RCA Engine đi dọc theo trace tìm ra node lá sâu nhất bị lỗi là `postgresql`, giúp cô lập thủ phạm trong 1 giây thay vì SRE phải đi đọc log từng service.
  - **Khắc phục (Giai đoạn 5)**: Đề xuất SRE tăng kích thước pool qua cấu hình config, hoặc tự động kích hoạt tính năng giới hạn lưu lượng (rate limiting) ở tầng API Gateway để bảo vệ DB.

---

### 💾 2. VÙNG MỎNG MANH 2: CACHING STATE & SINGLE POINT OF FAILURE (INC-2)
* **Điểm yếu**: Dịch vụ lưu giỏ hàng (`valkey-cart`) chạy dạng single-replica (1 pod duy nhất) và lưu state trực tiếp trong bộ nhớ không có ổ đĩa ghi dữ liệu (no persistence). Khi Pod bị dời sang node khác hoặc bị OOM, dữ liệu giỏ hàng của khách hàng mất sạch hoàn toàn.
* **Cảnh báo nguy hiểm (Remediation Risk)**: Đối với lỗi này, **tuyệt đối không được tự động restart pod** (bởi vì restart sẽ xóa sạch giỏ hàng của những khách hàng còn lại).
* **Cách AIOps Engine giải quyết**:
  - **Safety Gate (Chốt an toàn Giai đoạn 5)**: Khi phát hiện sự cố liên quan đến `valkey-cart` (INC-2), Safety Gate đối chiếu luật và **chuyển đổi hành động đề xuất thành `none` (Không hành động tự động)**.
  - **Human-in-the-loop (Slack approval)**: Thay vì tự động restart, Engine bắn một cảnh báo khẩn cấp lên Slack kèm theo phân tích cảnh báo SPOF cho SRE. SRE có thể phê duyệt lệnh nâng số lượng replica lên $\ge 2$ để tạo bản sao dự phòng an toàn trước khi di dời pod.

---

### 🚀 3. VÙNG MỎNG MANH 3: DEPLOYMENT GATING & ROLLOUT PROBES (INC-3)
* **Điểm yếu**: Khi cập nhật phiên bản mới (deploy), Kubernetes đẩy lượng truy cập vào pod mới trước khi nó khởi động xong (thiếu Readiness Probe). Các request thanh toán (`payment`) đổ vào pod chưa sẵn sàng dẫn đến lỗi 5xx.
* **Cách AIOps Engine giải quyết**:
  - **Phát hiện**: Z-Score phát hiện tỉ lệ lỗi tăng đột biến trên service `payment` trùng khớp với thời điểm có sự kiện `rollout` trong log hệ thống.
  - **RCA**: Xác định lỗi phát sinh từ các pod mới khởi tạo.
  - **Khắc phục**: Engine đề xuất lệnh rollback an toàn:
    `kubectl rollout undo deployment/payment -n techx-tf3`
    SRE nhấn nút **`[Approve]`** trên Slack để lập tức đưa hệ thống về phiên bản cũ ổn định trong 10 giây, chặn đứng lỗi thanh toán cho khách hàng.

---

## 💡 Điểm cộng khi Pitching trước Hội đồng duyệt (Mẹo bảo vệ)

Khi ban giám khảo hỏi: *"Làm sao hệ thống AIOps của bạn biết vùng nào mỏng manh để xử lý?"*
👉 **Bạn trả lời**:
> "Hệ thống AIOps của chúng tôi được thiết kế dựa trên tri thức sự cố quá khứ (Knowledge Base). Chúng tôi không tự động hóa mù quáng. Với các vùng mỏng manh liên quan đến tài nguyên như CSDL (INC-1) hay triển khai (INC-3), hệ thống cung cấp giải pháp xử lý nhanh. Nhưng với điểm chết đơn lẻ SPOF (INC-2), hệ thống kích hoạt chốt chặn an toàn (Safety Gate) và cơ chế phê duyệt thủ công (Human-in-the-loop) để bảo vệ tính toàn vẹn dữ liệu của khách hàng."
