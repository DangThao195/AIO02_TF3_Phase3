import os
import re
import json
import boto3
import sys

# Đảm bảo import được config.py từ thư mục hiện tại
sys.path.append(os.path.dirname(__file__))
from config import AWS_REGION

def load_playbooks():
    paths = [
        "../phase3/onboarding/INCIDENT_HISTORY.md",
        "phase3/onboarding/INCIDENT_HISTORY.md",
        "INCIDENT_HISTORY.md"
    ]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError("INCIDENT_HISTORY.md not found!")

def parse_playbooks(text):
    # Sử dụng regex lookahead để tách nội dung theo từng tiêu đề "## INC-"
    sections = re.split(r'(?=## INC-\d+)', text)
    playbooks = []
    for sec in sections:
        sec = sec.strip()
        if not sec.startswith("## INC-"):
            continue
        
        # Trích xuất mã ID (ví dụ: INC-1) và Tiêu đề
        header_match = re.match(r'## (INC-\d+)\s*·\s*(.*?)\s*\n', sec)
        if header_match:
            incident_id = header_match.group(1)
            title = header_match.group(2)
        else:
            id_match = re.search(r'INC-\d+', sec)
            incident_id = id_match.group(0) if id_match else "INC-UNKNOWN"
            title = "SRE Incident Playbook"
            
        playbooks.append({
            "incident_id": incident_id,
            "title": title,
            "text": sec
        })
    return playbooks

def get_embedding(bedrock_client, text):
    # Thử gọi Titan Embeddings V2 trước (mặc định 1024 chiều)
    try:
        body = json.dumps({
            "inputText": text,
            "dimensions": 1024,
            "normalize": True
        })
        response = bedrock_client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=body
        )
        response_body = json.loads(response.get('body').read())
        return response_body.get('embedding')
    except Exception as e:
        print(f"Warning: Titan v2 failed ({e}). Falling back to Titan v1...")
        # Fallback về Titan Embeddings V1 (1536 chiều)
        body = json.dumps({
            "inputText": text
        })
        response = bedrock_client.invoke_model(
            modelId="amazon.titan-embed-text-v1",
            contentType="application/json",
            accept="application/json",
            body=body
        )
        response_body = json.loads(response.get('body').read())
        return response_body.get('embedding')

def build_index():
    print("=== STARTING OFFLINE VECTOR INDEXING ===")
    text = load_playbooks()
    playbooks = parse_playbooks(text)
    print(f"Found {len(playbooks)} SRE playbooks to embed.")
    
    # Khởi tạo Bedrock Runtime Client (Tự động kế thừa AWS keys từ config.py gán vào os.environ)
    region = os.getenv("AWS_DEFAULT_REGION", AWS_REGION)
    bedrock_client = boto3.client(
        service_name="bedrock-runtime",
        region_name=region
    )
    
    indexed_playbooks = []
    for pb in playbooks:
        # Loại bỏ các ký tự phi-ASCII khi in để tránh lỗi console Windows
        safe_title = pb['title'].encode('ascii', 'ignore').decode('ascii')
        print(f"-> Embedding playbook for {pb['incident_id']} - '{safe_title}'...")
        try:
            emb = get_embedding(bedrock_client, pb['text'])
            pb['embedding'] = emb
            indexed_playbooks.append(pb)
        except Exception as e:
            print(f"Error: Failed to embed {pb['incident_id']}: {e}")
            
    index_path = os.path.join(os.path.dirname(__file__), "playbooks_vector_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(indexed_playbooks, f, indent=2, ensure_ascii=False)
        
    print(f"\nSUCCESS: Vector index written to {index_path}")

if __name__ == "__main__":
    build_index()
