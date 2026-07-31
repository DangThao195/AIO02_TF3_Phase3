# 📋 TỔNG HỢP BIẾN MÔI TRƯỜNG (ENVIRONMENT VARIABLES) CHO PRODUCTION

Tài liệu này tổng hợp toàn bộ các biến môi trường (`Environment Variables`) của dịch vụ **Shopping Copilot API**, phân loại rõ ràng phục vụ việc kiểm tra và cấu hình **K8s ConfigMap & Secrets** cho đội **CDO**.

---

## 1. ⚡ GENAI CACHE & SESSION MEMORY CONFIGS (VALKEY CACHE)

> **Ghi chú:** Các biến này quản lý tầng Caching Titan Embeddings v2, chống rò rỉ PII, và quản lý Session State trên ElastiCache Valkey.

| Tên Biến | Mặc định Production | Mô tả / Mục đích | Loại K8s |
| :--- | :--- | :--- | :--- |
| `CACHE_SCHEMA_VERSION` | `"7"` | **BẮT BUỘC BUMP UP** khi data thay đổi: Tự động invalidation toàn bộ cache cũ khi rollout pod — không cần FLUSHDB. | ConfigMap |
| `SEMANTIC_CACHE_THRESHOLD` | `"0.93"` | Ngưỡng Cosine Similarity an toàn mới cho Titan Vector Embeddings (chống HIT sai câu). | ConfigMap |
| `VALKEY_URL` | `rediss://:5dZhhRiPLXDDLuQFv4OaZs2z5IPUIx4T@master.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com:6379/1?ssl_cert_reqs=none` | Connection URI kết nối ElastiCache Valkey DB 1. | Secret / ConfigMap |
| `VALKEY_HOST` | `master.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com` | Hostname của ElastiCache Valkey Cluster. | ConfigMap |
| `VALKEY_REMOTE_PORT` | `6379` | Port mặc định của Valkey ElastiCache Cluster. | ConfigMap |
| `STRICT_VALKEY` | `"true"` | Bắt buộc chạy 100% qua Valkey (không dùng fallback JSON local trên prod). | ConfigMap |

---

## 2. 🗄️ DATABASE CONNECTION (AWS RDS POSTGRESQL)

> **Ghi chú:** Quản lý kết nối tới RDS PostgreSQL cho schema `catalog`, `reviews`, và `copilot.user_memory`.

| Tên Biến | Mặc định Production | Mô tả / Mục đích | Loại K8s |
| :--- | :--- | :--- | :--- |
| `DB_HOST` | `techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com` | Endpoint RDS PostgreSQL Cluster. | ConfigMap |
| `DB_PORT` | `5432` | Port kết nối PostgreSQL trực tiếp trên AWS K8s. | ConfigMap |
| `DB_USER` | `otelu` | Database User (Master / Owner). | ConfigMap / Secret |
| `DB_PASSWORD` | `"w8kS1Ruk-nKRm_2G0t1vGw>0!RL7"` | Password tài khoản RDS PostgreSQL. | Secret |
| `DB_NAME` | `otel` | Tên Database chính (`otel`). | ConfigMap |
| `DB_SSLMODE` | `prefer` | Chế độ kết nối SSL/TLS với RDS (`prefer` hoặc `require`). | ConfigMap |
| `DB_CONNECTION_STRING` | `"host=techx-tf3-postgres... port=5432 user=otelu password='...' dbname=otel sslmode=prefer"` | String kết nối đầy đủ (Optional fallback). | Secret / ConfigMap |

---

## 3. 🤖 AWS BEDROCK LLM & GUARDRAILS CONFIGS

> **Ghi chú:** Quản lý kết nối tới Bedrock Converse API (Nova Pro / Nova Lite) và Guardrails.

| Tên Biến | Mặc định Production | Mô tả / Mục đích | Loại K8s |
| :--- | :--- | :--- | :--- |
| `BEDROCK_MODEL_ID` | `apac.amazon.nova-pro-v1:0` | ID LLM chính xử lý Intent & Agent Reasoning. | ConfigMap |
| `BEDROCK_FALLBACK_MODEL_ID` | `apac.amazon.nova-lite-v1:0` | ID LLM dự phòng khi Nova Pro bị Rate Limit / Circuit Breaker. | ConfigMap |
| `BEDROCK_REGION` | `ap-southeast-1` | AWS Region chạy Bedrock LLM. | ConfigMap |
| `BEDROCK_GUARDRAIL_ID` | `3ab7r29x59x4` | ID của AWS Bedrock Guardrail (Safety & Content Filter). | ConfigMap |
| `BEDROCK_GUARDRAIL_VERSION` | `DRAFT` | Version của Bedrock Guardrail (`DRAFT` hoặc số phiên bản). | ConfigMap |
| `BEDROCK_GUARDRAIL_REGION` | `us-east-1` | AWS Region cài đặt Bedrock Guardrail. | ConfigMap |

