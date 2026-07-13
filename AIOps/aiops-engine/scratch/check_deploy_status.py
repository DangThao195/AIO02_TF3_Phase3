import os
import sys
import boto3

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import AWS_REGION

def check():
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_DEFAULT_REGION", AWS_REGION)
    
    session = boto3.Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    aoss_client = session.client('opensearchserverless')
    bedrock_client = session.client('bedrock-agent')
    
    print("Checking OpenSearch Serverless Collections...")
    try:
        colls = aoss_client.list_collections()
        for c in colls.get('collectionSummaries', []):
            print(f"- Collection: {c['name']} (ID: {c['id']}) Status: {c['status']}")
    except Exception as e:
        print(f"Error checking collections: {e}")
        
    print("\nChecking Bedrock Knowledge Bases...")
    try:
        kbs = bedrock_client.list_knowledge_bases()
        for k in kbs.get('knowledgeBaseSummaries', []):
            print(f"- KB: {k['name']} (ID: {k['knowledgeBaseId']}) Status: {k['status']}")
    except Exception as e:
        print(f"Error checking KBs: {e}")

if __name__ == "__main__":
    check()
