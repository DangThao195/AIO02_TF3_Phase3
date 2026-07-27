"""
test_error_injection.py
=======================
Unit tests for Task 3: Error Injection Endpoint (AIE1 Phase 3)

Tests cover:
  - guardrails/error_injection.py state management (in-memory mode)
  - LLMTraceHTTPHandler POST /inject/error and GET /inject/error endpoints
  - Integration: get_ai_assistant_response honours injected error
"""
import json
import sys
import os
import threading
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make guardrails importable from repo root
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guardrails.error_injection as ei_module
from guardrails.error_injection import (
    VALID_ERROR_TYPES,
    clear_error_injection,
    get_injected_error_type,
    get_injection_status,
    set_error_injection,
)


def _reset_injection():
    """Reset both Redis (mocked) and in-memory state."""
    ei_module._mem_inject_error = None


# ===========================================================================
# 1. Unit tests – error_injection module (no Redis)
# ===========================================================================

class TestErrorInjectionModuleNoRedis(unittest.TestCase):
    """All tests run with Redis unavailable → pure in-memory mode."""

    def setUp(self):
        _reset_injection()
        # Patch redis_client to None so all tests use in-memory fallback
        self._patcher = patch.object(ei_module, "redis_client", None)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        _reset_injection()

    def test_initial_state_inactive(self):
        self.assertIsNone(get_injected_error_type())

    def test_set_valid_error_type(self):
        for etype in sorted(VALID_ERROR_TYPES):
            set_error_injection(etype)
            self.assertEqual(get_injected_error_type(), etype)
            _reset_injection()

    def test_set_invalid_error_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            set_error_injection("invalid_type")
        self.assertIn("invalid_type", str(ctx.exception))

    def test_clear_injection(self):
        set_error_injection("429")
        self.assertEqual(get_injected_error_type(), "429")
        clear_error_injection()
        self.assertIsNone(get_injected_error_type())

    def test_get_injection_status_inactive(self):
        status = get_injection_status()
        self.assertFalse(status["active"])
        self.assertIsNone(status["error_type"])
        self.assertIn("backend", status)
        self.assertEqual(set(status["valid_error_types"]), VALID_ERROR_TYPES)

    def test_get_injection_status_active(self):
        set_error_injection("timeout")
        status = get_injection_status()
        self.assertTrue(status["active"])
        self.assertEqual(status["error_type"], "timeout")

    def test_thread_safety(self):
        """Concurrent set/clear should not corrupt state."""
        errors = []

        def worker(etype):
            try:
                set_error_injection(etype)
                _ = get_injected_error_type()
                clear_error_injection()
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(etype,))
            for etype in list(VALID_ERROR_TYPES) * 4
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread safety errors: {errors}")


# ===========================================================================
# 2. Unit tests – error_injection module (mock Redis)
# ===========================================================================

class TestErrorInjectionModuleWithRedis(unittest.TestCase):
    def setUp(self):
        _reset_injection()
        self._mock_redis = MagicMock()
        self._mock_redis.ping.return_value = True
        self._patcher = patch.object(ei_module, "redis_client", self._mock_redis)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        _reset_injection()

    def test_set_writes_to_redis(self):
        set_error_injection("429")
        self._mock_redis.set.assert_called_once_with(
            ei_module.REDIS_KEY_INJECT, "429"
        )

    def test_clear_deletes_redis_key(self):
        clear_error_injection()
        self._mock_redis.delete.assert_called_once_with(ei_module.REDIS_KEY_INJECT)

    def test_get_reads_from_redis(self):
        self._mock_redis.get.return_value = "timeout"
        result = get_injected_error_type()
        self.assertEqual(result, "timeout")
        self._mock_redis.get.assert_called_with(ei_module.REDIS_KEY_INJECT)

    def test_get_returns_none_when_redis_empty(self):
        self._mock_redis.get.return_value = None
        self.assertIsNone(get_injected_error_type())

    def test_redis_error_falls_back_to_memory(self):
        # Redis ping works but get raises
        self._mock_redis.get.side_effect = Exception("redis down")
        ei_module._mem_inject_error = "500"
        result = get_injected_error_type()
        # Fallback to in-memory when Redis get fails
        self.assertEqual(result, "500")


# ===========================================================================
# 3. HTTP endpoint tests via LLMTraceHTTPHandler
# ===========================================================================

