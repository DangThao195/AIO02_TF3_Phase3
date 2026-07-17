# Configuration & Environment

> **Phase 3 — Integration & Production** | *File: `.env`, `tools/service_config.py`*

## Environment Variables

### LLM Backend
| Variable | Default | Description |
|---|---|---|
| `BEDROCK_MODEL_ID` | `apac.amazon.nova-lite-v1:0` | Bedrock model ID |
| `BEDROCK_REGION` | `ap-southeast-1` | AWS region |
| `BEDROCK_GUARDRAIL_ID` | — | Bedrock Guardrail ID (L2b) |
| `BEDROCK_GUARDRAIL_VERSION` | `DRAFT` | Guardrail version |
| `BEDROCK_GUARDRAIL_REGION` | `us-east-1` | Guardrail AWS region |

### Service Addresses (EKS gRPC/REST)
| Variable | Default | Description |
|---|---|---|
| `CATALOG_ADDR` | `localhost:3550` | ProductCatalog gRPC |
| `CART_ADDR` | `localhost:7070` | Cart gRPC |
| `REVIEWS_ADDR` | `localhost:9090` | ProductReview gRPC |
| `RECO_ADDR` | `localhost:8081` | Recommendation gRPC |
| `CURRENCY_ADDR` | `localhost:7001` | Currency gRPC |
| `SHIPPING_ADDR` | `http://localhost:50052` | Shipping REST |

### Redis Cache (Phase 3 Production)
| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `CACHE_ENABLED` | `true` | Enable/disable cache |

### Database (Search Flow 1 + Sync)
| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_USER` | `otelu` | DB user |
| `DB_PASSWORD` | `otelp` | DB password |
| `DB_NAME` | `otel` | DB name |
| `DB_CONNECTION_STRING` | `host=localhost port=5432 user=otelu password=otelp dbname=otel` | Full connection string |

### RAG Knowledge Base
| Variable | Default | Description |
|---|---|---|
| `BEDROCK_KB_ID` | — | Bedrock Knowledge Base ID |
| `BEDROCK_KB_DATA_SOURCE_ID` | — | KB Data Source ID |
| `PRODUCTS_S3_BUCKET` | `techx-products-catalog-2026` | S3 bucket for product data |

### Confirmation HMAC
| Variable | Default | Description |
|---|---|---|
| `COPILOT_CONFIRMATION_SECRET` | `tf3-copilot-dev-secret-change-in-prod` | HMAC secret key (production: Kubernetes Secret) |

### Server
| Variable | Default | Description |
|---|---|---|
| `PORT` | `8001` | HTTP server port |
| `MOCK_EKS` | `false` | Mock EKS gRPC services |
| `LANGGRAPH_ENABLED` | `true` | Enable LangGraph path |

### AWS
| Variable | Default | Description |
|---|---|---|
| `AWS_PROFILE` | `default` | AWS CLI profile |
| `AWS_REGION` | `ap-southeast-1` | AWS region |

## Service Config Module

**File:** `tools/service_config.py`

```python
import os

CATALOG_ADDR = os.environ.get("CATALOG_ADDR", "localhost:3550")
CART_ADDR = os.environ.get("CART_ADDR", "localhost:7070")
REVIEWS_ADDR = os.environ.get("REVIEWS_ADDR", "localhost:9090")
RECO_ADDR = os.environ.get("RECO_ADDR", "localhost:8081")
CURRENCY_ADDR = os.environ.get("CURRENCY_ADDR", "localhost:7001")
SHIPPING_ADDR = os.environ.get("SHIPPING_ADDR", "http://localhost:50052")
```

## .env File (Git-ignored)

File `.env` ở project root, không commit lên Git. Production dùng Kubernetes Secrets.

## Kubernetes Secret Mapping (EKS)

| Env Variable | K8s Secret Key |
|---|---|
| `COPILOT_CONFIRMATION_SECRET` | `confirmation-secret` |
| `DB_PASSWORD` | `db-password` |
| `BEDROCK_GUARDRAIL_ID` | `guardrail-id` |

## Secret Rules

1. **Không commit giá trị thật** vào file tracked
2. Production secret dùng Kubernetes Secrets (AWS Secrets Manager hoặc SSM Parameter Store)
3. Local dev dùng `.env` (gitignored)
4. `COPILOT_CONFIRMATION_SECRET` mặc định là dev secret — production bắt buộc đổi
