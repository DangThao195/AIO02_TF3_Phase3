import os

# Đọc cấu hình từ file .env nếu có (giúp chạy thử local không cần gán biến môi trường thủ công)
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# Map external AWS credentials if present in env to standard AWS env vars for boto3
if os.getenv("EXTERNAL_AWS_ACCESS_KEY_ID"):
    os.environ["AWS_ACCESS_KEY_ID"] = os.getenv("EXTERNAL_AWS_ACCESS_KEY_ID")
if os.getenv("EXTERNAL_AWS_SECRET_ACCESS_KEY"):
    os.environ["AWS_SECRET_ACCESS_KEY"] = os.getenv("EXTERNAL_AWS_SECRET_ACCESS_KEY")
if os.getenv("EXTERNAL_AWS_REGION"):
    os.environ["AWS_DEFAULT_REGION"] = os.getenv("EXTERNAL_AWS_REGION")
    os.environ["AWS_REGION"] = os.getenv("EXTERNAL_AWS_REGION")


# API Configuration
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-server.techx-tf3.svc.cluster.local")
JAEGER_URL = os.getenv("JAEGER_URL", "http://jaeger-query.techx-tf3.svc.cluster.local")
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://opensearch.techx-tf3.svc.cluster.local:9200")

# AWS Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID", None)
S3_BUCKET_NAME = os.getenv("AIOPS_S3_BUCKET", "tf3-aiops-models-197826770971")

# Simulation Sandbox Server URL
SIMULATION_SERVER_URL = os.getenv("SIMULATION_SERVER_URL", "http://localhost:8000")


# Slack/Discord webhook for notifications & Human Approval
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")



# CMDR Safety Whitelists & Invariants (C6 Contract)
WHITELISTED_ACTIONS = ["scale", "restart", "toggle-tf-flag", "cache-flush", "breaker-force"]

# Max actions allowed per incident per hour
MAX_ACTIONS_PER_HOUR = 3

# Max time allowed for execution and verification (in seconds)
EXECUTION_TIMEOUT_SECONDS = 300  # 5 minutes

# Verification monitoring period after action (in seconds)
VERIFICATION_PERIOD_SECONDS = 300  # 5 minutes

# Shared simulation state for Sandbox mode
SIMULATION_STATE = {
    "scenario": "stable",
    "remediated": False
}
