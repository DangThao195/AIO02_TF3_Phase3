# docs-aio-engine.md — AIOps Engine: Tài liệu Kỹ thuật Toàn diện

> **Phiên bản**: 1.0.0 | **Cập nhật**: 2026-07-15
> **Scope**: Mô tả luồng hoạt động, phân tích key points, đánh giá so với SLO/Mandates, và đề xuất tối ưu hóa.

---

## 1. Tổng quan Kiến trúc

AIOps Engine là một hệ thống **Closed-Loop Autonomous Incident Response** — tự động phát hiện, chẩn đoán, đề xuất và thực thi khắc phục sự cố cho hạ tầng microservices TechX Corp trên Kubernetes. Hệ thống được xây dựng theo mô hình **CMDR Pipeline** (Collect → Monitor → Diagnose → Remediate).

### Stack công nghệ

| Layer | Công nghệ |
|---|---|
| API Server | FastAPI + Uvicorn (Python 3.10) |
| LLM Backend | AWS Bedrock (Amazon Nova Micro / Titan Embed) |
| Observability | Prometheus (metrics), Jaeger (traces), OpenSearch (logs) |
| Log Clustering | Drain3 (template mining) |
| Notification / Approval | Slack Block Kit (Interactive webhook) |
| Orchestration | Kubernetes kubectl (namespace `techx-tf3`) |
| Feature Flag | flagd |
| Topology Graph | services.json (static adjacency list, MD5-versioned) |

### Topology dịch vụ (services.json)

```
frontend → checkout → payment → payments-db
        → product-catalog → postgresql
        → cart → valkey-cart
        → recommendation
checkout → shipping
         → currency
product-reviews → llm
accounting → kafka
fraud-detection → flagd
```

---

## 2. Luồng hoạt động Pipeline CMDR

Pipeline vận hành theo **hai chế độ song song**:

```
┌─────────────────────────────────────────────────────────────────┐
│  MODE A: Webhook-Driven (Alertmanager → /webhook/alerts)        │
│  MODE B: Active Polling Loop (async background, mỗi 30 giây)   │
└─────────────────────────────────────────────────────────────────┘
```

Cả hai đều hội tụ vào cùng một hàm xử lý `process_incident_background()`.


### 2.1 Giai đoạn 1 — Anomaly Detection (`anomaly_detector.py`)

**Mục đích**: Phát hiện bất thường từ telemetry trước khi leo thang thành sự cố lớn.

#### Lớp 1: SLO Burn-Rate Monitor

```
PromQL query (5m window):
  sum(rate(http_server_duration_milliseconds_count{http_status_code=~"5.."}[5m]))
  / sum(rate(http_server_duration_milliseconds_count[5m])) * 720

PromQL query (1h window): tương tự

Ngưỡng: burn_rate_5m >= 14.4 AND burn_rate_1h >= 14.4
```

Đây là **multi-window burn rate alerting** theo tiêu chuẩn Google SRE Book (Chapter 5). Hệ số `× 720` = 30 ngày × 24 giờ, nghĩa là nếu burn rate = 14.4 thì toàn bộ error budget sẽ cạn trong `30/14.4 ≈ 2.08 ngày`. Yêu cầu cả hai cửa sổ cùng vượt ngưỡng để loại bỏ false positive.

#### Lớp 2: ML Z-Score Saturation Monitor

```python
z_score = (current_value - mean_7d) / stddev_7d
```

Phát hiện bất thường dựa trên baseline 7 ngày trượt. Dùng cho CPU, memory, Kafka consumer lag. Z-Score > 2.0 = cảnh báo; Z-Score = 999.0 khi metric không tồn tại (fail-safe về phía an toàn).

**Đặc điểm quan trọng**: Mode Simulation có thể overwrite kết quả thực bằng giá trị cứng (Z=5.0 / Z=0.0) để test end-to-end mà không cần hạ tầng thật.

---

### 2.2 Giai đoạn 2 — Alert Correlation & RCA Localization

