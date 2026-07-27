#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import time
import logging
import psycopg2
from dotenv import load_dotenv

# Ensure we can import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from guardrails.input_filter import check_input

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("db_migration_worker")

def migrate_is_safe_column(batch_size=500, sleep_between=0.1):
    """Quét toàn bộ reviews cũ bằng Regex Guardrails và cập nhật cột is_safe."""
    load_dotenv()
    
    db_conn_str = os.environ.get('DB_CONNECTION_STRING')
    if not db_conn_str:
        logger.error("DB_CONNECTION_STRING environment variable is not set!")
        sys.exit(1)
        
    logger.info("Connecting to database...")
    try:
        conn = psycopg2.connect(db_conn_str)
        cursor = conn.cursor()
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)
        
    # Temporarily disable Bedrock Guardrail for DB migration scan to avoid Bedrock cost and latency
    original_guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID")
    if "BEDROCK_GUARDRAIL_ID" in os.environ:
        del os.environ["BEDROCK_GUARDRAIL_ID"]
        
    try:
        # Run SQL schema migration first
        logger.info("Step 1: Running schema migration from migration.sql...")
        migration_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration.sql")
        if os.path.exists(migration_file):
            with open(migration_file, 'r', encoding='utf-8') as f:
                sql_commands = f.read()
            cursor.execute(sql_commands)
            conn.commit()
            logger.info("Schema migration successful.")
        else:
            logger.warning("migration.sql not found! Running ALTER TABLE inline...")
            cursor.execute("ALTER TABLE reviews.productreviews ADD COLUMN IF NOT EXISTS is_safe BOOLEAN DEFAULT TRUE;")
            cursor.execute("CREATE INDEX IF NOT EXISTS productreviews_prod_safe_idx ON reviews.productreviews (product_id, is_safe);")
            conn.commit()
            
        # Step 2: Batch scanning and updating
        logger.info("Step 2: Starting background batch scan of reviews...")
        offset = 0
        total_processed = 0
        total_updated = 0
        
        while True:
            # Fetch a batch of reviews
            query = "SELECT id, description FROM reviews.productreviews ORDER BY id LIMIT %s OFFSET %s;"
            cursor.execute(query, (batch_size, offset))
            rows = cursor.fetchall()
            
            if not rows:
                break
                
            logger.info(f"Processing batch: offset={offset}, size={len(rows)}...")
            
            for row_id, description in rows:
                desc_str = description or ""
                # Evaluate safety using input_filter (Regex only)
                result = check_input(desc_str)
                if not result.is_safe:
                    logger.warning(
                        f"Review ID {row_id} is unsafe! Reason: {result.blocked_reason}. "
                        f"Text: '{desc_str[:60]}...'"
                    )
                    cursor.execute(
                        "UPDATE reviews.productreviews SET is_safe = FALSE WHERE id = %s;",
                        (row_id,)
                    )
                    total_updated += 1
                total_processed += 1
                
            conn.commit()
            offset += batch_size
            time.sleep(sleep_between)  # Avoid putting too much I/O pressure on Postgres
            
        logger.info(f"Migration scan completed! Total processed: {total_processed}, Marked unsafe: {total_updated}")
        
    except Exception as e:
        logger.error(f"Error during migration scan: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        # Restore environment variable
        if original_guardrail_id:
            os.environ["BEDROCK_GUARDRAIL_ID"] = original_guardrail_id
        cursor.close()
        conn.close()
        logger.info("Database connection closed.")

if __name__ == "__main__":
    migrate_is_safe_column(batch_size=500, sleep_between=0.1)
