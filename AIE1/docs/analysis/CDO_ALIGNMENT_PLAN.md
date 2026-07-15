# Kế Hoạch Trao Đổi Hạ Tầng Caching LLM Với Team CDO

Tài liệu này chứa kịch bản, nội dung và các câu hỏi chuẩn bị để nhóm AIO thảo luận và thống nhất phương án hạ tầng Caching LLM với nhóm CDO (Cloud/DevOps), đảm bảo đáp ứng các tiêu chí của [MANDATE-06-ai-trust-safety.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/mandates/MANDATE-06-ai-trust-safety.md).

---

## 1. Mục Tiêu Cuộc Họp
- Thống nhất lựa chọn hạ tầng triển khai Cache: **PostgreSQL** (bảng Unlogged) hay **Redis** (Helm Chart trên K8s hoặc AWS Managed ElastiCache) hay **Hybrid**.
- Xác định phân chia công việc (Ownership) giữa hai đội AIO và CDO để cấu hình Docker, Helm, và CI/CD.
- Thống nhất các tham số tài nguyên (RAM/Disk) cấp phát cho hệ thống cache.

---

## 2. Kịch Bản & Mẫu Trao Đổi Chi Tiết

Dưới đây là các kịch bản chuẩn bị sẵn để bạn gửi/thảo luận trực tiếp tùy theo hướng đề xuất:

### Kịch bản A: Nếu đề xuất dùng **PostgreSQL** (Đơn giản, Tiết kiệm - Có giải pháp chống treo/chậm)
> *"Chào team CDO, nhóm AI (AIO) hiện tại đang triển khai tính năng Caching cho trợ lý LLM để tối ưu chi phí token và tốc độ phản hồi. Để đơn giản hóa hạ tầng, bên mình đề xuất **tận dụng Database PostgreSQL hiện tại** để tạo một bảng cache dạng `UNLOGGED` (không ghi file WAL để tối ưu tốc độ ghi).
>
> Để chuẩn bị cho các câu hỏi kỹ thuật về **hiệu năng (latency)** và **nguy cơ treo cơ sở dữ liệu chính (DB freezing/locking)**, bên mình đã thiết kế sẵn các giải pháp giảm thiểu rủi ro sau:
> 
> 1. **Chống treo luồng bằng Query Timeout**: Trên app server, chúng mình sẽ đặt thời gian chờ tối đa cho mỗi truy vấn cache là **100ms**. Nếu Postgres bị chậm hoặc quá tải vượt quá 100ms, ứng dụng sẽ tự động ngắt kết nối (fail-open) và đi trực tiếp tới LLM/Mock hoặc trả về thông báo tĩnh thân thiện. Điều này đảm bảo trang sản phẩm **không bao giờ bị treo** vì đợi DB.
> 2. **Chống nghẽn I/O ghi đĩa bằng UNLOGGED Table**: Bảng cache sẽ được khởi tạo ở dạng `UNLOGGED`. Nó giúp bỏ qua ghi log WAL, ghi trực tiếp lên bộ đệm RAM nên tốc độ ghi cực nhanh, không gây tranh chấp I/O đĩa cứng với DB chính.
> 3. **Chống quét toàn bảng bằng Unique Index**: Tạo chỉ mục duy nhất cho `cache_key`. Đảm bảo truy vấn đọc/ghi đạt độ phức tạp O(1) hoặc O(log N), thời gian tìm kiếm thực tế < 2ms, không gây Full Table Scan làm nghẽn DB.
> 4. **Tránh cạn kiệt Connection bằng Connection Pooling**: Nhóm sẽ tích hợp thư viện pooling phía ứng dụng để tái sử dụng connection, tránh việc mở mới kết nối liên tục gây quá tải cổng DB.
> 
> CDO xem giúp mình cấu hình này có ổn cho database hiện tại không? Dung lượng đĩa của Postgres có thoải mái để chứa thêm khoảng 1-2 GB dữ liệu cache không?"*

#### Phân tích Chi tiết Kịch bản A đối với Mandate-06:
* **Điểm PHÙ HỢP với Mandate-06**:
  - **Đường lui dự phòng (Resilience)**: Cơ chế Query Timeout (100ms) đảm bảo app server luôn chạy ổn định (fail-open) kể cả khi DB bị chậm/treo, tuân thủ đúng yêu cầu *"không làm treo trang sản phẩm"*.
  - **Khả năng kiểm toán (Auditability)**: Kiểu dữ liệu `JSONB` của Postgres hỗ trợ CDO/AIO dễ dàng chạy các câu lệnh SQL phân tích để tổng hợp số liệu Eval chất lượng (như tỷ lệ ảo giác của mô hình, token tiêu tốn, kiểm định của Judge).
  - **Ngân sách (Budget)**: Tái sử dụng cụm RDS Postgres hiện tại giúp chi phí phát sinh bằng **$0/tháng**, tuân thủ hoàn hảo *"ngân sách hiện tại của TF"*.
* **Điểm CHƯA PHÙ HỢP (Hạn chế)**:
  - **Rủi ro đe dọa SLO (Nghẽn DB chính)**: Đọc/ghi cache liên tục dễ gây tranh chấp tài nguyên (CPU/IOPS) trực tiếp với các bảng nghiệp vụ chính (products, reviews), gián tiếp làm chậm trang sản phẩm khi lưu lượng tăng đột biến.
  - **Bão Cache (Cache Storm) khi DB restart**: Vì sử dụng bảng `UNLOGGED` để tối ưu hiệu năng ghi, dữ liệu cache sẽ bị xoá sạch hoàn toàn nếu DB restart. Khi đó, lượng truy cập đồng loạt gây ra Cache Miss hàng loạt $\rightarrow$ dồn dập gọi LLM gây sập hệ thống hoặc quá tải quota (Rate Limit).
