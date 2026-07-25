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

### Kịch bản A: Sử dụng PostgreSQL (Đơn giản, Tiết kiệm)

#### 1. Mẫu tin nhắn thảo luận với CDO:
> [!TIP]
> *“Chào team CDO, nhóm AI (AIO) hiện tại đang triển khai tính năng Caching cho trợ lý LLM để tối ưu chi phí token và tốc độ phản hồi. Để đơn giản hóa hạ tầng, bên mình đề xuất **tận dụng Database PostgreSQL hiện tại** để tạo một bảng cache dạng `UNLOGGED` (không ghi file WAL để tối ưu tốc độ ghi).*
> 
> *Để chuẩn bị cho các câu hỏi kỹ thuật về **hiệu năng (latency)** và **nguy cơ treo cơ sở dữ liệu chính (DB freezing/locking)**, bên mình đã thiết kế sẵn các giải pháp giảm thiểu rủi ro sau:*
> * *1. **Query Timeout (100ms)**: Trên app server, thời gian chờ tối đa cho mỗi truy vấn cache là 100ms. Nếu Postgres chậm, ứng dụng sẽ tự động fail-open (ngắt kết nối và đi thẳng tới LLM), đảm bảo storefront không bao giờ bị treo.*
> * *2. **UNLOGGED Table**: Bảng cache sẽ bỏ qua ghi log WAL, ghi trực tiếp lên bộ đệm RAM để tránh nghẽn I/O đĩa cứng.*
> * *3. **Unique Index**: Tạo chỉ mục duy nhất cho `cache_key` giúp truy vấn đạt O(1) / O(log N) với độ trễ < 2ms.*
> * *4. **Connection Pooling**: Sử dụng pooler phía ứng dụng để bảo vệ cổng DB.*
> 
> *CDO xem giúp mình cấu hình này có ổn cho database hiện tại không? Dung lượng đĩa của Postgres có thoải mái để chứa thêm khoảng 1-2 GB dữ liệu cache không?”*

#### 2. Đối chiếu với Mandate-06:
* **Điểm PHÙ HỢP**:
  * **Đường lui dự phòng (Resilience)**: Cơ chế Query Timeout (100ms) đảm bảo app server luôn fail-open an toàn, đáp ứng yêu cầu *"không làm treo trang sản phẩm"*.
  * **Khả năng kiểm toán (Auditability)**: Lưu trữ metadata dạng `JSONB` trong Postgres hỗ trợ truy vấn SQL báo cáo số đo Eval rất tốt (tỷ lệ ảo giác, lượng token).
  * **Ngân sách (Budget)**: Tái sử dụng cụm RDS Postgres hiện tại giúp chi phí phát sinh là **$0/tháng**, nằm trọn trong *"ngân sách hiện tại"*.
* **Điểm CHƯA PHÙ HỢP (Hạn chế)**:
  * **Tranh chấp tài nguyên**: Đọc/ghi cache liên tục dễ gây nghẽn CPU/Disk I/O của Postgres chính, ảnh hưởng trực tiếp đến SLO trang storefront.
  * **Bão Cache (Cache Storm)**: Dữ liệu bảng `UNLOGGED` bị xóa sạch khi DB restart, gây cache miss hàng loạt dẫn đến gọi dồn dập và quá tải API LLM.

#### 3. Phương án khắc phục (Mitigations):
* **Dùng Read Replica**: CDO chuyển các truy vấn đọc cache (`SELECT`) sang instance Read Replica chuyên đọc để giảm tải cho DB chính.
* **Cấu hình Connection Poolers (PgBouncer)**: Giới hạn số lượng kết nối tối đa cho cache query để bảo vệ connection slot của DB nghiệp vụ.
* **Cache Warm-up Worker**: Script tự động quét sinh trước cache cho top 100 sản phẩm hot khi DB vừa khởi động lại.
* **Cache Expiry Jitter**: Thêm thời gian sống ngẫu nhiên ($24\text{ giờ} \pm 1\text{ giờ}$) để tránh cache hết hạn đồng loạt gây nghẽn LLM.

---

### Kịch bản B: Sử dụng Redis (Hiệu năng cao, Chuẩn Production)

