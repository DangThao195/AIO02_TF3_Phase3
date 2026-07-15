import os
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import psycopg2
    from psycopg2 import pool, extras
except Exception:  # pragma: no cover - optional dependency in local dev
    psycopg2 = None
    pool = None
    extras = None

logger = logging.getLogger(__name__)


@dataclass
class DBConfig:
    host: str = field(
        default_factory=lambda: os.getenv("DB_HOST", "localhost")
    )
    port: int = field(
        default_factory=lambda: int(os.getenv("DB_PORT", "5432"))
    )
    dbname: str = field(
        default_factory=lambda: os.getenv("DB_NAME", "otel")
    )
    user: str = field(
        default_factory=lambda: os.getenv("DB_USER", "otelu")
    )
    password: str = field(
        default_factory=lambda: os.getenv("DB_PASSWORD", "otelp")
    )
    minconn: int = field(
        default_factory=lambda: int(os.getenv("DB_MIN_CONN", "2"))
    )
    maxconn: int = field(
        default_factory=lambda: int(os.getenv("DB_MAX_CONN", "10"))
    )
    connect_timeout: int = field(
        default_factory=lambda: int(os.getenv("DB_TIMEOUT", "30"))
    )
    sslmode: str = field(
        default_factory=lambda: os.getenv("DB_SSLMODE", "disable")
    )
    application_name: str = field(
        default_factory=lambda: os.getenv("DB_APP_NAME", "shopping-copilot")
    )

    def get_connect_kwargs(self) -> dict:
        kwargs: dict = {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "connect_timeout": self.connect_timeout,
            "sslmode": self.sslmode,
            "application_name": self.application_name,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "options": f"-c statement_timeout={self.connect_timeout * 1000}",
        }
        return kwargs

    def get_uri(self) -> str:
        scheme = "postgresql"
        return f"{scheme}://{self.user}:****@{self.host}:{self.port}/{self.dbname}"


_pool = None
_config: Optional[DBConfig] = None


def get_config() -> DBConfig:
    global _config
    if _config is None:
        _config = DBConfig()
    return _config


def init_pool(config: Optional[DBConfig] = None):
    global _pool, _config
    if _pool is not None:
        logger.warning("Pool already initialized; closing existing pool first")
        close_all()

    _config = config or get_config()
    kwargs = _config.get_connect_kwargs()
    logger.info(
        "Initializing PostgreSQL pool — %s min=%s max=%s",
        _config.get_uri(), _config.minconn, _config.maxconn,
    )
    if pool is None:
        raise RuntimeError("psycopg2 is not installed")
    _pool = pool.ThreadedConnectionPool(
        _config.minconn, _config.maxconn, **kwargs
    )
    logger.info("PostgreSQL pool ready")
    return _pool


def _get_pool():
    if _pool is None:
        return init_pool()
    return _pool


def _connection_alive(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


def get_connection() -> Any:
    if pool is None:
        raise RuntimeError("psycopg2 is not installed")
    p = _get_pool()
    conn = p.getconn()
    if not _connection_alive(conn):
        logger.warning("Stale connection detected; discarding and retrying")
        p.putconn(conn, close=True)
        conn = p.getconn()
    return conn


def put_connection(conn) -> None:
    if _pool is None:
        logger.warning("Pool not initialized; closing connection directly")
        try:
            conn.close()
        except Exception:
            pass
        return
    try:
        _pool.putconn(conn)
    except Exception as exc:
        logger.error("Failed to return connection to pool: %s", exc)
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def get_conn():
    conn = get_connection()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        put_connection(conn)


def execute_query(
    conn,
    query: str,
    params: Optional[list] = None,
    *,
    dictionary: bool = True,
) -> list[dict]:
    if extras is None:
        raise RuntimeError("psycopg2 is not installed")
    factory = extras.RealDictCursor if dictionary else None
    with conn.cursor(cursor_factory=factory) as cur:
        cur.execute(query, params or ())
        rows = cur.fetchall()
        if dictionary:
            return [dict(r) for r in rows]
        return rows


def execute(
    conn,
    query: str,
    params: Optional[list] = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(query, params or ())
        return cur.rowcount


def close_all() -> None:
    global _pool
    if _pool is not None:
        logger.info("Closing PostgreSQL pool")
        try:
            _pool.closeall()
        except Exception as exc:
            logger.error("Error closing pool: %s", exc)
        _pool = None
