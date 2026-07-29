# Hướng Dẫn Thiết Lập RAG Bedrock Knowledge Base (KB) cho Sản Phẩm

Tài liệu này hướng dẫn cách thiết lập AWS Bedrock Knowledge Base để làm Vector Database lưu trữ danh mục sản phẩm của tệp `products`, phục vụ tính năng tìm kiếm ngữ cảnh (RAG) cho Shopping Copilot.

---

## 1. Cơ Chế Hoạt Động
1. Sử dụng script `scripts/sync_db_to_s3.py` để quét bảng sản phẩm trong DB (SQLite/PostgreSQL) và ghi đè dưới dạng các file văn bản riêng lẻ `.txt` (ví dụ `OLJCESPC7Z.txt`) lên S3.
2. AWS Bedrock Knowledge Base được cấu hình trỏ vào thư mục S3 này để tiến hành Vector hóa dữ liệu bằng model `titan-embed-text-v2:0` và đồng bộ vào OpenSearch Serverless.
3. Khi Chatbot nhận câu hỏi, nó sẽ truy vấn KB này để lấy ra Product ID phù hợp nhất.

---

## 2. Bước 1: Tạo S3 Staging Bucket và đẩy dữ liệu lên S3
1. Truy cập AWS S3 Console, tạo một Bucket mới có tên ví dụ: `techx-products-catalog-<id>` (hoặc dùng bucket có sẵn của TF).
2. Mở file `.env` của dự án và cấu hình biến môi trường:
   ```env
   PRODUCTS_S3_BUCKET=techx-products-catalog-<id>
   ```
3. Chạy script để serialize sản phẩm từ DB và đẩy lên S3:
   ```bash
   python scripts/sync_db_to_s3.py
   ```
   *Kiểm tra trên S3 Console, bạn sẽ thấy thư mục `products/` chứa các tệp như `OLJCESPC7Z.txt`.*

---

## 3. Bước 2: Tạo Bedrock Knowledge Base trên AWS Console

> ⚠️ **LƯU Ý QUAN TRỌNG:** Hãy chuyển vùng AWS Console sang **`us-east-1` (N. Virginia)** trước khi bắt đầu. Vùng Singapore (`ap-southeast-1`) hiện chưa hỗ trợ model Titan Text Embeddings v2.

1. Truy cập **Amazon Bedrock** Console tại vùng **`us-east-1`** $\rightarrow$ chọn **Knowledge bases** $\rightarrow$ chọn **Create knowledge base**.
2. **Knowledge base details:**
   * Điền tên: `shopping-products-kb`
   * IAM Role: Chọn **Create and use a new service role**.
3. **Data source:**
   * Chọn nguồn dữ liệu: **Amazon S3**.
   * Trỏ S3 URI đến thư mục vừa tạo: `s3://techx-products-catalog-<id>/products/`.
4. **Embed model & Vector store:**
   * Embed model: Chọn **Titan Text Embeddings v2** (`amazon.titan-embed-text-v2:0`).
   * Vector database: Chọn **Quick create a new vector store** (tự động tạo OpenSearch Serverless Collection) hoặc trỏ vào OpenSearch Serverless của dự án.
5. **Ingestion (Đồng bộ):**
   * Sau khi tạo thành công KB, nhấn vào Data Source vừa tạo và click **Sync** để tiến hành Vector hóa lần đầu.

---

## 4. Bước 3: Cấu hình Copilot sử dụng Bedrock KB

1. Lấy **Knowledge Base ID** (chuỗi 10 ký tự, ví dụ: `PUW7NE1CYA`) từ trang chi tiết KB vừa tạo.
2. Thêm ID này vào file `.env` của Shopping Copilot:
   ```env
   BEDROCK_KB_ID=PUW7NE1CYA
   ```
3. Khởi chạy lại chatbot. Từ lúc này, luồng tìm kiếm `search_products_v2` sẽ tự động kích hoạt chiến lược `BedrockRAGStrategy` chạy song song cùng SQL để tăng độ chính xác tìm kiếm ngữ nghĩa!

---

## 5. Tự động hóa đồng bộ (Sync) 2-trong-1