#### AlertCorrelator (`alert_correlator.py`)

Xử lý các alert đầu vào qua **hai lớp lọc**:

**Lớp 1 — Fingerprint Deduplication**
```
fingerprint = f"{service}|{alertname}|{severity}"
```
Gom các alert trùng lặp về cùng một entry, đếm tần suất.

**Lớp 2 — Topology Correlation (Union-Find BFS)**
```
Khoảng cách giữa 2 service (BFS trên undirected graph):
  dist(s1, s2) <= max_hop (mặc định = 2) → union vào cùng cluster
```
Alerts trong vùng lan truyền `max_hop=2` được gom thành một incident cluster. Culprit được chọn là service **xa frontend nhất** (downstream deepest) — heuristic đúng cho phần lớn cascading failure.

#### RCAEngine (`rca_engine.py`) — Jaeger DAG Traversal

```
Input: Jaeger trace JSON
Processing:
  1. Xây dựng cây cha-con từ span references (CHILD_OF)
  2. Đánh dấu các span có tag error=true
  3. Tìm error span có độ sâu lớn nhất (leaf node) → đó là culprit
Output: service name của culprit
```

**Hàm `get_span_depth`** dùng đệ quy ngược (từ span lên root). Đây là điểm tiềm ẩn rủi ro với trace có độ sâu lớn (xem phần đánh giá bên dưới).


---

### 2.3 Giai đoạn 3 — Evidence Collection (`evidence_collector.py`)

**Mục đích**: Thu thập và nén dữ liệu thô trước khi đưa vào LLM (giảm token cost).

```
Input:  culprit_service, alert_time (±30 giây), trace_id
        → OpenSearch query (otel-logs-* index)
        → Drain3 Log Template Mining

Output: evidence_pack = {
  culprit_service, trace_id, alert_time,
  log_templates: [{ template, count }],  # đã nén
  total_raw_logs: N
}
```

**Drain3** là thuật toán log parsing dạng tree-based. Từ N dòng log thô, nó gom thành M template (M << N), giữ lại pattern trong khi loại bỏ giá trị biến động (timestamp, IP, request ID). Điều này cực kỳ quan trọng để:
1. Tránh vượt context window của LLM.
2. Giảm token cost (chi phí Bedrock API).
3. Cung cấp tín hiệu cô đọng hơn cho LLM chẩn đoán.

---

### 2.4 Giai đoạn 4 — LLM Diagnostic Engine (`llm_diagnostician.py`)

Đây là trung tâm trí tuệ của pipeline với **Hybrid RAG architecture**:

```
┌──────────────────────────────────────────────────────┐
│  Hybrid RAG Retrieval (điều phối theo ưu tiên)       │
│                                                        │
│  Priority 1: AWS Bedrock Knowledge Base (Cloud KB)   │
│     ↓ (fallback nếu BEDROCK_KB_ID chưa cấu hình)    │
│  Priority 2: Local Vector KB (playbooks_vector_index) │
│     ↓ (fallback nếu embedding thất bại)              │
│  Priority 3: Raw INCIDENT_HISTORY.md (text scan)     │
└──────────────────────────────────────────────────────┘
```

**Embedding**: Amazon Titan Embed v2 (1024 dims) → fallback sang v1 nếu lỗi.

**Cosine Similarity Threshold**: 0.35 — Chỉ inject playbook vào prompt nếu đủ tương đồng. Dưới ngưỡng → báo "không tìm thấy sự cố tương quan" để tránh hallucination.

**Multi-model support**: Prompt được format tự động theo model ID (Nova, Claude/Anthropic, Meta Llama, Mistral, Titan).

**JSON Recovery**: Bộ parser đàn hồi với 3 lớp: `json.loads()` → cắt `{}` → regex field-by-field. Đảm bảo LLM output luôn được parse dù có markdown wrapping hay unescaped quotes.

