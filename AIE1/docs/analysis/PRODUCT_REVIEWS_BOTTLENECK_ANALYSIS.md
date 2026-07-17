# Báo cáo Phân tích Điểm nghẽn Dịch vụ Product Reviews

Tài liệu này tổng hợp chi tiết các điểm nghẽn hiệu năng, độ trễ, và rủi ro vận hành trong luồng xử lý của dịch vụ Product Reviews. Các điểm nghẽn được phân loại theo mức độ ảnh hưởng, độ phức tạp thuật toán (Big O), số lượng vòng lặp, và độ khó thực hiện để hỗ trợ việc đưa ra quyết định đánh đổi (tradeoff).

---

## 1. Bảng So sánh & Đánh giá Mức độ Ưu tiên (Priority Matrix)

| # | Điểm nghẽn (Bottleneck) | Vòng lặp & Độ phức tạp hiện tại | Sau khi tối ưu | Mức độ ảnh hưởng | Mức độ ưu tiên | Trạng thái |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **Không sử dụng DB Connection Pool** | $O(Q \times C_{\text{connect}})$ lần bắt tay TCP/SSL | $O(1)$ tái sử dụng kết nối | Nghiêm trọng | **P0 (Khẩn cấp)** | **Đã triển khai** |
| 2 | **gRPC Thread Pool quá nhỏ (`max_workers=10`)** | $O(1)$ nghẽn hàng đợi (Queue Block) | $O(1)$ xử lý đồng thời thực thụ | Nghiêm trọng | **P0 (Khẩn cấp)** | **Đã triển khai** |
| 3 | **Thiếu Timeout gRPC gọi Product Catalog** | $O(\infty)$ nếu Catalog Service bị treo | $O(\text{timeout})$ ngắt sớm | Cao | **P0 (Khẩn cấp)** | **Đã triển khai** |
| 4 | **Thiếu Timeout cho AWS Bedrock Client** | $O(\text{default } 60\text{s})$ chờ phản hồi | $O(\text{timeout } 3\text{s}\text{-}10\text{s})$ | Cao | **P1 (Cao)** | **Đã triển khai** |
| 5 | **Ghi Log đồng bộ trong vòng lặp đọc Reviews** | **1 vòng lặp:** $O(N)$ log I/O tuần tự | $O(1)$ log tổng thể (không lặp) | Trung bình | **P1 (Cao)** | **Đã triển khai** |
| 6 | **Quét Regex Guardrail tuần tự mọi Review** | **1 vòng lặp:** $O(N \times R \times L)$ với $R$ regex, độ dài $L$ | $O(1)$ amortized (dùng Cache) | Trung bình | **P2 (Trung bình)**| **Tạm hoãn để tradeoff cùng LLM Cache** |
| 7 | **Xử lý tuần tự các Tool Calls (OpenAI)** | **1 vòng lặp:** $O(\sum D_i)$ (tổng độ trễ các tools) | $O(\max D_i)$ (chạy song song) | Thấp | **P2 (Trung bình)**| **Đã triển khai** |

*Chú thích:* 
* $N$: Số lượng reviews của một sản phẩm.
* $R$: Số lượng mẫu Regex cần quét (28+ patterns).
* $L$: Chiều dài trung bình của nội dung văn bản review.
* $D_i$: Độ trễ mạng của tool call thứ $i$.
* $Q$: Số lượng truy vấn tới cơ sở dữ liệu.
* $C_{\text{connect}}$: Chi phí thiết lập kết nối (bắt tay TCP, TLS/SSL, xác thực).

---

## 2. Phân tích Chi tiết & Giải pháp cho Điểm nghẽn Thuật toán (Sắp xếp theo mức độ nghiêm trọng giảm dần)

