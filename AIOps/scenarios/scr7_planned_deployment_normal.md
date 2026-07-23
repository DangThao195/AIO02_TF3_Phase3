# Scenario: Planned Deployment Rollout (Normal Operations)

**Scenario ID:** SCR-007  
**Incident Name:** Planned Deployment Rollout - NOT AN INCIDENT  
**Type:** Normal Operational Activity  
**Severity:** None (Expected Behavior)  
**SLO Violated:** No  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-007",
  "incident_name": "Planned Deployment Rollout - Normal Operations",
  "incident_type": "normal_deployment",
  "affected_services": ["frontend"],
  "affected_infrastructure": [],
  "severity": "none",
  "slo_violated": false,
  "customer_impact": "None - Zero-downtime deployment successful",
  
  "timeline": {
    "deployment_start": "2026-07-23T10:30:00+07:00",
    "canary_phase": "10:30-10:35 (5 minutes at 20% weight)",
    "full_rollout": "10:35-10:42 (7 minutes gradual increase to 100%)",
    "completion": "2026-07-23T10:42:00+07:00",
    "duration_minutes": 12,
    "description": "Rolling update of frontend service - v1.2.3 to v1.2.4 (UI improvements)"
  },
  
  "description": "Planned deployment of frontend service using Argo Rollouts with canary strategy. Pod churn visible: old pods terminating, new pods starting. Transient metric fluctuations during pod restarts: brief CPU spikes, connection draining, readiness probe delays. But: error rate stays <0.5%, no failed requests, RPS continuous, SLO maintained. This is NORMAL DEPLOYMENT BEHAVIOR - not an incident. Key indicators: matches deployment timeline, pod lifecycle events, transient nature, zero customer errors.",
  
  "tags": ["deployment", "rollout", "canary", "normal_behavior", "pod_churn", "false_positive_prevention"]
}
```

---

## 2️⃣ Telemetry Behavior

### 2.1. Metrics Schema & Behavior

```json
{
  "metrics_behavior": {
    "frontend_service": {
      "pod_ready_count": {
        "metric_path": "sum(kube_pod_status_ready{pod=~'frontend.*',condition='true'})",
        "unit": "count",
        "baseline": {
          "mean": 3,
          "pattern": "stable"
        },
        "during_deployment": {
          "behavior": "oscillating_with_extra_capacity",
          "pattern": "3 → 4 → 3 → 4 → 3 (rolling)",
          "reasoning": "RollingUpdate with maxSurge=1: creates new pod before terminating old, always ≥3 pods ready"
        }
      },
      
      "pod_not_ready_count": {
        "metric_path": "sum(kube_pod_status_ready{pod=~'frontend.*',condition='false'})",
        "unit": "count",
        "baseline": {
          "mean": 0
        },
        "during_deployment": {
          "behavior": "transient_spikes",
          "pattern": "0 → 1 → 0 → 1 → 0 (brief, <30s each)",
          "reasoning": "New pods go through: Pending → ContainerCreating → Running(NotReady) → Ready"
        }
      },
      
      "rps": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='frontend',span_kind='SPAN_KIND_SERVER'}[5m]))",
        "unit": "requests/second",
        "baseline": {
          "mean": 50,
          "std_dev": 5,
          "pattern": "stable"
        },
        "during_deployment": {
          "behavior": "stable",
          "mean": 50,
          "std_dev": 5,
          "reasoning": "RPS unchanged - rolling update maintains capacity, users don't notice"
        }
      },
      
      "error_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='frontend',status_code='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='frontend'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 0.002,
          "std_dev": 0.001,
          "pattern": "low_stable"
        },
        "during_deployment": {
          "behavior": "stable",
          "mean": 0.002,
          "peak_value": 0.003,
          "reasoning": "Error rate unchanged - graceful connection draining prevents errors"
        }
      },
      
      "latency_p90": {
        "metric_path": "histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name='frontend',span_kind='SPAN_KIND_SERVER'}[5m])) by (le))",
        "unit": "milliseconds",
        "baseline": {
          "mean": 150,
          "std_dev": 20,
          "pattern": "stable"
        },
        "during_deployment": {
          "behavior": "brief_transient_spikes",
          "spike_pattern": "150ms → 220ms → 150ms (3 spikes, each <1 minute)",
          "reasoning": "New pods warming up: JIT compilation, cache cold start, connection pool initialization"
        }
      },
      
      "cpu_usage_per_pod": {
        "metric_path": "rate(container_cpu_usage_seconds_total{container='frontend'}[5m])",
        "unit": "cores",
        "baseline": {
          "mean": 0.3,
          "std_dev": 0.05,
          "pattern": "stable"
        },
        "during_deployment": {
          "behavior": "spikes_on_new_pods",
          "new_pod_pattern": "Spike to 0.8 cores for ~30s during startup, then settle to 0.3",
          "reasoning": "Startup costs: loading code, initializing connections, warming caches"
        }
      },
      
      "memory_usage_per_pod": {
        "metric_path": "container_memory_working_set_bytes{container='frontend'}",
        "unit": "bytes",
        "baseline": {
          "mean": "200Mi",
          "pattern": "stable"
        },
        "during_deployment": {
          "behavior": "new_pod_ramp",
          "new_pod_pattern": "Start at 50Mi → ramp to 200Mi over 2-3 minutes",
          "reasoning": "Memory allocated gradually as connections established and caches filled"
        }
      },
      
      "active_connections": {
        "metric_path": "sum(envoy_http_downstream_cx_active{envoy_cluster_name='frontend'})",
        "unit": "connections",
        "baseline": {
          "mean": 150,
          "pattern": "stable"
        },
        "during_deployment": {
          "behavior": "rebalancing",
          "pattern": "Per-pod: some drain 50→0, new pods ramp 0→50",
          "total": "Total stays ~150 (load balancer redistributes)",
          "reasoning": "Connection draining on old pods, new connections to new pods"
        }
      }
    }
  }
}
```

### 2.2. Logs Schema & Patterns

```json
{
  "logs_behavior": {
    "frontend_service": {
      "normal_logs": {
        "rate": "Standard logging"
      },
      
      "deployment_logs": {
        "patterns": [
          {
            "pattern": "INFO: Starting application version v1.2.4",
            "frequency": "3 times (once per new pod)",
            "timing": "At start of each pod lifecycle",
            "reasoning": "New version starting up"
          },
          {
            "pattern": "INFO: gRPC server listening on :8080",
            "frequency": "3 times",
            "reasoning": "Server initialization successful"
          },
          {
            "pattern": "INFO: Readiness probe succeeded",
            "frequency": "3 times",
            "reasoning": "Pod ready to receive traffic"
          },
          {
            "pattern": "INFO: Received SIGTERM, starting graceful shutdown",
            "frequency": "3 times (old pods)",
            "reasoning": "Kubernetes terminating old pods gracefully"
          },
          {
            "pattern": "INFO: Draining connections, no new requests accepted",
            "frequency": "3 times",
            "reasoning": "Connection draining during termination"
          },
          {
            "pattern": "INFO: All connections closed, shutting down",
            "frequency": "3 times",
            "reasoning": "Clean shutdown after drain period"
          }
        ],
        "no_errors": true,
        "note": "Logs show clean pod lifecycle - no errors, crashes, or unexpected behavior"
      }
    },
    
    "kubernetes_events": {
      "patterns": [
        {
          "event": "ReplicaSet frontend-v1-2-4-xxxx created",
          "timing": "10:30:00",
          "reasoning": "Deployment creates new ReplicaSet for v1.2.4"
        },
        {
          "event": "Scaled up replica set frontend-v1-2-4-xxxx to 1 (canary)",
          "timing": "10:30:05",
          "reasoning": "Argo Rollouts starts canary at 20%"
        },
        {
          "event": "Pod frontend-v1-2-4-abc created",
          "timing": "10:30:06"
        },
        {
          "event": "Successfully pulled image frontend:v1.2.4",
          "timing": "10:30:15"
        },
        {
          "event": "Started container frontend",
          "timing": "10:30:18"
        },
        {
          "event": "Readiness probe succeeded",
          "timing": "10:30:25"
        },
        {
          "event": "Scaled up replica set frontend-v1-2-4-xxxx to 2",
          "timing": "10:35:10",
          "reasoning": "Canary healthy, promoting to 50%"
        },
        {
          "event": "Scaled down replica set frontend-v1-2-3-yyyy to 2",
          "timing": "10:35:15",
          "reasoning": "Terminating old pod after new pod ready"
        },
        {
          "event": "Killing container with grace period 30",
          "timing": "10:35:16"
        }
      ]
    }
  }
}
```

### 2.3. Trace Behavior

```json
{
  "traces_behavior": {
    "normal_traces": {
      "request_flow": {
        "total_spans": 15,
        "duration_p90": 150,
        "error_rate": 0.002
      }
    },
    
    "during_deployment": {
      "request_flow_stable": {
        "total_spans": 15,
        "duration_p90": 150,
        "duration_p99": 220,
        "error_rate": 0.002,
        "note": "P99 slightly higher due to cold-start on new pods, but P90 unchanged - most requests unaffected"
      },
      
      "version_mix": {
        "description": "Traces show mix of v1.2.3 and v1.2.4 service versions during rollout",
        "reasoning": "Normal during canary - traffic split between versions",
        "both_versions_healthy": true
      }
    }
  }
}
```

---

## 3️⃣ Root Cause Information

```json
{
  "root_cause": {
    "summary": "NOT AN INCIDENT - Planned deployment rollout with canary strategy",
    "category": "normal_operational_activity",
    "subcategory": "controlled_deployment",
    
    "why_this_is_NOT_an_incident": [
      {
        "indicator": "Matches deployment timeline exactly",
        "evidence": "Git commit merged at 10:25, ArgoCD sync at 10:30, rollout 10:30-10:42",
        "reasoning": "Perfect correlation with planned deployment activity"
      },
      {
        "indicator": "Pod lifecycle events are normal",
        "evidence": "All pods go through: Pending → Running → Ready → Terminating → Terminated cleanly",
        "reasoning": "No crashes, restarts, or failures - textbook Kubernetes lifecycle"
      },
      {
        "indicator": "Error rate unchanged",
        "evidence": "Error rate 0.2% before, during, and after deployment",
        "reasoning": "Zero customer impact - graceful connection draining working"
      },
      {
        "indicator": "Transient metric changes",
        "evidence": "CPU/latency spikes last <60s per pod, then return to baseline",
        "reasoning": "Warm-up costs are temporary, not persistent problems"
      },
      {
        "indicator": "Canary progression healthy",
        "evidence": "20% canary → 5 min observation → 50% → 100%, no rollback",
        "reasoning": "Rollout strategy validation passed at each gate"
      },
      {
        "indicator": "No cascading effects",
        "evidence": "Only frontend affected, downstream services (checkout, payment) see no changes",
        "reasoning": "Isolated change with controlled blast radius"
      },
      {
        "indicator": "RPS continuous",
        "evidence": "RPS stays at 50 req/s throughout, no drops or spikes",
        "reasoning": "MaxSurge=1 ensures capacity maintained, users don't experience interruption"
      }
    ],
