import re

file_path = "llm_diagnostician.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Normalize line endings
content = content.replace("\r\n", "\n")

# 1. Update the prompt template with Blast Radius instructions
old_task = """3. Phần "analysis" trong JSON trả về bắt buộc phải là một phân tích kỹ thuật SRE chuyên nghiệp (bằng TIẾNG VIỆT) và phải đưa ra các dẫn chứng (citations) rõ ràng dựa trên các nguồn dữ liệu sau:
   - Dẫn chứng về cấu trúc cuộc gọi (Topology): Chỉ ra cụ thể từ đồ thị Jaeger Trace ID `{evidence_pack['trace_id']}`, phát hiện bottleneck hoặc luồng kết nối bị gián đoạn bắt đầu từ service `{evidence_pack['culprit_service']}`.
   - Dẫn chứng về nhật ký lỗi (Log Templates): Nêu rõ mẫu log được phân cụm bởi thuật toán Drain3 (ví dụ: mẫu log `'[Template]'` xuất hiện `[X]` lần báo lỗi gì).
   - Dẫn chứng về chỉ số giám sát (Metric Algorithm): Đối chiếu chỉ số lỗi burn-rate hoặc điểm Z-Score đã vượt ngưỡng ra sao.
   - Nếu không khớp sự cố lịch sử nào, vẫn phải ghi nhận: "Phân tích nguyên nhân gốc của sự cố hiện tại từ dữ liệu ghi chép cụm. Không có dữ liệu sự cố lịch sử nào có sẵn để so sánh trực tiếp. Tuy nhiên, dựa trên thông tin về các sự cố lịch sử, có thể xem xét các yếu tố tiềm ẩn như lỗi Single-replica hoặc vấn đề với readiness probe. Vì không có thông tin về các gợi ý cụ thể về nguyên nhân từ các ghi chép cụm, ta sẽ giả định rằng đây có thể là một sự cố mới không có trùng khớp trực tiếp với các sự cố lịch sử..." VÀ phải chèn thêm các dẫn chứng thực tế từ Jaeger trace và log thô đi kèm."""

new_task = """3. Xác định Vùng ảnh hưởng (Blast Radius): Bạn phải chỉ rõ các microservice nào khác trong hệ thống có thể bị ảnh hưởng dây chuyền và giải thích chi tiết chúng bị ảnh hưởng như thế nào (ví dụ: bị tăng độ trễ lan truyền, nhận lỗi gRPC/HTTP 5xx, hoặc bị tắc nghẽn hàng đợi).
4. Phần "analysis" trong JSON trả về bắt buộc phải là một phân tích kỹ thuật SRE chuyên nghiệp (bằng TIẾNG VIỆT) và phải đưa ra các dẫn chứng (citations) rõ ràng dựa trên các nguồn dữ liệu sau:
   - Dẫn chứng về cấu trúc cuộc gọi (Topology): Chỉ ra cụ thể từ đồ thị Jaeger Trace ID `{evidence_pack['trace_id']}`, phát hiện bottleneck hoặc luồng kết nối bị gián đoạn bắt đầu từ service `{evidence_pack['culprit_service']}`.
   - Dẫn chứng về nhật ký lỗi (Log Templates): Nêu rõ mẫu log được phân cụm bởi thuật toán Drain3 (ví dụ: mẫu log `'[Template]'` xuất hiện `[X]` lần báo lỗi gì).
   - Dẫn chứng về chỉ số giám sát (Metric Algorithm): Đối chiếu chỉ số lỗi burn-rate hoặc điểm Z-Score đã vượt ngưỡng ra sao.
   - Vùng ảnh hưởng (Blast Radius): Liệt kê danh sách các dịch vụ bị ảnh hưởng dây chuyền (ví dụ: frontend, checkout) và mô tả tác động cụ thể tới người dùng.
   - Nếu không khớp sự cố lịch sử nào, vẫn phải ghi nhận: "Phân tích nguyên nhân gốc của sự cố hiện tại từ dữ liệu ghi chép cụm. Không có dữ liệu sự cố lịch sử nào có sẵn để so sánh trực tiếp. Tuy nhiên..." VÀ phải chèn thêm các dẫn chứng thực tế từ Jaeger trace và log thô đi kèm."""

content = content.replace(old_task, new_task)

# Also update the JSON format block in f-string to add Blast Radius mention
old_json_format = """  "analysis": "Phân tích kỹ thuật chi tiết chứa đầy đủ dẫn chứng cấu trúc cuộc gọi Jaeger, log Drain3 và thuật toán metric...","""
new_json_format = """  "analysis": "Phân tích kỹ thuật chi tiết chứa đầy đủ dẫn chứng cấu trúc cuộc gọi Jaeger, log Drain3, thuật toán metric và phân tích Vùng ảnh hưởng (Blast Radius)...","""

content = content.replace(old_json_format, new_json_format)