### 2.1. Kết nối Database không có Connection Pool (P0 - Nghiêm trọng)
* **Ngữ cảnh hệ thống & Khái niệm (Database Connection Starvation / Overhead):** 
  Dịch vụ Product Reviews nhận hàng trăm yêu cầu gRPC đồng thời từ người dùng. Khi không dùng pool, mỗi truy vấn SQL buộc phải thiết lập một kết nối vật lý mới tới Postgres. Việc này tạo ra một "cơn bão kết nối" (connection storm) làm tiêu hao CPU của cơ sở dữ liệu cho quá trình bắt tay (handshake) và nhanh chóng chạm ngưỡng giới hạn kết nối tối đa (`max_connections`) của hệ quản trị cơ sở dữ liệu, khiến toàn bộ các yêu cầu đọc ghi tiếp theo bị từ chối thẳng thừng (starvation).
* **Mã nguồn liên quan:** Khởi tạo kết nối trong [database.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/database.py).
* **Số lượng vòng lặp:** Không có vòng lặp nội bộ, thực thi tuần tự cho mỗi câu query $Q$.
* **Độ phức tạp hiện tại:** 
  $$O(Q \times C_{\text{connect}})$$
  Với mỗi truy vấn $Q$ tới DB, hệ thống tốn chi phí thiết lập kết nối $C_{\text{connect}}$ (bắt tay TCP, TLS, xác thực).
* **Sau khi tối ưu:** Độ phức tạp giảm về $O(1)$ (tận dụng kết nối sẵn có trong pool bộ nhớ).
* **Hệ quả khi tải cao:** Gây nghẽn cổ chai latency tại bước kết nối DB và nhanh chóng làm cạn kiệt tài nguyên DB connection limit.
* **Giải pháp cụ thể:** Sử dụng connection pool luồng an toàn bằng `psycopg2.pool.ThreadedConnectionPool`.
  > [!WARNING]
  > **Bẫy triển khai #1 — Thiếu commit/rollback khi chuyển sang Pool:**
  > Code hiện tại dùng `with psycopg2.connect() as conn:` — cú pháp `with` này tự động commit khi thành công và rollback khi exception. Khi chuyển sang `db_pool.getconn()`, cơ chế auto-commit **không còn hoạt động nữa**. Nếu không thêm `connection.commit()` và `connection.rollback()` thủ công, kết nối trả về pool sẽ nằm trong trạng thái transaction lỗi, khiến các request sau mượn lại kết nối đó gặp lỗi `InFailedSqlTransaction`.

  > [!WARNING]
  > **Bẫy triển khai #2 — Xung đột giữa `maxconn` và `max_workers`:**
  > Nếu gRPC Thread Pool được tăng lên `max_workers=50` (Mục 3.1) nhưng DB Connection Pool chỉ có `maxconn=20`, khi hơn 20 request đồng thời cần truy vấn DB, các thread còn lại sẽ bị block chờ mượn kết nối. Cần điều chỉnh `maxconn` tối thiểu bằng `30` để tránh nghẽn cổ chai mới.

  * *Mã nguồn đề xuất (đã bổ sung commit/rollback):*
    ```python
    from psycopg2.pool import ThreadedConnectionPool
    
    # Khởi tạo một pool toàn cục duy nhất
    # LƯU Ý: maxconn cần phối hợp với max_workers của gRPC server
    db_pool = ThreadedConnectionPool(minconn=5, maxconn=30, dsn=db_connection_str)
    
    def fetch_product_reviews_from_db(request_product_id):
        connection = None
        try:
            # Mượn kết nối từ pool thay vì tạo mới
            connection = db_pool.getconn()
            with connection.cursor() as cursor:
                query = "SELECT username, description, score FROM reviews.productreviews WHERE product_id = %s"
                cursor.execute(query, (request_product_id, ))
                records = cursor.fetchall()
            connection.commit()  # BẮT BUỘC: commit thủ công khi dùng pool
            return records
        except Exception as e:
            if connection is not None:
                connection.rollback()  # BẮT BUỘC: rollback khi có lỗi
            raise e
        finally:
            if connection is not None:
                # Đảm bảo trả kết nối về pool trong khối finally
                db_pool.putconn(connection)
    ```