---

## 4. 📚 BEDROCK KNOWLEDGE BASE (RAG) & OPENSEARCH

> **Ghi chú:** Cấu hình RAG Vector Search & Review Knowledge Base qua AWS Bedrock Knowledge Base.

| Tên Biến | Mặc định Production | Mô tả / Mục đích | Loại K8s |
| :--- | :--- | :--- | :--- |
| `BEDROCK_KB_ID` | `UCTITOWFHE` | Bedrock Knowledge Base ID cho sản phẩm. | ConfigMap |
| `BEDROCK_KB_DATA_SOURCE_ID` | `OJQNE88GXV` | Data Source ID catalog sản phẩm. | ConfigMap |
| `REVIEWS_DATA_SOURCE_ID` | `M2YA7L7GEA` | Data Source ID reviews sản phẩm. | ConfigMap |
| `PRODUCTS_S3_BUCKET` | `techx-products-catalog-2026` | S3 Bucket lưu trữ tài liệu RAG. | ConfigMap |
| `OPENSEARCH_MASTER_USERNAME` | `admin` | Username OpenSearch Vector Index. | Secret |
| `OPENSEARCH_MASTER_PASSWORD` | `*9moAsBNKCwW4HogX*X-` | Password OpenSearch Vector Index. | Secret |
| `DOMAIN_ENDPOINT` | `https://search-techx-products-search-booilkgm5kisxgyqqjo4xjpcke.us-east-1.es.amazonaws.com` | Endpoint OpenSearch Domain. | ConfigMap |

---

## 5. 🔗 INTERNAL MICROSERVICE ENDPOINTS (K8S CLUSTER DNS)

> **Ghi chú:** Cấu hình DNS của 6 Microservices phục vụ Tool Calling trên cụm EKS.

| Tên Biến | Giá trị Production (K8s DNS) | Giá trị Local Dev |
| :--- | :--- | :--- |
| `CATALOG_ADDR` | `product-catalog:8080` | `localhost:3550` |
| `CART_ADDR` | `cart:8080` | `localhost:7070` |
| `REVIEWS_ADDR` | `product-reviews:3551` | `localhost:9090` |
| `RECO_ADDR` | `recommendation:8080` | `localhost:8081` |
| `CURRENCY_ADDR` | `currency:8080` | `localhost:7001` |
| `SHIPPING_ADDR` | `http://shipping:8080` | `http://localhost:50052` |

---

## 6. ⚙️ APP SERVER CONFIGS

| Tên Biến | Mặc định Production | Mô tả / Mục đích | Loại K8s |
| :--- | :--- | :--- | :--- |
| `COPILOT_PORT` | `8001` | Port ứng dụng FastAPI uvicorn lắng nghe. | ConfigMap |
| `AWS_REGION` | `ap-southeast-1` | Region mặc định cho AWS SDK boto3. | Container Env |


---

### ⚠️ LƯU Ý QUAN TRỌNG KHI CDO DEPLOY:
1. **Cache Invalidation (Không FLUSHDB):** Khi cần invalidate cache (thay đổi schema sản phẩm, pricing logic, v.v.), chỉ cần **tăng `CACHE_SCHEMA_VERSION`** lên bất kỳ số nào cao hơn hiện tại (hiện tại: `"7"`). Cache cũ sẽ bị bỏ qua tự động (MISS) và rebuild dần — **không cần FLUSHDB hay restart Valkey**.
2. **ConfigMap Revision Bump:** Sau khi cập nhật `CACHE_SCHEMA_VERSION` hoặc `SEMANTIC_CACHE_THRESHOLD`, bắt buộc phải bump tag `techx.io/configmap-revision` trong deployment manifest để Kubernetes trigger rolling update Pod mới nhận env mới.
3. **Container Env Override:** Biến `AWS_REGION` nên được khai báo trực tiếp ở `spec.containers[].env` để tránh bị Webhook mặc định đè giá trị.
4. **VALKEY_URL là Secret:** URL chứa password — phải đặt trong K8s `Secret`, không đặt plain text trong `ConfigMap`.