Chúng ta sử dụng tệp script hợp nhất **[`scripts/cron_sync_and_sync_kb.py`](file:///d:/Cloude-DevOps/Phase-3/AIO02_TF3_Phase3/AIE2/shopping-copilot/scripts/cron_sync_and_sync_kb.py)**. Khi chạy, script này sẽ quét Database, đẩy tệp lên S3 và kích hoạt đồng bộ hóa Bedrock KB ngay lập tức.

Trước khi chạy, hãy cấu hình các biến môi trường sau trong tệp `.env`:
```env
PRODUCTS_S3_BUCKET=techx-products-catalog-us
BEDROCK_KB_ID=PUW7NE1CYA
BEDROCK_KB_DATA_SOURCE_ID=wz9ke-data-source  # ID của S3 Data Source lấy từ Bedrock Console
BEDROCK_KB_REGION=us-east-1
```

Để chạy thử nghiệm thủ công ở local:
```bash
python scripts/cron_sync_and_sync_kb.py
```

---

## 6. Cách Thiết lập AWS Lambda (Nếu chạy Serverless ngoài Cluster)

Để chạy tệp sync này dưới dạng AWS Lambda:
1. **Đóng gói mã nguồn:** 
   Lambda cần driver PostgreSQL (nếu chạy thật) và thư viện AWS. Hãy zip tệp `scripts/cron_sync_and_sync_kb.py` kèm theo thư viện `psycopg2-binary`.
2. **Cấu hình Lambda Function:**
   * Run time: Python 3.10+
   * Handler: `cron_sync_and_sync_kb.lambda_handler`
   * **VPC:** Chọn VPC của EKS Cluster, chọn Private Subnet và Security Group cho phép kết nối đến PostgreSQL (`port 5432`).
3. **IAM Role cho Lambda:**
   Gắn chính sách cho phép Lambda ghi dữ liệu lên S3 và gọi Bedrock KB:
   ```json
   {
       "Version": "2012-10-17",
       "Statement": [
           {
               "Effect": "Allow",
               "Action": ["s3:PutObject", "bedrock:StartIngestionJob"],
               "Resource": [
                   "arn:aws:s3:::techx-products-catalog-us/products/*",
                   "arn:aws:bedrock:us-east-1:197826770971:knowledge-base/PUW7NE1CYA"
               ]
           }
       ]
   }
   ```
4. **Trigger:** Thêm Trigger **EventBridge (CloudWatch Events)** chạy định kỳ `rate(1 hour)` để tự động chạy Lambda mỗi giờ.

---

## 7. Cách Thiết lập Kubernetes CronJob trên EKS (Khuyến Nghị - Đơn Giản Nhất)

Do PostgreSQL nằm trong mạng nội bộ K8s của EKS, chạy một CronJob định kỳ bên trong cluster là cách đơn giản và an toàn nhất (không cần NAT Gateway hay cấu hình VPC cho Lambda).

CDO có thể tạo một file manifest `cronjob.yaml` và áp dụng vào cluster:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: shopping-copilot-sync-kb
  namespace: techx-tf3
spec:
  schedule: "0 * * * *"  # Chạy mỗi giờ một lần
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: techx-corp  # Sử dụng Service Account có quyền S3/Bedrock
          containers:
          - name: sync-agent
            image: <ACCOUNT>.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:1.0-shopping-copilot
            command: ["python", "scripts/cron_sync_and_sync_kb.py"]
            env:
            - name: DB_CONNECTION_STRING
              value: "host=postgresql user=otelu password=otelp dbname=otel"
            - name: PRODUCTS_S3_BUCKET
              value: "techx-products-catalog-us"
            - name: BEDROCK_KB_ID
              value: "PUW7NE1CYA"
            - name: BEDROCK_KB_DATA_SOURCE_ID
              value: "wz9ke-data-source"
            - name: BEDROCK_KB_REGION
              value: "us-east-1"
          restartPolicy: OnFailure
```

CDO chỉ cần chạy:
```bash
kubectl apply -f cronjob.yaml
```
Hạ tầng EKS sẽ tự động lên lịch chạy script, kết nối trực tiếp PostgreSQL và dùng quyền của Service Account để đẩy dữ liệu lên S3, kích hoạt Bedrock KB Sync chéo vùng hoàn toàn tự động!