**Local Fallback `match_incident_locally()`**: Pattern matcher deterministic cho 8 loại incident (INC-1 đến INC-8). Hoạt động hoàn toàn offline khi Bedrock không khả dụng.

**Output chuẩn từ LLM**:
```json
{
  "analysis": "...",
  "matched_incident": "INC-X",
  "proposed_action": "scale|restart|toggle-tf-flag|cache-flush|breaker-force|none",
  "action_command": "kubectl ...",
  "rollback_command": "kubectl ...",
  "confidence_score": 0.0–1.0
}
```


---

### 2.5 Giai đoạn 5 — Risk Assessment & Remediation (`main.py`, `remediation_handler.py`)

Đây là **bộ lọc an toàn 5 lớp** trước khi bất kỳ lệnh nào được thực thi:

```
┌──────────────────────────────────────────────────────────────┐
│  SAFETY GATE PIPELINE                                         │
│                                                               │
│  [1] validate_action()     → Whitelist check + keyword ban   │
│      Whitelist: scale, restart, toggle-tf-flag,              │
│                 cache-flush, breaker-force                    │
│      Banned keywords: rm, delete, flagd-sync, token, ...     │
│                                                               │
│  [2] Command Template Lock → Overwrite LLM command với       │
│      template cứng từ COMMAND_TEMPLATES dict                 │
│                                                               │
│  [3] Risk Classification                                      │
│      LOW:    cache-flush, breaker-force                       │
│      MEDIUM: scale, restart, toggle-tf-flag                  │
│      HIGH:   unknown action                                   │
│      ↓ confidence_score < 0.80 → nâng LOW lên MEDIUM        │
│                                                               │
│  [4] Execution Route                                          │
│      LOW    → Auto-execute ngay lập tức                      │
│      MEDIUM → Slack card chờ Approve/Reject từ human         │
│      HIGH   → Auto-reject                                     │
│                                                               │
│  [5] Rate Limit Gate                                          │
│      action_counters[incident_id] >= 3 → Block               │
└──────────────────────────────────────────────────────────────┘
```

#### Luồng Approve (MEDIUM Risk)

```
Slack Button [Approve]
  → /slack/interactive endpoint
  → sanitize_command() (namespace injection guard)
  → execute_k8s_command(dry_run=True)  ← Lớp dry-run validation
  → execute_k8s_command(dry_run=False) ← Thực thi thật
  → verify_remediation() — polling Z-score mỗi 30s trong 5 phút
      ↓ Success → close incident
      ↓ Failure → trigger_rollback(rollback_command)
                     ↓ Success → cảnh báo, close incident
                     ↓ Failure → escalate() → SRE on-call
```

---

### 2.6 Thông báo & Human-in-the-Loop (`slack_notifier.py`)

Slack Block Kit card bao gồm:
- Phân tích RCA dạng bullet points (Hiện tượng / Nguyên nhân / Bằng chứng / Blast Radius)
- Matched incident từ Knowledge Base + confidence score
- Lệnh kubectl được đề xuất
- Hai nút tương tác: **✅ Approve** và **❌ Reject**

Fallback khi `SLACK_WEBHOOK_URL` chưa cấu hình: in ra console (không crash).

---

## 3. Sơ đồ Luồng Tổng thể

