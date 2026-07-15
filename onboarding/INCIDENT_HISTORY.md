# 📖 LỊCH SỬ SỰ CỐ & HƯỚNG DẪN KHẮC PHỤC (SRE PLAYBOOK KB)

Trích sổ ghi chép sự cố của đội vận hành TechX-Corp. Đây là tập hợp những lần hệ thống từng gặp trục trặc trên EKS Cluster và **đã được xử lý thành công**. Tài liệu này đóng vai trò làm **Cơ sở tri thức (Knowledge Base)** để AIOps Engine (LLM) đối chiếu hành vi lỗi và đưa ra giải pháp khắc phục an toàn.

> [!NOTE]
> **Lưu ý quan trọng:** Đây là những sự cố **trong quá khứ đã đóng**. Nó đóng vai trò làm dữ liệu mẫu so khớp. Khi hệ thống gặp sự cố vỡ SLO, hãy đối chiếu các chỉ số Jaeger Trace và logs với sổ sự cố này để đưa ra chẩn đoán chính xác.

---

## INC-1 · Checkout chậm và lỗi cạn connection pool PostgreSQL (đã đóng)

* **Khi nào:** Đợt khuyến mãi quý trước.
* **Triệu chứng:** Vào giờ cao điểm, tỉ lệ đặt hàng thành công tụt xuống ~95%, p95 latency checkout vọt lên vài giây. Khách bỏ giỏ hàng.
* **Nguyên nhân gốc:** Dịch vụ `product-catalog` gọi đến database PostgreSQL bị cạn kiệt connection pool (vượt quá giới hạn max connections). Các truy vấn gRPC/HTTP xếp hàng chờ đợi kết nối rồi bị timeout.
* **Đã xử:** Khắc phục bằng cách scale-up số lượng replicas pod `product-catalog` để phân tán tải kết nối (`kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2`).
* **Bài học còn treo:** Hệ thống chưa được kiểm chứng kỹ dưới tải cao; cần thiết kế kích thước pool động hoặc cơ chế hàng đợi.

---

## INC-2 · Mất giỏ hàng sau khi node Valkey được lên lịch lại (đã đóng)

* **Khi nào:** Một lần bảo trì cụm định kỳ.
* **Triệu chứng:** Một nhóm khách hàng mất sạch giỏ hàng đang chọn, trang checkout báo lỗi kết nối lưu trữ giỏ hàng.
* **Nguyên nhân gốc:** Lớp lưu giỏ hàng `valkey-cart` chạy đơn lẻ (Single replica SPOF) không có lưu trữ bền vững (non-persistent). Khi pod bị rescheduled sang node mới, dữ liệu lưu trong bộ nhớ (in-memory state) mất sạch.
* **Đã xử:** Tuyệt đối không được restart pod tự động vì restart sẽ làm mất sạch dữ liệu giỏ hàng còn lại của các user khác. Cần giữ nguyên trạng thái và cảnh báo cho SRE scale hoặc deploy cấu hình Valkey persistent.
* **Bài học còn treo:** Cần cấu hình Valkey lưu trữ bền vững (Persistent Volume) thay vì in-memory mộc.

---

## INC-3 · Lỗi thanh toán gRPC timeout trong lúc deploy (đã đóng)

* **Khi nào:** Một lần release thường kỳ.
* **Triệu chứng:** Trong vài phút lúc deploy, một phần request thanh toán lỗi gRPC status 4 (timeout / deadline exceeded) mặc dù bản mới không có bug.
* **Nguyên nhân gốc:** Kết nối EventStream gRPC giữa `fraud-detection` và `flagd` bị gián đoạn timeout. Pod mới nhận traffic trước khi khởi động xong do thiếu readiness gating hoặc cấu hình timeout không tương thích.
* **Đã xử:** Khắc phục nhanh bằng cách dọn cache / scale lại pod `fraud-detection` (`kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=1`) để bắt đầu lại gRPC EventStream mới.
* **Bài học còn treo:** Phải đồng bộ hóa cơ chế liveness/readiness probe cho toàn bộ microservices.

---

## INC-4 · Treo trang chi tiết sản phẩm do Bedrock API rate limit 429 (đã đóng)

* **Khi nào:** Đợt khuyến mãi lớn có lưu lượng khách truy cập tăng vọt.
* **Triệu chứng:** Trang chi tiết sản phẩm load cực kỳ chậm (>5 giây), tính năng tóm tắt review bằng AI báo lỗi liên tục.
* **Nguyên nhân gốc:** Cổng dịch vụ review gọi đến AWS Bedrock API vượt quá giới hạn tần suất yêu cầu, nhà cung cấp trả về lỗi HTTP 429 (Too Many Requests / Rate Limit).
* **Đã xử:** Tắt tính năng AI review summary bằng cách kích hoạt Feature Flag cục bộ (`kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=true`), giúp trang web fallback về hiển thị review thô bình thường để hồi phục latency.
* **Bài học còn treo:** Cần triển khai rate limiting nội bộ hoặc cơ chế caching kết quả LLM để giảm tần suất gọi API trực tiếp.

