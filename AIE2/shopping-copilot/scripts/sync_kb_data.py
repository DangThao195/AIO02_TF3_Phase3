"""
sync_kb_data.py
===============
Đồng bộ toàn bộ dữ liệu cần thiết cho RAG vào Bedrock KB một lần:
  1. Export bảng reviewproduct từ PostgreSQL -> file .txt -> S3 (reviews/)
  2. Tạo Data Source thứ 2 trong Bedrock KB (nếu chưa có) trỏ vào s3://techx-products-catalog-2026/reviews/
  3. Trigger sync cho cả 2 Data Sources

Chạy:
  python sync_kb_data.py

Yêu cầu:
  - Port-forward EKS PostgreSQL đang chạy tại localhost:5433 (dùng 5433 để tránh xung đột với PostgreSQL local)
  - File .env chứa đầy đủ DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import io
import time
import json
import boto3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
AWS_REGION      = os.getenv("BEDROCK_KB_REGION", "us-east-1")
KB_ID           = os.getenv("BEDROCK_KB_ID", "UCTITOWFHE")
S3_BUCKET       = os.getenv("PRODUCTS_S3_BUCKET", "techx-products-catalog-2026")
S3_REVIEWS_PREFIX = "reviews/"
ROLE_ARN        = "arn:aws:iam::197826770971:role/service-role/AmazonBedrockExecutionRoleForKnowledgeBase_acy87"

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5433")
DB_NAME     = os.getenv("DB_NAME", "otel")
DB_USER     = os.getenv("DB_USER", "otelu")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ── AWS Clients ──────────────────────────────────────────────────────────────
session       = boto3.Session(profile_name=os.getenv("AWS_PROFILE", "default"))
s3_client     = session.client("s3", region_name=AWS_REGION)
bedrock_agent = session.client("bedrock-agent", region_name=AWS_REGION)


# ── Step 1: Export reviews từ PostgreSQL → S3 ────────────────────────────────
def export_reviews_to_s3():
    print("=" * 60)
    print("STEP 1: Export reviewproduct -> S3")
    print("=" * 60)

    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            database=DB_NAME, user=DB_USER, password=DB_PASSWORD
        )
    except Exception as e:
        print(f"[ERROR] Cannot connect to PostgreSQL: {e}")
        return False

    cur = conn.cursor()

    # Lấy tên cột thực tế
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'reviews' AND table_name = 'productreviews'
        ORDER BY ordinal_position
    """)
    columns = [row[0] for row in cur.fetchall()]
    print(f"[INFO] Table columns: {columns}")

    # Lấy toàn bộ review
    cur.execute('SELECT * FROM reviews.productreviews ORDER BY 1')
    rows = cur.fetchall()
    print(f"[INFO] Total reviews: {len(rows)}")

    if not rows:
        print("[WARN] No review data found in database.")
        conn.close()
        return True

    # Group reviews by product_id (thường là cột thứ 2 hoặc có tên product_id)
    product_id_col = None
    for candidate in ["product_id", "productid", "product"]:
        if candidate in columns:
            product_id_col = columns.index(candidate)
            break
    if product_id_col is None:
        product_id_col = 1  # fallback: cột thứ 2

    reviews_by_product = {}
    for row in rows:
        pid = str(row[product_id_col])
        if pid not in reviews_by_product:
            reviews_by_product[pid] = []
        reviews_by_product[pid].append(row)

    # Format và upload từng file per product
    uploaded = 0
    for pid, product_reviews in reviews_by_product.items():
        lines = [f"Product ID: {pid}", f"Product Reviews ({len(product_reviews)} total):"]
        for review in product_reviews:
            review_dict = dict(zip(columns, review))
            # Tạo dòng review tổng hợp (hiển thị tất cả cột)
            parts = []
            for col, val in review_dict.items():
                if col != columns[product_id_col]:  # bỏ product_id vì đã có ở trên
                    parts.append(f"{col}: {val}")
            lines.append(f"  - {' | '.join(parts)}")

        content = "\n".join(lines)
        s3_key = f"{S3_REVIEWS_PREFIX}{pid}_reviews.txt"

        try:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/plain; charset=utf-8"
            )
            uploaded += 1
        except Exception as e:
            print(f"[ERROR] Failed to upload {s3_key}: {e}")

    conn.close()
    print(f"[OK] Uploaded {uploaded} review files to s3://{S3_BUCKET}/{S3_REVIEWS_PREFIX}")
    return True