---

### 2.2. Ghi Log đồng bộ trong vòng lặp đọc Reviews (P1 - Trung bình)
* **Ngữ cảnh hệ thống & Khái niệm (Synchronous Log Blocking / Disk I/O Bottleneck):**
  Trong Python, thư viện logging mặc định ghi log đồng bộ (ghi trực tiếp xuống ổ đĩa cứng hoặc bộ đệm console stdout). Khi luồng thực thi ghi log chi tiết cho từng đánh giá của một sản phẩm có hàng trăm review, luồng CPU xử lý request sẽ phải dừng lại đợi đĩa cứng ghi xong dữ liệu mới chạy tiếp. Điều này vô tình chuyển đổi một tác vụ đọc bộ nhớ/mạng rất nhanh thành một tác vụ bị nghẽn bởi tốc độ đọc ghi đĩa cứng vật lý (Disk I/O Bottleneck).
* **Mã nguồn liên quan:** Vòng lặp `for row in records` ở dòng 286-292 trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L286-L292).
* **Số lượng vòng lặp:** 1 vòng lặp tuần tự duyệt qua $N$ bản ghi reviews lấy từ DB.
* **Độ phức tạp hiện tại:** 
  $$O(N \times I/O_{\text{sync}})$$
  Với mỗi dòng review, hệ thống gọi `logger.info` để format chuỗi và ghi ra console/standard output một cách đồng bộ. Khi $N$ lớn, chi phí I/O đồng bộ này sẽ khóa chặt thread xử lý.
* **Sau khi tối ưu:** Độ phức tạp giảm về $O(1)$ thao tác I/O cho cả request bằng cách chỉ ghi log 1 dòng tổng hợp bên ngoài vòng lặp.
* **Hệ quả khi tải cao:** Gây tắc nghẽn I/O hệ thống file/console, tăng thời gian phản hồi của API đọc review.
* **Giải pháp cụ thể:** Hạ cấp độ log trong vòng lặp thành `DEBUG` (hoặc loại bỏ hoàn toàn) để tránh ghi đĩa ở môi trường Production.
  * *Mã nguồn đề xuất:*
    ```python
    def get_product_reviews(request_product_id):
        # ...
        for row in records:
            # Thay đổi INFO -> DEBUG
            logger.debug(f"  username: {row[0]}, description: {row[1]}, score: {str(row[2])}")
            product_reviews.product_reviews.add(...)
        
        # Thêm log tổng hợp bên ngoài vòng lặp
        logger.info(f"Retrieved {len(records)} reviews for product_id: {request_product_id}")
        return product_reviews
    ```

---

### 2.3. Quét Regex Guardrail tuần tự cho mọi Review (P2 - Thấp)
* **Ngữ cảnh hệ thống & Khái niệm (O(N) CPU Bound / Inline Security Scan Overhead):**
  Để ngăn chặn tấn công Prompt Injection lưu trữ trong cơ sở dữ liệu (Stored Prompt Injection - kẻ xấu cố tình viết câu đánh giá chứa mã lệnh hệ thống hòng chiếm quyền kiểm soát LLM khi LLM đọc review), hệ thống phải quét nội dung review trước khi truyền vào LLM. Tuy nhiên, việc quét trực tiếp (inline) tuần tự toàn bộ danh sách review bằng các mẫu regex phức tạp ngay trên luồng sinh câu trả lời của client biến dịch vụ từ I/O-bound thành CPU-bound rất nặng, gây tăng trễ không đáng có.
