#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# Python
import os
import hashlib
import simplejson as json

# Postgres
import psycopg2
from psycopg2.pool import ThreadedConnectionPool

import time
import logging

logger = logging.getLogger("database")

def must_map_env(key: str):
    value = os.environ.get(key)
    if value is None:
        raise Exception(f'{key} environment variable must be set')
    return value

db_connection_str = must_map_env('DB_CONNECTION_STRING')
db_pool = None

def init_db_pool(retries: int = 5, delay: float = 2.0):
    global db_pool
    for attempt in range(1, retries + 1):
        try:
            db_pool = ThreadedConnectionPool(minconn=5, maxconn=30, dsn=db_connection_str)
            logger.info("[DATABASE] Connection pool initialized successfully.")
            return db_pool
        except Exception as e:
            logger.warning(f"[DATABASE] Connection pool init attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    # Final attempt or fallback creation
    db_pool = ThreadedConnectionPool(minconn=1, maxconn=30, dsn=db_connection_str)
    return db_pool

try:
    init_db_pool()
except Exception as exc:
    logger.error(f"[DATABASE] Initial pool creation error: {exc}")


def get_db_connection():
    """Retrieve connection from pool with auto-reconnection retry."""
    global db_pool
    if db_pool is None or db_pool.closed:
        init_db_pool()
    try:
        conn = db_pool.getconn()
        if conn.closed != 0:
            db_pool.putconn(conn, close=True)
            conn = db_pool.getconn()
        return conn
    except Exception as e:
        logger.warning(f"[DATABASE] Pool connection failed, re-initializing pool: {e}")
        init_db_pool()
        return db_pool.getconn()


def fetch_product_reviews(product_id):
    try:
        return json.dumps(fetch_product_reviews_from_db(product_id), use_decimal=True)
    except Exception as e:
        return json.dumps({"error": str(e)})

def fetch_product_reviews_from_db(request_product_id):

    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Define the SQL query
            query = "SELECT username, description, score FROM reviews.productreviews WHERE product_id= %s AND is_safe = TRUE"

            # Execute the query
            cursor.execute(query, (request_product_id, ))

            # Fetch all the rows from the query result
            records = cursor.fetchall()
        connection.commit()
        return records

    except Exception as e:
        if connection is not None:
            connection.rollback()
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)

def fetch_avg_product_review_score_from_db(request_product_id):

    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Define the SQL query
            query = "SELECT AVG(score) FROM reviews.productreviews WHERE product_id= %s AND is_safe = TRUE"

            # Execute the query
            cursor.execute(query, (request_product_id, ))

            # Fetch all the rows from the query result
            records = cursor.fetchall()

            # Extract the average score
            if records:
                # records will be a list like [(average_score,)]
                average_score = records[0][0]
            else:
                # Handle the case where no records are returned (e.g., no reviews for the product)
                average_score = None

            # return the score as a string rounded to 1 decimal place
            result = f"{average_score:.1f}"
        connection.commit()
        return result

    except Exception as e:
        if connection is not None:
            connection.rollback()
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)

def get_review_version(product_id: str) -> str:
    """Tính mã phiên bản review dựa trên count + max id.
    Khi có review mới hoặc review bị đánh dấu unsafe → version thay đổi → Cache Miss tự động.
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT COUNT(*), COALESCE(MAX(id), 0)
                FROM reviews.productreviews
                WHERE product_id = %s AND is_safe = TRUE
            """
            cursor.execute(query, (product_id,))
            count, max_id = cursor.fetchone()
        connection.commit()
        raw = f"{product_id}:{count}:{max_id}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]
    except Exception as e:
        if connection is not None:
            connection.rollback()
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)