* **Giải pháp khắc phục từ nhóm AI (Mitigations)**:
  - **Dùng Read Replica**: CDO cấu hình chuyển toàn bộ các lệnh đọc cache (`SELECT`) sang instance Read Replica chuyên đọc để giảm tải cho DB chính.
  - **Cấu hình Connection Poolers (PgBouncer)**: CDO giới hạn số lượng kết nối tối đa dành cho cache query để bảo vệ connection slot của các tác vụ nghiệp vụ quan trọng khác.
  - **Cache Warm-up Worker**: Viết script chạy nền tự động quét sinh trước cache cho top 100 sản phẩm hot nhất ngay khi DB vừa khởi động lại.
  - **Cache Expiry Jitter**: Thêm thời gian sống ngẫu nhiên ($24\text{ giờ} \pm 1\text{ giờ}$) khi ghi cache để phân tán thời điểm hết hạn của các key, tránh nghẽn LLM.


### Kịch bản B: Nếu đề xuất dùng **Redis** (Hiệu năng cao, Chuẩn Production)
> *"Chào team CDO, nhóm AI (AIO) muốn bổ sung **Redis** làm tầng Runtime Caching cho LLM để đảm bảo độ trễ phản hồi <1ms và cô lập hoàn toàn tải lượng đọc/ghi cache ra khỏi Database PostgreSQL chính (tránh nguy cơ nghẽn DB làm treo trang sản phẩm dưới tải cao).
> 
> Nhờ CDO tư vấn giúp mình xem phương án triển khai nào khả thi hơn:
> * **Phương án B.1 (Chạy trực tiếp trên K8s)**: CDO có thể hỗ trợ cài một Redis service (ví dụ Helm Chart của Bitnami) lên cụm K8s hiện tại và cấu hình Persistent Volume (PVC) được không? Cụm hiện tại có đủ RAM dư thừa không (dự kiến cấp phát khoảng 256MB - 512MB RAM cho Redis)?
> * **Phương án B.2 (AWS Managed)**: Nếu K8s không khuyến nghị chạy cơ sở dữ liệu dạng Stateful như Redis, CDO có hỗ trợ xin cấp phát một cụm AWS ElastiCache for Redis nhỏ (ví dụ node `cache.t4g.micro` hoặc `cache.t4g.medium` trong mạng VPC nội bộ) không?"*

### Kịch bản C: Đề xuất phương án tối ưu nhất - **Hybrid** (Redis + Postgres)
> *"Chào team CDO, để tuân thủ tối đa các ràng buộc của chỉ thị **Mandate-06** (vừa đảm bảo độ trễ siêu thấp không treo trang, vừa lưu trữ log kiểm toán có cấu trúc để làm báo cáo Eval gửi mentor), nhóm AIO đề xuất hướng đi **Hybrid**:
> * Sử dụng **Redis** (chạy Helm trên K8s hoặc AWS ElastiCache) để lưu trữ Cache Key - Answer phục vụ truy vấn thời gian thực của khách hàng.
> * Sử dụng **PostgreSQL** có sẵn để lưu trữ nhật ký kiểm toán (Audit Logs) chứa metadata chi tiết và số đo Eval chất lượng để báo cáo.
> 
> CDO đánh giá giúp mình hướng đi này có khả thi với hạ tầng hiện tại không và cần chuẩn bị những gì nhé!"*

---

## 3. Các Câu Hỏi Cần Chất Vấn & Làm Rõ Với CDO

| Câu hỏi thảo luận | Lý do cần hỏi | Ghi chú phản hồi của CDO |
| :--- | :--- | :--- |
| **Cụm K8s còn trống bao nhiêu tài nguyên RAM?** | Nếu cụm quá chật chội, việc chạy thêm container Redis có thể gây OOM (Out Of Memory) ảnh hưởng đến dịch vụ chính. | |
| **Chính sách cấp phát Persistent Volume (PV/PVC) như thế nào?** | Nếu tự dựng Redis trên K8s, cần lưu trữ dữ liệu cache bền vững qua mỗi lần Pod restart. | |
| **Ngân sách hạ tầng AWS hiện tại của TF còn bao nhiêu?** | AWS ElastiCache tốn thêm khoảng $30 - $60 / tháng. Cần xác nhận xem ngân sách có cho phép không hay bắt buộc phải tận dụng Postgres/EC2 cũ. | |
| **Bên nào sẽ chịu trách nhiệm bảo trì Helm Chart/Manifest cho Redis?** | Xác định rõ ranh giới trách nhiệm (AIO cung cấp config cấu hình ứng dụng, CDO cài đặt và giám sát RAM/Port). | |

---

## 4. Các Bước Tiếp Theo Sau Khi Đồng Thuận
1. **Ký ADR (Architectural Decision Record)**: Cập nhật tài liệu quyết định kiến trúc chung có chữ ký phê duyệt từ Lead của cả hai bên (AIO và CDO).
2. **Cập nhật CI/CD**: CDO cập nhật file cấu hình Helm Chart (`values.yaml`) để thêm biến môi trường kết nối Redis/Postgres Cache mới.
3. **Triển khai Code**: AIO tiến hành viết code cache thực tế trong file `product_reviews_server.py` theo mô hình kết nối đã thống nhất.