* **Mã nguồn liên quan:** Hàm [normalize_reviews_for_context](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L136) gọi [check_input](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/guardrails/input_filter.py#L200).
* **Số lượng vòng lặp:** 1 vòng lặp tuần tự duyệt qua toàn bộ $N$ reviews được lấy lên từ database.
* **Độ phức tạp hiện tại:** 
  $$O(N \times R \times L)$$
  Với mỗi review trong số $N$ reviews, mã nguồn thực hiện quét toàn bộ $R$ regex patterns (28+ mẫu). Với mỗi pattern, thuật toán thực hiện tìm kiếm trên chuỗi độ dài $L$. Đây là tác vụ ngốn CPU (CPU-bound) cực kỳ lớn khi một sản phẩm hot có hàng trăm hoặc hàng nghìn review ($N \gg 100$).
* **Sau khi tối ưu:** Độ phức tạp giảm xuống còn $O(N)$ (nếu dùng Cache chỉ tốn $O(1)$ lookup trong bộ nhớ cho mỗi review đã quét qua), hoặc giảm về $O(1)$ trên luồng đọc nếu quét khi ghi.
* **Hệ quả khi tải cao:** CPU tăng cao đột biến, kéo dài thời gian phản hồi của dịch vụ AI RAG.
* **Trạng thái Trade-off (Tạm hoãn):** 
  > [!NOTE]
  > **Tạm hoãn để phối hợp thiết kế cùng Tầng Caching Dịch Vụ ([PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/analysis/PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md)):**
  * Sẽ được cân nhắc tradeoff kỹ hơn giữa **Phương án A: Caching trên RAM (lru_cache Python hoặc Redis)** và **Phương án B: Thêm cột `is_safe` vào DB** (chạy quét 1 lần duy nhất lúc ghi review mới để đưa trễ luồng đọc về hẳn $O(1)$ không tốn RAM).

---

### 2.4. Xử lý tuần tự các Tool Calls trong luồng OpenAI (P2 - Thấp)
* **Ngữ cảnh hệ thống & Khái niệm (Sequential Network Blocking / Latency Accumulation):**
  Trong kiến trúc RAG, LLM có thể yêu cầu lấy nhiều thông tin độc lập từ các hệ thống khác nhau (ví dụ: vừa lấy thông tin catalog vừa lấy review). Do các cuộc gọi này độc lập về dữ liệu, việc gọi tuần tự (chờ xong tool này mới gọi tool kia) làm tích lũy độ trễ mạng (latency accumulation). Việc chạy tuần tự biến tổng thời gian phản hồi thành tổng độ trễ của tất cả các dịch vụ liên kết, làm chậm phản hồi cuối cùng tới khách hàng.
* **Mã nguồn liên quan:** Vòng lặp `for tool_call in tool_calls:` ở dòng 450-476 trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L450-L476).
* **Số lượng vòng lặp:** 1 vòng lặp tuần tự duyệt qua các yêu cầu gọi công cụ (`tool_calls`) từ LLM.
* **Độ phức tạp hiện tại:** 
  $$O\left(\sum_{i=1}^{T} D_i\right)$$
  Trong đó $T$ là số lượng tool gọi (thường $T \le 2$ gồm `fetch_product_reviews` và `fetch_product_info`), $D_i$ là độ trễ thực thi (mạng/DB) của tool thứ $i$. Do xử lý tuần tự, tổng thời gian xử lý là tổng độ trễ của tất cả các tools.
