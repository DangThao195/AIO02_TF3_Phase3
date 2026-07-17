# Thiết Kế Hệ Thống Caching Dịch Vụ Product Reviews
*(Product Review Server Caching Design)*

Tài liệu này tích hợp toàn bộ giải pháp thiết kế bộ nhớ đệm (Caching) cho dịch vụ Product Reviews. Hệ thống được thiết kế hai tầng tối ưu hóa bổ trợ lẫn nhau nhằm triệt tiêu độ trễ mạng (I/O-bound) từ các API LLM bên ngoài và độ trễ CPU (CPU-bound) từ bộ lọc Regex Guardrail.

---

## 1. Kiến Trúc Tổng Quan (Overall Caching Architecture)

Quy trình xử lý một yêu cầu hỏi đáp trợ lý AI (RAG Pipeline) qua hai tầng Caching được mô hình hóa dưới đây:

```mermaid
flowchart TD
    Req(["Yêu cầu của Client <br>(product_id, question)"]) --> InputGuard["1. Bộ lọc đầu vào <br>(Input Guardrails)"]
    InputGuard -->|Không an sau| Block["Chặn & Trả về thông báo bảo mật"]
    
    InputGuard -->|An toàn| KeyGen["2. Tạo LLM Cache Key <br>(product_id + review_version + model_id + question)"]
    KeyGen --> LLMCacheLookup{"3. Tra cứu LLM Cache <br>(LLM Cache Lookup)"}
    
    LLMCacheLookup -->|Cache HIT <br> latency < 10ms| RetCache["Trả về kết quả từ Cache"]
    
    LLMCacheLookup -->|Cache MISS| ToolExec["4. Gọi Tool song song <br>(Catalog Info & Reviews DB)"]
    
    ToolExec --> FetchDB["Đọc Reviews từ DB <br>(Chỉ lấy các dòng is_safe = TRUE)"]
    
    FetchDB --> LLMCall["5. Gửi Context sạch sang LLM"]
    LLMCall --> Judge{"6. Đánh giá độ trung thực <br>(Fidelity Judge)"}
    
    Judge -->|FAIL| Fallback["Trả về Fallback <br>(KHÔNG lưu Cache)"]
    Judge -->|PASS| PolicyCheck{"7. Thỏa mãn Cache Policy?"}
    
    PolicyCheck -->|Có| SaveCache["Ghi LLM Cache kèm Metadata"]
    SaveCache --> RetLLM["Trả về kết quả mới sinh"]
    PolicyCheck -->|Không| RetLLM
```

---

## 2. Tầng 1: LLM Response Caching (Tối ưu hóa API Latency)

### 2.1. Đặt Cache Lookup Trước Lời Gọi LLM (Cache-First)
Cache đóng vai trò là tuyến phòng thủ đầu tiên. Khi **Cache Hit**, kết quả được trả về ngay lập tức cho client mà không thực thi luồng gọi LLM hay truy vấn DB, giúp giảm thời gian phản hồi từ **~1.6 giây xuống < 10 mili-giây** và tiết kiệm 100% token tiêu thụ.

### 2.2. Cấu Trúc Siêu Dữ Liệu Cache (Cache Metadata)
Bản ghi Cache được cấu trúc hóa dưới dạng JSON Object chứa đầy đủ thông tin hỗ trợ kiểm toán (auditing) và gỡ lỗi (debugging):
```json
{
  "answer": "Sản phẩm A được đánh giá cao nhờ thiết kế nhỏ gọn, tuy lượng pin chưa ấn tượng...",
  "provider": "bedrock",
  "model": "amazon.nova-lite-v1:0",
  "created_at": 1783935288,
  "ttl": 86400,
  "review_version": "57f59d57a922",
  "token_usage": {
    "input_tokens": 1250,
    "output_tokens": 240
  }
}
```

### 2.3. Cơ Chế Invalidation Động (Dynamic Invalidation)
Thay vì dùng các lệnh xóa cache thủ công, hệ thống tính toán khóa cache động để tự động vô hiệu hóa cache cũ khi có dữ liệu mới:
* Khóa cache được tính theo công thức:
  $$\text{Cache Key} = \text{SHA256}(\text{product\_id} + \text{review\_version} + \text{model\_id} + \text{normalize}(\text{question}))$$