```
[Prometheus Alertmanager]          [Active Polling Loop / 30s]
        │                                      │
        ▼                                      ▼
 POST /webhook/alerts              check_slo_burn_rate()
        │                          check_infra_z_score()
        │                                      │
        └──────────────┬───────────────────────┘
                       ▼
            AlertCorrelator.correlate_alerts()
            ├─ Fingerprint Dedup (Layer 1)
            └─ Topology Union-Find (Layer 3, BFS max_hop=2)
                       │
                       ▼
            RCAEngine.locate_culprit_service()
            └─ Jaeger DAG Traversal → deepest error span
                       │
                       ▼
            EvidenceCollector.build_evidence_pack()
            ├─ OpenSearch log query (±30s window)
            └─ Drain3 template mining → compressed templates
                       │
                       ▼
            LLMDiagnostician.diagnose()
            ├─ Hybrid RAG: Bedrock KB / Local Vector / Raw MD
            ├─ AWS Bedrock invoke (Nova/Claude/Llama/Mistral)
            └─ JSON Recovery Parser
                       │
                       ▼
            Risk Assessment & Safety Gate
            ├─ Whitelist + Command Template Lock
            ├─ Risk: LOW → Auto-Execute
            ├─ Risk: MEDIUM → Slack Approval Card
            └─ Risk: HIGH → Auto-Reject
                       │
                  [MEDIUM path]
                       ▼
            Slack [Approve] → dry-run → execute → verify (5min)
                                                   ├─ OK → Close
                                                   └─ FAIL → Rollback → Escalate
```


---

## 4. Đánh giá so với SLO và Mandates của Dự án

### 4.1 Điểm mạnh — Pipeline đang làm tốt

**✅ Bảo vệ SLO Checkout (≥ 99.0%) — ưu tiên đúng**
Burn-rate alerting với cả hai cửa sổ 5m + 1h trước khi vỡ SLO là cách tiếp cận đúng đắn. Hệ thống phát hiện từ sớm (khi budget đang cháy) thay vì chỉ đo sau khi SLO đã vỡ.

**✅ Fallback chain đầy đủ (Checkout SLO protection)**
Pipeline có đủ: Auto-execute (LOW) → Human Approval (MEDIUM) → Auto-reject (HIGH) → Rollback → Escalate. Không có đường nào dẫn đến "lệnh nguy hiểm chạy mà không có người biết".

**✅ Safety Contract C6 được triển khai nhiều lớp**
Command Template Lock + Namespace Injection Guard + Forbidden Keyword Check + Dry-run Gate + Rate Limit (3/giờ) là chuỗi kiểm soát tốt cho môi trường production.

**✅ INC-2 (valkey-cart) được xử lý đặc biệt đúng**
`proposed_action = "none"` khi phát hiện INC-2 là quyết định đúng — restart pod stateful sẽ làm mất toàn bộ giỏ hàng, vi phạm Cart SLO ≥ 99.5%.

**✅ Sandbox Simulation hoàn chỉnh**
8 kịch bản incident (inc1–inc8) có thể inject và test end-to-end mà không cần hạ tầng thật. Đây là điểm cực tốt cho dev/test môi trường.

**✅ Graph Freshness với auto-reload mỗi 5 phút**
`periodic_graph_reload_loop()` đảm bảo topology không stale khi có service mới deploy.

---

### 4.2 Điểm yếu — Rủi ro cần chú ý

**⚠️ [CRITICAL] In-memory state `active_incidents` — Single Point of Failure**
Toàn bộ trạng thái incident được giữ trong dict Python trong cùng process. Khi pod restart (do OOM, deploy, node failure), toàn bộ active incidents mất sạch. Điều này nghĩa là:
- Slack card đã gửi đi → user bấm Approve → endpoint trả về fallback `product-reviews-server` thay vì service thật.
- Không có audit trail của ai đã approve gì, lúc nào.
- Khi scale lên nhiều replicas, các pod không chia sẻ state → race condition.

**⚠️ [CRITICAL] `get_span_depth()` dùng đệ quy ngược, độ phức tạp O(spans²)**
Với trace từ hệ thống lớn (>100 spans), hàm này traverse toàn bộ `parent_child_map` cho mỗi span, mỗi bước đệ quy. Chi phí là O(N²) trong worst case. Production traces của checkout có thể có 50-200 spans.

**⚠️ [HIGH] `verify_remediation()` chạy blocking trong ThreadPoolExecutor**
`verify_remediation()` sleep 30 giây × 10 lần = tối đa 5 phút. Hàm này chạy trong `run_in_executor`, nhưng mỗi incident chiếm một thread suốt 5 phút. Với nhiều incident đồng thời, có thể exhaust thread pool.