* **Sau khi tối ưu:** Độ phức tạp giảm về $O(\max(D_1, D_2, \dots, D_T))$ (chỉ phụ thuộc vào công cụ phản hồi lâu nhất nhờ cơ chế chạy song song).
* **Hệ quả khi tải cao:** Làm tăng thời gian phản hồi một cách không cần thiết nếu mô hình quyết định gọi đồng thời cả hai công cụ.
* **Giải pháp cụ thể:** Sử dụng thư viện `concurrent.futures.ThreadPoolExecutor` để song song hóa việc thực thi các tool call độc lập và tập hợp kết quả đồng thời.
  > [!WARNING]
  > **Bẫy triển khai #3 — Xử lý biến `raw_reviews_for_judge` và thứ tự `messages` khi song song hóa:**
  > 1. Kết quả của `fetch_product_reviews` sau khi lấy về cần được truyền tiếp qua `normalize_reviews_for_context()` để tạo biến `raw_reviews_for_judge` (dùng cho bước Judge đánh giá). Khi song song hóa, cần đảm bảo biến này được gán đúng từ kết quả của tool `fetch_product_reviews`, không bị ghi đè hoặc bỏ sót bởi kết quả của `fetch_product_info`.
  > 2. Thứ tự các phần tử trong danh sách `messages` ảnh hưởng đến ngữ cảnh mà LLM nhận được. Cần append kết quả tool vào `messages` theo đúng thứ tự `tool_call_id` ban đầu, không phải theo thứ tự hoàn thành ngẫu nhiên của `as_completed`.

  * *Mã nguồn đề xuất:*
    ```python
    from concurrent import futures
    
    # Khi xử lý tool_calls:
    with futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
        future_to_tool = {}
        for tool_call in tool_calls:
            function_args = json.loads(tool_call.function.arguments)
            # Gửi song song các task
            if tool_call.function.name == "fetch_product_reviews":
                future = executor.submit(fetch_product_reviews, product_id=function_args.get("product_id"))
            elif tool_call.function.name == "fetch_product_info":
                future = executor.submit(fetch_product_info, product_id=function_args.get("product_id"))
            future_to_tool[future] = tool_call
            
        # Thu thập kết quả theo thứ tự tool_calls ban đầu (KHÔNG dùng as_completed)
        for future in future_to_tool:
            tool_call = future_to_tool[future]
            result = future.result()
            # Xử lý normalize và gán raw_reviews_for_judge nếu là fetch_product_reviews
            # Append vào messages theo đúng thứ tự...
    ```

---

## 3. Các lỗi nghẽn và Rủi ro Cấu trúc Hạ tầng (Sắp xếp theo mức độ nghiêm trọng giảm dần)

### 3.1. gRPC Thread Pool quá nhỏ (`max_workers=10`) (P0 - Nghiêm trọng)
* **Ngữ cảnh hệ thống & Khái niệm (Thread Pool Starvation / Thread Exhaustion):**
  gRPC Server trong môi trường Python sử dụng một pool gồm các luồng (thread) xử lý để đồng thời tiếp nhận các cuộc gọi API từ client. Vì Python gRPC chạy đồng bộ, mỗi thread sẽ bị giữ chân hoàn toàn trong suốt quá trình chờ LLM phản hồi (I/O Blocked). Khi số thread chỉ giới hạn ở `10`, chỉ cần có 10 người dùng hỏi trợ lý AI đồng thời là toàn bộ thread pool sẽ bị cạn kiệt (starvation), khiến hệ thống không thể phản hồi bất cứ request nào khác, bao gồm cả những tác vụ đọc database thông thường chỉ mất vài mili-giây.
* **Mã nguồn liên quan:** Dòng 598 trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L598).
* **Mô tả:** Khởi tạo gRPC server sử dụng thread pool chỉ có tối đa 10 workers để gánh toàn bộ tác vụ.
* **Hệ quả:** Thường xuyên gây lỗi nghẽn hàng đợi (Queue block) và timeout.
* **Giải pháp cụ thể:** Tăng quy mô Thread Pool bằng cách điều chỉnh tham số `max_workers` khi khởi động gRPC server trong file [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py).
  * *Mã nguồn đề xuất:*
    ```python
    # Thay thế:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    # Thành:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=50))
    ```

### 3.2. Thiếu Timeout gRPC gọi Product Catalog Service (P0 - Nghiêm trọng)
* **Ngữ cảnh hệ thống & Khái niệm (Unbounded Blocking Call / Cascade Failure):**
  Trong hệ thống phân tán (Microservices), lỗi lan truyền (cascade failure) là rủi ro nguy hiểm nhất. Dịch vụ Product Reviews phụ thuộc trực tiếp vào Product Catalog Service để lấy thông tin sản phẩm. Nếu Catalog Service bị treo mạng hoặc quá tải phản hồi cực chậm, cuộc gọi gRPC không có timeout sẽ khóa chặt thread xử lý của dịch vụ ta vô thời hạn. Lỗi từ Catalog Service sẽ trực tiếp lây lan và làm treo đứng hoàn toàn dịch vụ Product Reviews.