# ── Step 2: Đảm bảo Data Source reviews tồn tại trong KB ────────────────────
def ensure_reviews_datasource():
    print("\n" + "=" * 60)
    print("STEP 2: Ensure 'reviews' Data Source exists in Bedrock KB")
    print("=" * 60)

    # Kiểm tra Data Source đã tồn tại chưa
    resp = bedrock_agent.list_data_sources(knowledgeBaseId=KB_ID)
    existing = {ds["name"]: ds["dataSourceId"] for ds in resp.get("dataSourceSummaries", [])}
    print(f"[INFO] Existing data sources: {list(existing.keys())}")

    if "techx-s3-reviews" in existing:
        reviews_ds_id = existing["techx-s3-reviews"]
        print(f"[INFO] Reviews Data Source already exists: {reviews_ds_id}")
    else:
        print("[INFO] Creating new Data Source for reviews...")
        ds_resp = bedrock_agent.create_data_source(
            knowledgeBaseId=KB_ID,
            name="techx-s3-reviews",
            description="Product reviews from PostgreSQL -> S3",
            dataDeletionPolicy="RETAIN",
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{S3_BUCKET}",
                    "inclusionPrefixes": [S3_REVIEWS_PREFIX]
                }
            }
        )
        reviews_ds_id = ds_resp["dataSource"]["dataSourceId"]
        print(f"[OK] Created reviews Data Source: {reviews_ds_id}")

    return existing, reviews_ds_id


# ── Step 3: Trigger sync cho cả 2 Data Sources ──────────────────────────────
def trigger_sync(existing_ds: dict, reviews_ds_id: str):
    print("\n" + "=" * 60)
    print("STEP 3: Trigger sync for all Data Sources")
    print("=" * 60)

    all_ds_ids = list(existing_ds.values())
    if reviews_ds_id not in all_ds_ids:
        all_ds_ids.append(reviews_ds_id)

    job_ids = []
    for ds_id in all_ds_ids:
        try:
            job = bedrock_agent.start_ingestion_job(
                knowledgeBaseId=KB_ID,
                dataSourceId=ds_id
            )
            job_id = job["ingestionJob"]["ingestionJobId"]
            job_ids.append((ds_id, job_id))
            print(f"[OK] Sync triggered | DataSource: {ds_id} | Job: {job_id}")
        except Exception as e:
            print(f"[WARN] Could not trigger sync for {ds_id}: {e}")

    # Chờ tất cả job hoàn tất
    print("\n[INFO] Waiting for all sync jobs to complete...")
    for ds_id, job_id in job_ids:
        while True:
            status_resp = bedrock_agent.get_ingestion_job(
                knowledgeBaseId=KB_ID,
                dataSourceId=ds_id,
                ingestionJobId=job_id
            )
            job_info = status_resp["ingestionJob"]
            status = job_info["status"]
            stats = job_info["statistics"]
            print(f"  [{ds_id}] Status: {status} | Scanned: {stats['numberOfDocumentsScanned']} | Indexed: {stats['numberOfNewDocumentsIndexed']}")

            if status in ("COMPLETE", "FAILED"):
                break
            time.sleep(5)

    print("\n[DONE] All sync jobs finished!")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ok = export_reviews_to_s3()
    if not ok:
        print("[ABORT] Skipping KB sync due to DB connection error.")
        exit(1)

    existing_ds, reviews_ds_id = ensure_reviews_datasource()
    trigger_sync(existing_ds, reviews_ds_id)

    print("\n" + "=" * 60)
    print("All done! Bedrock KB now contains both products and reviews.")
    print(f"  KB ID: {KB_ID}")
    print(f"  S3 Bucket: s3://{S3_BUCKET}/")
    print(f"    - products/  (product catalog)")
    print(f"    - reviews/   (product reviews from PostgreSQL)")
    print("=" * 60)
