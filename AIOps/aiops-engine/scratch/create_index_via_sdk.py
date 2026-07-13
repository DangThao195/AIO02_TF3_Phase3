import os
import sys
import json
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import AWS_REGION

region = "us-east-1"
collection_endpoint = "trr490g18kpnofbpupe3.us-east-1.aoss.amazonaws.com"  # Host name only (no https://)
index_name = "sre-playbooks-index"

def run():
    key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    awsauth = AWS4Auth(key_id, secret_key, region, 'aoss')
    
    print(f"Initializing OpenSearch Serverless client for host: {collection_endpoint}...")
    client = OpenSearch(
        hosts=[{'host': collection_endpoint, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection
    )
    
    index_body = {
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
    
    print(f"Sending create index request for: {index_name}...")
    try:
        response = client.indices.create(index=index_name, body=index_body)
        print(f"SUCCESS: Index created successfully: {response}")
    except Exception as e:
        print(f"FAILED to create index: {e}")

if __name__ == "__main__":
    run()
