"""
scripts/demo_trace.py — Demo cách hoạt động của LLM Observability / Tracer (Mandate #24)
"""

import requests
import json

API_URL = "http://localhost:8001"

def demo():
    print("=" * 70)
    print("🔍 DEMO LLM OBSERVABILITY & TRACING (MANDATE #24)")
    print("=" * 70)

    # Clear cache to force cold LLM calls for full trace generation
    try:
        requests.post(f"{API_URL}/api/v1/cache/clear", timeout=10)
        print("🧹 Cleared cache for clean trace generation.")
    except Exception:
        pass

    # 1. Gửi request chat có chứa PII marker (email, phone)
    print("\n1️⃣ GỬI REQUEST CHAT (Có PII marker: email + SĐT)...")
    payload = {
        "user_id": "user_demo_999",
        "session_id": "sess_demo_888",
        "message": "tìm kính thiên văn dưới 100 đô, liên hệ email demo@gmail.com, SĐT 0901234567"
    }
    
    resp = requests.post(f"{API_URL}/api/chat", json=payload, timeout=60)
    res_data = resp.json()
    request_id = res_data.get("request_id") or resp.headers.get("X-Request-ID") or resp.headers.get("x-request-id")
    cache_flag = res_data.get("cache")

    print(f"   • HTTP Status: {resp.status_code}")
    print(f"   • Cache Flag:  '{cache_flag}'")
    print(f"   • Request ID:  '{request_id}'")
    print(f"   • Reply Preview: '{res_data.get('reply', '')[:100]}...'")

    if not request_id:
        print("❌ Lỗi: Không lấy được request_id từ response")
        return

    # 2. Reconstruct trace chain bằng request_id
    print(f"\n2️⃣ FETCH CHUỖI TRACE BẰNG REQUEST ID: {request_id}")
    trace_resp = requests.get(f"{API_URL}/api/traces/{request_id}", timeout=10)
    traces_data = trace_resp.json()
    spans = traces_data.get("traces", [])

    print(f"   • Tổng số LLM Call Spans tìm thấy: {len(spans)}")
    print("   • Chi tiết chuỗi các bước (Call Chain):")
    
    for i, span in enumerate(spans, 1):
        print(f"\n     ── Span {i}: Layer = '{span.get('layer')}' ──")
        print(f"        - Model:        {span.get('model')}")
        print(f"        - Latency:      {span.get('latency_ms')} ms")
        print(f"        - Tokens:       {span.get('total_tokens')} (Prompt: {span.get('prompt_tokens')}, Completion: {span.get('completion_tokens')})")
        print(f"        - Cost Est:     ${span.get('estimated_cost_usd'):.8f} USD")
        print(f"        - Outcome:      {span.get('outcome')}")
        print(f"        - User Hash:    {span.get('user_id')}")
        print(f"        - Prompt Preview (Sanitized PII):")
        print(f"          '{span.get('prompt_preview')[:120]}...'")

    # 3. Trigger Trace Lỗi / Fallback
    print(f"\n3️⃣ TRIGGER TẠO TRACE LỖI / FALLBACK...")
    err_resp = requests.post(f"{API_URL}/api/traces/trigger-error", timeout=10).json()
    err_req_id = err_resp.get("request_id")
    print(f"   • Generated Error Request ID: '{err_req_id}'")
    
    # Fetch error trace
    err_trace_data = requests.get(f"{API_URL}/api/traces/{err_req_id}", timeout=10).json()
    err_spans = err_trace_data.get("traces", [])
    if err_spans:
        e_span = err_spans[0]
        print(f"   • Error Trace Outcome: '{e_span.get('outcome')}'")
        print(f"   • Error Detail:       '{e_span.get('error')}'")

    # 4. View Tổng Hợp (Summary View)
    print(f"\n4️⃣ VIEW TỔNG HỢP COST & LATENCY theo Layer (`GET /api/traces/summary`):")
    summary_resp = requests.get(f"{API_URL}/api/traces/summary?period=24", timeout=10).json()
    summary_dict = summary_resp.get("summary", {})
    
    total_calls = sum(s.get("calls", 0) for s in summary_dict.values())
    total_cost = sum(s.get("total_cost_usd", 0.0) for s in summary_dict.values())
    total_tokens = sum(s.get("total_tokens", 0) for s in summary_dict.values())

    print(f"   • Period:            {summary_resp.get('period_hours')} hours")
    print(f"   • Total LLM Calls:   {total_calls}")
    print(f"   • Total Cost:        ${total_cost:.6f} USD")
    print(f"   • Total Tokens:      {total_tokens}")
    print("\n   • Bảng phân rã chi tiết theo Layer (Observed Spans):")
    
    for key, stats in summary_dict.items():
        print(f"     - [{stats.get('layer')}]: calls={stats.get('calls')}, avg_latency={stats.get('avg_latency_ms')}ms, cost=${stats.get('total_cost_usd'):.6f}, errors={stats.get('errors')}")

    print("\n" + "=" * 70)
    print("🎉 KHẢ NĂNG TRACING HOẠT ĐỘNG HOÀN HẢO THEO ĐÚNG MANDATE #24!")
    print("=" * 70)

if __name__ == "__main__":
    demo()
