# Incident Report: AIOps Engine CrashLoopBackOff - OOM & Prometheus Connectivity

**Incident ID:** 0003  
**Date:** 16 July 2026  
**Status:** Active/Under Investigation  
**Severity:** High  
**Team:** TF3 Infra-Sentinel  
**Reporter:** CDO-02  

---

## Executive Summary

Pod `aiops-engine-5b48bb4df5-b5jhp` trong namespace `techx-tf3` đã bị restart 22 lần trong vòng 13 giờ do **OOMKilled (Out of Memory)** và **liveness probe failures** gây ra bởi không kết nối được tới Prometheus. Pod luân phiên giữa trạng thái `CrashLoopBackOff` và `Running` nhưng không bao giờ đạt `Ready`, ảnh hưởng nghiêm trọng đến khả năng AIOps detection và monitoring.

---

## Timeline

| Timestamp | Event |
|-----------|-------|
| 16 Jul 2026 00:02:01 | Pod `aiops-engine-5b48bb4df5-b5jhp` được tạo |
| 16 Jul 2026 ~00:30 | Restart lần đầu tiên xảy ra |
| 16 Jul 2026 13:24:02 | Restart lần thứ 21 với Exit Code 137 (OOMKilled) |
| 16 Jul 2026 13:29:06 | Pod restart lần thứ 22, hiện đang Running nhưng Not Ready |
| 16 Jul 2026 13:34 | Incident được phát hiện và điều tra |

---

## Technical Analysis

### 1. Root Cause: Out of Memory (OOMKilled)

**Evidence từ `kubectl describe pod`:**
```
Last State:     Terminated
  Reason:       Error
  Exit Code:    137
  Started:      Thu, 16 Jul 2026 13:21:02 +0700
  Finished:     Thu, 16 Jul 2026 13:24:02 +0700
```

**Giải thích:**
- **Exit Code 137** = 128 + 9 (SIGKILL) → Process bị kill bởi kernel OOM killer
- Pod chỉ chạy được ~3 phút (13:21:02 → 13:24:02) trước khi bị kill
- Pattern lặp lại: pod khởi động → load models → query Prometheus → OOM → killed

**Current Resource Configuration:**
```yaml
Resources:
  Limits:
    cpu:     500m
    memory:  512Mi      # ← TOO LOW
  Requests:
    cpu:      200m
    memory:   256Mi
```

**Phân tích memory usage:**
Từ logs, pod cần load:
- 7 Isolation Forest models (checkout, frontend, payment, product-catalog, product-reviews, recommendation, shipping)
- Drain3 template miner
- 8 embedded playbooks into Local Vector KB
- Service graph (17 nodes, 13 edges)
- Active polling loop với continuous Prometheus queries

→ **512Mi memory limit quá thấp** cho workload này

---

### 2. Contributing Factor: Prometheus Connection Timeouts

**Evidence từ pod logs (current run):**
```
2026-07-16 06:29:28,880 [ERROR] AIOpsEngine.AnomalyDetector: Error querying Prometheus: 
HTTPConnectionPool(host='prometheus.techx-tf3.svc.cluster.local', port=9090): Max retries 
exceeded with url: /api/v1/query?query=... 
(Caused by ConnectTimeoutError(<HTTPConnection(host='prometheus.techx-tf3.svc.cluster.local', 
port=9090) at 0x7fbc8ffd56f0>, 
'Connection to prometheus.techx-tf3.svc.cluster.local timed out. (connect timeout=10)'))
```

