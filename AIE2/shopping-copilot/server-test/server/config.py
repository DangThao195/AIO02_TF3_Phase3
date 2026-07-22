import os
from pathlib import Path


DB_PATH: str = os.environ.get("DB_PATH", str(Path(__file__).resolve().parent.parent / "shopping.db"))
GRPC_PORT: int = int(os.environ.get("GRPC_PORT", "50051"))