* **Mã nguồn liên quan:** Hàm [fetch_product_info](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L549).
* **Mô tả:** Cuộc gọi `product_catalog_stub.GetProduct` không cấu hình tham số `timeout`.
* **Hệ quả:** Dễ dàng làm treo đứng toàn bộ server nếu Catalog Service bị chậm.
* **Giải pháp cụ thể:** Thiết lập tham số `timeout` rõ ràng vào cuộc gọi gRPC client trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py).
  * *Mã nguồn đề xuất:*
    ```python
    def fetch_product_info(product_id):
        try:
            # Thêm timeout=3.0 giây
            product = product_catalog_stub.GetProduct(
                demo_pb2.GetProductRequest(id=product_id), 
                timeout=3.0
            )
            return MessageToJson(product)
        except Exception as e:
            return json.dumps({"error": str(e)})
    ```

### 3.3. Thiếu Timeout cho AWS Bedrock Client (P1 - Cao)
* **Ngữ cảnh hệ thống & Khái niệm (Unbounded Cloud I/O / Long-tail Latency):**
  Khi tích hợp dịch vụ bên thứ ba (AWS Cloud), đường truyền mạng và độ tải của API Cloud nằm ngoài tầm kiểm soát của hệ thống nội bộ. Thời gian phản hồi có thể chịu hiện tượng trễ đuôi dài (long-tail latency). Việc để timeout mặc định của thư viện boto3 là 60 giây có nghĩa ta chấp nhận cho phép worker thread của gRPC bị giữ chân trong vòng 1 phút nếu AWS gặp trục trặc. Đây là một con số quá lớn đối với trải nghiệm người dùng cuối và nhanh chóng vắt kiệt tài nguyên thread pool cục bộ.
* **Mã nguồn liên quan:** Khởi tạo `bedrock_client` ở dòng 610 trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L610).
* **Mô tả:** Boto3 client gọi API Bedrock không có cấu hình read/connect timeout tùy chỉnh.
* **Hệ quả:** Treo thread xử lý gRPC tới 60s khi AWS Bedrock phản hồi chậm.
* **Giải pháp cụ thể:** Khởi tạo `bedrock_client` đi kèm với cấu hình `botocore.config.Config` có giới hạn connect và read timeout cụ thể trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py).
  * *Mã nguồn đề xuất:*
    ```python
    from botocore.config import Config
    
    # Connect timeout 3s, Read timeout 10s cho các mô hình AI sinh text
    bedrock_config = Config(connect_timeout=3.0, read_timeout=10.0)
    bedrock_client = boto3.client('bedrock-runtime', region_name=aws_region, config=bedrock_config)
    ```

---

## 4. Kế hoạch & Lộ trình Hành động Chi tiết (Implementation Roadmap)

Khuyên dùng thực hiện sửa đổi mã nguồn tuần tự theo 3 giai đoạn dưới đây nhằm tối ưu hóa sự ổn định trước, sau đó mới đến hiệu năng.

### Giai đoạn 1: Khắc phục khẩn cấp rủi ro sập và treo dịch vụ (Ưu tiên P0)
*Mục tiêu: Ngăn ngừa cạn kiệt thread pool và giải phóng tài nguyên hệ thống nhanh chóng khi các dịch vụ liên kết gặp sự cố.*

#### 1. Cấu hình lại Thread Pool của gRPC Server
* **File cần sửa:** [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L598)
* **Chi tiết thay đổi:**
  ```python
  # Thay thế:
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  # Thành:
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=50))
  ```