* **`review_version`:** Mã băm SHA256 dựa trên timestamp của review mới nhất và tổng số lượng review của sản phẩm. Khi có review mới, `review_version` thay đổi $\rightarrow$ Gây ra **Cache Miss** và nạp lại dữ liệu mới.
* **`model_id`:** Mã nhận diện mô hình LLM. Tránh xung đột cache khi hệ thống chuyển đổi mô hình (ví dụ: nâng cấp từ Nova Lite lên Nova Micro hoặc OpenAI GPT).

### 2.4. Chính Sách Chọn Lọc Cache (Cache Policy)
* **Không Cache:** Các câu trả lời thuộc diện lỗi mạng, lỗi LLM, lạc đề (`OUT_OF_SCOPE`), hoặc thiếu thông tin (`NO_INFO`).
* **Chỉ Cache Khi Đạt Kiểm Định:** Chỉ lưu kết quả khi bộ đánh giá độ trung thực phê duyệt (`approved == True`). Tránh lưu trữ câu trả lời bị ảo giác (hallucinated) khiến các request sau nhận thông tin sai lệch.

### 2.5. Lựa Chọn Hạ Tầng Lưu Trữ: PostgreSQL vs Redis (Trade-off Analysis)

Dưới đây là bảng phân tích trade-off chi tiết giữa hai lựa chọn hạ tầng lưu trữ phục vụ cho tầng Cache:

| Tiêu chí | PostgreSQL (Database Quan Hệ) | Redis (In-Memory Key-Value) | Đánh giá & Rationale |
| :--- | :--- | :--- | :--- |
| **Độ trễ & Hiệu năng (Latency & Throughput)** | **~5-15 ms**<br>- Phải xử lý SQL parser, lập chỉ mục (Indexes) và truy xuất ổ đĩa (Disk I/O) nếu dữ liệu không nằm trên RAM. | **< 1 ms**<br>- Lưu hoàn toàn trên bộ nhớ RAM (In-Memory).<br>- Phản hồi tức thì với throughput cực cao (hàng trăm ngàn ops/giây). | **Redis Thắng**:<br>- Phù hợp với các hệ thống có lưu lượng lớn hoặc yêu cầu độ trễ phản hồi thời gian thực. |
| **Quản lý vòng đời Cache (TTL & Eviction)** | **Phức tạp (Manual)**<br>- Phải tự định nghĩa cột `expire_at`. Code ứng dụng phải tự kiểm tra hạn sử dụng khi truy vấn.<br>- Cần cài đặt Cronjob / Daemon để định kỳ chạy lệnh `DELETE` dọn dẹp RAM/Disk. | **Tự động & Tối ưu**<br>- Hỗ trợ TTL tự nhiên ở cấp độ key thông qua lệnh `SETEX` / `EXPIRE`. Dữ liệu tự động biến mất khi hết hạn.<br>- Hỗ trợ các cơ chế loại bỏ tự động (Eviction Policies) như LRU (Least Recently Used) khi đầy bộ nhớ. | **Redis Thắng**:<br>- Việc tự động quản lý vòng đời giúp code ứng dụng sạch hơn và tối ưu hóa bộ nhớ RAM tự động. |
| **Chi phí Hạ tầng & Tài nguyên (Cost & Resources)** | **Rất Thấp (Tối ưu)**<br>- **Local**: $0 (Tận dụng Postgres sẵn có).<br>- **AWS**: Không phát sinh thêm chi phí phần cứng (chỉ sử dụng chung instance RDS/Aurora hiện tại).<br>- **Lưu trữ**: Lưu trên ổ đĩa SSD (EBS GP3 có giá rất rẻ, chỉ khoảng **~$0.08 / GB / tháng**). | **Cao hơn**<br>- **Local**: Tốn thêm RAM để chạy container Redis riêng biệt (~50-100MB RAM).<br>- **AWS (ElastiCache)**: Tốn thêm chi phí tạo cluster Redis. Một instance `cache.t4g.medium` (3GB RAM) có giá khoảng **~$30 / tháng**. Nếu chạy dạng High-Availability (Primary-Replica) sẽ là **~$60 / tháng**.<br>- **Lưu trữ**: RAM có chi phí đắt gấp **~50 - 90 lần** so với SSD per GB (khoảng **~$5 - $7 / GB / tháng**). | **PostgreSQL Thắng hoàn toàn về mặt chi phí**:<br>- Tiết kiệm đáng kể ngân sách ban đầu và tài nguyên phần cứng, đặc biệt phù hợp khi kích thước tập cache chưa quá lớn. |
| **Tính Nhất Quán & Khả năng Phục Hồi (Consistency & Durability)** | **Rất Cao (ACID)**<br>- Đảm bảo tính toàn vẹn dữ liệu cực tốt nhờ cơ chế ACID.<br>- Dữ liệu ghi xuống Disk ngay lập tức, không lo bị mất mát khi server mất điện hoặc restart. | **Trung bình**<br>- Mặc định tối ưu hóa cho tốc độ. Cơ chế ghi đĩa bất đồng bộ (RDB/AOF Snapshotting) có thể gây mất mát dữ liệu nhỏ nếu hệ thống sập đột ngột.<br>- Tuy nhiên, vì đây chỉ là dữ liệu **Cache** (có thể tái sinh từ LLM), việc mất mát nhỏ không gây ảnh hưởng lớn đến tính đúng đắn hệ thống. | **PostgreSQL Thắng**:<br>- Nhưng đối với bài toán Caching, tính chất Durability không quá khắt khe như Database chính, do đó yếu tố này không phải là rào cản lớn với Redis. |
| **Triển khai ở môi trường Local & Docker** | **Đơn giản tối đa**<br>- Chỉ cần viết thêm script khởi tạo Schema cho bảng cache trên DB PostgreSQL đang có sẵn. Không cần sửa đổi file `docker-compose.yaml`. | **Cần thêm cấu hình**<br>- Cần thêm service Redis vào file `docker-compose.yaml` (thêm container mới).<br>- Code Python phải import thư viện `redis` (thêm vào `requirements.txt`). | **PostgreSQL Thắng**:<br>- Giúp giữ cho môi trường Local cực kỳ tinh gọn, ít thành phần phụ thuộc. |
| **Deploy & Vận hành trên AWS Cloud** | **Amazon RDS / Aurora Serverless**<br>- Tái sử dụng Instance RDS hiện tại, chỉ tăng nhẹ tải đọc/ghi. Vận hành tập trung trên một DB duy nhất. | **Amazon ElastiCache / MemoryDB**<br>- Cần quản lý thêm một dịch vụ chuyên biệt (ElastiCache). Có cơ chế Cluster / Replication tự động phân mảnh và sao lưu.<br>- Giảm tải hoàn toàn truy vấn đọc/ghi cache cho PostgreSQL chính để dành tài nguyên cho các nghiệp vụ ACID quan trọng khác. | **Redis Thắng về mặt kiến trúc**:<br>- Giúp tách biệt rõ ràng lớp lưu trữ chính (Database) và lớp bộ đệm (Caching), tăng độ bền vững và khả năng scale cho hệ thống lớn. |