---

## INC-5 · Chậm xử lý đơn hàng do Kafka Consumer Lag lớn trên accounting (đã đóng)

* **Khi nào:** Sau sự kiện Flash Sale lớn.
* **Triệu chứng:** Khách hàng thanh toán thành công nhưng không thấy đơn hàng được ghi nhận trong trang lịch sử đơn hàng hoặc sổ kế toán.
* **Nguyên nhân gốc:** Lưu lượng đặt hàng tăng vọt làm nghẽn hàng đợi Kafka. Dịch vụ `accounting` tiêu thụ tin nhắn (Consumer) bị chậm, tạo ra khoảng trễ lớn (Consumer Lag hàng ngàn tin nhắn).
* **Đã xử:** Scale up số lượng replicas của `accounting` pod để tăng tốc độ tiêu thụ tin nhắn trong hàng đợi song song (`kubectl -n techx-tf3 scale deploy/accounting --replicas=2`).
* **Bài học còn treo:** Cần tự động scale pod `accounting` dựa trên trị số Kafka Lag.

---

## INC-6 · Chậm phản hồi trang gợi ý do Memory Pressure & GC Latency (đã đóng)

* **Khi nào:** Trong giờ cao điểm mua sắm.
* **Triệu chứng:** Phần gợi ý sản phẩm liên quan load cực kỳ chậm hoặc trống trơn, pod `recommendation` báo tiêu thụ RAM chạm ngưỡng 95%.
* **Nguyên nhân gốc:** Dịch vụ stateless `recommendation` bị rò rỉ bộ nhớ nhẹ hoặc chịu áp lực bộ nhớ cao (Memory Pressure), dẫn đến việc bộ thu gom rác (Garbage Collector) của Python liên tục dừng luồng chạy (GC pauses) làm nghẽn xử lý.
* **Đã xử:** Tiến hành khởi động lại mềm (Soft restart) deployment (`kubectl -n techx-tf3 rollout restart deployment/recommendation`) để giải phóng bộ nhớ đệm. Vì dịch vụ này là stateless (không lưu trạng thái) nên restart rất an toàn.
* **Bài học còn treo:** Cần optimize code Python để giảm mức sử dụng RAM và sửa lỗi rò rỉ bộ nhớ.

---

## INC-7 · Mất tính năng AI reviews summary do kẹt Circuit Breaker (đã đóng)

* **Khi nào:** Sau khi nhà cung cấp LLM phục hồi từ sự cố cúp điện.
* **Triệu chứng:** Tính năng tóm tắt AI review hiển thị thông báo "AI summary disabled" mặc dù API Bedrock đã hoạt động bình thường trở lại.
* **Nguyên nhân gốc:** Khóa ngắt mạch (Circuit Breaker) trên dịch vụ `product-reviews` tự động mở (OPEN) khi API Bedrock bị lỗi, nhưng sau khi API hoạt động lại, nó bị kẹt ở trạng thái OPEN không tự phục hồi về CLOSE.
* **Đã xử:** Sử dụng lệnh ép đóng mạch (force-close-breaker) để nối lại dòng kết nối (`kubectl -n techx-tf3 exec deploy/product-reviews -- force-close-breaker`).
* **Bài học còn treo:** Cần cấu hình lại thời gian tự động phục hồi (half-open timeout) của Circuit Breaker.

---

## INC-8 · Latency tăng tức thời do Cold Start dịch vụ quy đổi ngoại tệ (đã đóng)

* **Khi nào:** Ngay sau khi pod `currency` được cập nhật phiên bản mới.
* **Triệu chứng:** Lượt thanh toán đầu tiên của khách nước ngoài bị trễ khoảng 3-4 giây rồi sau đó hoạt động nhanh bình thường trở lại.
* **Nguyên nhân gốc:** Pod `currency` mới khởi động phải thực hiện nạp và lưu cache tỷ giá từ API bên ngoài (Warming cache / Cold Start). Hệ thống không có lỗi thật, chỉ là độ trễ khởi động tạm thời.
* **Đã xử:** Sự cố tự phục hồi (Self-healed) mà không cần can thiệp. SRE tuyệt đối không restart pod vì restart sẽ làm lặp lại chu kỳ Cold Start này.
* **Bài học còn treo:** Cần cấu hình pre-warming cache trong bước khởi động (initContainers) của Kubernetes pod.

---

**Điểm chung:** các sự cố trên đều xoay quanh **độ tin cậy dưới áp lực** - quá tải, mất node, deploy, giới hạn của nhà cung cấp LLM. Hệ thống chạy tốt lúc bình thường nhưng chưa được làm cứng cho lúc có biến. Khi bạn tiếp quản, đây là vùng đáng soi trước tiên.
