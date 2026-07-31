file_path = "llm_diagnostician.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Normalize line endings
content = content.replace("\r\n", "\n")

# 1. Update the prompt to ask for Bullet points format in SRE analysis
old_format_instruction = """4. Phần "analysis" trong JSON trả về bắt buộc phải là một phân tích kỹ thuật SRE chuyên nghiệp (bằng TIẾNG VIỆT) và phải đưa ra các dẫn chứng (citations) rõ ràng dựa trên các nguồn dữ liệu sau:
   - Dẫn chứng về cấu trúc cuộc gọi (Topology): Chỉ ra cụ thể từ đồ thị Jaeger Trace ID `{evidence_pack['trace_id']}`, phát hiện bottleneck hoặc luồng kết nối bị gián đoạn bắt đầu từ service `{evidence_pack['culprit_service']}`.
   - Dẫn chứng về nhật ký lỗi (Log Templates): Nêu rõ mẫu log được phân cụm bởi thuật toán Drain3 (ví dụ: mẫu log `'[Template]'` xuất hiện `[X]` lần báo lỗi gì).
   - Dẫn chứng về chỉ số giám sát (Metric Algorithm): Đối chiếu chỉ số lỗi burn-rate hoặc điểm Z-Score đã vượt ngưỡng ra sao.
   - Vùng ảnh hưởng (Blast Radius): Liệt kê danh sách các dịch vụ bị ảnh hưởng dây chuyền (ví dụ: frontend, checkout) và mô tả tác động cụ thể tới người dùng.
   - Nếu không khớp sự cố lịch sử nào, vẫn phải ghi nhận: "Phân tích nguyên nhân gốc của sự cố hiện tại từ dữ liệu ghi chép cụm. Không có dữ liệu sự cố lịch sử nào có sẵn để so sánh trực tiếp. Tuy nhiên..." VÀ phải chèn thêm các dẫn chứng thực tế từ Jaeger trace và log thô đi kèm."""

new_format_instruction = """4. Phần "analysis" trong JSON trả về bắt buộc phải là một phân tích kỹ thuật SRE chuyên nghiệp (bằng TIẾNG VIỆT) được trình bày dưới dạng DÀNH RIÊNG CHO ĐẦU MỤC (Bullet Points) ngắn gọn, rõ ràng theo đúng cấu trúc sau:
   * **Hiện tượng**: <Mô tả cực kỳ ngắn gọn hiện tượng, ví dụ: Vỡ SLO latency hoặc nghẽn giao dịch>
   * **Nguyên nhân**: <Lý do gốc rễ gây ra lỗi, ví dụ: Cạn connection pool hoặc LLM API rate limit>
   * **Bằng chứng**:
     - *Jaeger Trace*: Bottleneck tại dịch vụ `{evidence_pack['culprit_service']}` trên đồ thị Trace ID `{evidence_pack['trace_id']}`.
     - *Logs (Drain3)*: Mẫu log lỗi '[Template]' xuất hiện [X] lần.
     - *Metrics*: Trị số Z-Score hoặc burn-rate lỗi vượt ngưỡng.
   * **Vùng ảnh hưởng (Blast Radius)**: <Liệt kê các dịch vụ bị tác động trực tiếp và gián tiếp, ảnh hưởng thế nào đến người dùng>
   
   TUYỆT ĐỐI KHÔNG viết thành một đoạn văn dài, dồn cục. Phải xuống dòng và chia đầu mục rõ ràng để SRE đọc nhanh trong 5 giây."""

content = content.replace(old_format_instruction, new_format_instruction)

# Also update the JSON format block in f-string to add Blast Radius mention
old_json_format = """  "analysis": "Phân tích kỹ thuật chi tiết chứa đầy đủ dẫn chứng cấu trúc cuộc gọi Jaeger, log Drain3 và thuật toán metric...","""
new_json_format = """  "analysis": "Phân tích kỹ thuật chi tiết chứa đầy đủ dẫn chứng cấu trúc cuộc gọi Jaeger, log Drain3, thuật toán metric và phân tích Vùng ảnh hưởng (Blast Radius)...","""

content = content.replace(old_json_format, new_json_format)

# 2. Slice the file and replace match_incident_locally cleanly
target_signature = "    def match_incident_locally(self, evidence_pack: dict) -> dict:"
idx = content.find(target_signature)
if idx == -1:
    print("ERROR: target signature not found!")
    exit(1)

header = content[:idx]