#### Kết luận Trade-off:
- **Chọn PostgreSQL** khi: Dự án đang ở giai đoạn Prototype, muốn **tối giản hóa hạ tầng**, tiết kiệm chi phí, không muốn quản lý thêm container/dịch vụ ngoài PostgreSQL và tải lượng truy cập không quá lớn.
- **Chọn Redis** khi: Hệ thống phục vụ lượng người dùng lớn ở môi trường **Production**, yêu cầu **độ trễ siêu thấp (< 1ms)**, cần cơ chế quản lý TTL tự động mà không làm ảnh hưởng đến hiệu năng ghi/đọc của cơ sở dữ liệu quan hệ chính.

#### Đánh giá Mức độ Tương thích với Mandate-06:
Để lựa chọn hạ tầng phù hợp nhất với các chỉ thị trong [MANDATE-06-ai-trust-safety.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/mandates/MANDATE-06-ai-trust-safety.md), hai hạ tầng được đánh giá theo 3 lăng kính ràng buộc cốt lõi:
1. **Tiêu chí Độ bền bỉ chống treo trang (Resilience & Fallback - Yêu cầu số 1):** 
   * **Redis Thắng:** Bằng cách lưu cache trên RAM độc lập, Redis cô lập hoàn toàn truy vấn cache khỏi PostgreSQL nghiệp vụ chính (nơi đang gánh dữ liệu catalog, reviews). Khi chịu tải cao, điều này ngăn chặn hiện tượng nghẽn cổ chai cơ sở dữ liệu chính, đáp ứng tốt nhất yêu cầu *"không để treo trang sản phẩm"*.
