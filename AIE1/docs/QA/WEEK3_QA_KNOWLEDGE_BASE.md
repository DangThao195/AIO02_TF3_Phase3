# Bộ 100 Câu Hỏi & Đáp Sâu Sắc Về Kiến Thức Hệ Thống Tuần 3 (AIE1 Task Force)

Tài liệu này lưu trữ bộ 100 câu hỏi và câu trả lời chuyên sâu về mặt kiến trúc, lập trình, SRE, chất lượng và bảo mật liên quan đến dịch vụ Product Reviews trợ lý AI trong tuần vận hành thứ 3.

---

## 📑 Mục lục
1. [Phần 1: Kiến trúc Caching Hai Tầng & Bảo Mật Cache (Câu 1 - 25)](#phần-1-kiến-trúc-caching-hai-tầng--bảo-mật-cache-câu-1---25)
2. [Phần 2: Tính Bền Vững, Fallback & Circuit Breaker (Câu 26 - 50)](#phần-2-tính-bền-vững-fallback--circuit-breaker-câu-26---50)
3. [Phần 3: Giám Sát, Telemetry & HTTP Sidecar Server (Câu 51 - 75)](#phần-3-giám-sát-telemetry--http-sidecar-server-câu-51---75)
4. [Phần 4: Đánh Giá Chất Lượng LLM-as-a-Judge & Rubrics (Câu 76 - 100)](#phần-4-đánh-giá-chất-lượng-llm-as-a-judge--rubrics-câu-76---100)

---

##  Phân 1: Kiến trúc Caching Hai Tầng & Bảo Mật Cache (Câu 1 - 25)

#### Q1: Tại sao hệ thống lại cần cơ chế Caching hai tầng thay vì một tầng duy nhất?
**A:** Caching hai tầng giải quyết đồng thời hai loại điểm nghẽn khác nhau: Tầng 1 (Redis Cache) lưu trữ phản hồi LLM hoàn chỉnh giúp triệt tiêu độ trễ mạng (I/O-bound) từ các cuộc gọi API bên ngoài; Tầng 2 (PostgreSQL Safe Reviews Filter) lọc trước các review có thuộc tính `is_safe = TRUE` để triệt tiêu thời gian xử lý CPU (CPU-bound) của bộ lọc Regex Guardrail.

#### Q2: Sự khác biệt cốt lõi giữa "Cold Cache" và "Hot Cache" trong số liệu latency là gì?
**A:** "Cold Cache" là lần chạy đầu tiên khi cache chưa được nạp, hệ thống bắt buộc phải gọi LLM và tốn trung bình ~2.8 giây. "Hot Cache" xảy ra ở các lần gọi sau khi dữ liệu đã có sẵn trong Redis, phản hồi trả về ngay lập tức với độ trễ siêu nhỏ (~4.4 ms), tăng tốc độ phản hồi gấp ~641 lần.

#### Q3: Cấu trúc của Cache Key cho LLM Response trong Redis được thiết kế như thế nào?
**A:** Cache Key được tạo ra bằng thuật toán băm SHA256 từ chuỗi nối tiếp có cấu trúc: `SHA256(product_id + review_version + model_id + question + user_id)`.

#### Q4: Tại sao tham số `user_id` lại là bắt buộc phải xuất hiện trong cấu trúc Cache Key?
**A:** Để đảm bảo tính cách ly dữ liệu giữa các khách hàng khác nhau. Nếu không có `user_id`, câu trả lời chứa thông tin riêng tư (PII) được cache của User A có thể bị trả về cho User B nếu họ hỏi cùng một câu hỏi cho cùng một sản phẩm, gây rò rỉ dữ liệu nghiêm trọng.

#### Q5: Sự cố "Cache Stampede" (Bão Cache) là gì và hệ thống phòng chống nó như thế nào?
**A:** Cache Stampede xảy ra khi một key cache phổ biến hết hạn (hoặc bị miss) đúng lúc có hàng ngàn request đồng thời đổ vào. Khi đó, tất cả các luồng đồng thời gọi trực tiếp tới LLM gây sập API hoặc nghẽn mạng. Hệ thống phòng chống bằng cơ chế **Distributed Lock** (Khóa phân tán Redis `SET NX EX 10`). Chỉ luồng đầu tiên lấy được khóa được phép gọi LLM và ghi cache, các luồng khác xếp hàng polling chờ đợi.

#### Q6: Tại sao chúng ta sử dụng Redis (Valkey) thay vì lưu trữ bảng cache trực tiếp trong PostgreSQL nghiệp vụ?
**A:** Redis lưu trữ dữ liệu hoàn toàn trên bộ nhớ RAM (In-Memory) cho tốc độ phản hồi cực cao (< 1ms). Việc sử dụng PostgreSQL làm cache sẽ gây tranh chấp CPU/Disk I/O với database nghiệp vụ chính khi chịu tải cao, dễ dẫn đến hiện tượng treo cổng kết nối DB nghiệp vụ.

#### Q7: Cơ chế "Fail-Open" hoạt động như thế nào khi kết nối Redis Cache bị mất hoặc lỗi?
**A:** Khi gọi Redis gặp ngoại lệ (ConnectionError, Timeout), hệ thống bắt ngoại lệ (try-except), ghi nhận log cảnh báo và tự động bỏ qua cache để đi trực tiếp tới luồng gọi LLM (Fail-Open), đảm bảo trang chi tiết sản phẩm của storefront không bị gián đoạn.

#### Q8: Tại sao thuộc tính `review_version` lại cần thiết trong cấu trúc Cache Key?
**A:** `review_version` đại diện cho hàm băm (MD5 hoặc SHA) của toàn bộ tập reviews hiện tại của sản phẩm đó. Khi có một review mới được thêm vào database, `review_version` thay đổi, làm Cache Key thay đổi theo. Điều này giúp tự động vô hiệu hóa (invalidation) cache cũ và nạp context mới nhất của sản phẩm.

#### Q9: Chính sách thu hồi khóa (Eviction Policy) tối ưu của Redis cho hệ thống cache này là gì?
**A:** Sử dụng chính sách `allkeys-lru` (Least Recently Used) kết hợp với thiết lập thời gian sống cố định (TTL 24 giờ). Khi bộ nhớ RAM của Redis bị đầy, các khóa lâu ngày không được truy cập sẽ tự động bị thu hồi trước.

#### Q10: "Fidelity Cache Policy" của hệ thống hoạt động như thế nào đối với các câu trả lời của LLM?
**A:** Chỉ các câu trả lời vượt qua bài kiểm tra độ trung thực của Judge (Fidelity Gate với `unsupported_claims == 0` và `contradicted_claims == 0`) mới được ghi vào Redis Cache. Các câu trả lời bị dán nhãn ảo giác (Unverified) sẽ bị chặn và tuyệt đối không được ghi cache.

#### Q11: Tại sao p95 latency của Hot Cache trong bảng số liệu thực tế vẫn ở mức cao (~15 giây)?
**A:** Đây là hệ quả trực tiếp từ **Fidelity Cache Policy**. Các case bị Unverified (không trung thực) không được lưu vào cache. Ở các request sau, hệ thống bắt buộc phải bỏ qua cache và gọi lại LLM thực tế để tái đánh giá, dẫn đến độ trễ ở phân vị p95 (chứa các case unverified này) vẫn cao bằng thời gian gọi LLM.

#### Q12: Làm thế nào ứng dụng khách hàng (client) nhận biết được câu trả lời được lấy từ Cache hay LLM?
**A:** Dịch vụ gRPC trả về cờ trạng thái cache thông qua cặp metadata trailing key-value: `cache: hit` (lấy từ cache) hoặc `cache: miss` (gọi trực tiếp LLM).

#### Q13: Database caching tầng 2 (is_safe) giải quyết bài toán gì trong PostgreSQL?
**A:** Giúp loại bỏ việc chạy đi chạy lại bộ lọc Regex Guardrail trên các review cũ. Khi review được import hoặc insert, hệ thống quét regex 1 lần duy nhất và ghi kết quả `is_safe = TRUE` hoặc `FALSE` vào cột. Khi runtime, câu query SQL chỉ quét `WHERE is_safe = TRUE` để lấy context sạch cực kỳ nhanh chóng.

#### Q14: Cách ly cache theo người dùng có làm tăng dung lượng bộ nhớ Redis không? Làm thế nào để tối ưu?
**A:** Có làm tăng dung lượng do tạo nhiều key khác nhau cho mỗi user. Tối ưu hóa bằng cách thiết lập TTL ngắn (ví dụ: 12 - 24 giờ) và chỉ kích hoạt cache cách ly cho các câu hỏi mang tính cá nhân hóa hoặc câu hỏi tự do.

#### Q15: Điều gì xảy ra khi tham số `user_id` bị trống hoặc null trong request gRPC?
**A:** Hệ thống sẽ gán một giá trị mặc định (ví dụ: `"anonymous"`) hoặc hash rỗng để tạo cache key chung cho các khách hàng vãng lai chưa đăng nhập.

#### Q16: Việc băm SHA256 cho Cache Key có làm ảnh hưởng đến hiệu năng CPU của app server không?
**A:** Không đáng kể. Thuật toán băm SHA256 trên một chuỗi ngắn vài trăm ký tự chỉ tốn vài micro-giây của CPU, hoàn toàn vượt trội so với thời gian mạng gọi LLM tốn hàng giây.

#### Q17: Có nên dùng nén dữ liệu (như gzip) trước khi lưu JSON metadata vào Redis không?
**A:** Không cần thiết nếu dung lượng bản ghi tóm tắt nhỏ (< 2KB). Việc nén và giải nén JSON nhỏ sẽ tốn thêm CPU cycle của app server mà không tiết kiệm được bao nhiêu dung lượng RAM của Redis.

#### Q18: Tại sao hệ thống sử dụng lệnh `SETEX` thay vì lệnh `SET` thông thường khi ghi cache?
**A:** Lệnh `SETEX` (Set with Expiry) cho phép thiết lập giá trị và thời gian hết hạn (TTL) một cách nguyên tử (atomic operation), tránh việc ghi key thành công nhưng gặp sự cố trước khi set TTL gây ra các key rác vĩnh viễn (leak memory).

#### Q19: Cache key có bị ảnh hưởng bởi sự thay đổi của prompt hay không?
**A:** Có. Trong Cache Key có tham số `model_id`. Khi thay đổi model hoặc cấu hình prompt hệ thống, hash key sẽ thay đổi để nạp lại bản tóm tắt tương ứng với logic prompt mới.

#### Q20: Làm thế nào để xóa thủ công (clear cache) một sản phẩm cụ thể khi phát hiện dữ liệu lỗi?
**A:** Có thể quét và xóa các khóa có pattern `*product_id*` trong Redis bằng lệnh `DEL` hoặc sử dụng cổng quản trị HTTP Sidecar để kích hoạt lệnh xóa cache theo product ID.

#### Q21: Điều gì xảy ra nếu tập reviews của sản phẩm trống? Hệ thống có lưu cache không?
**A:** Hệ thống sẽ trả về mã `NO_INFO` sớm mà không gọi LLM và không cần lưu cache, tránh lãng phí dung lượng Redis.

#### Q22: Sự khác biệt giữa `unlogged table` trong Postgres và Redis cache về độ bền vững?
**A:** Cả hai đều mất dữ liệu khi restart dịch vụ. Tuy nhiên, Redis hỗ trợ cơ chế lưu trữ snapshot bất đồng bộ (RDB) hoặc ghi log (AOF) xuống đĩa cứng để tự động khôi phục cache sau khi restart, điều mà bảng `unlogged` của Postgres không tự động làm nếu không có cấu hình phức tạp.

#### Q23: Tại sao không đưa trực tiếp nội dung câu hỏi (raw question) vào Redis key mà phải băm SHA256?
**A:** Vì câu hỏi của người dùng có thể rất dài, chứa ký tự đặc biệt, xuống dòng hoặc khoảng trắng dư thừa gây khó khăn cho việc quản lý key của Redis. Việc băm SHA256 chuẩn hóa key thành một chuỗi hex cố định 64 ký tự.

#### Q24: Cache có bảo vệ hệ thống khỏi các cuộc tấn công DDoS không?
**A:** Có. Bằng cách hit cache ở tầng đầu tiên, hệ thống không bị nghẽn API LLM và giảm tải tối đa cho cơ sở dữ liệu chính khi có lượng request khổng lồ truy cập vào các sản phẩm hot.

#### Q25: Tỷ lệ tiết kiệm chi phí thực tế (Cost Saving) khi có Cache hoạt động là bao nhiêu?
**A:** Theo số liệu thực tế đo đạc trong ADR 0006, lượng token tiêu thụ và chi phí API ước tính giảm **83.3%** trên Hot Cache.

---

## Phần 2: Tính Bền Vững, Fallback & Circuit Breaker (Câu 26 - 50)

#### Q26: Circuit Breaker (Bộ ngắt mạch) giải quyết vấn đề gì trong tích hợp GenAI?
**A:** Tránh hiện tượng treo luồng (thread starvation) của server khi API của nhà cung cấp LLM (như AWS Bedrock) bị sập hoặc phản hồi siêu chậm. Circuit Breaker tự động ngắt kết nối và chuyển sang chế độ dự phòng mà không cần đợi timeout lâu.

#### Q27: 3 Trạng thái của Circuit Breaker hoạt động như thế nào?
**A:** 
1. **CLOSED (Đóng):** Trạng thái bình thường, cho phép mọi request đi qua LLM.
2. **OPEN (Mở):** Khi tỷ lệ lỗi vượt ngưỡng, CB tự động ngắt, chặn mọi cuộc gọi tới LLM và chuyển hướng sang Fallback ngay lập tức.
3. **HALF-OPEN (Nửa mở):** Sau thời gian cool-down, CB cho phép một số lượng nhỏ request thử nghiệm đi qua LLM để kiểm tra dịch vụ đã phục hồi chưa.

#### Q28: Các tham số cấu hình của Circuit Breaker trong dịch vụ Product Reviews là gì?
**A:** Số lỗi liên tiếp kích hoạt OPEN: **5 lỗi**. Thời gian cool-down để chuyển sang HALF-OPEN: **30 giây**. Trạng thái được lưu tập trung trên Redis.

#### Q29: Tại sao trạng thái của Circuit Breaker lại nên lưu trên Redis thay vì lưu trong bộ nhớ RAM của app server?
**A:** Để đảm bảo tính nhất quán trạng thái khi chạy nhiều instance (pod) ứng dụng sau Kubernetes Load Balancer. Khi một pod phát hiện lỗi và ngắt mạch, tất cả các pod khác cũng đồng loạt ngắt mạch nhờ đọc chung trạng thái từ Redis.

#### Q30: Cơ chế "Automatic Retry" trong luồng gọi LLM sử dụng chiến lược gì?
**A:** Sử dụng thư viện `tenacity` cấu hình thuật toán **Exponential Backoff với Full Jitter** (thử lại tối đa 3 lần, độ trễ tăng dần lũy thừa kèm yếu tố ngẫu nhiên để tránh hiện tượng cộng hưởng tải).

#### Q31: Lỗi nào được phân loại là Retryable (được phép thử lại) và Non-retryable?
**A:** 
* **Retryable:** Lỗi nghẽn mạng, lỗi API 5xx, lỗi giới hạn cuộc gọi HTTP 429.
* **Non-retryable:** Lỗi sai cú pháp tham số truyền vào (400 Bad Request), lỗi xác thực API Key (401/403 Unauthorized). Các lỗi này sẽ kích hoạt Fallback ngay lập tức.

#### Q32: Graceful Degradation (Hạ cấp êm ái) 3 tầng của hệ thống là gì?
**A:** 
* **Tầng 1 (Chính):** Gọi trực tiếp Bedrock sinh phản hồi thời gian thực.
* **Tầng 2 (Dự phòng 1):** Lấy bản tóm tắt tĩnh đã được lưu trữ sẵn trong PostgreSQL của sản phẩm đó.
* **Tầng 3 (Dự phòng cuối):** Trả về thông điệp mặc định thân thiện: *"Product review summary is temporarily unavailable. Please try again in a few moments."*

#### Q33: Tại sao chúng ta cần bọc parse JSON (`json.loads`) trong hàm validate arguments của tool-use?
**A:** LLM đôi khi sinh ra chuỗi JSON bị lỗi cú pháp (thiếu dấu ngoặc, sai định dạng). Nếu gọi `json.loads` trực tiếp không có `try-except JSONDecodeError`, gRPC server sẽ bị crash đột ngột.

#### Q34: Sự khác biệt giữa thông báo `UNVERIFIED_SUMMARY_MESSAGE` và `FALLBACK_SUMMARY_MESSAGE` là gì?
**A:** 
* `UNVERIFIED_SUMMARY_MESSAGE` trả về khi **nội dung bị Judge phát hiện ảo giác/không trung thực**.
* `FALLBACK_SUMMARY_MESSAGE` trả về khi **hạ tầng LLM gặp sự cố kỹ thuật** (sập mạng, hết rate limit, timeout).

#### Q35: Làm thế nào để giả lập và tiêm lỗi (Failure Injection) phục vụ kiểm thử resilience?
**A:** Kích hoạt Feature Flag `llmRateLimitError` qua flagd hoặc gọi API phụ `POST /inject` trên cổng 8086 để ép server giả lập mã lỗi 429 hoặc timeout.

#### Q36: Circuit Breaker có tự phục hồi (recover) khi API LLM hoạt động bình thường trở lại không?
**A:** Có. Ở trạng thái HALF-OPEN, nếu các cuộc gọi LLM thử nghiệm thành công liên tiếp, CB sẽ tự động chuyển về trạng thái CLOSED và mở lại luồng phục vụ chính.

#### Q37: Lợi ích của cơ chế "Graceful Shutdown" sử dụng `server.stop(grace=5.0)` là gì?
**A:** Tránh việc ngắt kết nối đột ngột làm hỏng trải nghiệm của người dùng đang trong quá trình nhận phản hồi RAG, đồng thời cho phép gRPC server đóng các connection pool sạch sẽ.

#### Q38: Tại sao gRPC Health Check phải chuyển thành `NOT_SERVING` trước khi shutdown 5 giây?
**A:** Để báo hiệu cho Kubernetes Ingress Controller hoặc AWS Load Balancer ngừng định tuyến các request mới vào pod này, giúp pod hạ tải an toàn trước khi tắt hoàn toàn.

#### Q39: Cơ chế auto-reconnection giải quyết bài toán gì tại thời điểm startup?
**A:** Tránh hiện tượng CrashLoopBackOff của Pod Kubernetes. Nếu PostgreSQL hoặc Redis khởi động chậm hơn ứng dụng vài giây, app server không có retry kết nối sẽ bị crash lập tức và đi vào vòng lặp restart vô tận.

#### Q40: Thuật toán Circuit Breaker được triển khai dựa trên thư viện nào hay tự viết?
**A:** Triển khai tùy biến bằng cách đọc/ghi trực tiếp trạng thái lên Redis (lưu các key `cb:state`, `cb:failure_count`, `cb:last_state_change`), đảm bảo mã nguồn nhẹ và kiểm soát hoàn toàn logic.

#### Q41: Tại sao không dùng Circuit Breaker mặc định của Service Mesh (như Istio)?
**A:** Circuit Breaker ở tầng ứng dụng (Application-level CB) giúp kiểm soát chi tiết ngữ cảnh lỗi (ví dụ: chỉ ngắt mạch khi lỗi LLM, nhưng vẫn cho phép các API đọc review nghiệp vụ thông thường hoạt động).

#### Q42: Làm thế nào để kiểm soát "Blast Radius" (Phạm vi ảnh hưởng) khi tiêm lỗi?
**A:** Chỉ tiêm lỗi hoặc áp dụng cơ chế ngắt mạch trên phạm vi hẹp (ví dụ: theo từng `product_id` hoặc `model_id` cụ thể) thay vì ngắt toàn bộ dịch vụ.

#### Q43: Hàm `is_fallback_override_active()` có vai trò gì trong cơ chế tự dập sự cố?
**A:** Nó là cổng kiểm tra xem AIOps Engine có đang yêu cầu kích hoạt luồng khẩn cấp hay không thông qua việc đọc Redis key `product_reviews:fallback_override`.

#### Q44: Làm thế nào để chống hiện tượng nghẽn luồng khi kết nối DB PostgreSQL bị timeout?
**A:** Thiết lập tham số `connect_timeout` và `statement_timeout` trong connection string Postgres ở mức ngắn (ví dụ: 2-3 giây) kết hợp với pool size giới hạn.

#### Q45: Việc ghi log lỗi (error logging) trong luồng fallback cần lưu ý gì về bảo mật?
**A:** Tuyệt đối không ghi thông tin thô của request chứa dữ liệu nhạy cảm của khách hàng (PII) hoặc token xác thực API Key vào log file.

#### Q46: Tại sao luồng fallback PostgreSQL Cache lại không ghi nhận dữ liệu mới vào cache?
**A:** Vì dữ liệu dự phòng (static summary) là dữ liệu cũ, không phải kết quả sinh thời gian thực từ LLM hiện tại, nên việc ghi đè ngược lại cache sẽ làm sai lệch tính cập nhật của dữ liệu.

#### Q47: Circuit Breaker có bảo vệ hệ thống khỏi việc tăng chi phí đột biến khi bị spam không?
**A:** Có. Khi bị spam dẫn đến lỗi rate limit liên tục, CB mở ra (OPEN) giúp chặn đứng các request gửi tới API tính phí của Bedrock, chuyển sang trả về dự phòng miễn phí.

#### Q48: Làm thế nào để ứng dụng tự động kiểm tra lại kết nối với Redis?
**A:** Định kỳ chạy lệnh `ping()` của Redis client trong tiến trình nền hoặc kiểm tra trước mỗi luồng đọc/ghi cache.

#### Q49: Làm thế nào để cấu hình thời gian chờ (timeout) cho cuộc gọi AWS Bedrock?
**A:** Cấu hình tham số `connect_timeout` và `read_timeout` trong đối tượng `botocore.config.Config` khi khởi tạo client boto3.

#### Q50: Hệ thống xử lý thế nào khi cả 3 tầng (LLM, DB Cache, Default Message) đều thất bại?
**A:** Trường hợp xấu nhất này, ứng dụng bắt ngoại lệ cuối cùng và trả về mã lỗi gRPC tiêu chuẩn `INTERNAL` kèm thông điệp khẩn cấp ngắn gọn để không làm trắng trang storefront.

---

## Phần 3: Giám Sát, Telemetry & HTTP Sidecar Server (Câu 51 - 75)

#### Q51: Tại sao dịch vụ `product-reviews` cần chạy thêm một HTTP server phụ trên cổng 8086?
**A:** Vì dịch vụ chính giao tiếp qua gRPC (cổng 8085). Cổng HTTP phụ 8086 hoạt động như một Sidecar admin interface phục vụ các yêu cầu giám sát, kiểm thử, lấy vết telemetry (trace) và bơm lỗi mà không làm ảnh hưởng đến cổng nghiệp vụ chính.

#### Q52: Làm thế nào để lấy thông tin vết (Trace Log) của một request RAG cụ thể?
**A:** Client hoặc API Gateway gửi request `GET /trace/<trace_id>` tới cổng 8086 để trích xuất JSON trace đầy đủ được lưu trữ trong Redis.

#### Q53: Dữ liệu trace lưu trữ trong Redis có thời gian sống (TTL) là bao nhiêu và tại sao?
**A:** TTL được đặt là **24 giờ**. Đây là khoảng thời gian tối ưu đủ để đội vận hành (SRE/AIOps) phân tích, debug các sự cố trong ngày và tự động giải phóng dung lượng bộ nhớ Redis sau đó.

#### Q54: Bộ lọc PII (Sanitization) hoạt động như thế nào trước khi trả về dữ liệu trace qua API?
**A:** Mọi thông tin nhạy cảm của khách hàng như tên người dùng (`username`), địa chỉ email, số điện thoại, hoặc token API trong JSON trace sẽ được che đi bằng các ký tự mã hóa (ví dụ: `[REDACTED]`) để bảo vệ quyền riêng tư.

#### Q55: Sự khác biệt giữa OpenTelemetry Trace và Custom Prometheus Metrics trong dự án là gì?
**A:** Trace ghi nhận chi tiết hành trình của một request đơn lẻ (micro-level); Metrics ghi nhận số liệu thống kê tổng hợp của toàn hệ thống (macro-level) như tổng số request, tỷ lệ lỗi, số lần fallback.

#### Q56: Chỉ số counter `app_ai_fallback_total` có các nhãn (labels) nào?
**A:** 
* `source`: Nguồn kích hoạt (`"redis_override"`, `"rate_limit"`, `"timeout"`, `"circuit_breaker"`).
* `error`: Loại lỗi (`"forced"`, `"429"`, `"timeout"`, `"500"`).

#### Q57: Làm thế nào để theo dõi luồng đi của request xuyên suốt nhiều dịch vụ (Distributed Tracing)?
**A:** Sử dụng cơ chế truyền `traceparent` (W3C Trace Context) qua gRPC metadata. Server trích xuất traceparent này để liên kết các span của `frontend` ➜ `product-reviews` ➜ `product-catalog` trong Jaeger.

#### Q58: Cấu hình cổng HTTP phụ sử dụng framework nào trong Python?
**A:** Sử dụng Python HTTP server tích hợp sẵn (`http.server`) chạy trên luồng nền (background thread) để đảm bảo không làm nghẽn hoặc ảnh hưởng hiệu năng của gRPC server chính chạy trên ThreadPool.

#### Q59: Endpoint `POST /replay` hoạt động như thế nào trong kịch bản AIOps?
**A:** Nó nhận các kịch bản mô phỏng từ bên ngoài, tự động thực thi chuỗi tự dập lỗi và ghi nhận log kiểm toán (audit log) có cấu trúc giúp AIOps Engine verify tính đúng đắn.

#### Q60: Ghi nhận log kiểm toán (Audit Log) sử dụng định dạng file nào và tại sao?
**A:** Định dạng **JSON Lines (.jsonl)**. Mỗi dòng là một đối tượng JSON độc lập, giúp việc đọc và phân tích log bằng các công cụ tự động hoặc script python cực kỳ dễ dàng mà không cần load toàn bộ file vào bộ nhớ.

#### Q61: Các trường thông tin bắt buộc trong mỗi bản ghi Audit Log của closed-loop là gì?
**A:** `run_id` (định danh lượt chạy), `timestamp` (thời gian dạng ISO UTC), `phase` (pha chạy: trigger/action/verify/rollback/recover), `status` (trạng thái: FIRED/OK/FAIL), và `detail` (mô tả chi tiết).

#### Q62: Tại sao không dùng Prometheus Client mặc định mà phải cấu hình Custom Exporter?
**A:** Để tùy biến đẩy các chỉ số đặc thù về AI (như token usage, cost, judge agreement rate) lên Prometheus Server của dự án.

#### Q63: Làm thế nào để kiểm tra sức khỏe (Health Check) của gRPC server từ bên ngoài?
**A:** Sử dụng công cụ `grpc-health-probe` gọi dịch vụ `grpc.health.v1.Health` trên cổng 8085. Nếu trả về `SERVING` tức là server khỏe mạnh.

#### Q64: Việc ghi nhận metric `app_ai_fallback_total` có làm tăng đáng kể tài nguyên hệ thống không?
**A:** Không. Ghi nhận metric chỉ là thao tác tăng số đếm (in-memory counter increment) cực kỳ nhẹ, không tốn I/O đĩa.

#### Q65: Làm thế nào để cấu hình Jaeger Agent endpoint trong dịch vụ?
**A:** Thiết lập thông qua biến môi trường `OTEL_EXPORTER_OTLP_ENDPOINT` trỏ tới collector agent của Jaeger (ví dụ: `http://localhost:4317`).

#### Q66: Telemetry có tự động ghi nhận số lượng Input và Output tokens của cuộc gọi Bedrock không?
**A:** Có. Hệ thống trích xuất thông tin này từ trường `usage` của response API Bedrock và ghi vào span attributes của OpenTelemetry.

#### Q67: Có nên ghi log kiểm toán sang PostgreSQL thay vì file local không?
**A:** Ghi ra file local dạng JSON Lines là phương án chuẩn cloud-native (lưu log ra stdout/file để các log forwarder như FluentBit/Logstash gom về trung tâm), giúp tránh ghi đồng bộ làm chậm ứng dụng.

#### Q68: Làm thế nào để kiểm tra xem cổng 8086 hoạt động tốt hay không?
**A:** Gửi request `GET /health` hoặc `GET /trace/non-exist-id` để kiểm tra phản hồi HTTP 200/404 từ cổng 8086.

#### Q69: Tại sao log kiểm toán (audit log) cần chứa trường `run_id` dạng UUID?
**A:** Để phân biệt rõ ràng dữ liệu của các đợt kiểm thử hoặc sự cố khác nhau khi đọc tệp log tích lũy.

#### Q70: Làm thế nào để che giấu các thông tin nhạy cảm trong SQL query khi sinh trace?
**A:** OpenTelemetry SQL database client tự động tham số hóa (parameterize) các câu lệnh SQL, ẩn đi các giá trị truyền vào thực tế trong trace span.

#### Q71: Hệ thống làm thế nào để đo lường độ trễ mạng chính xác của cuộc gọi LLM?
**A:** Đo thời gian bắt đầu và kết thúc của span bọc quanh hàm `converse()` (AWS Bedrock) hoặc gọi OpenAI API.

#### Q72: Tại sao metrics của dịch vụ cần được hiển thị trên Grafana Dashboard?
**A:** Để giúp đội vận hành SRE quan sát trực quan biểu đồ xu hướng lỗi, lượng tiền tiêu thụ theo thời gian thực và phát hiện bất thường ngay lập tức.

#### Q73: Prometheus Server lấy dữ liệu metrics từ dịch vụ bằng cơ chế nào?
**A:** Cơ chế Pull (Scrape). Prometheus định kỳ gửi HTTP request tới endpoint `/metrics` của dịch vụ để thu thập số liệu.

#### Q74: Làm thế nào để ngăn chặn việc ghi log quá nhiều làm tràn đĩa cứng (log bloating)?
**A:** Cấu hình log rotation (giới hạn dung lượng file log tối đa và số lượng file lưu trữ cũ) trong cấu hình logging của Python.

#### Q75: Telemetry có ghi nhận kết quả đánh giá (approved/unverified) của Judge không?
**A:** Có. Trường `verdict` hoặc `fidelity_score` được ghi trực tiếp làm thuộc tính của trace span để phân tích chất lượng.

---

## Phần 4: Đánh Giá Chất Lượng LLM-as-a-Judge & Rubrics (Câu 76 - 100)

#### Q76: "LLM-as-a-Judge" là gì và tại sao nó lại được chọn để đánh giá tóm tắt sản phẩm?
**A:** LLM-as-a-Judge sử dụng một mô hình ngôn ngữ lớn làm giám khảo để chấm điểm chất lượng câu trả lời của mô hình khác. Nó được chọn vì việc đánh giá tóm tắt (summary) mang tính ngữ nghĩa cao, các công cụ so khớp chuỗi truyền thống (như ROUGE, BLEU) không đánh giá được lỗi ảo giác tinh vi.

#### Q77: Bộ Rubrics đánh giá Fidelity gồm những tiêu chí cốt lõi nào?
**A:** 
1. **Faithfulness (Tính trung thực):** Claims phải bắt nguồn từ reviews gốc.
2. **Aspect Coverage (Độ bao phủ):** Trả lời đúng khía cạnh được hỏi.
3. **Sentiment Alignment (Nhất quán cảm xúc):** Cảm xúc phù hợp với rating thực tế.

#### Q78: Cách dán nhãn của LLM Judge đối với từng claim là gì?
**A:** 
* `supported`: Tuyên bố đúng, có bằng chứng review.
* `unsupported`: Tuyên bố tự vẽ ra, không có bằng chứng.
* `contradicted`: Tuyên bố mâu thuẫn trực tiếp với reviews.

#### Q79: Chỉ số "Agreement Rate" (Tỷ lệ đồng thuận) được tính như thế nào?
**A:** Bằng số ca LLM Judge chấm trùng khớp nhãn với con người chia cho tổng số ca đánh giá (10 ca gán nhãn thủ công) nhân với 100%.

#### Q80: Ngưỡng nghiệm thu (Quality Gate) tối thiểu của Agreement Rate là bao nhiêu?
**A:** Tối thiểu phải đạt **80%** trở lên.

#### Q81: Tại sao chúng ta cần bẻ nhỏ bản tóm tắt thành từng tuyên bố đơn lẻ (Claim-level) để đánh giá?
**A:** Đánh giá cấp độ claim (Claim-level evaluation) giúp tránh việc LLM Judge chấm điểm cảm tính toàn bộ đoạn văn, giúp chỉ ra chính xác câu nào bị lỗi và tăng tính thuyết phục của kết quả.

#### Q82: "Self-evaluation bias" là gì và làm thế nào để giảm thiểu nó?
**A:** Là hiện tượng một mô hình tự chấm điểm cho chính câu trả lời của nó thường có xu hướng chấm nới tay (bias cao). Giảm thiểu bằng cách sử dụng các mô hình khác nhau hoặc của các nhà cung cấp khác nhau cho vai trò Candidate và Judge (ví dụ: Candidate dùng Nova Lite, Judge dùng Nova Micro).

#### Q83: Làm thế nào hệ thống xử lý các câu trả lời bị Judge dán nhãn là `unsupported` hoặc `contradicted` ở môi trường production?
**A:** Hệ thống sẽ ngay lập tức kích hoạt luồng **Fail-Closed**, ẩn bản tóm tắt đó đi và trả về tin nhắn an toàn: `The summary cannot be verified. Please try again later.`.

#### Q84: prompt hệ thống (system prompt) của Judge được thiết kế như thế nào để đảm bảo đầu ra chuẩn?
**A:** Prompt ép mô hình Judge chỉ được phép trả về duy nhất định dạng JSON chứa danh sách các claims, nhãn tương ứng (supported/unsupported/contradicted) và lý do giải thích, cấm trả về văn bản tự do.

#### Q85: Tại sao Judge lại cần thông tin `trusted_derived_review_facts` (số review, điểm số min/max)?
**A:** Để làm dữ liệu kiểm chứng cứng (ground truth facts), giúp Judge đối chiếu dễ dàng khi summary viết các câu khẳng định chung chung như "không có ai chê sản phẩm này" hay "điểm đánh giá toàn 5 sao".

#### Q86: Thiết kế của Judge tại Runtime và Offline/Hybrid Evaluator khác nhau như thế nào?
**A:** Runtime Judge sử dụng schema tối giản để giảm latency tối đa phục vụ người dùng thời gian thực. Hybrid Evaluator (`eval_fidelity.py`) sử dụng prompt phức tạp hơn để tính toán thêm các điểm số chi tiết phục vụ báo cáo chất lượng offline.

#### Q87: Việc gọi Judge trực tuyến (online) có làm tăng đáng kể độ trễ phản hồi không?
**A:** Có. Nó làm tăng thêm khoảng 1.0 - 1.5 giây cho cuộc gọi thứ hai. Do đó, việc kích hoạt **LLM Response Caching** là tối quan trọng để triệt tiêu độ trễ này ở các request sau.

#### Q88: Tập dữ liệu `human_labeled_cases.jsonl` được tạo ra như thế nào?
**A:** Thành viên nhóm AIE1 tự chọn lọc 10 câu hỏi và câu trả lời mẫu, đối chiếu thủ công với database review và tự gán nhãn supported/unsupported để làm tập đối sánh chuẩn (Ground Truth).

#### Q89: Điều gì xảy ra nếu định dạng JSON trả về từ Judge bị lỗi cú pháp?
**A:** Hệ thống sẽ tự động thử lại (retry) tối đa 3 lần. Nếu vẫn lỗi, hệ thống trả về thông báo lỗi thân thiện: `The AI is busy right now. Please try again later.`.

#### Q90: Tại sao không nên đặt một ngưỡng điểm (threshold) cứng cố định cho chất lượng tóm tắt?
**A:** Để tránh việc hệ thống bị "học tủ" (overfitting) trên tập dữ liệu kiểm thử. Việc đánh giá dựa trên tập ca ẩn của dự án sẽ phản ánh chính xác chất lượng thực tế.

#### Q91: Làm thế nào để Judge nhận diện được các câu hỏi không thể trả lời (Unanswerable)?
**A:** Khi thông tin review và mô tả sản phẩm trống hoặc không liên quan đến câu hỏi, Judge mong đợi Candidate trả về mã `NO_INFO` hoặc "không có thông tin", nếu Candidate tự bịa thông tin sẽ bị chấm `unsupported`.

#### Q92: Rubrics có kiểm tra lỗi rò rỉ prompt hệ thống (system prompt leak) không?
**A:** Có. Bộ lọc đầu ra (Output Guardrail) quét kết quả để phát hiện các từ khóa nhạy cảm liên quan đến prompt hệ thống trước khi trả về.

#### Q93: Tại sao Judge Nova Micro lại được chọn thay vì gpt-4o?
**A:** Nova Micro có tốc độ phản hồi cực nhanh, chi phí siêu rẻ ($0.035 / triệu tokens), hoàn toàn đáp ứng tốt việc phân tích cú pháp logic đơn giản tại runtime.

#### Q94: Làm thế nào để cập nhật hoặc thay đổi Rubrics đánh giá?
**A:** Cập nhật lại chuỗi prompt định nghĩa trong file `guardrails/evaluator.py` hoặc file cấu hình prompt tương ứng của dịch vụ.

#### Q95: Việc đánh giá độ trung thực có áp dụng cho ngôn ngữ tiếng Việt không?
**A:** Có. Hệ thống prompt của Judge được thiết kế hỗ trợ đa ngôn ngữ, phân tích ngữ nghĩa chính xác cho cả tiếng Anh và tiếng Việt.

#### Q96: Tại sao Judge không tự quyết định biến boolean `approved` mà ứng dụng phải tự tính?
**A:** Để tránh việc mô hình Judge bị mâu thuẫn logic (ví dụ: liệt kê claims có claim `unsupported` nhưng ở dưới lại gắn cờ `approved = True`). Ứng dụng tự duyệt dựa trên nhãn claims đảm bảo tính nhất quán 100%.

#### Q97: Có cần thiết phải lưu trữ log lịch sử chấm điểm của Judge không?
**A:** Rất cần thiết. Log này được ghi vào bảng kiểm toán hoặc file log để giám sát tỷ lệ ảo giác của mô hình theo thời gian và cải tiến prompt.

#### Q98: Sự khác biệt giữa lỗi "hallucination" và lỗi "contradicted" là gì?
**A:** 
* `hallucination` (unsupported) là thông tin tự vẽ ra, không có trong nguồn.
* `contradicted` là thông tin nói ngược lại hoàn toàn với những gì reviews gốc viết (ví dụ: review chê pin yếu nhưng summary viết pin trâu).

#### Q99: Làm thế nào để đánh giá tính nhất quán cảm xúc (Sentiment Alignment)?
**A:** So sánh phân tích cảm xúc của bản tóm tắt với tỷ lệ phân bổ sao (rating) của sản phẩm trong database (ví dụ: sản phẩm có 90% đánh giá 1 sao thì bản tóm tắt không được mang sắc thái tích cực).

#### Q100: Tại sao Quality Gate yêu cầu phải chạy tự động qua `make eval-mandate14`?
**A:** Để đảm bảo tính tái tạo (reproducibility) của kết quả đo đạc. Mentor hoặc bất kỳ kỹ sư nào trong dự án đều có thể tự chạy lệnh này để kiểm chứng các con số cam kết chất lượng mà không cần thao tác thủ công.