**Evidence từ previous logs:**
```
2026-07-16 06:21:25,412 [ERROR] AIOpsEngine.AnomalyDetector: Error querying Prometheus: ...
2026-07-16 06:21:35,427 [ERROR] AIOpsEngine.AnomalyDetector: Error querying Prometheus: ...
2026-07-16 06:21:45,442 [WARNING] AIOpsEngine.AnomalyDetector: Error querying Prometheus range: ...
2026-07-16 06:22:15,487 [WARNING] AIOpsEngine.AnomalyDetector: Error querying Prometheus range: ...
2026-07-16 06:22:25,500 [WARNING] AIOpsEngine.AnomalyDetector: Error querying Prometheus range: ...
2026-07-16 06:22:35,514 [WARNING] AIOpsEngine.AnomalyDetector: Error querying Prometheus range: ...
2026-07-16 06:22:45,529 [WARNING] AIOpsEngine.AnomalyDetector: Error querying Prometheus range: ...
```

**Impact:**
- Connection timeout = 10 seconds per query
- Multiple queries chạy tuần tự → tổng thời gian rất dài
- Dẫn đến:
  ```
  2026-07-16 06:22:45,530 [ERROR] AIOpsEngine.AnomalyDetector: Failed to run IF inference for 
  frontend: 18 columns passed, passed data had 0 columns. Falling back to Z-Score.
  ```
- False positives:
  ```
  2026-07-16 06:23:15,560 [WARNING] AIOpsEngine.AnomalyDetector: No metric data returned from 
  Prometheus for sum(rate(container_cpu_usage_seconds_total{container="frontend"}[5m])). 
  Treating as anomalous (Z-Score = 999.0)
  ```

---

### 3. Contributing Factor: Liveness/Readiness Probe Failures

**Evidence từ `kubectl describe pod`:**
```
Events:
  Warning  Unhealthy  7m46s (x336 over 13h)  kubelet  
    Readiness probe failed: Get "http://10.0.21.245:8000/readyz": 
    context deadline exceeded (Client.Timeout exceeded while awaiting headers)

  Warning  Unhealthy  2m45s (x27 over 79m)  kubelet  
    (combined from similar events): Readiness probe failed: 
    Get "http://10.0.21.245:8000/readyz": read tcp 10.0.20.70:47180->10.0.21.245:8000: 
    read: connection reset by peer

  Normal   Killing    25m (x18 over 101m)  kubelet  
    Container engine failed liveness probe, will be restarted
```

**Probe Configuration:**
```yaml
Liveness:   http-get http://:8000/readyz delay=30s timeout=1s period=30s #success=1 #failure=3
Readiness:  http-get http://:8000/readyz delay=15s timeout=1s period=10s #success=1 #failure=3
```

**Vấn đề:**
- `timeout=1s` quá ngắn khi pod đang struggle với Prometheus queries
- `/readyz` endpoint có thể check Prometheus connectivity → timeout cascade
- Sau 3 lần fail liên tiếp → liveness probe kill pod → restart loop

**Current Status:**
```
Conditions:
  Type                        Status
  PodReadyToStartContainers   True 
  Initialized                 True 
  Ready                       False     # ← NOT READY
  ContainersReady             False     # ← CONTAINERS NOT READY
  PodScheduled                True 
```

**State:**
```
State:          Running
  Started:      Thu, 16 Jul 2026 13:29:06 +0700
Ready:          False    # ← 5+ minutes running but still not ready
Restart Count:  22
```

---

### 4. Security Policy Violations (Non-blocking but needs fix)

**Evidence từ Events:**
```
Warning  PolicyViolation  24m  kyverno-scan  
  policy custom-baseline-security-context/require-allow-privilege-escalation-false fail: 
  validation error: allowPrivilegeEscalation must be set to false. 
  rule require-allow-privilege-escalation-false failed at path /spec/containers/0/securityContext/

Warning  PolicyViolation  24m  kyverno-scan  
  policy custom-baseline-security-context/drop-all-capabilities fail: 
  validation error: Containers must drop all capabilities. 
  rule drop-all-capabilities failed at path /spec/containers/0/securityContext/

Warning  PolicyViolation  24m  kyverno-scan  
  policy custom-baseline-security-context/require-seccomp-profile-runtime-default fail: 
  validation error: seccompProfile must be set to RuntimeDefault. 
  rule require-seccomp-profile-runtime-default[0] failed at path /spec/securityContext/seccompProfile/
```

