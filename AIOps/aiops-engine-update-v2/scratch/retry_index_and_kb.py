import os
import sys
import time
import json
import boto3
import urllib.parse
import urllib.request
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import AWS_REGION

# Cấu hình cứng các giá trị đã tạo ở task trước
region = "us-east-1"
collection_endpoint = "https://trr490g18kpnofbpupe3.us-east-1.aoss.amazonaws.com"
collection_arn = "arn:aws:aoss:us-east-1:197826770971:collection/trr490g18kpnofbpupe3"
role_arn = "arn:aws:iam::197826770971:role/AmazonBedrockExecutionRoleForKB-f6230446"
bucket_name = "techx-aiops-playbooks-f6230446"
index_name = "sre-playbooks-index"
unique_id = "f6230446"

def sign_and_send_aoss_request(session, method, url, body_str):
    credentials = session.get_credentials()
    frozen_creds = credentials.get_frozen_credentials()
    
    headers = {
        'Content-Type': 'application/json',
        'host': urllib.parse.urlparse(url).netloc
    }
    
    aws_req = AWSRequest(method=method, url=url, data=body_str, headers=headers)
    signer = SigV4Auth(frozen_creds, 'aoss', session.region_name)
    signer.add_auth(aws_req)
    
    req = urllib.request.Request(
        url=url,
        data=body_str.encode('utf-8') if body_str else None,
        headers=dict(aws_req.headers),
        method=method
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except Exception as e:
        return 500, str(e)

def retry():
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    session = boto3.Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    bedrock_client = session.client('bedrock-agent')
    
    print("=== RETRYING INDEX CREATION ===")
    url = f"{collection_endpoint}/{index_name}"
    index_mapping = {
        "settings": {
            "index.knn": True
        },
        "mappings": {
            "properties": {
                "id": {
                    "type": "keyword"
                },
                "vector": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {
                        "name": "hnsw",
                        "engine": "nmslib",
                        "space_type": "cosinesimil",
                        "parameters": {}
                    }
                },
                "text": {
                    "type": "text"
                },
                "meta": {
                    "type": "text"
                }
            }
        }
    }
    
    code, resp = sign_and_send_aoss_request(session, 'PUT', url, json.dumps(index_mapping))
    if code in [200, 201]:
        print("-> SUCCESS: Index created successfully on retry!")
    else:
        print(f"-> FAILED (Code {code}): {resp}")
        print("Maybe permission is still propagating or User ARN format has mismatch in policy. Let's inspect.")
        return

    print("\n=== CREATING BEDROCK KNOWLEDGE BASE ===")
    try:
        kb_res = bedrock_client.create_knowledge_base(
            name=f"aiops-playbooks-kb-{unique_id}",
            description="Co so tri thuc chẩn đoán sự cố cho AIOps Engine",
            roleArn=role_arn,
            knowledgeBaseConfiguration={
                'type': 'VECTOR',
                'vectorKnowledgeBaseConfiguration': {
                    'embeddingModelArn': f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
                }
            },
            storageConfiguration={
                'type': 'OPENSEARCH_SERVERLESS',
                'opensearchServerlessConfiguration': {
                    'collectionArn': collection_arn,
                    'vectorIndexName': index_name,
                    'fieldMapping': {
                        'vectorField': 'vector',
                        'textField': 'text',
                        'metadataField': 'meta'
                    }
                }
            }
        )
        
        kb_id = kb_res['knowledgeBase']['knowledgeBaseId']
        print(f"-> Bedrock KB created. ID: {kb_id}")
        
        print("-> Linking S3 Data Source...")
        ds_res = bedrock_client.create_data_source(
            knowledgeBaseId=kb_id,
            name=f"s3-playbooks-{unique_id}",
            description="Nguon du lieu playbook SRE tu S3",
            dataSourceConfiguration={
                'type': 'S3',
                's3DataSourceConfiguration': {
                    'bucketArn': f"arn:aws:s3:::{bucket_name}",
                    'inclusionPrefixes': ['playbooks/']
                }
            }
        )
        ds_id = ds_res['dataSource']['dataSourceId']
        print(f"-> S3 Data Source linked successfully. ID: {ds_id}")
        
        print("-> Triggering sync job...")
        sync_res = bedrock_client.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        job_id = sync_res['ingestionJob']['ingestionJobId']
        print(f"-> Ingestion Job started. ID: {job_id}")
        print("\n=== ALL STEPS COMPLETED SUCCESSFULLY ===")
        print(f"KNOWLEDGE_BASE_ID: {kb_id}")
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    retry()