**⚠️ [MEDIUM] Topology graph tĩnh (services.json) không phản ánh runtime thật**
`services.json` là adjacency list cứng, phải sửa tay mỗi khi thêm service. Nếu một service mới được deploy nhưng chưa cập nhật file này, AlertCorrelator sẽ không gom được các alert liên quan → tạo ra nhiều incident cluster rời rạc thay vì một.

**⚠️ [MEDIUM] Polling Loop dedup chỉ dựa trên `if active_incidents`**
Logic "nếu đang có incident active thì skip" là coarse-grained. Một SLO burn trên checkout và một Z-score spike trên accounting là hai sự cố độc lập, nhưng sẽ bị dedup thành một bởi điều kiện này.

**⚠️ [LOW] `action_counters` không được reset theo giờ**
Tên biến và comment ghi "3 lần/giờ" nhưng counter không bao giờ được xóa — nó chỉ tăng. Sau 3 lần approve một incident_id, mọi lần approve tiếp theo đều bị block vĩnh viễn, ngay cả 24 giờ sau.

**⚠️ [LOW] Fallback cứng `culprit_service = "checkout"`**
Khi `locate_culprit_service()` trả về `"unknown-service"`, code fallback về `"checkout"` — service quan trọng nhất trong hệ thống. Đây là quyết định nguy hiểm nếu sự cố thực sự không phải ở checkout.


---

### 4.3 Đánh giá tổng thể so với Mandates

| Tiêu chí Mandate | Trạng thái | Ghi chú |
|---|---|---|
| Giữ SLO Checkout ≥ 99.0% | ✅ Đúng hướng | Burn-rate alerting đúng tiêu chuẩn SRE |
| Không hiển thị AI summary sai lệch | ✅ | toggle-tf-flag action xử lý INC-4 |
| Rollback plan kèm theo mọi action | ✅ | COMMAND_TEMPLATES + ROLLBACK_TEMPLATES |
| Zero-downtime operation | ⚠️ Rủi ro | in-memory state mất khi pod restart |
| An toàn dữ liệu (Cart SLO) | ✅ | INC-2 hardcoded `proposed_action=none` |
| Bằng chứng hoàn thành có audit | ⚠️ Thiếu | Không có persistent audit log |
| Cost-aware (không gọi API lãng phí) | ✅ | Dedup + "active_incidents skip" |

---

## 5. Đề xuất Tối ưu hóa cho Môi trường Thực tế

### 5.1 [P0 — Urgent] Externalize Incident State ra Redis/DynamoDB

**Vấn đề**: In-memory dict mất khi pod restart, không hỗ trợ multi-replica.

**Giải pháp**:
```python
# Thay thế active_incidents dict bằng Redis
import redis
r = redis.Redis(host="redis-service", port=6379, decode_responses=True)

# Set với TTL tự động (tránh memory leak)
r.setex(f"incident:{incident_id}", 3600, json.dumps(diagnosis))
r.get(f"incident:{incident_id}")
r.delete(f"incident:{incident_id}")
```

Dùng Redis với TTL 1 giờ vừa giải quyết state persistence, vừa tự động fix bug `action_counters` không reset.

---

### 5.2 [P0 — Urgent] Thay `get_span_depth()` đệ quy bằng BFS/iterative DFS

**Vấn đề**: O(spans²) với trace lớn, risk stackoverflow với trace sâu.

**Giải pháp**:
```python
def get_span_depth_iterative(self, span_id_to_find, parent_child_map):
    """BFS từ root tính depth cho tất cả span trong một lần."""
    # Tìm root spans (không có parent)
    all_children = {child for children in parent_child_map.values() for child in children}
    roots = [sid for sid in parent_child_map if sid not in all_children]
    
    depth_map = {}
    queue = [(root, 0) for root in roots]
    while queue:
        node, depth = queue.pop(0)
        depth_map[node] = depth
        for child in parent_child_map.get(node, []):
            queue.append((child, depth + 1))
    return depth_map  # Tính một lần, tra cứu O(1)
```