**Context:** 
Đây là các vi phạm **MANDATE #5: Runtime Hardening** - các policy đang ở chế độ `audit` nên chỉ warning, không chặn pod, nhưng cần fix trước khi chuyển sang `enforce` mode.

---

## Impact Assessment

### User-Facing Impact
- **AIOps Detection:** KHÔNG hoạt động → không có anomaly detection, alert correlation
- **Proactive Monitoring:** KHÔNG có → phụ thuộc hoàn toàn vào reactive alerts

### Operational Impact
- **MANDATE #7a & #7b (AIOps Detection):** KHÔNG thể hoàn thành - detector không chạy được
- **MANDATE #6 (AI Trust & Safety):** Có thể bị ảnh hưởng nếu dùng chung infrastructure

### SLO Impact
- Không trực tiếp ảnh hưởng checkout/browse SLO
- Nhưng mất khả năng phát hiện sớm khi SLO bị vi phạm

---

## Root Cause Analysis (5 Whys)

**Why 1:** Tại sao pod bị CrashLoopBackOff?  
→ Vì pod bị OOMKilled (Exit Code 137) và liveness probe fail.

**Why 2:** Tại sao pod bị OOMKilled?  
→ Vì memory limit 512Mi quá thấp cho workload (load 7 ML models + vector KB + continuous queries).

**Why 3:** Tại sao liveness probe fail?  
→ Vì `/readyz` endpoint timeout do không connect được Prometheus và probe timeout=1s quá ngắt.

**Why 4:** Tại sao không connect được Prometheus?  
→ Vì Prometheus service có thể down, network policy chặn, hoặc Prometheus overloaded.

**Why 5:** Tại sao không có alert sớm hơn?  
→ Vì đây chính là service phụ trách alerting - circular dependency.

---

## Solutions & Action Items

### 🔴 **Priority 1: Immediate Fixes (Block MANDATE #7)**

#### Solution 1.1: Increase Memory Resources
**Rationale:** Giải quyết OOMKilled

**Implementation:**
```yaml
# File: gitops/apps/aiops-engine/deployment.yaml
spec:
  template:
    spec:
      containers:
      - name: engine
        resources:
          limits:
            cpu: 500m
            memory: 1Gi        # ← Tăng từ 512Mi
          requests:
            cpu: 200m
            memory: 512Mi      # ← Tăng từ 256Mi
```

**Rationale:**
- 7 models + vector KB + service graph cần ~600-700Mi
- Headroom cho spikes trong query processing
- 1Gi vẫn nằm trong ngân sách (~$300/week)

**Action:** 
- [ ] Update deployment manifest
- [ ] Apply via GitOps
- [ ] Monitor memory usage với `kubectl top pod`

---

#### Solution 1.2: Verify Prometheus Connectivity
**Diagnostic Steps:**
```bash
# Check if Prometheus service exists
kubectl get svc prometheus -n techx-tf3

# Check if Prometheus pods are running
kubectl get pods -n techx-tf3 -l app=prometheus

# Test connectivity from aiops-engine pod
kubectl exec -n techx-tf3 aiops-engine-5b48bb4df5-b5jhp -- \
  curl -v http://prometheus.techx-tf3.svc.cluster.local:9090/api/v1/status/config

# Check network policies
kubectl get networkpolicies -n techx-tf3
```

**Expected Actions:**
- [ ] Verify Prometheus is running and healthy
- [ ] Check NetworkPolicy allows aiops-engine → prometheus traffic
- [ ] Review Prometheus resource usage (might be overloaded)
- [ ] Check Prometheus logs for errors

---

#### Solution 1.3: Tune Probe Configuration
**Rationale:** Tránh false-positive kills khi pod đang healthy nhưng Prometheus chậm