class _FakeSocket:
    """Minimal socket shim for BaseHTTPRequestHandler."""

    def __init__(self, request_bytes: bytes):
        self._in = BytesIO(request_bytes)
        self._out = BytesIO()

    def makefile(self, mode, **kwargs):
        if "r" in mode:
            return self._in
        return self._out

    def sendall(self, data):
        self._out.write(data)

    def getsockname(self):
        return ("127.0.0.1", 8086)

    def getpeername(self):
        return ("127.0.0.1", 9999)

    def shutdown(self, *args):
        pass

    def close(self):
        pass


def _make_handler(method: str, path: str, body: bytes | None = None):
    """Instantiate LLMTraceHTTPHandler without a real socket server."""
    from product_reviews_server import LLMTraceHTTPHandler  # noqa: PLC0415

    headers = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
    if body is not None:
        headers += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
    headers += "\r\n"
    raw = headers.encode() + (body or b"")

    sock = _FakeSocket(raw)
    with patch.object(LLMTraceHTTPHandler, "_authorized", return_value=True):
        handler = LLMTraceHTTPHandler.__new__(LLMTraceHTTPHandler)
        handler.client_address = ("127.0.0.1", 9999)
        handler.server = MagicMock()
        handler.connection = sock
        handler.rfile = sock._in
        handler.wfile = sock._out
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.command = method
        handler.path = path
        handler.headers = {}
        if body is not None:
            handler.headers = {"content-length": str(len(body))}

    return handler, sock


def _parse_response(sock: _FakeSocket):
    """Extract status code and parsed JSON body from raw HTTP response."""
    raw = sock._out.getvalue().decode("utf-8", errors="replace")
    lines = raw.split("\r\n")
    status_line = lines[0]  # e.g. "HTTP/1.0 200 OK"
    status_code = int(status_line.split()[1])
    body_start = raw.index("\r\n\r\n") + 4
    body_json = json.loads(raw[body_start:])
    return status_code, body_json