---

### 5.3 [P1] Service Discovery thay thế services.json tĩnh

**Vấn đề**: Topology graph phải sửa tay, stale khi deploy service mới.

**Giải pháp**: Tự động xây dựng topology từ Jaeger service dependencies API:
```python
async def build_topology_from_jaeger(self):
    """Query Jaeger API lấy dependency map thực tế."""
    url = f"{JAEGER_URL}/api/dependencies"
    params = {"endTs": int(time.time() * 1000), "lookback": 86400000}  # 24h
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code == 200:
        deps = resp.json().get("data", [])
        graph = {}
        for dep in deps:
            parent = dep["parent"]
            child = dep["child"]
            graph.setdefault(parent, []).append(child)
        return graph
    return {}
```

Kết hợp với `reload_graph()` hiện tại làm fallback.

---

### 5.4 [P1] Tách biệt Dedup logic theo SLO domain

**Vấn đề**: `if active_incidents` dedup toàn bộ hệ thống, bỏ qua các sự cố độc lập.

**Giải pháp**: Dedup theo SLO domain thay vì global:

```python
# Phân loại service theo SLO domain
SLO_DOMAINS = {
    "checkout_flow": ["checkout", "payment", "currency", "shipping", "payments-db"],
    "cart_flow":     ["cart", "valkey-cart"],
    "browse_flow":   ["frontend", "product-catalog", "postgresql", "recommendation"],
    "ai_feature":    ["product-reviews", "llm"],
    "infra":         ["accounting", "kafka", "fraud-detection", "flagd"]
}

# active_incidents per domain thay vì global
active_incidents_by_domain = {domain: {} for domain in SLO_DOMAINS}
```

Checkout incident không block diagnosis cho cart incident.


---

### 5.5 [P1] Thêm Persistent Audit Log cho mọi action

**Vấn đề**: Không có audit trail → không thể nộp "bằng chứng hoàn thành" theo Mandate.

**Giải pháp**: Ghi structured event log sau mỗi bước quan trọng:

```python
import json, datetime

def audit_log(event_type: str, incident_id: str, actor: str, details: dict):
    record = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,  # DETECTED, DIAGNOSED, APPROVED, EXECUTED, ROLLED_BACK, ESCALATED
        "incident_id": incident_id,
        "actor": actor,  # "system" | "slack_user_id"
        "details": details
    }
    with open("audit.log", "a") as f:
        f.write(json.dumps(record) + "\n")
```

Ship log này vào OpenSearch cùng với OTEL logs để query sau.

---

### 5.6 [P2] Thêm Confidence-based Escalation thay vì chỉ Risk Level

**Vấn đề**: Confidence score hiện chỉ dùng để nâng LOW→MEDIUM. Một diagnosis với confidence=0.4 vẫn có thể auto-execute nếu là LOW risk.

**Giải pháp**: Hard floor cho auto-execution:

```python
# Tuyệt đối không auto-execute nếu confidence < 0.75
AUTO_EXECUTE_MIN_CONFIDENCE = 0.75

if current_risk == "LOW":
    if confidence_score < AUTO_EXECUTE_MIN_CONFIDENCE:
        logger.warning(f"Confidence {confidence_score} below auto-execute threshold. Routing to human approval.")
        current_risk = "MEDIUM"  # Force human review
    else:
        handler.execute_k8s_command(action_command)
```

---

### 5.7 [P2] Adaptive Polling thay vì Fixed 30s Interval

**Vấn đề**: Polling cứng 30 giây — quá thưa khi có incident, quá dày khi stable (tốn API calls Prometheus).

**Giải pháp**: Backoff/speedup theo tình trạng hệ thống:

```python
# Adaptive interval
base_interval = 30
current_interval = base_interval

if is_breached:
    current_interval = max(10, current_interval // 2)  # Tăng tốc độ quét khi có vấn đề
else:
    current_interval = min(120, current_interval * 1.5)  # Giảm dần khi stable

await asyncio.sleep(current_interval)
```

