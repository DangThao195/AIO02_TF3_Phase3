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

## 5. Tự động hóa đồng bộ (Sync) khi cập nhật sản phẩm mới
Mỗi khi có sản phẩm mới hoặc thay đổi mô tả sản phẩm trong Database:
1. Chạy lại script để ghi đè dữ liệu mới lên S3:
   ```bash
   python scripts/sync_db_to_s3.py
   ```
2. Gọi API để Bedrock KB cập nhật các thay đổi trên S3 (Chỉ cập nhật file mới/thay đổi):
   ```python
   import boto3
   client = boto3.client('bedrock-agent', region_name='us-east-1')
   client.start_ingestion_job(
       knowledgeBaseId="<BEDROCK_KB_ID>",
       dataSourceId="<DATA_SOURCE_ID>"
   )
   ```
   *(Đoạn code này có thể tích hợp vào Lambda cron-job hoặc sự cố/automation playbooks của CDO)*