2. **Tiêu chí Khả năng kiểm toán hệ thống (Auditability - Yêu cầu số 4):**
   * **PostgreSQL Thắng:** Kiểu dữ liệu `JSONB` của Postgres hỗ trợ truy vấn SQL phân tích cấu trúc phức tạp cực tốt. Dễ dàng thống kê: *Bao nhiêu request bị Fidelity Judge từ chối? Tổng số token tiêu tốn là bao nhiêu?* Điều này giúp việc báo cáo số đo kiểm định chất lượng (Eval) cho Mentor hoặc Ban giám khảo trực quan và khả thi hơn rất nhiều so với cơ chế Key-Value của Redis.
3. **Tiêu chí Ràng buộc về ngân sách (Budget & Resources):**
   * **PostgreSQL Thắng:** Tiết kiệm hoàn toàn chi phí hạ tầng bổ sung (chi phí cho AWS ElastiCache tốn thêm khoảng **$30 - $60 / tháng**), tối ưu hóa ngân sách hiện tại của Task Force.

* **Hướng tiếp cận Hybrid đề xuất:** Kết hợp dùng **Redis** để phục vụ cache đáp ứng thời gian thực < 1ms (đáp ứng Resilience) và đồng thời ghi log kiểm toán, số đo eval cấu trúc vào **PostgreSQL** (đáp ứng Auditability).

---

## 3. Tầng 2: Regex Guardrail Caching (Tối ưu hóa CPU Latency)

### 3.1. Phân Tích Điểm Nghẽn CPU-bound
Tại bước chuẩn hóa context trước khi gửi LLM, hệ thống phải quét Regex bảo mật chống Prompt Injection độc hại cho mọi review.
* Độ phức tạp thuật toán: $$O(N \times R \times L)$$
  Với $N$ reviews, $R$ mẫu regex (28+ mẫu), $L$ độ dài văn bản. Đây là tác vụ ngốn CPU cực lớn. Nếu LLM Cache bị Miss, việc quét tuần tự này trên request path sẽ tạo ra độ trễ thắt nút cổ chai (Latency Spike).

### 3.2. Phân Tích Trade-off Chi Tiết Theo Tiêu Chí Hệ Thống

Để giảm bớt độ phức tạp khi đánh giá đồng thời 3 phương án, việc so sánh được chia nhỏ thành 3 nhóm tiêu chí cốt lõi, mỗi bảng đều tích hợp cột **Đánh giá & Rationale** để làm rõ ưu thế kỹ thuật:

#### A. Nhóm Tiêu Chí 1: Hiệu Năng & Độ Trễ (Read Path Performance)

| Tiêu chí                       | Phương án A (RAM/Redis)                                                                                | Phương án B (DB Column `is_safe`)                                                                                        | Phương án C (Chỉ dùng LLM Cache)                                                                                           | Đánh giá & Rationale                                                                                                                           |
| :----------------------------- | :----------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------- |
| **Độ trễ đọc (Read Latency)**  | **Thấp (~1-2 ms)**<br>- Tốn $O(N)$ lookup. Nếu dùng Redis cần gom lệnh `MGET` để giảm lượt round-trip. | **Siêu thấp (0 ms CPU)**<br>- Lọc ngay tại câu query: `WHERE is_safe = true`. Không phát sinh trễ mạng phụ hay CPU quét. | **Rất cao (Latency Spike)**<br>- Treo thread xử lý gRPC để quét CPU-bound $O(N \times R \times L)$ khi gặp LLM Cache Miss. | **Phương án B Thắng Tuyệt Đối**:<br>- Triệt tiêu hoàn toàn tác vụ quét khỏi request path, giúp luồng đọc đạt hiệu năng tối ưu và ổn định nhất. |
| **Tải trọng CPU (API Server)** | **Thấp**<br>- Chỉ tốn CPU băm SHA256 và so khớp khóa cache.                                            | **Cực thấp (Gần như bằng 0)**<br>- Không xử lý logic quét Regex trên API path.                                           | **Rất cao**<br>- Nguy cơ nghẽn CPU Thread Starvation trên server gRPC khi chịu tải cao.                                    | **Phương án B Thắng**:<br>- Giữ cho server gRPC luôn ở trạng thái I/O-bound thuần túy, loại bỏ rủi ro nghẽn luồng xử lý do CPU quá tải.        |

#### B. Nhóm Tiêu Chí 2: Tài Nguyên & Chi Phí (Resources & Infrastructure Cost)