---

### 5.8 [P2] Streaming LLM Response để giảm perceived latency

**Vấn đề**: `invoke_model()` là blocking call, với Nova Micro có thể mất 3-8 giây. Trong thời gian này Slack không có gì để hiển thị cho SRE.

**Giải pháp**: Dùng `invoke_model_with_response_stream()` của Bedrock và gửi partial update:

```python
response = self.bedrock_client.invoke_model_with_response_stream(
    modelId=self.model_id, body=body, ...
)
full_text = ""
for event in response["body"]:
    chunk = event.get("chunk", {})
    if chunk:
        delta = json.loads(chunk["bytes"]).get("delta", {}).get("text", "")
        full_text += delta
        # Có thể push interim update lên Slack "Đang phân tích..."
```

---

### 5.9 [P3] Thay Local Cosine Similarity bằng FAISS / OpenSearch k-NN

**Vấn đề**: `retrieve_relevant_playbooks_locally()` tính cosine similarity tuần tự qua toàn bộ KB. Khi KB lớn (>1000 playbooks), độ trễ tăng tuyến tính.

**Giải pháp**: Index playbooks vào OpenSearch với `knn` plugin (đã có sẵn trong stack):

```json
PUT /aiops-playbooks
{
  "mappings": {
    "properties": {
      "embedding": { "type": "knn_vector", "dimension": 1024 },
      "text": { "type": "text" },
      "incident_id": { "type": "keyword" }
    }
  }
}
```

Query k-NN trả về kết quả trong O(log N) thay vì O(N).

---

## 6. Tóm tắt Điểm số Đánh giá

| Tiêu chí | Điểm | Nhận xét |
|---|---|---|
| Detection accuracy (burn-rate + Z-score) | 8/10 | Đúng tiêu chuẩn, nhưng thiếu anomaly detection cho p95 latency trực tiếp |
| RCA localization | 7/10 | Jaeger DAG traversal tốt, nhưng depth algorithm có bug hiệu năng |
| Evidence quality | 8/10 | Drain3 clustering là điểm sáng, giảm noise hiệu quả |
| LLM Diagnostic accuracy | 7/10 | Hybrid RAG + local fallback tốt, nhưng prompt engineering cho `none` action chưa đủ cứng |
| Safety gates | 9/10 | 5 lớp bảo vệ rất kỹ, phù hợp SLO production |
| State management | 4/10 | In-memory only — điểm yếu nhất của hệ thống |
| Observability của chính Engine | 5/10 | Thiếu metrics về pipeline latency, LLM cost, false positive rate |
| Resilience (multi-replica) | 3/10 | Không thể scale ngang hiện tại do in-memory state |
| **Tổng thể** | **6.4/10** | **Prototype tốt, cần ít nhất P0 fixes trước khi production** |

---

## 7. Roadmap Ưu tiên

```
Tuần 1 (Trước production):
  [P0] Fix 1: Externalize state → Redis (giải quyết SPOF + action_counters bug)
  [P0] Fix 2: Replace recursive span depth → BFS iterative

Tuần 2 (Cải thiện correctness):
  [P1] Dynamic topology từ Jaeger dependencies API
  [P1] Domain-scoped dedup thay vì global lock
  [P1] Persistent audit log → OpenSearch

Tuần 3+ (Scale & optimize):
  [P2] Adaptive polling interval
  [P2] Confidence hard floor cho auto-execution
  [P2] Streaming LLM response
  [P3] OpenSearch k-NN thay local cosine similarity
  [P3] Prometheus metrics cho chính AIOps Engine
       (pipeline_duration_seconds, llm_call_total, false_positive_rate)
```

---

*Tài liệu này được tạo tự động từ phân tích source code của `aiops-engine`. Cập nhật khi có thay đổi kiến trúc.*
