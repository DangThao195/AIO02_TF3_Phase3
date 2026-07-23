"""
logging_config.py — Centralized logging setup

- JSON format for file logs (machine-parsable)
- Plain format for console (human-readable)
- RotatingFileHandler (10MB, 5 backups)
- ContextFilter injects session_id / trace_id / user_id into every record
- Separate log files per concern

Usage in main.py:
    from src.logging_config import setup_logging
    setup_logging()
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
import traceback
from contextvars import ContextVar
from typing import Any

# ── Context variables (set per-request in middleware) ──
request_context: ContextVar[dict[str, str]] = ContextVar("request_context", default={})

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


# ── JSON Formatter ────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Log formatter that outputs JSON for structured log analysis."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = request_context.get()
        ts_sec = record.created
        ts_us = int((ts_sec - int(ts_sec)) * 1_000_000)
        ts_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts_sec))
        data: dict[str, Any] = {
            "ts": f"{ts_str}.{ts_us:06d}Z",
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "session_id": ctx.get("session_id", ""),
            "trace_id": ctx.get("trace_id", ""),
            "user_id": ctx.get("user_id", ""),
        }
        if hasattr(record, "tool_name"):
            data["tool"] = record.tool_name
        if hasattr(record, "tool_args"):
            data["tool_args"] = record.tool_args
        if hasattr(record, "grpc_code"):
            data["grpc_code"] = record.grpc_code
        if hasattr(record, "status_code"):
            data["status_code"] = record.status_code

        if record.exc_info and record.exc_info[0]:
            data["exc"] = "".join(traceback.format_exception(*record.exc_info))

        if record.levelno >= logging.WARNING:
            data["stack"] = traceback.format_stack()[:5]

        return json.dumps(data, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable format for console output."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = request_context.get()
        base = super().format(record)
        sid = ctx.get("session_id", "")
        if sid:
            base = f"[{sid[:12]}] {base}"
        return base


# ── Context Filter ────────────────────────────────────────────────

class ContextFilter(logging.Filter):
    """Ensures every log record has extra fields for JSON formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_context.get()
        for k in ("session_id", "trace_id", "user_id"):
            if not hasattr(record, k):
                setattr(record, k, ctx.get(k, ""))
        return True


# ── Setup ─────────────────────────────────────────────────────────

_is_setup = False


def setup_logging(log_dir: str = _LOG_DIR, level: int = logging.INFO) -> None:
    """Configure all loggers once. Safe to call multiple times."""
    global _is_setup
    if _is_setup:
        return
    _is_setup = True

    os.makedirs(log_dir, exist_ok=True)

    json_fmt = JSONFormatter()
    plain_fmt = PlainFormatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Root logger: capture everything
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # ── File: combined.log (INFO+) ──
    combined = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "combined.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    combined.setLevel(level)
    combined.setFormatter(json_fmt)
    combined.addFilter(ContextFilter())
    root.addHandler(combined)

    # ── File: error.log (ERROR+) ──
    err_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "error.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(json_fmt)
    err_handler.addFilter(ContextFilter())
    root.addHandler(err_handler)

    # ── Console stdout (INFO+) ──
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(plain_fmt)
    root.addHandler(console)

    # ── Logger-specific file handlers ──
    _add_file_logger("api", log_dir, level, json_fmt)
    _add_file_logger("graph", log_dir, level, json_fmt)
    _add_file_logger("tools", log_dir, level, json_fmt)
    _add_file_logger("guardrails", log_dir, logging.WARNING, json_fmt)

    # ── Trace log: graph.io (DEBUG+) for node I/O logging ──
    trace_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "trace.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    trace_handler.setLevel(logging.DEBUG)
    trace_handler.setFormatter(json_fmt)
    trace_handler.addFilter(ContextFilter())
    io_logger = logging.getLogger("graph.io")
    io_logger.setLevel(logging.DEBUG)
    io_logger.propagate = False
    io_logger.addHandler(trace_handler)

    logging.getLogger(__name__).info("[logging_config] Logging initialized — dir=%s level=%s", log_dir, logging.getLevelName(level))


def _add_file_logger(name: str, log_dir: str, level: int, fmt: logging.Formatter) -> None:
    """Add a separate RotatingFileHandler for a specific logger namespace."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, f"{name}.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(fmt)
    handler.addFilter(ContextFilter())

    # Prevent propagation to root's handlers (avoid duplicate)
    logger.propagate = True
    logger.addHandler(handler)


# ── Helper: log with extra fields ────────────────────────────────

def log_tool_error(logger: logging.Logger, tool_name: str, args: dict, error: Exception, grpc_code: str = "") -> None:
    """Log a tool error with structured extra fields."""
    extra = {
        "tool_name": tool_name,
        "tool_args": {k: v for k, v in args.items() if k != "password"},
    }
    if grpc_code:
        extra["grpc_code"] = grpc_code
    logger.error(
        "[%s] %s | args=%s", tool_name, grpc_code or str(error),
        {k: v for k, v in args.items() if k not in ("password", "token")},
        exc_info=True,
        extra=extra,
    )