class TestInjectErrorHTTPHandler(unittest.TestCase):
    def setUp(self):
        _reset_injection()

    def tearDown(self):
        _reset_injection()

    def _post_inject(self, payload: dict):
        body = json.dumps(payload).encode()
        from product_reviews_server import LLMTraceHTTPHandler  # noqa

        with patch("product_reviews_server._authorized_", return_value=True, create=True):
            with patch.object(ei_module, "redis_client", None):
                raw_req = (
                    f"POST /inject/error HTTP/1.1\r\n"
                    f"Host: localhost\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n\r\n"
                ).encode() + body
                sock = _FakeSocket(raw_req)
                handler = MagicMock(spec=LLMTraceHTTPHandler)
                handler._authorized.return_value = True
                handler._read_json_body.return_value = payload
                handler._send_json = lambda code, resp: (
                    sock._out.write(
                        (
                            f"HTTP/1.0 {code} OK\r\nContent-Type: application/json\r\n\r\n"
                            + json.dumps(resp)
                        ).encode()
                    )
                )
                # Call do_POST logic directly
                LLMTraceHTTPHandler.do_POST(handler)
                raw_out = sock._out.getvalue().decode()
                body_str = raw_out.split("\r\n\r\n", 1)[-1] if "\r\n\r\n" in raw_out else raw_out
                return json.loads(body_str) if body_str else {}

    def test_post_activate_429(self):
        """POST /inject/error with error_type=429 activates injection."""
        with patch.object(ei_module, "redis_client", None):
            body = json.dumps({"error_type": "429", "active": True}).encode()
            raw_req = (
                f"POST /inject/error HTTP/1.1\r\nHost: localhost\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
            ).encode() + body

            from product_reviews_server import LLMTraceHTTPHandler

            sock = _FakeSocket(raw_req)
            handler = MagicMock(spec=LLMTraceHTTPHandler)
            handler.path = "/inject/error"
            handler._authorized.return_value = True
            handler._read_json_body.return_value = {"error_type": "429", "active": True}
            captured = {}
            handler._send_json.side_effect = lambda code, resp: captured.update(
                {"code": code, "resp": resp}
            )
            with patch("product_reviews_server.logger"):
                LLMTraceHTTPHandler.do_POST(handler)

            self.assertEqual(captured["code"], 200)
            self.assertTrue(captured["resp"]["ok"])
            self.assertEqual(captured["resp"]["error_type"], "429")
            self.assertEqual(get_injected_error_type(), "429")

    def test_post_clear_injection(self):
        """POST /inject/error with active=false clears injection."""
        set_error_injection("timeout")
        self.assertEqual(get_injected_error_type(), "timeout")

        with patch.object(ei_module, "redis_client", None):
            from product_reviews_server import LLMTraceHTTPHandler

            handler = MagicMock(spec=LLMTraceHTTPHandler)
            handler.path = "/inject/error"
            handler._authorized.return_value = True
            handler._read_json_body.return_value = {"active": False}
            captured = {}
            handler._send_json.side_effect = lambda code, resp: captured.update(
                {"code": code, "resp": resp}
            )
            with patch("product_reviews_server.logger"):
                LLMTraceHTTPHandler.do_POST(handler)

        self.assertEqual(captured["code"], 200)
        self.assertFalse(captured["resp"]["active"])
        self.assertIsNone(get_injected_error_type())

    def test_post_invalid_error_type_returns_400(self):
        """POST /inject/error with unknown error_type → 400."""
        with patch.object(ei_module, "redis_client", None):
            from product_reviews_server import LLMTraceHTTPHandler

            handler = MagicMock(spec=LLMTraceHTTPHandler)
            handler.path = "/inject/error"
            handler._authorized.return_value = True
            handler._read_json_body.return_value = {"error_type": "unknown_err"}
            captured = {}
            handler._send_json.side_effect = lambda code, resp: captured.update(
                {"code": code, "resp": resp}
            )
            with patch("product_reviews_server.logger"):
                LLMTraceHTTPHandler.do_POST(handler)

        self.assertEqual(captured["code"], 400)
        self.assertIn("error", captured["resp"])

    def test_post_missing_error_type_returns_400(self):
        """POST /inject/error missing error_type field → 400."""
        with patch.object(ei_module, "redis_client", None):
            from product_reviews_server import LLMTraceHTTPHandler

            handler = MagicMock(spec=LLMTraceHTTPHandler)
            handler.path = "/inject/error"
            handler._authorized.return_value = True
            handler._read_json_body.return_value = {"active": True}
            captured = {}
            handler._send_json.side_effect = lambda code, resp: captured.update(
                {"code": code, "resp": resp}
            )
            with patch("product_reviews_server.logger"):
                LLMTraceHTTPHandler.do_POST(handler)

        self.assertEqual(captured["code"], 400)

    def test_get_injection_status_inactive(self):
        """GET /inject/error returns inactive status."""
        _reset_injection()
        with patch.object(ei_module, "redis_client", None):
            from product_reviews_server import LLMTraceHTTPHandler

            handler = MagicMock(spec=LLMTraceHTTPHandler)
            handler._authorized.return_value = True
            handler.path = "/inject/error"
            captured = {}
            handler._send_json.side_effect = lambda code, resp: captured.update(
                {"code": code, "resp": resp}
            )

            from urllib.parse import urlparse

            with patch("product_reviews_server.urlparse", return_value=urlparse("/inject/error")):
                LLMTraceHTTPHandler.do_GET(handler)

        self.assertEqual(captured["code"], 200)
        self.assertFalse(captured["resp"]["active"])

    def test_get_injection_status_active(self):
        """GET /inject/error returns active status after set."""
        set_error_injection("500")
        with patch.object(ei_module, "redis_client", None):
            from product_reviews_server import LLMTraceHTTPHandler

            handler = MagicMock(spec=LLMTraceHTTPHandler)
            handler._authorized.return_value = True
            handler.path = "/inject/error"
            captured = {}
            handler._send_json.side_effect = lambda code, resp: captured.update(
                {"code": code, "resp": resp}
            )

            from urllib.parse import urlparse

            with patch("product_reviews_server.urlparse", return_value=urlparse("/inject/error")):
                LLMTraceHTTPHandler.do_GET(handler)

        self.assertEqual(captured["code"], 200)
        self.assertTrue(captured["resp"]["active"])
        self.assertEqual(captured["resp"]["error_type"], "500")


# ===========================================================================
# 4. Integration: get_ai_assistant_response honours error injection
# ===========================================================================