#### 1. Mẫu tin nhắn thảo luận với CDO:
> [!TIP]
> *“Chào team CDO, nhóm AI (AIO) muốn bổ sung **Redis** làm tầng Runtime Caching cho LLM để đảm bảo độ trễ phản hồi <1ms và cô lập hoàn toàn tải lượng đọc/ghi cache ra khỏi Database PostgreSQL chính (tránh nguy cơ nghẽn DB làm treo trang sản phẩm dưới tải cao).*
> 
> *Nhờ CDO tư vấn giúp mình xem phương án triển khai nào khả thi hơn:*
> * **Phương án B.1 (Chạy trực tiếp trên K8s)**: CDO có thể hỗ trợ cài một Redis service (Helm Chart Bitnami) lên cụm K8s hiện tại và cấu hình Persistent Volume (PVC) được không? Cụm có đủ RAM dư thừa (~256MB - 512MB RAM) không?
> * **Phương án B.2 (AWS Managed)**: CDO có hỗ trợ xin cấp phát một cụm AWS ElastiCache for Redis nhỏ (node `cache.t4g.micro` hoặc `cache.t4g.medium` trong mạng VPC nội bộ) không?”*

#### 2. Đối chiếu với Mandate-06:
* **Điểm PHÙ HỢP**:
  * **Độ bền bỉ tối đa (Resilience)**: Độ trễ phản hồi cực nhanh (< 1ms) và cô lập tải lượng cache hoàn toàn khỏi database nghiệp vụ chính. Phòng ngừa nguy cơ nghẽn DB chính gây treo storefront, bảo vệ SLO trang sản phẩm.
  * **Tự động dọn dẹp (Resilience)**: Cơ chế TTL tích hợp của Redis giúp tự động thu hồi RAM khi key hết hạn, giảm thiểu lỗi tràn bộ nhớ (OOM).
* **Điểm CHƯA PHÙ HỢP (Hạn chế)**:
  * **Ngân sách (Budget)**: Tốn thêm chi phí thuê AWS ElastiCache riêng biệt (khoảng **$30 - $60 / tháng**), làm tăng hóa đơn dịch vụ AWS của dự án.
  * **Khả năng kiểm toán (Auditability)**: Dữ liệu dạng Key-Value trong Redis rất khó chạy các truy vấn SQL tổng hợp số liệu phức tạp để phục vụ mục tiêu kiểm toán chất lượng (Eval) của Mandate.
  * **Tiêu tốn RAM của máy chủ Node (nếu tự host K8s)**: Khác với AWS ElastiCache sử dụng RAM độc lập chuyên dụng (0.5GB - 3GB), chạy container Redis trực tiếp trên cụm EKS sẽ tranh chấp RAM trực tiếp với các microservice khác của storefront, có nguy cơ gây OOM (Out Of Memory) làm crash Node nếu cache phình to không kiểm soát.

#### 3. Phương án khắc phục (Mitigations):
* **Tối ưu chi phí bằng K8s container**: Ưu tiên triển khai theo Phương án B.1 (tự host bằng container trên cụm EKS hiện có). Việc này giúp **giảm chi phí phát sinh về mức $0/tháng** (tiết kiệm hoàn toàn khoản chi **$30 - $60/tháng** của AWS ElastiCache) nhờ tận dụng tài nguyên RAM/CPU dư thừa sẵn có trên các node EC2 của cụm EKS.
* **Chống OOM bằng maxmemory và allkeys-lru**: Khi cấu hình Helm Chart Redis, bắt buộc set cấu hình giới hạn cứng `maxmemory 256mb` (hoặc `512mb`) và thiết lập `maxmemory-policy allkeys-lru`. Khi bộ nhớ chạm ngưỡng giới hạn, Redis sẽ tự động xóa các cache key cũ, ít sử dụng nhất để nhường chỗ cho key mới, đảm bảo **không bao giờ vượt ngưỡng RAM được cấp phát** trên cụm K8s.
* **Đồng bộ hóa kết quả kiểm toán**: Dùng Redis để phục vụ cache tốc độ cao, nhưng đẩy các log kiểm định (Audit Logs) phi tập trung về OpenTelemetry/Jaeger hoặc lưu bản ghi thống kê siêu nhẹ về bảng PostgreSQL chính.

