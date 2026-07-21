import os
import sys
import boto3
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import AWS_REGION

region = "us-east-1"
collection_arn = "arn:aws:aoss:us-east-1:197826770971:collection/trr490g18kpnofbpupe3"
role_arn = "arn:aws:iam::197826770971:role/AmazonBedrockExecutionRoleForKB-f6230446"
bucket_name = "techx-aiops-playbooks-f6230446"
index_name = "sre-playbooks-index"
unique_id = "f6230446"

def run():
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    session = boto3.Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    bedrock_client = session.client('bedrock-agent')
    
    # Dọn dẹp KB lỗi cũ nếu có
    for old_id in ["PUW7NE1CYA"]:
        try:
            print(f"Cleaning up old KB: {old_id}...")
            bedrock_client.delete_knowledge_base(knowledgeBaseId=old_id)
            time.sleep(2)
        except Exception as e:
            pass
            
    print("Creating Bedrock Knowledge Base (Retrying final link)...")
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
        print(f"-> SUCCESS: Bedrock KB created. ID: {kb_id}")
        
        print("-> Linking S3 Data Source...")
        ds_res = bedrock_client.create_data_source(
            knowledgeBaseId=kb_id,
            name=f"s3-playbooks-{unique_id}",
            description="Nguon du lieu playbook SRE tu S3",
            dataSourceConfiguration={
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': f"arn:aws:s3:::{bucket_name}",
                    'inclusionPrefixes': ['playbooks/']
                }
            }
        )
        ds_id = ds_res['dataSource']['dataSourceId']
        print(f"-> SUCCESS: S3 Data Source linked. ID: {ds_id}")
        
        print("-> Triggering sync job...")
        sync_res = bedrock_client.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        job_id = sync_res['ingestionJob']['ingestionJobId']
        print(f"-> SUCCESS: Ingestion Job started. ID: {job_id}")
        
        print("\n=== CLOUD-NATIVE DEPLOYMENT COMPLETED SUCCESSFULLY ===")
        print(f"BEDROCK_KB_ID={kb_id}")
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    run()
