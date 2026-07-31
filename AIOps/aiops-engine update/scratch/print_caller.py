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
    
    sts = session.client('sts')
    aoss = session.client('opensearchserverless')
    
    print("=== AWS CALLER IDENTITY ===")
    try:
        identity = sts.get_caller_identity()
        print(f"UserId: {identity['UserId']}")
        print(f"Account: {identity['Account']}")
        print(f"Arn: {identity['Arn']}")
    except Exception as e:
        print(f"Error getting identity: {e}")
        
    print("\n=== AOSS DATA ACCESS POLICIES ===")
    try:
        policies = aoss.list_access_policies(type='data')
        for p in policies.get('accessPolicySummaries', []):
            print(f"\nPolicy Name: {p['name']}")
            policy_detail = aoss.get_access_policy(name=p['name'], type='data')
            print(json.dumps(json.loads(policy_detail['accessPolicyDetail']['policy']), indent=2))
    except Exception as e:
        print(f"Error listing access policies: {e}")

if __name__ == "__main__":
    import json
    check()