#### 2. Cấu hình Timeout cho cuộc gọi Product Catalog
* **File cần sửa:** [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L551)
* **Chi tiết thay đổi:**
  ```python
  # Thay thế:
  product = product_catalog_stub.GetProduct(demo_pb2.GetProductRequest(id=product_id))
  # Thành:
  product = product_catalog_stub.GetProduct(demo_pb2.GetProductRequest(id=product_id), timeout=3.0)
  ```

#### 3. Cấu hình Timeout cho AWS Bedrock Client
* **File cần sửa:** [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L610)
* **Chi tiết thay đổi:**
  ```python
  # Thay thế:
  bedrock_client = boto3.client('bedrock-runtime', region_name=aws_region)
  # Thành:
  from botocore.config import Config
  bedrock_config = Config(connect_timeout=3.0, read_timeout=10.0)
  bedrock_client = boto3.client('bedrock-runtime', region_name=aws_region, config=bedrock_config)
  ```

---

### Giai đoạn 2: Tối ưu hóa tài nguyên DB và I/O hệ thống (Ưu tiên P1)
*Mục tiêu: Đưa chi phí kết nối DB về hằng số $O(1)$ và triệt tiêu log I/O dư thừa.*

#### 1. Tích hợp Connection Pooling cho Postgres
* **File cần sửa:** [database.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/database.py)
* **Chi tiết thay đổi:**
  1. Khởi tạo một đối tượng ThreadedConnectionPool toàn cục với `maxconn=30` (phối hợp với `max_workers=50` của gRPC).
  2. Cập nhật hàm `fetch_product_reviews_from_db` và `fetch_avg_product_review_score_from_db` để mượn và trả kết nối.
  3. **BẮT BUỘC** thêm `connection.commit()` khi thành công và `connection.rollback()` khi lỗi (xem Bẫy triển khai #1 tại Mục 2.1).
  ```python
  from psycopg2.pool import ThreadedConnectionPool
  
  db_pool = ThreadedConnectionPool(minconn=5, maxconn=30, dsn=db_connection_str)
  
  def fetch_product_reviews_from_db(request_product_id):
      connection = None
      try:
          connection = db_pool.getconn()
          with connection.cursor() as cursor:
              # thực thi truy vấn SQL bình thường...
          connection.commit()   # BẮT BUỘC
      except Exception as e:
          if connection is not None:
              connection.rollback()  # BẮT BUỘC
          raise e
      finally:
          if connection is not None:
              db_pool.putconn(connection)
  ```

#### 2. Giảm tải Log đồng bộ trong vòng lặp review
* **File cần sửa:** [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L287)
* **Chi tiết thay đổi:** Đổi mức logging của log trong vòng lặp từ `INFO` về `DEBUG` để tắt log tại môi trường Production.
  ```python
  # Thay thế:
  logger.info(f"  username: {row[0]}, description: {row[1]}, score: {str(row[2])}")
  # Thành:
  logger.debug(f"  username: {row[0]}, description: {row[1]}, score: {str(row[2])}")
  ```

---

### Giai đoạn 3: Tối ưu hóa thuật toán nâng cao (Ưu tiên P2)
*Mục tiêu: Đưa độ trễ các bước xử lý RAG về hằng số, chạy song song hóa I/O.*

#### 1. Chạy song song các Tool Calls (OpenAI Path)
* **File cần sửa:** [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L450)
* **Chi tiết thay đổi:** Sử dụng `concurrent.futures.ThreadPoolExecutor` để kích hoạt đồng thời các tool call như `fetch_product_reviews` và `fetch_product_info`.

#### 2. Lưu Cache kết quả quét Regex Guardrail (TẠM HOÃN TRÀO ĐỔI VỚI LLM CACHING)
* **Trạng thái:** Tạm hoãn để phối hợp thiết kế cùng lớp **LLM Caching Layer** nhằm phân tích tradeoff tối ưu hơn (ví dụ: giải pháp ghi thẳng kết quả quét `is_safe` thành cột dữ liệu trong PostgreSQL để giảm tải bộ nhớ RAM lưu cache, so sánh với cache Redis).
