# ADR-003: Cơ Chế Quản Lý Phiên Bản & Cập Nhật Nóng (Hot Reload) Cho Mô Hình Isolation Forest

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-14
- **Tác giả / Ký tên**: Hảo (Leader team AIOps)
- **Phạm vi tác động**: AI Engine (`aiops-engine`), MLOps Pipeline

---

## 1. Bối cảnh (Context)

Dự án AIOps triển khai mô hình Isolation Forest (IF) để phát hiện bất thường sớm. Quá trình huấn luyện mô hình được thực hiện định kỳ bằng Kubernetes CronJob trên EKS và kết quả được đẩy lên AWS S3. 

Tuy nhiên, cơ chế cũ gặp một số hạn chế:
1. **Lỗi Không Đồng Bộ (Atomicity Issue):** Khi đẩy bộ 7 mô hình lên S3, nếu đường truyền bị gián đoạn giữa chừng (ví dụ lỗi ở file thứ 4), Engine chính khi load lại sẽ tải lẫn lộn giữa mô hình mới và cũ.
2. **Khó Khăn Khi Rollback:** Khi mô hình mới hoạt động không tốt (gây False Positive cao), việc khôi phục lại mô hình cũ đòi hỏi phải redeploy code hoặc can thiệp thủ công rất phức tạp.
3. **Phải Restart Pod để Cập Nhật:** Phiên bản cũ chỉ load mô hình một lần duy nhất lúc khởi tạo (`__init__`). Khi có mô hình mới trên S3, Engine phải restart pod mới nhận diện được, làm mất tính liên tục (zero-downtime) của Phase 3.

---

## 2. Quyết Định Kiến Trúc (Decisions)

### **A. Sử dụng active_manifest.json làm Source of Truth**
* Mỗi lượt chạy của Job huấn luyện thành công sẽ tạo ra một file Manifest: `active_manifest.json` ghi nhận:
  * ID phiên bản (`version`), thời gian huấn luyện (`trained_at`).
  * Chỉ số F1-Score trung bình và chi tiết từng dịch vụ (`per_service_metrics`).
  * Trạng thái kiểm định chất lượng (`validation_passed`): Chỉ đặt `true` khi F1, Precision và Recall của tất cả dịch vụ đều vượt qua Guardrail.
  * Đường dẫn lưu trữ cụ thể của từng mô hình (`model_paths`).
* Dịch vụ Engine khi chạy sẽ ưu tiên đọc file Manifest này. Nếu `validation_passed == true`, Engine tải chính xác các mô hình được định nghĩa. Nếu manifest thiếu hoặc không đạt kiểm định, Engine rơi về cơ chế dự phòng (Fallback) tải từ thư mục `current/` để đảm bảo tính tương thích ngược.

### **B. Cơ chế Lưu Trữ Song Song (Backward Compatibility)**
* Mô hình được lưu trữ ở 2 dạng trên S3:
  1. Thư mục Archive: `archive/<timestamp>/<service>_iforest.joblib` (Quản lý phiên bản lịch sử).
  2. Thư mục Current: `current/<service>_iforest.joblib` (Tương thích ngược).

### **C. Hỗ trợ Hot Reload qua REST API**
* Tích hợp endpoint `POST /reload-models` vào Engine (`main.py`).
* Khi nhận request từ SRE hoặc lệnh webhook tự động, Engine sẽ tải lại file Manifest và nạp nóng mô hình mới vào bộ nhớ RAM ngay lập tức mà không cần khởi động lại container (zero-downtime).

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
* Đảm bảo tính nguyên tử (Atomicity): Engine chỉ nạp bộ mô hình mới khi và chỉ khi toàn bộ mô hình trong phiên bản đó đã được upload thành công và cập nhật manifest.
* Hỗ trợ Rollback nhanh gọn: Chỉ cần chỉnh sửa tệp Manifest trỏ về phiên bản lịch sử cũ trên S3 để phục hồi trạng thái ổn định.
* Tách biệt MLOps độc lập, không làm treo hệ thống khi deploy hay restart.

### **Đánh đổi**:
* Tăng số lượng file lưu trữ trên S3 (tuy nhiên kích thước file joblib của Isolation Forest rất nhỏ, chỉ khoảng vài trăm KB nên dung lượng tăng thêm không đáng kể).

---

## 4. Ghi Chú Vận Hành & Khuyến Nghị Bảo Mật (Operational & Security Notes)

### **A. Sử dụng IRSA (IAM Roles for Service Accounts) thay cho Key Tĩnh**
* **Khuyến nghị bảo mật:** Trong môi trường EKS Production, việc sử dụng các IAM Key tĩnh (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) được coi là anti-pattern và chứa đựng rủi ro rò rỉ thông tin cao.
* **Giải pháp khuyến nghị:** Nên thiết lập IRSA trên cụm EKS:
  1. Tạo một IAM Role có chính sách quyền hạn tối thiểu cho S3 và Bedrock.
  2. Tạo một ServiceAccount trong Kubernetes liên kết với IAM Role qua Annotation (`eks.amazonaws.com/role-arn`).
  3. Gán ServiceAccount này vào Pod của Engine và CronJob để K8s tự động cấp phát token bảo mật tạm thời (temporary credentials), loại bỏ hoàn toàn các key tĩnh.

### **B. Giới Hạn Của Bộ Nhớ Đệm Trạng Thái (In-Memory State Management)**
* **Hạn chế:** Trong `main.py`, danh sách các incident đang xử lý (`active_incidents`) được lưu trữ trực tiếp trên bộ nhớ đệm RAM của Pod (In-Memory Dictionary).
* **Rủi ro:** Khi Pod bị restart (do Deployment mới hoặc Node bị thu hồi), trạng thái các incident đang chờ phản hồi từ Slack sẽ bị mất. SRE/Operator sẽ không thể thực thi hành động remediate qua nút bấm trên Slack Card do ID incident không còn tồn tại trên RAM.
* **Khắc phục dài hạn:** Cần chuyển đổi cơ chế quản lý trạng thái từ RAM sang một cơ sở dữ liệu phân tán bền vững (ví dụ: Redis hoặc OpenSearch) để duy trì trạng thái incident xuyên suốt vòng đời Pod.

### **C. Giảm Cửa Sổ Dữ Liệu Huấn Luyện (Cold Start baseline)**
* **Vấn đề:** Khi khởi chạy trên cụm EKS mới dựng dưới 1 ngày, việc sử dụng cửa sổ mặc định 7 ngày (`duration_days=7`) dẫn đến 85% mẫu dữ liệu lịch sử bằng 0. Khi có traffic chạy thật, Isolation Forest sẽ coi traffic bình thường này là bất thường.
* **Khắc phục:** Giảm cửa sổ dữ liệu huấn luyện Prometheus xuống **1 ngày** (`duration_days=1`) để loại bỏ các chuỗi dữ liệu trống trong quá trình Cold Start của cụm mới.