| Tiêu chí | Phương án A (RAM/Redis) | Phương án B (DB Column `is_safe`) | Phương án C (Chỉ dùng LLM Cache) | Đánh giá & Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Tiêu hao bộ nhớ RAM** | **Cao (Tốn RAM)**<br>- Cần ~100MB-200MB RAM cho 1 triệu reviews.<br>- Nhân bản RAM theo số pod gRPC nếu dùng local cache. | **Tối ưu (0 MB RAM)**<br>- Hoàn toàn không chiếm dụng bộ nhớ RAM đệm. | **Tối ưu (0 MB RAM)**<br>- Không lưu trữ dữ liệu đệm. | **Phương án B & C Thắng**:<br>- Tiết kiệm tài nguyên RAM đắt đỏ trên Cloud, giảm chi phí hạ tầng (phù hợp với ràng buộc ngân sách của **Mandate-06**). |
| **Tiêu hao đĩa cứng (Disk SSD)** | **Tối ưu (0 MB Disk)**<br>- Chỉ lưu trữ trên bộ nhớ RAM đệm. | **Rất thấp (~1 MB Disk)**<br>- Kiểu `BOOLEAN` tốn **1 byte/dòng**. Cho 1 triệu reviews chỉ tốn **1 MB** SSD. | **Tối ưu (0 MB Disk)**<br>- Không lưu trữ dữ liệu đệm. | **Phương án B Thắng**:<br>- Chi phí lưu trữ SSD vô cùng rẻ (~$0.08 / GB / tháng), mức tiêu thụ 1MB là hoàn toàn không đáng kể so với lợi ích mang lại. |

#### C. Nhóm Tiêu Chí 3: Vận Hành & Bảo Trì (Operations & Maintainability)

| Tiêu chí | Phương án A (RAM/Redis) | Phương án B (DB Column `is_safe`) | Phương án C (Chỉ dùng LLM Cache) | Đánh giá & Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Scale ngang (Horizontal Scaling)** | **Phức tạp**<br>- Local cache gây không nhất quán dữ liệu giữa các pods. Redis cần cluster đồng bộ. | **Đơn giản**<br>- Trạng thái lưu tập trung ở DB chính. Các pods API scale độc lập và đồng bộ tự nhiên qua SQL query. | **Đơn giản**<br>- Hệ thống hoàn toàn stateless. | **Phương án B Thắng**:<br>- Bảo đảm tính nhất quán dữ liệu tuyệt đối giữa các pod gRPC song song mà không cần cấu hình thêm sync layer phức tạp. |
| **Thay đổi bộ quy tắc Regex** | **Đơn giản**<br>- Chỉ cần xóa cache hoặc nâng phiên bản `guardrail_version` để tự tạo cache mới. | **Cần Migration chạy nền**<br>- Cần chạy background job quét lại dữ liệu cũ và UPDATE cột `is_safe`. | **Tự động**<br>- Bộ rules mới được áp dụng ngay lập tức cho các request tiếp theo. | **Phương án A & C Thắng**:<br>- Tiện lợi hơn khi thường xuyên thay đổi rules. Tuy nhiên, Phương án B xử lý được bằng Background Job chạy nền mà không làm treo trang (đáp ứng Resilience). |

---

### 3.3. Giải Pháp Tối Ưu Được Chọn: Phương án B (Database Column `is_safe`)
Để đáp ứng tốt nhất các ràng buộc của **Mandate-06** (không làm treo trang khi quá tải, tiết kiệm tài nguyên hạ tầng):
1. **Chuyển dịch tải CPU sang luồng Ghi (Write path):** Đánh giá sản phẩm là tác vụ "Đọc nhiều, Ghi ít". Thực hiện quét và lưu thuộc tính `is_safe` lúc người dùng lưu review giúp luồng đọc RAG đạt hiệu năng tối đa.
2. **Không tốn thêm RAM:** Loại bỏ sự phụ thuộc vào cache RAM cho tầng Guardrail.
3. **Khi cập nhật mẫu Regex bảo mật:** Luồng ghi áp dụng ngay mẫu mới. Đối với các review cũ trong DB, một Background Job sẽ được kích hoạt để quét lại và cập nhật cột `is_safe` mà không làm ảnh hưởng đến dịch vụ đang chạy.

---

## 4. Minh Họa Logic Mã Nguồn Python