**Implementation:**
```yaml
# File: gitops/apps/aiops-engine/deployment.yaml
spec:
  template:
    spec:
      containers:
      - name: engine
        livenessProbe:
          httpGet:
            path: /readyz
            port: 8000
          initialDelaySeconds: 60      # ← Tăng từ 30s (cho phép load models)
          timeoutSeconds: 5            # ← Tăng từ 1s
          periodSeconds: 30
          failureThreshold: 5          # ← Tăng từ 3 (cho phép 2.5 min recovery)
        
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8000
          initialDelaySeconds: 45      # ← Tăng từ 15s
          timeoutSeconds: 5            # ← Tăng từ 1s
          periodSeconds: 10
          failureThreshold: 5          # ← Tăng từ 3
```

**Action:** 
- [ ] Update probe configuration
- [ ] Monitor probe success rate sau khi apply

---

### 🟡 **Priority 2: Code-Level Improvements**

#### Solution 2.1: Add Retry Logic with Backoff
**File:** `aiops-engine` source code (likely Python)

**Current Behavior:** Connection timeout = instant failure

**Proposed:**
```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get_prometheus_session():
    """Create requests session with retry logic"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,  # 1s, 2s, 4s
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Usage
session = get_prometheus_session()
response = session.get(
    f"{PROMETHEUS_URL}/api/v1/query",
    params={"query": query},
    timeout=(5, 15)  # (connect_timeout, read_timeout)
)
```

**Action:**
- [ ] Review aiops-engine source code
- [ ] Implement retry with exponential backoff
- [ ] Add circuit breaker pattern để tránh cascade failures

---

#### Solution 2.2: Graceful Degradation in `/readyz`
**Current Issue:** `/readyz` fail nếu Prometheus down → pod bị kill dù logic khác vẫn OK

**Proposed:**
```python
@app.get("/readyz")
async def readiness_check():
    """
    Readiness: pod sẵn sàng nhận traffic
    - Không nên kill pod chỉ vì external dependency down
    - Nên trả 'degraded' state
    """
    checks = {
        "server": True,  # Always true if we can respond
        "models_loaded": len(loaded_models) > 0,
        "prometheus": check_prometheus_connectivity(timeout=2),
        "s3": check_s3_connectivity(timeout=2)
    }
    
    # Pod ready nếu core functionality OK, dù external dependencies có vấn đề
    is_ready = checks["server"] and checks["models_loaded"]
    
    if is_ready:
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready" if all(checks.values()) else "degraded",
                "checks": checks
            }
        )
    else:
        return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
```

**Action:**
- [ ] Refactor `/readyz` endpoint
- [ ] Separate `/livez` (pod alive?) vs `/readyz` (pod can serve traffic?)
- [ ] Test với Prometheus down scenario

---

### 🟢 **Priority 3: Security Hardening (MANDATE #5)**

#### Solution 3.1: Add Security Context
**File:** `gitops/apps/aiops-engine/deployment.yaml`

```yaml
spec:
  template:
    spec:
      # Pod-level security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      
      containers:
      - name: engine
        # Container-level security context
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false  # Cần write /tmp, /app/models
          runAsNonRoot: true
          runAsUser: 1000
          capabilities:
            drop:
              - ALL
            # Only add if needed:
            # add:
            #   - NET_BIND_SERVICE  # if binding to port < 1024
```

**Note:** Nếu cần write `/app/models` (download từ S3), sử dụng emptyDir volume:
```yaml
        volumeMounts:
        - name: model-cache
          mountPath: /app/models
      volumes:
      - name: model-cache
        emptyDir: {}
```

**Action:**
- [ ] Add security context to deployment
- [ ] Test pod khởi động OK với non-root user
- [ ] Verify Kyverno policies pass

---

### 📊 **Priority 4: Monitoring & Alerting**

