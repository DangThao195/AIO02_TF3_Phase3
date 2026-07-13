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

# Cấu hình cứng các giá trị đã tạo từ task trước
region = "us-east-1"
collection_endpoint = "https://trr490g18kpnofbpupe3.us-east-1.aoss.amazonaws.com"
collection_arn = "arn:aws:aoss:us-east-1:197826770971:collection/trr490g18kpnofbpupe3"
role_arn = "arn:aws:iam::197826770971:role/AmazonBedrockExecutionRoleForKB-f6230446"
bucket_name = "techx-aiops-playbooks-f6230446"
index_name = "sre-playbooks-index"
unique_id = "f6230446"

def sign_and_send_aoss_request(credentials_dict, method, url, body_str):
    """Ký request AWS SigV4 sử dụng credentials tạm thời của assumed role."""
    headers = {
        'Content-Type': 'application/json',
        'host': urllib.parse.urlparse(url).netloc
    }
    
    # Tạo AWS Request
    aws_req = AWSRequest(method=method, url=url, data=body_str, headers=headers)
    
    # Ký SigV4 bằng các key tạm thời
    from botocore.credentials import Credentials
    creds = Credentials(
        access_key=credentials_dict['AccessKeyId'],
        secret_key=credentials_dict['SecretAccessKey'],
        token=credentials_dict['SessionToken']
    )
    
    signer = SigV4Auth(creds, 'aoss', region)
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

def run():
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    session = boto3.Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    sts_client = session.client('sts')
    bedrock_client = session.client('bedrock-agent')
    
    # -------------------------------------------------------------
    # BƯỚC 1: Assume Role của Bedrock để mượn quyền data plane aoss
    # -------------------------------------------------------------
    print(f"Assuming IAM Role: {role_arn}...")
    try:
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName="AOSSIndexCreatorSession",
            DurationSeconds=900
        )
        temp_creds = assumed_role['Credentials']
        print("-> Successfully assumed role and retrieved temporary credentials.")
    except Exception as e:
        print(f"ERROR assuming role: {e}")
        return

    # -------------------------------------------------------------
    # BƯỚC 2: Tạo Index bằng quyền của Assumed Role
    # -------------------------------------------------------------
    print(f"\nCreating Vector Index '{index_name}' via assumed role...")
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
    
    code, resp = sign_and_send_aoss_request(temp_creds, 'PUT', url, json.dumps(index_mapping))
    if code in [200, 201]:
        print("-> SUCCESS: Index created successfully using assumed role credentials!")
    else:
        print(f"-> FAILED (Code {code}): {resp}")
        return

    # -------------------------------------------------------------
    # BƯỚC 3: Tạo Bedrock Knowledge Base & Data Source
    # -------------------------------------------------------------
    print(f"\nCreating Bedrock Knowledge Base...")
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
        print(f"-> Bedrock KB created successfully. ID: {kb_id}")
        
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
        
        print("\n=== CLOUD-NATIVE DEPLOYMENT COMPLETED ===")
        print(f"KNOWLEDGE_BASE_ID: {kb_id}")
        
    except Exception as e:
        print(f"ERROR creating KB: {e}")

if __name__ == "__main__":
    run()
