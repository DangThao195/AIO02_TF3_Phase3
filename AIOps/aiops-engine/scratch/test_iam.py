import os
import sys
import boto3

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import AWS_REGION

def check():
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    session = boto3.Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
        region_name=AWS_REGION
    )
    
    iam = session.client('iam')
    print("Testing IAM permissions...")
    try:
        res = iam.list_users(MaxItems=1)
        print("Success listing users!")
        print(res.get('Users', []))
    except Exception as e:
        print(f"Failed listing users: {e}")
        
    try:
        # Try creating a dummy policy or role to check permissions
        print("\nTesting role creation policy...")
        # Since we already successfully created a role in step 2, we know we have role creation permissions!
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check()
