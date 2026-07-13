import os


DB_DSN: str = os.environ.get(
    "DB_DSN",
    "postgresql://otelu:otelp@localhost:5432/shopping",
)
GRPC_PORT: int = int(os.environ.get("GRPC_PORT", "50051"))
POOL_MIN_SIZE: int = int(os.environ.get("POOL_MIN_SIZE", "2"))
POOL_MAX_SIZE: int = int(os.environ.get("POOL_MAX_SIZE", "10"))
