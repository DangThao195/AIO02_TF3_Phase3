import os
import sys
import time
import json
import uuid
import boto3
import urllib.parse
import urllib.request
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

# Đảm bảo đọc đúng config môi trường từ config.py
sys.path.append(os.path.dirname(__file__))
from config import AWS_REGION

def sign_and_send_aoss_request(session, method, url, body_str):
    """Ký request AWS SigV4 và gửi truy vấn tới OpenSearch Serverless API."""
    credentials = session.get_credentials()
    frozen_creds = credentials.get_frozen_credentials()
    
    headers = {
        'Content-Type': 'application/json',
        'host': urllib.parse.urlparse(url).netloc
    }
    
    # Tạo AWS Request và thực hiện ký SigV4
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

def deploy_kb():
    # Load AWS Credentials từ môi trường đã được config.py map
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_DEFAULT_REGION", AWS_REGION)
    
    if not key_id or not secret_key:
        print("ERROR: AWS credentials not found in env!")
        return

    print("=== STARTING CLOUD-NATIVE BEDROCK KB DEPLOYMENT ===")
    session = boto3.Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    s3_client = session.client('s3')
    iam_client = session.client('iam')
    aoss_client = session.client('opensearchserverless')
    bedrock_client = session.client('bedrock-agent')
    
    unique_id = str(uuid.uuid4())[:8]
    bucket_name = f"techx-aiops-playbooks-{unique_id}"
    collection_name = f"aiops-kb-{unique_id}"
    role_name = f"AmazonBedrockExecutionRoleForKB-{unique_id}"
    index_name = "sre-playbooks-index"
    
    # -------------------------------------------------------------
    # BƯỚC 1: Tạo S3 Bucket và Upload Playbook
    # -------------------------------------------------------------
    print(f"\n[STEP 1] Creating S3 Bucket: {bucket_name}...")
    try:
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print("-> S3 Bucket created successfully.")
        
        # Upload INCIDENT_HISTORY.md
        playbook_path = "../phase3/onboarding/INCIDENT_HISTORY.md"
        if not os.path.exists(playbook_path):
            playbook_path = "phase3/onboarding/INCIDENT_HISTORY.md"
        if not os.path.exists(playbook_path):
            playbook_path = "INCIDENT_HISTORY.md"
            
        print(f"-> Uploading file {playbook_path} to S3...")
        s3_client.upload_file(playbook_path, bucket_name, "playbooks/INCIDENT_HISTORY.md")
        print("-> Upload completed.")
    except Exception as e:
        print(f"ERROR at Step 1: {e}")
        return

    # -------------------------------------------------------------
    # BƯỚC 2: Tạo IAM Role cấp quyền cho Bedrock
    # -------------------------------------------------------------
    print(f"\n[STEP 2] Creating IAM Role: {role_name}...")
    try:
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "bedrock.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {
                            "aws:SourceAccount": session.client('sts').get_caller_identity()['Account']
                        }
                    }
                }
            ]
        }
        
        role_res = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Role for Bedrock to read S3 and write OpenSearch Serverless"
        )
        role_arn = role_res['Role']['Arn']
        print(f"-> IAM Role created. ARN: {role_arn}")
        
        # Tạo inline policy cho S3
        s3_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:ListBucket"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{bucket_name}",
                        f"arn:aws:s3:::{bucket_name}/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel"
                    ],
                    "Resource": [
                        f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
                    ]
                }
            ]
        }
        
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="BedrockKBExecutionS3Policy",
            PolicyDocument=json.dumps(s3_policy)
        )
        print("-> Attached S3 and Titan policy.")
    except Exception as e:
        print(f"ERROR at Step 2: {e}")
        return

    # -------------------------------------------------------------
    # BƯỚC 3: Khởi tạo OpenSearch Serverless Collection (Vector Search)
    # -------------------------------------------------------------
    print(f"\n[STEP 3] Creating OpenSearch Serverless Collection: {collection_name}...")
    try:
        # 3.1 Encryption Policy
        enc_policy_name = f"enc-{unique_id}"
        aoss_client.create_security_policy(
            name=enc_policy_name,
            type='encryption',
            policy=json.dumps({
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{collection_name}"]
                    }
                ],
                "AWSOwnedKey": True
            })
        )
        
        # 3.2 Network Policy (Public cho Dev/Test)
        net_policy_name = f"net-{unique_id}"
        aoss_client.create_security_policy(
            name=net_policy_name,
            type='network',
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": [f"collection/{collection_name}"]
                        },
                        {
                            "ResourceType": "dashboard",
                            "Resource": [f"collection/{collection_name}"]
                        }
                    ],
                    "AllowFromPublic": True
                }
            ])
        )
        
        # 3.3 Data Access Policy
        user_arn = session.client('sts').get_caller_identity()['Arn']
        data_policy_name = f"data-{unique_id}"
        aoss_client.create_access_policy(
            name=data_policy_name,
            type='data',
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": [f"collection/{collection_name}"],
                            "Permission": [
                                "aoss:CreateCollectionItems",
                                "aoss:DeleteCollectionItems",
                                "aoss:UpdateCollectionItems",
                                "aoss:DescribeCollectionItems"
                            ]
                        },
                        {
                            "ResourceType": "index",
                            "Resource": [f"index/{collection_name}/*"],
                            "Permission": [
                                "aoss:CreateIndex",
                                "aoss:DeleteIndex",
                                "aoss:UpdateIndex",
                                "aoss:DescribeIndex",
                                "aoss:ReadDocument",
                                "aoss:WriteDocument"
                            ]
                        }
                    ],
                    "Principal": [
                        role_arn, # Quyền cho Bedrock Role
                        user_arn  # Quyền cho User cá nhân để chạy init index
                    ]
                }
            ])
        )
        
        # 3.4 Tạo Collection thực tế
        coll_res = aoss_client.create_collection(
            name=collection_name,
            type='VECTORSEARCH',
            description="Vector DB for AIOps Playbooks KB"
        )
        collection_arn = coll_res['createCollectionDetail']['arn']
        print(f"-> Collection created. ARN: {collection_arn}")
        
        # Đợi Collection chuyển sang trạng thái ACTIVE (Thường mất ~3-5 phút)
        print("-> Waiting for Collection to become ACTIVE (takes 2-3 mins)...")
        while True:
            desc = aoss_client.batch_get_collection(names=[collection_name])
            status = desc['collectionDetails'][0]['status']
            print(f"   Current status: {status}")
            if status == 'ACTIVE':
                collection_endpoint = desc['collectionDetails'][0]['collectionEndpoint']
                break
            time.sleep(20)
            
        print(f"-> Collection ACTIVE. Endpoint: {collection_endpoint}")
        
        # Cập nhật IAM Role policy bổ sung quyền ghi OpenSearch Serverless
        aoss_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "aoss:APIAccessAll"
                    ],
                    "Resource": [
                        collection_arn
                    ]
                }
            ]
        }
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="BedrockKBExecutionAOSSPolicy",
            PolicyDocument=json.dumps(aoss_policy)
        )
        
    except Exception as e:
        print(f"ERROR at Step 3: {e}")
        return

    # Đợi 15 giây để IAM Policy đồng bộ hoàn toàn
    time.sleep(15)

    # -------------------------------------------------------------
    # BƯỚC 4: Tạo Vector Index trong OpenSearch Serverless
    # -------------------------------------------------------------
    print(f"\n[STEP 4] Creating Vector Index: '{index_name}'...")
    try:
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
        
        # Gửi request PUT có chữ ký SigV4 để tạo index
        code, resp = sign_and_send_aoss_request(session, 'PUT', url, json.dumps(index_mapping))
        if code in [200, 201]:
            print("-> Index created successfully.")
        else:
            print(f"ERROR creating Index (Code {code}): {resp}")
            return
    except Exception as e:
        print(f"ERROR at Step 4: {e}")
        return

    # -------------------------------------------------------------
    # BƯỚC 5: Khởi tạo Bedrock Knowledge Base & Data Source
    # -------------------------------------------------------------
    print(f"\n[STEP 5] Creating Bedrock Knowledge Base...")
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
        print(f"-> Bedrock KB initialized. ID: {kb_id}")
        
        # 5.2 Tạo Data Source liên kết tới S3 Bucket
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
        
        # 5.3 Kích hoạt đồng bộ hóa dữ liệu (Sync / Ingestion Job)
        print("-> Triggering ingestion job (sync)...")
        sync_res = bedrock_client.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        job_id = sync_res['ingestionJob']['ingestionJobId']
        print(f"-> Ingestion Job started. ID: {job_id}")
        
        print("\n=== CLOUD-NATIVE DEPLOYMENT COMPLETE ===")
        print(f"KNOWLEDGE_BASE_ID: {kb_id}")
        print("Tip: Save this KNOWLEDGE_BASE_ID to configure your environment!")
        
    except Exception as e:
        print(f"ERROR at Step 5: {e}")
        return

if __name__ == "__main__":
    deploy_kb()
