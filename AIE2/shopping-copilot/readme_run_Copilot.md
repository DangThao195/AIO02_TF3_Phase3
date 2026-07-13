# Hướng Dẫn Chạy & Thử Nghiệm Shopping Copilot Web UI

Tài liệu này hướng dẫn cách khởi động, tương tác và kiểm thử **Shopping Copilot** sử dụng **AWS Bedrock (Amazon Nova)** cùng giao diện Web Chat tương tác trực tiếp.

---

## 📋 1. Chuẩn bị Môi trường

1. **Python Virtual Environment:**
   Sử dụng Python của virtual environment hiện tại có sẵn ở:
   `d:\Cloude-DevOps\Phase-3\Phase3-TF3-Infra-Sentinel\.venv` (đã cài đủ các thư viện Bedrock, FastAPI, LangChain, RapidFuzz...).

2. **AWS Credentials:**
   Đảm bảo máy chạy có cấu hình AWS profile để gọi sang AWS Bedrock (được định nghĩa trong file `.env` qua biến `AWS_PROFILE=default`).

---

## 🚀 2. Cách Chạy Thử Nghiệm

Mở terminal tại thư mục của ứng dụng: `d:\Cloude-DevOps\Phase-3\AIO02_TF3_Phase3\AIE2\shopping-copilot` và chọn một trong hai chế độ dưới đây:

### 🔹 Chế độ A: Chạy Giả Lập Offline (Khuyên dùng để test nhanh)
Chế độ này gọi AWS Bedrock thật để LLM trả lời và lọc mã độc đầu vào, nhưng **giả lập (Mock) toàn bộ 5 Microservices gRPC** (không cần kết nối Kubernetes EKS thật).

1. Khởi động Web Server với cờ `--mock`:
   ```powershell
   & "d:\Cloude-DevOps\Phase-3\Phase3-TF3-Infra-Sentinel\.venv\Scripts\python.exe" src/main.py --mock
   ```
2. Mở trình duyệt truy cập: **[http://localhost:8001/chatbot](http://localhost:8001/chatbot)**

---

### 🔸 Chế độ B: Chạy Kết Nối Microservices Thật (EKS Live Mode)
Chế độ này kết nối trực tiếp đến các dịch vụ EKS (Product Catalog, Cart...) qua SSM Tunnel.

1. **Khởi động SSM Tunnel kết nối EKS** (chạy ở một terminal riêng):
   ```powershell
   $env:AWS_PROFILE="techx-corp"
   aws ssm start-session --target i-0ed38bc9cd8c4c2b0 --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters host="78F80EEA7B05283C4A1AD20C546A4559.gr7.ap-southeast-1.eks.amazonaws.com",portNumber="443",localPortNumber="8443" --region ap-southeast-1
   ```
2. **Khởi động Web Server** (không truyền cờ `--mock`):
   ```powershell
   & "d:\Cloude-DevOps\Phase-3\Phase3-TF3-Infra-Sentinel\.venv\Scripts\python.exe" src/main.py
   ```
3. Mở trình duyệt truy cập: **[http://localhost:8001/chatbot](http://localhost:8001/chatbot)**

---

## 🛠️ 3. Sử dụng Giao diện Kiểm Thử (Testing Sidebar UI)

Giao diện Web Chat đã được nâng cấp thêm **Thanh Cấu hình bên phải (Sidebar)** để hỗ trợ việc debug và kiểm thử tiện lợi hơn:

1. **Cấu hình User ID (Giỏ hàng):**
   * Bạn có thể đổi tên User ID bất cứ lúc nào (ví dụ: `test_user_001`, `hieu_admin`) và nhấn **Lưu**.
   * Hệ thống sẽ đồng bộ lịch sử hội thoại và giỏ hàng của chính User ID đó. Khi bạn yêu cầu chatbot thêm sản phẩm, sản phẩm sẽ được gán chính xác cho User ID đang hiển thị trên Sidebar.

2. **Giỏ hàng giả lập (Real-time):**
   * Hiển thị danh sách sản phẩm hiện đang có trong giỏ hàng của User ID được chọn, kèm giá tiền và tổng tiền.
   * Tự động cập nhật real-time ngay sau khi chatbot thêm sản phẩm thành công hoặc khi bạn nhấn nút **Xác nhận (Confirm)** trên khung chat.

3. **Trạng thái Microservices (EKS Mocks):**
   * Hiển thị trực quan trạng thái của các dịch vụ xem đang là `MOCKING` hay `ACTIVE`.
