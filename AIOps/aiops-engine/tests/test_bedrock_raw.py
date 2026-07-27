import os
import json
import boto3
import sys

# Load env variables from .env
env_path = "aiops-engine/.env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

ext_key_id = os.getenv("EXTERNAL_AWS_ACCESS_KEY_ID")
ext_secret_key = os.getenv("EXTERNAL_AWS_SECRET_ACCESS_KEY")
ext_region = os.getenv("EXTERNAL_AWS_REGION", "us-east-1")
model_id = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")

print(f"AWS region: {ext_region}")
print(f"Model ID: {model_id}")

try:
    bedrock_client = boto3.client(
        service_name="bedrock-runtime",
        region_name=ext_region,
        aws_access_key_id=ext_key_id,
        aws_secret_access_key=ext_secret_key
    )
    
    # Test simple query
    prompt = "Hello, write a JSON object with a single key 'message' containing 'hello world' and nothing else."
    
    body = json.dumps({
        "inferenceConfig": {
            "maxTokens": 200,
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
    
    response = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    
    resp_text = response.get("body").read().decode("utf-8")
    print("\n--- Raw Response ---")
    print(resp_text)
    
    response_body = json.loads(resp_text)
    llm_text = response_body["output"]["message"]["content"][0]["text"]
    print("\n--- Extracted Text ---")
    print(llm_text)
    
except Exception as e:
    print(f"\nERROR: {str(e)}")
    import traceback
    traceback.print_exc()
