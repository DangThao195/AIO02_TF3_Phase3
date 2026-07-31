import os
import sys
import json
import boto3

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import AWS_REGION, BEDROCK_MODEL_ID
from llm_diagnostician import LLMDiagnostician

def test():
    diag = LLMDiagnostician()
    
    # Dummy evidence pack for inc4 (Bedrock API 429 Rate Limit)
    evidence_pack = {
        "culprit_service": "llm",
        "trace_id": "mock-inc4",
        "log_templates": [
            {"template": "ERROR: Bedrock API call failed or timed out after 5000ms", "count": 1},
            {"template": "WARNING: LLM provider rate limit 429 Too Many Requests", "count": 12}
        ]
    }
    
    log_snippet = " ".join([t.get("template", "") for t in evidence_pack.get("log_templates", [])])
    query_text = f"Service: {evidence_pack.get('culprit_service', '')}. Logs: {log_snippet}"
    
    history = diag.retrieve_relevant_playbooks(query_text, k=2)
    
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
3. Phân tích "analysis" trong JSON trả về bắt buộc phải là một phân tích kỹ thuật SRE chuyên nghiệp (bằng TIẾNG VIỆT) được trình bày dưới dạng DÀNH RIÊNG CHO ĐẦU MỤC (Bullet Points) ngắn gọn, rõ ràng theo đúng cấu trúc sau:
   * **Hiện tượng**: <Mô tả cực kỳ ngắn gọn hiện tượng>
   * **Nguyên nhân**: <Lý do gốc rễ gây ra lỗi. Ở ĐÂY BẮT BUỘC PHẢI GHI RÕ TRÍCH DẪN NGUỒN THAM CHIẾU (ví dụ: 'Nguồn tham chiếu: INC-4 từ Bedrock Knowledge Base')>
   * **Bằng chứng**:
     - *Jaeger Trace*: Bottleneck tại dịch vụ llm.
     - *Logs (Drain3)*: Mẫu log lỗi '[Template]' xuất hiện [X] lần.
   * **Vùng ảnh hưởng (Blast Radius)**: <Vùng ảnh hưởng...>
 
Trả về kết quả ở định dạng JSON duy nhất như sau:
{{
  "analysis": "Phân tích...",
  "matched_incident": "INC-4",
  "proposed_action": "toggle-tf-flag",
  "action_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=true",
  "rollback_command": "kubectl -n techx-tf3 exec deploy/flagd -- toggle-flag tf3-ai-summary-disabled=false",
  "confidence_score": 0.95
}}
"""
    
    body = json.dumps({
        "inferenceConfig": {"maxTokens": 1000, "temperature": 0.1, "topP": 0.9},
        "messages": [{"role": "user", "content": [{"text": prompt}]}]
    })
    
    response = diag.bedrock_client.invoke_model(
        modelId=diag.model_id,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    
    resp_text = response.get("body").read().decode("utf-8")
    response_body = json.loads(resp_text)
    llm_text = response_body["output"]["message"]["content"][0]["text"]
    
    parsed = diag.clean_and_parse_json(llm_text)
    
    # Ghi toàn bộ kết quả chẩn đoán tiếng Việt chi tiết ra file text để tránh lỗi Console Charset
    out_file = "scratch/test_rag_citation_output.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("=== KẾT QUẢ TRUY XUẤT HÌNH ẢNH KB (RAG CHUNKS) ===\n")
        f.write(history)
        f.write("\n\n=== PHẢN HỒI THÔ TỪ LLM (RAW TEXT) ===\n")
        f.write(llm_text)
        f.write("\n\n=== KẾT QUẢ PARSE JSON SAU KHI LỌC DỮ LIỆU ===\n")
        f.write(json.dumps(parsed, indent=2, ensure_ascii=False))
        
    print(f"SUCCESS: Result written to {out_file}")

if __name__ == "__main__":
    test()
