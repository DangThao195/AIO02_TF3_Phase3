import os
import sqlite3
import boto3

def load_env():
    """Nạp biến môi trường từ tệp .env (khi chạy local)"""
    for path in [".env", "../.env", "../../.env"]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            break

# Nạp config
load_env()

# Cấu hình từ môi trường
S3_BUCKET_NAME = os.getenv("PRODUCTS_S3_BUCKET", "techx-products-catalog-us")
AWS_REGION = os.getenv("BEDROCK_KB_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "default")
BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID")
BEDROCK_KB_DATA_SOURCE_ID = os.getenv("BEDROCK_KB_DATA_SOURCE_ID") or os.getenv("DATA_SOURCE_ID")

def get_db_connection():
    """Kết nối database (tự động chọn PostgreSQL trên EKS hoặc SQLite ở local)"""
    db_conn_str = os.getenv("DB_CONNECTION_STRING")
    if db_conn_str:
        import psycopg2
        print("Connecting to PostgreSQL on EKS...")
        params = {}
        for pair in db_conn_str.split():
            k, v = pair.split("=")
            params[k] = v
        return psycopg2.connect(
            host=params.get("host", "postgresql"),
            database=params.get("dbname", "otel"),
            user=params.get("user", "otelu"),
            password=params.get("password", "otelp"),
            port=int(params.get("port", 5432))
        )
    else:
        db_path = os.path.join("server-test", "shopping.db")
        if not os.path.exists(db_path):
            db_path = os.path.join("../server-test", "shopping.db")
        print(f"Connecting to SQLite local: {db_path}...")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

def serialize_product(p):
    """Gói sản phẩm thành định dạng text tự nhiên"""
    p_id = p.get("id") or p.get("product_id")
    name = p.get("name")
    desc = p.get("description", "")
    price = p.get("price_units") if p.get("price_units") is not None else p.get("price", 0)
    cats = p.get("categories", "")
    return (
        f"Product ID: {p_id}\n"
        f"Product Name: {name}\n"
        f"Price: {price} USD\n"
        f"Category: {cats}\n"
        f"Description: {desc}\n"
    )

def upload_to_s3(s3_client, file_name, content):
    """Upload tệp lên S3"""
    s3_client.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=f"products/{file_name}",
        Body=content.encode("utf-8"),
        ContentType="text/plain"
    )

def trigger_bedrock_sync():
    """Gọi AWS API để ra lệnh cho Bedrock KB sync với S3"""
    if not BEDROCK_KB_ID or not BEDROCK_KB_DATA_SOURCE_ID:
        print("⚠️ Bỏ qua kích hoạt Sync Bedrock KB: Thiếu BEDROCK_KB_ID hoặc BEDROCK_KB_DATA_SOURCE_ID trong config.")
        return
        
    print(f"Kích hoạt đồng bộ Bedrock Knowledge Base (ID: {BEDROCK_KB_ID})...")
    # Sử dụng Session và AWS Profile tương ứng nếu có
    if os.getenv("AWS_EXECUTION_ENV") or not AWS_PROFILE:
        # Nếu chạy trên Lambda / ECS Task (dùng IAM Role trực tiếp, không profile)
        client = boto3.client("bedrock-agent", region_name=AWS_REGION)
    else:
        session = boto3.Session(profile_name=AWS_PROFILE)
        client = session.client("bedrock-agent", region_name=AWS_REGION)
        
    try:
        response = client.start_ingestion_job(
            knowledgeBaseId=BEDROCK_KB_ID,
            dataSourceId=BEDROCK_KB_DATA_SOURCE_ID
        )
        job_id = response["ingestionJob"]["ingestionJobId"]
        print(f"✅ Ingestion Job đã bắt đầu chạy thành công! ID: {job_id}")
    except Exception as e:
        print(f"❌ Lỗi kích hoạt đồng bộ Bedrock KB: {e}")

def lambda_handler(event, context):
    """Hàm entry point nếu chạy trên AWS Lambda"""
    run_sync()
    return {"statusCode": 200, "body": "Sync completed successfully"}

def run_sync():
    print(f"=== SYNC PROCESS START (S3 Bucket: {S3_BUCKET_NAME}) ===")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Quét sản phẩm từ Database
    products = []
    try:
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("SELECT id, name, description, categories, price_units FROM products")
            rows = cursor.fetchall()
            for r in rows:
                products.append({
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "categories": r["categories"],
                    "price_units": r["price_units"]
                })
        else:
            cursor.execute("SELECT id, name, description, categories, price_units FROM products")
            rows = cursor.fetchall()
            for r in rows:
                products.append({
                    "id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "categories": r[3] if isinstance(r[3], str) else ",".join(r[3]),
                    "price_units": r[4]
                })
    except Exception as e:
        print(f"❌ Lỗi truy vấn DB: {e}")
        return
    finally:
        cursor.close()
        conn.close()

    print(f"Tìm thấy {len(products)} sản phẩm. Bắt đầu đẩy lên S3...")

    # 2. Khởi tạo S3 Client
    if os.getenv("AWS_EXECUTION_ENV") or not AWS_PROFILE:
        s3 = boto3.client("s3", region_name=AWS_REGION)
    else:
        session = boto3.Session(profile_name=AWS_PROFILE)
        s3 = session.client("s3", region_name=AWS_REGION)

    # 3. Đẩy từng sản phẩm lên S3
    success_count = 0
    for p in products:
        p_id = p["id"]
        content = serialize_product(p)
        file_name = f"{p_id}.txt"
        try:
            upload_to_s3(s3, file_name, content)
            success_count += 1
        except Exception as e:
            print(f"❌ Lỗi upload sản phẩm {p_id}: {e}")
            
    print(f"Đã tải lên {success_count}/{len(products)} tệp tin mô tả sản phẩm.")

    # 4. Kích hoạt đồng bộ RAG
    if success_count > 0:
        trigger_bedrock_sync()
        
    print("=== PROCESS COMPLETED ===")

if __name__ == "__main__":
    run_sync()