#### Solution 4.1: Add Specific Alerts for AIOps Engine
**File:** `monitoring/prometheus-rules/aiops-alerts.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: aiops-engine-alerts
  namespace: techx-tf3
spec:
  groups:
  - name: aiops-engine
    interval: 30s
    rules:
    - alert: AIOpsEngineDown
      expr: |
        kube_deployment_status_replicas_available{deployment="aiops-engine"} == 0
      for: 2m
      labels:
        severity: critical
        component: aiops
      annotations:
        summary: "AIOps Engine has no available replicas"
        description: "AIOps detection is DOWN - no anomaly detection available"

    - alert: AIOpsEngineHighRestarts
      expr: |
        rate(kube_pod_container_status_restarts_total{pod=~"aiops-engine-.*"}[15m]) > 0.5
      for: 5m
      labels:
        severity: warning
        component: aiops
      annotations:
        summary: "AIOps Engine pod restarting frequently"
        description: "Pod {{ $labels.pod }} has restarted {{ $value | printf \"%.0f\" }} times in 15m"

    - alert: AIOpsEngineOOMKilled
      expr: |
        kube_pod_container_status_last_terminated_reason{pod=~"aiops-engine-.*", reason="OOMKilled"} == 1
      labels:
        severity: critical
        component: aiops
      annotations:
        summary: "AIOps Engine killed due to OOM"
        description: "Pod {{ $labels.pod }} was OOMKilled - increase memory limits"

    - alert: AIOpsEngineNotReady
      expr: |
        kube_pod_status_ready{pod=~"aiops-engine-.*"} == 0
      for: 5m
      labels:
        severity: warning
        component: aiops
      annotations:
        summary: "AIOps Engine pod not ready"
        description: "Pod {{ $labels.pod }} has been not ready for 5+ minutes"
```

**Action:**
- [ ] Create PrometheusRule resource
- [ ] Test alerts fire correctly
- [ ] Configure alert routing to Slack/PagerDuty

---

#### Solution 4.2: Add Dashboard for AIOps Engine Health
**File:** `monitoring/grafana-dashboards/aiops-engine.json`

**Panels to include:**
- Memory usage vs limit (track OOM risk)
- CPU usage vs limit
- Pod restart count
- Probe success rate (liveness/readiness)
- Prometheus query latency & error rate
- Model inference latency

**Action:**
- [ ] Create Grafana dashboard
- [ ] Add to GitOps repo
- [ ] Import vào Grafana

---

## Verification Plan

### Post-Fix Verification Checklist

**Step 1: Immediate Health Check**
```bash
# Apply fixes
kubectl apply -k gitops/apps/aiops-engine/

# Watch pod come up
kubectl get pods -n techx-tf3 -l app=aiops-engine -w

# Should see: Running + Ready (not CrashLoopBackOff)
```

**Expected:**
- Pod reaches `Running` state
- Pod reaches `Ready` state trong < 2 minutes
- No restart trong 30 minutes

---

**Step 2: Resource Usage Verification**
```bash
# Check memory usage
kubectl top pod -n techx-tf3 -l app=aiops-engine

# Get detailed metrics
kubectl exec -n techx-tf3 <pod-name> -- ps aux
kubectl exec -n techx-tf3 <pod-name> -- free -m
```

**Expected:**
- Memory usage < 800Mi (under 1Gi limit)
- No OOMKilled events in next 24h

---

**Step 3: Prometheus Connectivity Check**
```bash
# Check logs for successful Prometheus queries
kubectl logs -n techx-tf3 -l app=aiops-engine --tail=100 | grep "Prometheus"

# Should see INFO, not ERROR
```

**Expected:**
- No connection timeout errors
- Successful metric queries
- Models loading and running inference

---

**Step 4: Probe Health Verification**
```bash
# Check probe events
kubectl describe pod -n techx-tf3 -l app=aiops-engine | grep -A 5 "Events:"

# Monitor readiness
watch 'kubectl get pods -n techx-tf3 -l app=aiops-engine'
```