### 4.1. Hàm sinh Cache Key và Cache Policy cho LLM Cache
```python
import hashlib
import json
import time

def generate_cache_key(product_id: str, review_version: str, model_id: str, question: str) -> str:
    # Chuẩn hóa câu hỏi
    normalized_q = " ".join(question.lower().strip().split())
    raw_key = f"{product_id}:{review_version}:{model_id}:{normalized_q}"
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

def should_cache(response_text: str, eval_passed: bool) -> bool:
    # 1. Chỉ cache khi vượt qua Fidelity Judge
    if not eval_passed:
        return False
    
    # 2. Không cache các thông báo lỗi hoặc thông điệp fallback
    ignored_responses = {
        "The AI is busy right now. Please try again later.",
        "The summary cannot be verified. Please try again later.",
        "This question is out of scope. I only answer questions related to the product.",
        "No information in reviews."
    }
    if response_text in ignored_responses:
        return False
        
    return True
```

### 4.2. Logic luồng RAG tích hợp Caching & Song song hóa Tool Calls
```python
# Giả lập luồng xử lý AskProductAIAssistant tích hợp Caching
def ask_product_ai_assistant(product_id, question):
    # Bước 1: Quét Input Guardrail
    if not check_input(question).is_safe:
        return "Blocked by security policy."
        
    # Bước 2: Tạo Cache Key và kiểm tra LLM Cache
    review_version = get_product_review_version(product_id) # SHA256 các reviews của sản phẩm
    cache_key = generate_cache_key(product_id, review_version, llm_model, question)
    
    cached_data = get_cached_response(cache_key)
    if cached_data:
        logger.info("LLM Cache HIT")
        return cached_data["answer"]
        
    # Bước 3: Cache MISS -> Thực hiện gọi Tool song song
    logger.info("LLM Cache MISS. Fetching fresh data...")
    # (Thực hiện ThreadPoolExecutor gọi fetch_product_reviews and fetch_product_info song song...)
    
    # Bước 4: Lọc reviews bằng cột is_safe (Không quét Regex trên luồng đọc nữa)
    # query = "SELECT username, description, score FROM reviews.productreviews WHERE product_id = %s AND is_safe = TRUE"
    
    # Bước 5: Gọi LLM sinh kết quả và chạy Fidelity Judge
    # result = call_llm(context, question)
    # approved = evaluate_fidelity(context, result)
    
    # Bước 6: Lưu cache nếu thỏa mãn policy
    if should_cache(result, approved):
        save_to_cache(cache_key, product_id, result, review_version)
        
    return result
```

---

## 5. Lộ Trình Triển Khai Kỹ Thuật (Implementation Roadmap)

### Giai đoạn 1: Chuẩn bị hạ tầng & Database Migration
* **Database Schema Update:** Cập nhật cơ sở dữ liệu PostgreSQL để hỗ trợ lọc bảo mật ở tầng lưu trữ:
  ```sql
  ALTER TABLE reviews.productreviews ADD COLUMN is_safe BOOLEAN DEFAULT TRUE;
  CREATE INDEX idx_reviews_product_safe ON reviews.productreviews (product_id, is_safe);
  ```
* **Background Worker Migration:** Khởi tạo job chạy một lần để cập nhật cột `is_safe` cho toàn bộ các reviews cũ có sẵn trong DB thông qua hàm `check_input()`.
* **Thêm dependency Redis (`requirements.txt`):**
  ```text
  redis>=5.0.0
  ```

### Giai đoạn 2: Cấu hình Môi trường Phát triển (Local & Production Helm)
* **Local Docker Compose:** Thêm Redis service phục vụ test/phát triển local:
  ```yaml
  services:
    redis:
      image: redis:7-alpine
      container_name: redis-cache
      ports:
        - "6379:6379"
      command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
      restart: always
  ```
* **Production Helm configuration (`values-aio-llm.yaml`):**
  ```yaml
  env:
    - name: REDIS_HOST
      value: "redis-service.default.svc.cluster.local"
    - name: REDIS_PORT
      value: "6379"
    - name: CACHE_TYPE
      value: "redis"
  ```

### Giai đoạn 3: Cấu trúc hóa mã nguồn ứng dụng
* Cập nhật hàm ghi review mới: chạy quét regex trước khi insert vào DB để lưu giá trị `is_safe` chính xác.
* Cập nhật câu SQL trong [database.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/database.py) để chỉ lấy reviews có `is_safe = TRUE`.
* Tích hợp code kiểm tra cache ở đầu hàm `AskProductAIAssistant` và lưu cache ở cuối hàm trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py).
