# Hướng dẫn: Chuyển đổi từ OpenSearch Serverless → OpenSearch Managed

**Mục tiêu:** Giảm chi phí từ ~$350+/tháng xuống ~$25-50/tháng  
**Thời gian thực hiện:** ~1-2 giờ  
**Người thực hiện:** CDO (cần quyền quản trị AWS)  
**Ảnh hưởng:** Chatbot mất tính năng RAG trong ~30 phút (thời gian sync lại KB)

---

## Bước 0: Ghi lại thông tin hiện tại trước khi xóa

Lưu lại các ID sau (cần khi tạo lại KB):

| Thông tin | Giá trị hiện tại |
|---|---|
| Bedrock KB ID | `VGXRPNYPPA` |
| Data Source ID | `KWOKJG5BSI` |
| S3 Bucket | `techx-products-catalog-2026` |
| Region (Bedrock) | `us-east-1` |
| AWS Account | `197826770971` |

> ⚠️ **Không xóa S3 Bucket.** Dữ liệu sản phẩm trên S3 sẽ được tái sử dụng cho KB mới.

---

## Bước 1: Tạo OpenSearch Managed Cluster mới

Vào **AWS Console → Amazon OpenSearch Service → Create domain**:

```
Domain name:       techx-products-search
Deployment type:   Development and testing   ← QUAN TRỌNG, chọn loại này
Instance type:     t3.small.search           ← ~$25/tháng
Number of nodes:   1                         ← 1 node là đủ cho dev
Storage:           EBS gp3, 10 GB
Encryption:        Enable (bắt buộc để Bedrock KB kết nối được)
Access policy:     Only use fine-grained access control
Region:            us-east-1                 ← Phải cùng vùng với Bedrock KB
```

Chờ cluster tạo xong (~15 phút), ghi lại **Domain endpoint** dạng:
```
https://search-techx-products-search-xxxx.us-east-1.es.amazonaws.com
```

---

## Bước 2: Xóa Bedrock Knowledge Base cũ

Vào **AWS Console → Amazon Bedrock → Knowledge Bases → VGXRPNYPPA**:
1. Chọn **Delete Knowledge Base**
2. Xác nhận xóa

> ℹ️ **Giải thích:** Bedrock KB không thể đổi vector store sau khi tạo — bắt buộc phải xóa và tạo lại KB mới trỏ vào OpenSearch Managed.

---

## Bước 3: Tạo Bedrock Knowledge Base mới trỏ vào OpenSearch Managed

Vào **Amazon Bedrock → Knowledge Bases → Create Knowledge Base**:

**Phần Knowledge Base details:**
```
Name:            techx-products-kb-v2
IAM Role:        Tạo mới hoặc dùng role hiện có (cần quyền bedrock + opensearch)
```

**Phần Data source:**
```
Source type:     Amazon S3
S3 URI:          s3://techx-products-catalog-2026/
```

**Phần Vector store — chọn "Choose existing vector store":**
```
Vector store type:   OpenSearch Service (Managed)  ← KHÔNG phải Serverless
OpenSearch domain:   techx-products-search (vừa tạo ở Bước 1)
Vector index name:   products-index
Metadata field:      AMAZON_BEDROCK_METADATA
Text field:          AMAZON_BEDROCK_TEXT_CHUNK
Vector field:        AMAZON_BEDROCK_EMBEDDING (1024 dimensions)
```

**Embedding model:**
```
Model:  Amazon Titan Text Embeddings v2   ← Giữ nguyên như cũ
```

Sau khi tạo xong, ghi lại **KB ID mới** (dạng: `XXXXXXXXXX`).

---

## Bước 4: Sync dữ liệu vào KB mới

Vào KB mới → tab **Data sources** → chọn data source → **Sync**:

```bash
# Hoặc chạy bằng AWS CLI:
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <KB_ID_MỚI> \
  --data-source-id <DATA_SOURCE_ID_MỚI> \
  --region us-east-1
```

Chờ job hoàn thành (~10-15 phút tùy số lượng sản phẩm).

---

## Bước 5: Cập nhật biến môi trường

Cập nhật file `.env` trong project:

```env
# Thay KB ID cũ bằng KB ID mới
BEDROCK_KB_ID=<KB_ID_MỚI>
```

Nếu deploy trên EKS, CDO cần cập nhật ConfigMap:
```bash
kubectl edit configmap shopping-copilot-config -n techx-tf3
# Đổi BEDROCK_KB_ID sang giá trị mới
```

Sau đó restart pod chatbot:
```bash
kubectl rollout restart deployment/shopping-copilot -n techx-tf3
```

---

## Bước 6: Xóa OpenSearch Serverless collection cũ

Chỉ thực hiện bước này **sau khi đã xác nhận RAG hoạt động bình thường** với KB mới.

Vào **AWS Console → Amazon OpenSearch Service → Serverless → Collections**:
1. Tìm collection đang dùng (liên kết với KB `VGXRPNYPPA`)
2. Chọn **Delete**

> ✅ Sau khi xóa, chi phí OpenSearch Serverless dừng tính ngay lập tức.

---

## Kiểm tra RAG hoạt động sau migration

Chạy chatbot và test một câu hỏi cần RAG:
```
User: "tìm kính thiên văn phù hợp cho trẻ em"
Expected: Chatbot trả về sản phẩm kèm footer "(Nguồn: AWS Bedrock KB (RAG))"
```

Hoặc chạy script test:
```bash
cd AIE2/shopping-copilot
python tests/run_pipeline.py --ids search_telescope
```

---

## Kế hoạch rollback (nếu có sự cố)

Nếu KB mới có vấn đề, revert `BEDROCK_KB_ID` về giá trị cũ `VGXRPNYPPA`:
```bash
# .env
BEDROCK_KB_ID=VGXRPNYPPA
```
> ℹ️ KB cũ + OpenSearch Serverless vẫn còn tồn tại cho đến Bước 6, có thể dùng lại ngay.

---

## So sánh chi phí dự kiến

| | Trước migration | Sau migration |
|---|---|---|
| OpenSearch Serverless | ~$350+/tháng | $0 |
| OpenSearch Managed (t3.small) | $0 | ~$25/tháng |
| **Tổng** | **~$350+/tháng** | **~$25/tháng** |
| **Tiết kiệm** | | **~$325/tháng (~93%)** |

---

## Lưu ý khi lên Production

Khi hệ thống cần scale lên production thật, CDO có thể migrate ngược lại sang Serverless hoặc nâng cấp instance lên `r6g.large.search` bằng cách:
1. Tạo Bedrock KB mới trỏ vào OpenSearch Serverless/Managed lớn hơn (lặp lại Bước 3-5)
2. Chỉ cần đổi `BEDROCK_KB_ID` — code chatbot không thay đổi gì