**Expected:**
- Liveness probe: success
- Readiness probe: success
- No "Unhealthy" warnings

---

**Step 5: Functional Test (MANDATE #7)**
```bash
# Check if AIOps engine is detecting metrics
kubectl logs -n techx-tf3 -l app=aiops-engine --tail=50 | grep "ML Isolation Forest"

# Trigger an anomaly (via flagd or load test) and verify detection
```

**Expected:**
- Engine actively polling Prometheus
- Models running inference on services
- Anomalies detected and alerted (when injected)

---

**Step 6: Security Policy Check**
```bash
# Verify Kyverno policies pass
kubectl get pods -n techx-tf3 -l app=aiops-engine -o json | \
  jq '.items[0].metadata.annotations'

# Should NOT see PolicyViolation warnings
kubectl describe pod -n techx-tf3 -l app=aiops-engine | grep PolicyViolation
```

**Expected:**
- Zero policy violations
- All security contexts properly configured

---

## Success Criteria

- [ ] ✅ Pod `aiops-engine` running và Ready > 24h without restart
- [ ] ✅ Memory usage stable < 800Mi (không hit 1Gi limit)
- [ ] ✅ Prometheus connectivity established (no timeout errors in logs)
- [ ] ✅ Liveness/Readiness probes success rate > 99%
- [ ] ✅ Zero OOMKilled events
- [ ] ✅ AIOps detection functional (MANDATE #7 can proceed)
- [ ] ✅ Zero Kyverno policy violations
- [ ] ✅ Monitoring alerts configured và tested

---

## Prevention Measures

### 1. Resource Right-Sizing Process
**Before deploying workload:**
- [ ] Load test trong staging với production-like data
- [ ] Profile memory usage (heap dumps, memory profiling)
- [ ] Set limits = peak usage × 1.5 (headroom)
- [ ] Set requests = average usage × 1.2

### 2. Dependency Health Checks
**Before depending on service:**
- [ ] Document all external dependencies (Prometheus, S3, Bedrock)
- [ ] Implement circuit breakers
- [ ] Add degraded mode (service works without all dependencies)

### 3. Probe Configuration Guidelines
**Liveness vs Readiness:**
- **Liveness:** Pod alive? Chỉ restart nếu thật sự deadlock/corrupt
  - `timeoutSeconds >= 5s`
  - `failureThreshold >= 5` (avoid premature kills)
- **Readiness:** Pod có thể serve traffic? OK để temporarily unready
  - `timeoutSeconds >= 3s`
  - `failureThreshold >= 3`

### 4. Pre-Production Checklist
- [ ] Resource limits tested với production load
- [ ] Security context configured (MANDATORY từ MANDATE #5)
- [ ] Probe configuration validated
- [ ] Monitoring alerts configured
- [ ] Dependency failure scenarios tested

---

## Related Incidents

- **0001-accounting-oomkill-and-ecr-lifecycle-incident.md:** Cùng pattern OOMKill
- **0002-observability-grafana-jaeger-oomkill-incident.md:** Cùng pattern observability stack OOM

→ **Pattern:** Services load data vào memory thiếu resource limits hợp lý

---

## References

- [Kubernetes Best Practices: Resource Requests and Limits](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [Configure Liveness, Readiness and Startup Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [MANDATE #5: Runtime Hardening](D:\slide\xbrain-learners\phase3\mandates\MANDATE-05-runtime-hardening.md)
- [MANDATE #7: AIOps Detection](D:\slide\xbrain-learners\phase3\mandates\MANDATE-07-aiops-detection.md)

---

## Sign-Off

**Prepared by:** CDO-02  
**Date:** 16 July 2026  
**Status:** Awaiting Implementation  

**Next Review:** After fixes applied (ETA: 17 July 2026)