---

### Kịch bản C: Đề xuất phương án tối ưu nhất - Hybrid (Redis + Postgres)

#### 1. Mẫu tin nhắn thảo luận với CDO:
> [!TIP]
> *“Chào team CDO, để tuân thủ tối đa các ràng buộc của chỉ thị **Mandate-06** (vừa đảm bảo độ trễ siêu thấp không treo trang, vừa lưu trữ log kiểm toán có cấu trúc để làm báo cáo Eval gửi mentor), nhóm AIO đề xuất hướng đi **Hybrid**:*
> * *Sử dụng **Redis** (chạy Helm trên K8s hoặc AWS ElastiCache) để lưu trữ Cache Key - Answer phục vụ truy vấn thời gian thực của khách hàng.*
> * *Sử dụng **PostgreSQL** có sẵn để lưu trữ nhật ký kiểm toán (Audit Logs) chứa metadata chi tiết và số đo Eval chất lượng để báo cáo.*
> 
> *CDO đánh giá giúp mình hướng đi này có khả thi với hạ tầng hiện tại không và cần chuẩn bị những gì nhé!”*

#### 2. Đối chiếu với Mandate-06:
* **Điểm PHÙ HỢP**:
  * **Độ bền bỉ tuyệt đối (Resilience)**: Đọc/ghi cache thời gian thực chạy trên Redis tách biệt, không gây nghẽn PostgreSQL chính, đạt độ trễ < 1ms.
  * **Kiểm toán chất lượng (Auditability)**: Mọi thông tin gọi LLM, token tiêu tốn, kết quả Fidelity Judge đều được ghi nhận có cấu trúc tại bảng PostgreSQL riêng biệt, dễ dàng kiểm toán và trích xuất số đo.
  * **Chống Bão Cache (Cache Storm)**: Nếu Redis bị sập đột ngột và mất dữ liệu RAM, hệ thống có thể khôi phục (restore) nhanh chóng cache từ dữ liệu lưu trong PostgreSQL thay vì phải gọi lại API LLM.
* **Điểm CHƯA PHÙ HỢP (Hạn chế)**:
  * **Độ phức tạp lập trình (Development Complexity)**: Tăng **gấp 2 lần** so với phương án đơn nguồn vì code phải quản lý 2 driver kết nối khác nhau (Redis + Postgres), xử lý logic ghi đúp (Dual Write) đồng bộ, và quản trị các kịch bản lỗi khi 1 trong 2 nguồn bị sập.
  * **Tác động ngân sách (Budget Impact)**: Tốn thêm tài nguyên cho Redis. Nếu dùng AWS ElastiCache riêng sẽ tốn **$30 - $60 / tháng**. Nếu chạy container trên cụm EKS hiện có sẽ chiếm **256MB - 512MB RAM** của Worker Node (tương đương khoảng **$2 - $4 / tháng** tính theo đơn giá RAM).

#### 3. Phương án khắc phục (Mitigations):
* **Giảm 90% độ phức tạp bằng Caching Gateway Pattern**: Nhóm AI sẽ đóng gói toàn bộ logic kết nối kép và đồng bộ hóa PostgreSQL + Redis vào một class Adapter duy nhất (`CacheManager`). Phía app server chỉ cần gọi hàm qua interface chung (`cache_manager.get` / `set`), che giấu hoàn toàn sự phức tạp của hạ tầng bên dưới.
* **Tối ưu hóa ngân sách về $0/tháng và giảm 80% dung lượng đĩa**:
  * Chạy container Redis trực tiếp trên cụm EKS hiện có để đưa chi phí phần cứng phát sinh về **$0/tháng** (tiết kiệm hoàn toàn $30 - $60/tháng phí ElastiCache).
  * Áp dụng **Minified Audit Schema**: PostgreSQL chỉ lưu thông tin metadata siêu nhẹ (mã lỗi, token, timestamp ~0.1KB/dòng), không lưu chuỗi văn bản phản hồi thô cồng kềnh (~5KB/dòng). Điều này giúp **tiết kiệm 80% dung lượng đĩa cứng lưu trữ** và giảm thiểu tải ghi I/O lên Postgres.



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
