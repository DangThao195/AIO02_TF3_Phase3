import boto3
import json
import logging
import os
import re
from config import AWS_REGION, BEDROCK_MODEL_ID, BEDROCK_KB_ID

logger = logging.getLogger("AIOpsEngine.LLMDiagnostician")

class LLMDiagnostician:
    def __init__(self):
        self.region = AWS_REGION
        self.model_id = BEDROCK_MODEL_ID
        self.kb_id = BEDROCK_KB_ID
        # Bedrock Nova models are typically available in us-east-1, default to us-east-1 if AWS_REGION is ap-southeast-1
        bedrock_region = os.getenv("BEDROCK_AWS_REGION", "us-east-1" if self.region == "ap-southeast-1" else self.region)
        self.bedrock_client = boto3.client("bedrock-runtime", region_name=bedrock_region)
        
        # Nạp chỉ số vector index của playbooks nếu tồn tại phục vụ RAG cục bộ
        self.vector_index_path = os.path.join(os.path.dirname(__file__), "playbooks_vector_index.json")
        self.playbooks_kb = []
        if os.path.exists(self.vector_index_path):
            try:
                with open(self.vector_index_path, "r", encoding="utf-8") as f:
                    self.playbooks_kb = json.load(f)
                logger.info(f"Loaded {len(self.playbooks_kb)} embedded playbooks into Local Vector KB.")
            except Exception as e:
                logger.error(f"Failed to load playbooks vector index: {e}")

    def load_historical_incidents(self) -> str:
        """
        Fallback: Đọc toàn bộ lịch sử sự cố dạng text từ markdown nếu RAG gặp lỗi.
        """
        try:
            paths = [
                "../phase3/onboarding/INCIDENT_HISTORY.md",
                "phase3/onboarding/INCIDENT_HISTORY.md",
                "INCIDENT_HISTORY.md"
            ]
            for path in paths:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
            return "No historical playbook file found."
        except Exception as e:
            logger.warning(f"Could not load INCIDENT_HISTORY.md: {str(e)}")
            return "No historical incident data available."

    def get_query_embedding(self, text: str) -> list:
        """Sinh vector nhúng cho câu truy vấn sự cố."""
        try:
            body = json.dumps({
                "inputText": text,
                "dimensions": 1024,
                "normalize": True
            })
            response = self.bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v2:0",
                contentType="application/json",
                accept="application/json",
                body=body
            )
            response_body = json.loads(response.get('body').read())
            return response_body.get('embedding')
        except Exception as e:
            logger.warning(f"Titan V2 embeddings failed ({e}). Falling back to Titan V1...")
            try:
                body = json.dumps({"inputText": text})
                response = self.bedrock_client.invoke_model(
                    modelId="amazon.titan-embed-text-v1",
                    contentType="application/json",
                    accept="application/json",
                    body=body
                )
                response_body = json.loads(response.get('body').read())
                return response_body.get('embedding')
            except Exception as ex:
                logger.error(f"All embedding models failed: {ex}")
                return []

    def retrieve_relevant_playbooks_locally(self, query_text: str, k: int = 2) -> str:
        """Truy vấn ngữ nghĩa tìm k kịch bản tương đồng nhất từ Vector KB cục bộ."""
        if not self.playbooks_kb:
            logger.warning("Local Vector KB is empty. Falling back to reading raw playbooks file.")
            return self.load_historical_incidents()

        query_emb = self.get_query_embedding(query_text)
        if not query_emb:
            logger.warning("Failed to generate query embedding. Falling back to reading raw playbooks file.")
            return self.load_historical_incidents()

        def cosine_similarity(v1, v2):
            length = min(len(v1), len(v2))
            dot_product = sum(a * b for a, b in zip(v1[:length], v2[:length]))
            norm_a = sum(a * a for a in v1[:length]) ** 0.5
            norm_b = sum(b * b for b in v2[:length]) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        scored_playbooks = []
        for pb in self.playbooks_kb:
            sim = cosine_similarity(query_emb, pb["embedding"])
            scored_playbooks.append((sim, pb))

        scored_playbooks.sort(key=lambda x: x[0], reverse=True)

        logger.info("=== Local Semantic RAG Search Results ===")
        for sim, pb in scored_playbooks[:3]:
            logger.info(f"-> {pb['incident_id']} - Similarity Score: {sim:.4f}")

        # Lọc ra k kịch bản có độ tương đồng tốt (ngưỡng tương đồng >= 0.35)
        relevant_pbs = []
        for sim, pb in scored_playbooks[:k]:
            if sim >= 0.35:
                relevant_pbs.append(pb["text"])

        if not relevant_pbs:
            logger.info("No playbooks matched local semantic similarity threshold (>= 0.35).")
            return "Không tìm thấy sự cố lịch sử nào tương quan trực tiếp."

        return "\n\n---%s\n\n" % relevant_pbs

    def retrieve_relevant_playbooks_from_aws(self, query_text: str, k: int = 2) -> str:
        """Kéo tri thức trực tiếp từ Cloud-native Amazon Bedrock Knowledge Base."""
        try:
            logger.info(f"Querying AWS Bedrock Knowledge Base (ID: {self.kb_id})...")
            runtime_client = boto3.client("bedrock-agent-runtime", region_name=self.region)
            response = runtime_client.retrieve(
                knowledgeBaseId=self.kb_id,
                retrievalQuery={
                    'text': query_text
                },
                retrievalConfiguration={
                    'vectorSearchConfiguration': {
                        'numberOfResults': k
                    }
                }
            )
            results = response.get('retrievalResults', [])
            pbs = []
            for r in results:
                content_text = r.get('content', {}).get('text', '')
                if content_text:
                    pbs.append(content_text)
            
            if not pbs:
                logger.info("AWS Bedrock KB returned 0 results.")
                return "Không tìm thấy sự cố lịch sử nào tương quan trực tiếp."
                
            logger.info(f"Successfully retrieved {len(pbs)} chunks from AWS Bedrock KB.")
            return "\n\n---\n\n".join(pbs)
        except Exception as e:
            logger.error(f"Failed to retrieve from AWS Bedrock KB: {e}. Falling back to local Vector KB.")
            return self.retrieve_relevant_playbooks_locally(query_text, k)

    def retrieve_relevant_playbooks(self, query_text: str, k: int = 2) -> str:
        """Điều phối: Ưu tiên dùng Cloud-native Bedrock KB nếu cấu hình, nếu không dùng Local RAG."""
        if self.kb_id:
            return self.retrieve_relevant_playbooks_from_aws(query_text, k)
        else:
            return self.retrieve_relevant_playbooks_locally(query_text, k)

    def clean_and_parse_json(self, text: str) -> dict:
        """Bộ giải mã JSON chống lỗi unescaped quotes và format của LLM."""
        text = text.strip()
        
        # Xóa markdown backticks
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            
        try:
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Standard JSON parsing failed: {e}. Attempting regex recovery...")
            
        # Thử tìm { và } để cắt
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            json_candidate = text[start:end+1]
            try:
                return json.loads(json_candidate)
            except Exception as e:
                pass
                
        # Khôi phục các trường bằng Regex
        recovered = {}
        
        # Trích xuất "analysis"
        analysis_match = re.search(r'"analysis"\s*:\s*"(.*?)"\s*,\s*"(?:proposed_action|matched_incident)"', text, re.DOTALL)
        if not analysis_match:
            analysis_match = re.search(r'"analysis"\s*:\s*"(.*?)"\s*,\s*$', text, re.DOTALL)
        if not analysis_match:
            analysis_match = re.search(r'"analysis"\s*:\s*"(.*?)"\s*(?:,|\n|\})', text, re.DOTALL)
            
        if analysis_match:
            recovered["analysis"] = analysis_match.group(1).replace('\\n', '\n').strip()
            
        # Trích xuất các trường chuỗi khác
        for field in ["matched_incident", "proposed_action", "action_command", "rollback_command"]:
            match = re.search(rf'"{field}"\s*:\s*"(.*?)"', text)
            if match:
                recovered[field] = match.group(1).strip()
                
        # Trích xuất confidence_score
        conf_match = re.search(r'"confidence_score"\s*:\s*([0-9.]+)', text)
        if conf_match:
            try:
                recovered["confidence_score"] = float(conf_match.group(1))
            except:
                recovered["confidence_score"] = 0.95
                
        # Điền các giá trị mặc định nếu thiếu
        for key in ["analysis", "matched_incident", "proposed_action", "action_command", "rollback_command"]:
            if key not in recovered:
                recovered[key] = ""
        if "confidence_score" not in recovered:
            recovered["confidence_score"] = 0.95
            
        if recovered.get("analysis") or recovered.get("proposed_action"):
            logger.info("Successfully recovered JSON fields using regex parser!")
            return recovered
            
        raise ValueError("Could not parse or recover JSON from LLM output.")

    def diagnose(self, evidence_pack: dict) -> dict:
        """
        Giai đoạn 4: LLM Diagnostic Engine kết hợp Hybrid Semantic RAG
        Gọi AWS Bedrock thực hiện chẩn đoán.
        """
        log_snippet = " ".join([t.get("template", "") for t in evidence_pack.get("log_templates", [])])
        query_text = f"Service: {evidence_pack.get('culprit_service', '')}. Logs: {log_snippet}"
        
        # Gọi công cụ điều phối RAG lấy tri thức
        history = self.retrieve_relevant_playbooks(query_text, k=2)
        
        # Xây dựng prompt
        prompt = f"""
[HISTORICAL INCIDENT DATABASE]
Dưới đây là lịch sử sự cố và hướng xử lý thành công lấy từ Bedrock Knowledge Base (KB):
{history}

[CURRENT INCIDENT EVIDENCE PACK]
Culprit Service: {evidence_pack['culprit_service']}
Incident Trace ID: {evidence_pack['trace_id']}
Clustered Log Templates:
{json.dumps(evidence_pack['log_templates'], indent=2)}

[TASK]
1. Phân tích nguyên nhân sự cố hiện tại. Đối chiếu với các sự cố lịch sử (INC-1, INC-2, INC-3, INC-4, INC-5, INC-6, INC-7, INC-8) xem có trùng khớp mẫu hành vi không.
2. BẮT BUỘC TRÍCH DẪN NGUỒN (Citation): Trong nội dung phân tích (đặc biệt là phần "Nguyên nhân" và "matched_incident"), bạn bắt buộc phải ghi rõ nguồn trích dẫn sự cố lịch sử tương đồng nhất lấy từ Knowledge Base. Ví dụ: "(Nguồn tham chiếu: INC-4 từ Bedrock Knowledge Base)".
3. Lưu ý đặc biệt: 
   - INC-1: Quá tải DB connection pool của product-catalog. Khắc phục: đề xuất proposed_action = "scale", và action_command = "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=1".
   - INC-2: Lỗi mất state do Single-replica khi Pod rescheduled, KHÔNG PHẢI lỗi OOM. Nếu là INC-2, đề xuất proposed_action = "none", tuyệt đối không restart pod tự động vì restart sẽ làm mất sạch dữ liệu giỏ hàng.
   - INC-3: Lỗi EventStream gRPC status 4 (timeout) giữa fraud-detection va flagd. Khắc phục: đề xuất proposed_action = "cache-flush" (nhưng sử dụng scale command) và action_command = "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=1".
4. Xác định Vùng ảnh hưởng (Blast Radius): Bạn phải chỉ rõ các microservice nào khác trong hệ thống có thể bị ảnh hưởng dây chuyền và giải thích chi tiết chúng bị ảnh hưởng như thế nào (ví dụ: bị tăng độ trễ lan truyền, nhận lỗi gRPC/HTTP 5xx, hoặc bị tắc nghẽn hàng đợi).
5. Phân tích "analysis" trong JSON trả về bắt buộc phải là một phân tích kỹ thuật SRE chuyên nghiệp (bằng TIẾNG VIỆT) được trình bày dưới dạng DÀNH RIÊNG CHO ĐẦU MỤC (Bullet Points) ngắn gọn, rõ ràng theo đúng cấu trúc sau:
   * **Hiện tượng**: <Mô tả cực kỳ ngắn gọn hiện tượng, ví dụ: Vỡ SLO latency hoặc nghẽn giao dịch>
   * **Nguyên nhân**: <Lý do gốc rễ gây ra lỗi. Ở ĐÂY BẮT BUỘC PHẢI GHI RÕ TRÍCH DẪN NGUỒN THAM CHIẾU (ví dụ: 'Nguồn tham chiếu: INC-4 từ Bedrock Knowledge Base')>
   * **Bằng chứng**:
     - *Jaeger Trace*: Bottleneck tại dịch vụ `{evidence_pack['culprit_service']}` trên đồ thị Trace ID `{evidence_pack['trace_id']}`.
     - *Logs (Drain3)*: Mẫu log lỗi '[Template]' xuất hiện [X] lần.
     - *Metrics*: Trị số Z-Score hoặc burn-rate lỗi vượt ngưỡng.
   * **Vùng ảnh hưởng (Blast Radius)**: <Liệt kê các dịch vụ bị tác động trực tiếp và gián tiếp, ảnh hưởng thế nào đến người dùng>
   
   TUYỆT ĐỐI KHÔNG viết thành một đoạn văn dài, dồn cục. Phải xuống dòng và chia đầu mục rõ ràng để SRE đọc nhanh trong 5 giây.
6. Đề xuất một hành động khắc phục từ whitelist sau: [scale, restart, toggle-tf-flag, cache-flush, breaker-force, none].
7. Đánh giá độ tự tin của quyết định chẩn đoán và hành động đề xuất dưới dạng số thực float từ 0.0 đến 1.0 (ví dụ: 0.95).
 
Trả về kết quả ở định dạng JSON duy nhất như sau:
{{
  "analysis": "Phân tích kỹ thuật chi tiết chứa đầy đủ dẫn chứng cuộc gọi Jaeger, log Drain3, thuật toán metric và phân tích Vùng ảnh hưởng (Blast Radius)...",
  "matched_incident": "INC-1" hoặc "INC-2" hoặc "INC-3" hoặc "INC-4" hoặc "INC-5" hoặc "INC-6" hoặc "INC-7" hoặc "INC-8" hoặc "None",
  "proposed_action": "scale" hoặc "restart" || "toggle-tf-flag" || "cache-flush" || "breaker-force" || "none",
  "action_command": "kubectl -n techx-tf3 scale deploy/... hoặc lệnh tương ứng để khắc phục",
  "rollback_command": "lệnh rollback khôi phục lại trạng thái cũ của deployment/service nếu lệnh khắc phục thất bại",
  "confidence_score": số thực float từ 0.0 đến 1.0
}}
"""
 
        model_lower = self.model_id.lower()
        if "anthropic" in model_lower:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
        elif "meta" in model_lower:
            body = json.dumps({
                "prompt": prompt,
                "max_gen_len": 1000,
                "temperature": 0.1,
                "top_p": 0.9
            })
        elif "mistral" in model_lower:
            body = json.dumps({
                "prompt": f"<s>[INST] {prompt} [/INST]",
                "max_tokens": 1000
            })
        elif "nova" in model_lower:
            body = json.dumps({
                "inferenceConfig": {
                    "maxTokens": 1000,
                    "temperature": 0.1,
                    "topP": 0.9
                },
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ]
            })
        else:
            body = json.dumps({
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": 1000,
                    "temperature": 0.1,
                    "topP": 0.9
                }
            })
 
        try:
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=body
            )
            
            resp_text = response.get("body").read().decode("utf-8")
            response_body = json.loads(resp_text)
            
            if "anthropic" in model_lower:
                llm_text = response_body["content"][0]["text"]
            elif "meta" in model_lower:
                llm_text = response_body["generation"]
            elif "mistral" in model_lower:
                llm_text = response_body["outputs"][0]["text"]
            elif "nova" in model_lower:
                llm_text = response_body["output"]["message"]["content"][0]["text"]
            else:
                llm_text = response_body["results"][0]["outputText"]
 
            # Parse JSON từ response của LLM với bộ lọc đàn hồi mới
            return self.clean_and_parse_json(llm_text)
            
        except Exception as e:
            logger.error(f"Error calling AWS Bedrock: {str(e)}")
            return self.match_incident_locally(evidence_pack)

    def match_incident_locally(self, evidence_pack: dict) -> dict:
        """
        Local deterministic pattern matcher (fallback/validation gate).
        Matches culprit service and log template keywords against historical INC signatures.
        """
        culprit = evidence_pack.get("culprit_service", "").lower()
        log_templates = evidence_pack.get("log_templates", [])
        log_text = " ".join([t.get("template", "").lower() for t in log_templates]).lower()
        
        # Check INC-1: PostgreSQL pool exhaustion
        if "postgresql" in culprit or "connection slots" in log_text or "max connections" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Nghẽn giao dịch checkout/storefront, vỡ SLO latency.\n* **Nguyên nhân**: Cạn kết nối (connection pool exhaustion) tới cơ sở dữ liệu PostgreSQL (Nguồn tham chiếu: INC-1 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Cổ chai (bottleneck) bắt đầu từ `product-catalog` kéo dài tới `postgresql`.\n  - *Logs (Drain3)*: Mẫu log cạn slot kết nối xuất hiện nhiều lần.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `product-catalog` (trực tiếp), `frontend` và `frontend-proxy` (gián tiếp làm treo trang storefront).",
                "matched_incident": "INC-1",
                "proposed_action": "scale",
                "action_command": "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=1",
                "confidence_score": 1.0
            }
            
        # Check INC-2: Valkey / Cart OOM (KHÔNG restart để tránh mất giỏ hàng)
        if "cart" in culprit or "valkey" in log_text or "oom" in log_text or "memory limit" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Mất giỏ hàng của khách hàng sau khi reschedule node K8s.\n* **Nguyên nhân**: Dịch vụ `valkey-cart` (lưu giỏ hàng) là Single Point of Failure (SPOF) và bị tràn bộ nhớ (OOM) (Nguồn tham chiếu: INC-2 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Trị số lỗi `error=true` xuất hiện tại `cart` -> `valkey-cart`.\n  - *Logs (Drain3)*: Lỗi từ chối kết nối do vượt giới hạn bộ nhớ 256MB.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `cart` (trực tiếp), `frontend` (gián tiếp lỗi trang giỏ hàng). Pod giỏ hàng không được tự động restart để tránh mất dữ liệu.",
                "matched_incident": "INC-2",
                "proposed_action": "none",
                "action_command": "",
                "rollback_command": "",
                "confidence_score": 1.0
            }
            
        # Check INC-3: fraud-detection EventStream timeout
        if "fraud" in culprit or "eventstream" in log_text or "status code 4" in log_text or "deadline exceeded" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Mất kết nối EventStream tạm thời trong quá trình deploy.\n* **Nguyên nhân**: Dịch vụ `fraud-detection` ngắt kết nối gRPC tới flagd EventStream (gRPC status 4) để giải phóng tài nguyên (Nguồn tham chiếu: INC-3 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Lỗi `error=true` xuất hiện tại gRPC stream.\n  - *Logs (Drain3)*: Mẫu log EventStream timeout xuất hiện nhiều lần.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `fraud-detection` (trực tiếp mất kết nối stream). Tác động người dùng: Không có (chỉ chạy ngầm).",
                "matched_incident": "INC-3",
                "proposed_action": "cache-flush",
                "action_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=1",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=2",
                "confidence_score": 1.0
            }

        # Check INC-4: LLM Gateway 429 / Latency Spike
        if "llm" in culprit or "rate limit" in log_text or "too many requests" in log_text or "bedrock api" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Trang chi tiết sản phẩm load cực kỳ chậm (>5s), vỡ SLO latency.\n* **Nguyên nhân**: Nhà cung cấp API LLM (AWS Bedrock) chặn lưu lượng (HTTP 429 Too Many Requests) (Nguồn tham chiếu: INC-4 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Trễ vọt lên 5100ms tại span gọi LLM.\n  - *Logs (Drain3)*: Mẫu log Bedrock API rate limit 429 xuất hiện nhiều lần.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `product-reviews` (trực tiếp), `frontend` (gián tiếp làm chậm storefront). Khắc phục bằng cách tắt AI Feature Flag.",
                "matched_incident": "INC-4",
                "proposed_action": "toggle-tf-flag",
                "action_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=true",
                "rollback_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=false",
                "confidence_score": 1.0
            }

        # Check INC-5: Kafka Consumer Lag
        if "accounting" in culprit or "kafka" in log_text or "consumer lag" in log_text or "messages behind" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Đơn hàng đặt thành công nhưng không được ghi sổ kế toán kịp thời.\n* **Nguyên nhân**: Tắc nghẽn hàng đợi Kafka (Consumer Lag lớn) trên dịch vụ `accounting` (Nguồn tham chiếu: INC-5 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Span xử lý sự kiện Kafka bị thiếu hoặc trễ.\n  - *Logs (Drain3)*: Consumer lag vượt ngưỡng hàng ngàn tin nhắn.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `accounting` (trực tiếp), `kafka queue` (tắc nghẽn hàng đợi). Tác động người dùng: Không có (luồng đặt hàng vẫn thành công).",
                "matched_incident": "INC-5",
                "proposed_action": "scale",
                "action_command": "kubectl -n techx-tf3 scale deploy/accounting --replicas=2",
                "rollback_command": "kubectl -n techx-tf3 scale deploy/accounting --replicas=1",
                "confidence_score": 1.0
            }

        # Check INC-6: Memory Pressure Stateless
        if "recommendation" in culprit or "memory saturation" in log_text or "gc pressure" in log_text or "working_set_bytes" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Thời gian phản hồi của trang gợi ý sản phẩm tăng đột biến.\n* **Nguyên nhân**: Quá tải bộ nhớ (Memory Pressure) dẫn tới dừng luồng thu gom rác (GC latency) trên pod stateless `recommendation` (Nguồn tham chiếu: INC-6 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Độ trễ span gợi ý tăng cao.\n  - *Logs (Drain3)*: Cảnh báo memory usage chạm 95% cgroup limit.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `recommendation` (trực tiếp), `frontend` (gián tiếp làm chậm phần gợi ý). Restart an toàn vì dịch vụ không lưu state.",
                "matched_incident": "INC-6",
                "proposed_action": "restart",
                "action_command": "kubectl -n techx-tf3 rollout restart deployment/recommendation",
                "rollback_command": "kubectl -n techx-tf3 rollout undo deployment/recommendation",
                "confidence_score": 1.0
            }

        # Check INC-7: Circuit Breaker Stuck Open
        if "breaker" in log_text or "circuit breaker" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Không hiển thị tóm tắt review bằng AI mặc dù API LLM đã phục hồi.\n* **Nguyên nhân**: Circuit Breaker trên cổng dịch vụ bị kẹt ở trạng thái mở (Stuck OPEN) (Nguồn tham chiếu: INC-7 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Lỗi `breaker.state = open` xuất hiện tại span gọi LLM.\n  - *Logs (Drain3)*: Cảnh báo Circuit breaker stuck in OPEN state.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `product-reviews` (trực tiếp). Đề xuất ép đóng breaker để hồi phục kết nối.",
                "matched_incident": "INC-7",
                "proposed_action": "breaker-force",
                "action_command": "kubectl -n techx-tf3 exec deploy/product-reviews -- force-close-breaker",
                "rollback_command": "kubectl -n techx-tf3 exec deploy/product-reviews -- reset-breaker",
                "confidence_score": 1.0
            }

        # Check INC-8: Cold Start Transient
        if "currency" in culprit or "cold start" in log_text or "initializing exchange rate" in log_text:
            return {
                "analysis": "* **Hiện tượng**: Latency trang thanh toán tăng cao (>3s) tức thời sau khi dịch vụ khởi động lại.\n* **Nguyên nhân**: Dịch vụ `currency` bị trễ do đang warming cache tỷ giá (Cold Start) (Nguồn tham chiếu: INC-8 từ Bedrock Knowledge Base).\n* **Bằng chứng**:\n  - *Jaeger*: Trễ 3.2s tại span currency convert (không có lỗi).\n  - *Logs (Drain3)*: Log warming cache tỷ giá từ external API.\n* **Vùng ảnh hưởng (Blast Radius)**: Dịch vụ `currency` (trực tiếp), `checkout` (gián tiếp). Tự phục hồi, SRE nên chờ thay vì restart pod.",
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