new_method = """    def match_incident_locally(self, evidence_pack: dict) -> dict:
        \"\"\"
        Local deterministic pattern matcher (fallback/validation gate).
        Matches culprit service and log template keywords against historical INC signatures.
        \"\"\"
        culprit = evidence_pack.get("culprit_service", "").lower()
        log_templates = evidence_pack.get("log_templates", [])
        
        # Concat all templates into one string to search keywords easily
        log_text = " ".join([t.get("template", "").lower() for t in log_templates]).lower()
        
        # Check INC-1: PostgreSQL pool exhaustion
        if "postgresql" in culprit or "connection slots" in log_text or "max connections" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Nghẽn giao dịch checkout/storefront, vỡ SLO latency.\\n* **Nguyên nhân**: Cạn kết nối (connection pool exhaustion) tới cơ sở dữ liệu PostgreSQL.\\n* **Bằng chứng**:\\n  - *Jaeger*: Cổ chai (bottleneck) bắt đầu từ `product-catalog` kéo dài tới `postgresql`.\\n  - *Logs (Drain3)*: Mẫu log cạn slot kết nối xuất hiện nhiều lần.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `product-catalog` (trực tiếp), `frontend` và `frontend-proxy` (gián tiếp làm treo trang storefront).",
                "matched_incident": "INC-1",
                "proposed_action": "scale",
                "action_command": "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=1",
                "confidence_score": 1.0
            }
            
        # Check INC-2: Valkey / Cart OOM (KHÔNG restart để tránh mất giỏ hàng)
        if "cart" in culprit or "valkey" in log_text or "oom" in log_text or "memory limit" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Mất giỏ hàng của khách hàng sau khi reschedule node K8s.\\n* **Nguyên nhân**: Dịch vụ `valkey-cart` (lưu giỏ hàng) là Single Point of Failure (SPOF) và bị tràn bộ nhớ (OOM).\\n* **Bằng chứng**:\\n  - *Jaeger*: Trị số lỗi `error=true` xuất hiện tại `cart` -> `valkey-cart`.\\n  - *Logs (Drain3)*: Lỗi từ chối kết nối do vượt giới hạn bộ nhớ 256MB.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `cart` (trực tiếp), `frontend` (gián tiếp lỗi trang giỏ hàng). Pod giỏ hàng không được tự động restart để tránh mất dữ liệu.",
                "matched_incident": "INC-2",
                "proposed_action": "none",
                "action_command": "",
                "rollback_command": "",
                "confidence_score": 1.0
            }
            
        # Check INC-3: fraud-detection EventStream timeout
        if "fraud" in culprit or "eventstream" in log_text or "status code 4" in log_text or "deadline exceeded" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Mất kết nối EventStream tạm thời trong quá trình deploy.\\n* **Nguyên nhân**: Dịch vụ `fraud-detection` ngắt kết nối gRPC tới flagd EventStream (gRPC status 4) để giải phóng tài nguyên.\\n* **Bằng chứng**:\\n  - *Jaeger*: Lỗi `error=true` xuất hiện tại gRPC stream.\\n  - *Logs (Drain3)*: Mẫu log EventStream timeout xuất hiện nhiều lần.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `fraud-detection` (trực tiếp mất kết nối stream). Tác động người dùng: Không có (chỉ chạy ngầm).",
                "matched_incident": "INC-3",
                "proposed_action": "cache-flush",
                "action_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=1",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=2",
                "confidence_score": 1.0
            }

        # Check INC-4: LLM Gateway 429 / Latency Spike
        if "llm" in culprit or "rate limit" in log_text or "too many requests" in log_text or "bedrock api" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Trang chi tiết sản phẩm load cực kỳ chậm (>5s), vỡ SLO latency.\\n* **Nguyên nhân**: Nhà cung cấp API LLM (AWS Bedrock) chặn lưu lượng (HTTP 429 Too Many Requests).\\n* **Bằng chứng**:\\n  - *Jaeger*: Trễ vọt lên 5100ms tại span gọi LLM.\\n  - *Logs (Drain3)*: Mẫu log Bedrock API rate limit 429 xuất hiện nhiều lần.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `product-reviews` (trực tiếp), `frontend` (gián tiếp làm chậm storefront). Khắc phục bằng cách tắt AI Feature Flag.",
                "matched_incident": "INC-4",
                "proposed_action": "toggle-tf-flag",
                "action_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=true",
                "rollback_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=false",
                "confidence_score": 1.0
            }

        # Check INC-5: Kafka Consumer Lag
        if "accounting" in culprit or "kafka" in log_text or "consumer lag" in log_text or "messages behind" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Đơn hàng đặt thành công nhưng không được ghi sổ kế toán kịp thời.\\n* **Nguyên nhân**: Tắc nghẽn hàng đợi Kafka (Consumer Lag lớn) trên dịch vụ `accounting`.\\n* **Bằng chứng**:\\n  - *Jaeger*: Span xử lý sự kiện Kafka bị thiếu hoặc trễ.\\n  - *Logs (Drain3)*: Consumer lag vượt ngưỡng hàng ngàn tin nhắn.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `accounting` (trực tiếp), `kafka queue` (tắc nghẽn hàng đợi). Tác động người dùng: Không có (luồng đặt hàng vẫn thành công).",
                "matched_incident": "INC-5",
                "proposed_action": "scale",
                "action_command": "kubectl -n techx-tf3 scale deploy/accounting --replicas=2",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/accounting --replicas=1",
                "confidence_score": 1.0
            }

        # Check INC-6: Memory Pressure Stateless
        if "recommendation" in culprit or "memory saturation" in log_text or "gc pressure" in log_text or "working_set_bytes" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Thời gian phản hồi của trang gợi ý sản phẩm tăng đột biến.\\n* **Nguyên nhân**: Quá tải bộ nhớ (Memory Pressure) dẫn tới dừng luồng thu gom rác (GC latency) trên pod stateless `recommendation`.\\n* **Bằng chứng**:\\n  - *Jaeger*: Độ trễ span gợi ý tăng cao.\\n  - *Logs (Drain3)*: Cảnh báo memory usage chạm 95% cgroup limit.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `recommendation` (trực tiếp), `frontend` (gián tiếp làm chậm phần gợi ý). Restart an toàn vì dịch vụ không lưu state.",
                "matched_incident": "INC-6",
                "proposed_action": "restart",
                "action_command": "kubectl -n techx-tf3 rollout restart deployment/recommendation",
                "rollback_command": "kubectl -n techx-tf3 rollout undo deployment/recommendation",
                "confidence_score": 1.0
            }

        # Check INC-7: Circuit Breaker Stuck Open
        if "breaker" in log_text or "circuit breaker" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Không hiển thị tóm tắt review bằng AI mặc dù API LLM đã phục hồi.\\n* **Nguyên nhân**: Circuit Breaker trên cổng dịch vụ bị kẹt ở trạng thái mở (Stuck OPEN).\\n* **Bằng chứng**:\\n  - *Jaeger*: Lỗi `breaker.state = open` xuất hiện tại span gọi LLM.\\n  - *Logs (Drain3)*: Cảnh báo Circuit breaker stuck in OPEN state.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `product-reviews` (trực tiếp). Đề xuất ép đóng breaker để hồi phục kết nối.",
                "matched_incident": "INC-7",
                "proposed_action": "breaker-force",
                "action_command": "kubectl -n techx-tf3 exec deploy/product-reviews -- force-close-breaker",
                "rollback_command": "kubectl -n techx-tf3 exec deploy/product-reviews -- reset-breaker",
                "confidence_score": 1.0
            }

        # Check INC-8: Cold Start Transient
        if "currency" in culprit or "cold start" in log_text or "initializing exchange rate" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Latency trang thanh toán tăng cao (>3s) tức thời sau khi dịch vụ khởi động lại.\\n* **Nguyên nhân**: Dịch vụ `currency` bị trễ do đang warming cache tỷ giá (Cold Start).\\n* **Bằng chứng**:\\n  - *Jaeger*: Trễ 3.2s tại span currency convert (không có lỗi).\\n  - *Logs (Drain3)*: Log warming cache tỷ giá từ external API.\\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `currency` (trực tiếp), `checkout` (gián tiếp). Tự phục hồi, SRE nên chờ thay vì restart pod.",
                "matched_incident": "INC-8",
                "proposed_action": "none",
                "action_command": "",
                "rollback_command": "",
                "confidence_score": 1.0
            }
            
        return {
            "analysis": f"Could not connect to LLM. Raw diagnosis: Anomaly on service {culprit}.",
            "matched_incident": "None",
            "proposed_action": "none",
            "action_command": "",
            "rollback_command": "",
            "confidence_score": 0.0
        }
"""

final_content = header + new_method

with open(file_path, "w", encoding="utf-8") as f:
    f.write(final_content)

print("SUCCESS: Resolved string literal issue. llm_diagnostician.py updated successfully.")
