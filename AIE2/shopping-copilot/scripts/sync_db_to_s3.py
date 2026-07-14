import os
import re
import sqlite3
import boto3

# AWS Configuration
S3_BUCKET_NAME = os.getenv("PRODUCTS_S3_BUCKET", "techx-products-catalog-f6230446")
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", None)

def get_db_connection():
    """Kết nối database (tự động chọn PostgreSQL trên EKS hoặc SQLite ở local)"""
    db_conn_str = os.getenv("DB_CONNECTION_STRING")
    if db_conn_str:
        # Import động để tránh lỗi thiếu thư viện khi chạy ở local chỉ cần SQLite
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        print("Connecting to PostgreSQL on EKS...")
        # Parse connection string: host=postgresql user=otelu password=otelp dbname=otel
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
        # Chạy local (SQLite)
        db_path = os.path.join("server-test", "shopping.db")
        if not os.path.exists(db_path):
            db_path = os.path.join("../server-test", "shopping.db") # fallback
        print(f"Connecting to SQLite local: {db_path}...")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

def serialize_product(p):
    """Định dạng bản ghi product thành text tự nhiên phục vụ RAG"""
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

def upload_to_s3(file_name, content):
    """Upload tệp text lên S3 Staging Bucket"""
    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3", region_name=AWS_REGION)
    
    try:
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=f"products/{file_name}",
            Body=content.encode("utf-8"),
            ContentType="text/plain"
        )
        print(f"-> Uploaded: products/{file_name}")
    except Exception as e:
        print(f"❌ Lỗi upload sản phẩm {file_name}: {e}")

def run():
    print(f"=== DB TO S3 SYNC START (Bucket: {S3_BUCKET_NAME}) ===")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Query danh sách sản phẩm
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
            # PostgreSQL
            cursor.execute("SELECT id, name, description, categories, price_units FROM products")
            rows = cursor.fetchall()
            for r in rows:
                # categories in PG is text or list, let's normalize
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

    # 2. Xử lý & Upload từng sản phẩm thành file text
    for p in products:
        p_id = p["id"]
        content = serialize_product(p)
        file_name = f"{p_id}.txt"
        upload_to_s3(file_name, content)
        
    print("=== SYNC COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run()