class TestErrorInjectionIntegration(unittest.TestCase):
    """Verify get_ai_assistant_response returns FALLBACK when injection active."""

    def setUp(self):
        _reset_injection()

    def tearDown(self):
        _reset_injection()

    def _call_with_injection(self, error_type: str):
        """Activate injection, call server function, return response text."""
        set_error_injection(error_type)
        from contextlib import ExitStack
        import product_reviews_server as srv

        with ExitStack() as stack:
            stack.enter_context(patch.object(ei_module, "redis_client", None))
            stack.enter_context(patch.object(srv, "check_input", return_value=MagicMock(is_safe=True)))
            stack.enter_context(patch.object(srv, "filter_output", return_value=MagicMock(filtered_response="Is this product good?")))
            stack.enter_context(patch.object(srv, "is_clearly_off_topic_question", return_value=False))
            stack.enter_context(patch.object(srv, "get_cached_response", return_value=None))
            stack.enter_context(patch.object(srv, "acquire_lock", return_value=True))
            stack.enter_context(patch.object(srv, "get_review_version", return_value="v1"))
            stack.enter_context(patch.object(srv, "generate_cache_key", return_value="test_key"))
            stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=False))
            stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=True))
            stack.enter_context(patch.object(srv, "write_llm_trace"))
            stack.enter_context(patch.object(srv, "build_runtime_trace_record", return_value={
                "guardrails": {}, "cache": {}, "candidate": {}, "judge": {}
            }))
            stack.enter_context(patch.object(srv, "finalize_runtime_trace", return_value={}))
            stack.enter_context(patch.object(srv, "product_review_svc_metrics", {
                "app_ai_fallback_total": MagicMock(),
                "app_ai_assistant_counter": MagicMock(),
            }))
            mock_tracer = stack.enter_context(patch("product_reviews_server.tracer"))
            mock_span = MagicMock()
            mock_tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: mock_span
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")
            return response.response

    def test_injection_429_triggers_fallback(self):
        resp = self._call_with_injection("429")
        from product_reviews_server import FALLBACK_SUMMARY_MESSAGE
        self.assertEqual(resp, FALLBACK_SUMMARY_MESSAGE)

    def test_injection_timeout_triggers_fallback(self):
        resp = self._call_with_injection("timeout")
        from product_reviews_server import FALLBACK_SUMMARY_MESSAGE
        self.assertEqual(resp, FALLBACK_SUMMARY_MESSAGE)

    def test_injection_500_triggers_fallback(self):
        resp = self._call_with_injection("500")
        from product_reviews_server import FALLBACK_SUMMARY_MESSAGE
        self.assertEqual(resp, FALLBACK_SUMMARY_MESSAGE)

    def test_no_injection_does_not_trigger_fallback_early(self):
        """Without injection, flow passes through to LLM (mocked to return normal text)."""
        _reset_injection()
        from contextlib import ExitStack
        import product_reviews_server as srv

        with ExitStack() as stack:
            stack.enter_context(patch.object(srv, "check_input", return_value=MagicMock(is_safe=True)))
            stack.enter_context(patch.object(srv, "filter_output", return_value=MagicMock(filtered_response="Is this product good?")))
            stack.enter_context(patch.object(srv, "is_clearly_off_topic_question", return_value=False))
            stack.enter_context(patch.object(srv, "get_cached_response", return_value=None))
            stack.enter_context(patch.object(srv, "acquire_lock", return_value=True))
            stack.enter_context(patch.object(srv, "get_review_version", return_value="v1"))
            stack.enter_context(patch.object(srv, "generate_cache_key", return_value="test_key"))
            stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=False))
            stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=True))
            stack.enter_context(patch.object(ei_module, "redis_client", None))
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value=None))
            stack.enter_context(patch.object(srv, "write_llm_trace"))
            stack.enter_context(patch.object(srv, "build_runtime_trace_record", return_value={
                "guardrails": {}, "cache": {}, "candidate": {}, "judge": {}
            }))
            stack.enter_context(patch.object(srv, "finalize_runtime_trace", return_value={}))
            stack.enter_context(patch.object(srv, "product_review_svc_metrics", {
                "app_ai_fallback_total": MagicMock(),
                "app_ai_assistant_counter": MagicMock(),
            }))
            stack.enter_context(patch.object(srv, "llm_provider", "openai"))
            stack.enter_context(patch.object(srv, "build_runtime_prompts", return_value=("u", "a", "i")))
            stack.enter_context(patch.object(srv, "build_system_prompt", return_value="sys"))
            stack.enter_context(patch.object(srv, "call_candidate_chat", return_value="Great product!"))
            stack.enter_context(patch.object(srv, "post_process_output", return_value="Great product!"))
            stack.enter_context(patch.object(srv, "apply_runtime_fidelity_gate", return_value=("Great product!", "approved")))
            mock_tracer = stack.enter_context(patch("product_reviews_server.tracer"))
            mock_span = MagicMock()
            mock_tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: mock_span
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        # Should reach LLM path, not fallback early
        self.assertNotEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