# 2. Update the match_incident_locally method
pattern = r"    def match_incident_locally\(self, evidence_pack: dict\) -> dict:.*"

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
                "analysis": "PostgreSQL connection pool exhausted. Scaling up product-catalog replicas to distribute database connection load. Vùng ảnh hưởng (Blast Radius): product-catalog (trực tiếp nhận lỗi DB), frontend và frontend-proxy (gián tiếp bị tăng độ trễ tải trang sản phẩm).",
                "matched_incident": "INC-1",
                "proposed_action": "scale",
                "action_command": "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=1",
                "confidence_score": 1.0
            }
            
        # Check INC-2: Valkey / Cart OOM (KHÔNG restart để tránh mất giỏ hàng)
        if "cart" in culprit or "valkey" in log_text or "oom" in log_text or "memory limit" in log_text:
            return {
                "analysis": "Valkey connection refused / Cart OOM. Cart pod has Single-replica SPOF. Pod must NOT be automatically restarted to prevent losing user cart data. Alerting SRE to scale or deploy database persistence. Vùng ảnh hưởng (Blast Radius): cart (trực tiếp không ghi được session), frontend (gián tiếp lỗi trang giỏ hàng).",
                "matched_incident": "INC-2",
                "proposed_action": "none",
                "action_command": "",
                "rollback_command": "",
                "confidence_score": 1.0
            }
            
        # Check INC-3: fraud-detection EventStream timeout
        if "fraud" in culprit or "eventstream" in log_text or "status code 4" in log_text or "deadline exceeded" in log_text:
            return {
                "analysis": "fraud-detection connection to flagd EventStream timeout (gRPC status 4). This is normal behavior of flagd to free memory. Vùng ảnh hưởng (Blast Radius): fraud-detection (trực tiếp mất kết nối stream). Tác động người dùng: Không có (chỉ ảnh hưởng luồng bất đồng bộ ngầm).",
                "matched_incident": "INC-3",
                "proposed_action": "cache-flush",
                "action_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=1",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=2",
                "confidence_score": 1.0
            }

        # Check INC-4: LLM Gateway 429 / Latency Spike
        if "llm" in culprit or "rate limit" in log_text or "too many requests" in log_text or "bedrock api" in log_text:
            return {
                "analysis": "LLM API provider is rate limiting requests (HTTP 429). Triggering feature flag toggle to disable AI reviews summary, falling back to raw reviews rendering to recover latency. Vùng ảnh hưởng (Blast Radius): product-reviews (trực tiếp nghẽn gọi LLM), frontend (gián tiếp kéo dài thời gian load trang chi tiết sản phẩm).",
                "matched_incident": "INC-4",
                "proposed_action": "toggle-tf-flag",
                "action_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=true",
                "rollback_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=false",
                "confidence_score": 1.0
            }

        # Check INC-5: Kafka Consumer Lag
        if "accounting" in culprit or "kafka" in log_text or "consumer lag" in log_text or "messages behind" in log_text:
            return {
                "analysis": "Kafka Consumer Lag detected on accounting service. Scaling up replicas to increase message processing throughput. Vùng ảnh hưởng (Blast Radius): accounting (trực tiếp bị chậm xử lý event đơn hàng), kafka queue (tắc nghẽn hàng đợi). Tác động người dùng: Không có (luồng đặt hàng vẫn thành công).",
                "matched_incident": "INC-5",
                "proposed_action": "scale",
                "action_command": "kubectl -n techx-tf3 scale deploy/accounting --replicas=2",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/accounting --replicas=1",
                "confidence_score": 1.0
            }

        # Check INC-6: Memory Pressure Stateless
        if "recommendation" in culprit or "memory saturation" in log_text or "gc pressure" in log_text or "working_set_bytes" in log_text:
            return {
                "analysis": "Memory pressure / high Python GC latency on recommendation service. Safe to restart since this service is stateless. Vùng ảnh hưởng (Blast Radius): recommendation (trực tiếp bị trễ phản hồi gợi ý), frontend (gián tiếp phần gợi ý tải chậm).",
                "matched_incident": "INC-6",
                "proposed_action": "restart",
                "action_command": "kubectl -n techx-tf3 rollout restart deployment/recommendation",
                "rollback_command": "kubectl -n techx-tf3 rollout undo deployment/recommendation",
                "confidence_score": 1.0
            }

        # Check INC-7: Circuit Breaker Stuck Open
        if "breaker" in log_text or "circuit breaker" in log_text:
            return {
                "analysis": "LLM Circuit Breaker is stuck in OPEN state. Forcing circuit breaker to close to resume LLM integrations. Vùng ảnh hưởng (Blast Radius): product-reviews (trực tiếp không gọi được LLM), frontend (gián tiếp mất tính năng tóm tắt AI).",
                "matched_incident": "INC-7",
                "proposed_action": "breaker-force",
                "action_command": "kubectl -n techx-tf3 exec deploy/product-reviews -- force-close-breaker",
                "rollback_command": "kubectl -n techx-tf3 exec deploy/product-reviews -- reset-breaker",
                "confidence_score": 1.0
            }

        # Check INC-8: Cold Start Transient
        if "currency" in culprit or "cold start" in log_text or "initializing exchange rate" in log_text:
            return {
                "analysis": "Currency service is experiencing transient latency due to cold-start cache warming. No action required; system will self-heal. Vùng ảnh hưởng (Blast Radius): currency (trực tiếp trễ quy đổi tiền), checkout (gián tiếp làm chậm luồng thanh toán đơn hàng).",
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

content = re.sub(pattern, new_method, content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: llm_diagnostician.py updated with rich Blast Radius fallback analysis.")
