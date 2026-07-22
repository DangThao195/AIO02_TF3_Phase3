# Scenario: Accounting Service OOMKilled Loop

**Scenario ID:** SCR-001  
**Incident Name:** Accounting OOMKilled Loop  
**Based on:** Postmortem 0001 (08/07/2026)  
**Severity:** Medium  
**SLO Violated:** No (not customer-facing)  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-001",
  "incident_name": "Accounting Service OOMKilled Loop",
  "incident_type": "resource_saturation",
  "affected_services": ["accounting"],
  "affected_infrastructure": [],
  "severity": "medium",
  "slo_violated": false,
  "customer_impact": "None - Accounting is async consumer, not on checkout path. Risk: Lost order events if killed mid-processing",
  
  "timeline": {
    "detection_method": "Manual observation via kubectl get pods",
    "incident_duration": "Ongoing ~19 hours (44 restarts)",
    "description": "Discovered during routine cluster health check by observing high RESTARTS count"
  },
  
  "description": "Accounting pod experienced 44 OOMKilled restarts over ~19 hours. Service is Kafka consumer (.NET, EF Core + Confluent Kafka) processing order events from load-generator. Memory limit 120Mi was insufficient for continuous consumption workload, causing kernel to kill process when it exceeded limit.",
  
  "tags": ["memory", "oomkilled", "kafka_consumer", "resource_limits", ".net"]
}
```

---

## 2️⃣ Telemetry Behavior

### 2.1. Metrics Schema & Behavior

```json
{
  "metrics_behavior": {
    "accounting_service": {
      "pod_restarts": {
        "metric_path": "kube_pod_container_status_restarts_total{pod=~'accounting.*'}",
        "unit": "count",
        "baseline": {
          "mean": 0,
          "std_dev": 0,
          "pattern": "stable"
        },
        "during_incident": {
          "behavior": "gradual_increase",
          "start_value": 0,
          "peak_value": 44,
          "spike_pattern": "continuous_accumulation",
          "reasoning": "OOMKilled every time memory exceeds 120Mi limit"
        }
      },
      
      "memory_usage": {
        "metric_path": "container_memory_working_set_bytes{container='accounting'}",
        "unit": "bytes",
        "baseline": {
          "description": "Not available - pod kept restarting"
        },
        "during_incident": {
          "behavior": "ceiling_hit",
          "peak_value": "~120Mi (at limit)",
          "max_limit": "120Mi",
          "reasoning": "Memory grows until hitting limit, then OOMKilled"
        }
      },
      
      "cpu_usage": {
        "metric_path": "sum(rate(container_cpu_usage_seconds_total{container='accounting'}[5m]))",
        "unit": "cores",
        "baseline": {
          "description": "Normal for Kafka consumer workload"
        },
        "during_incident": {
          "behavior": "stable",
          "reasoning": "CPU not the bottleneck - memory was the issue"
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
    "accounting_service": {
      "normal_logs": {
        "description": "Normal Kafka consumer processing logs"
      },
      
      "incident_logs": {
        "kubernetes_events": [
          {
            "pattern": "OOMKilled",
            "frequency": "44 times over 19 hours",
            "source": "kubectl describe pod",
            "reasoning": "lastState.terminated.reason: OOMKilled, exitCode: 137"
          }
        ]
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
    "summary": "Memory limit too low (120Mi) for .NET Kafka consumer workload",
    "category": "resource_misconfiguration",
    "subcategory": "insufficient_memory_limit",
    
    "causal_chain": [
      {
        "step": 1,
        "component": "accounting",
        "what_happened": "Service set with memory limit 120Mi in values.yaml",
        "why": "Initial configuration underestimated .NET + EF Core + Kafka client memory needs",
        "evidence": [
          "components.accounting.resources.limits.memory: 120Mi in techx-corp-chart/values.yaml",
          "Accounting is .NET service with EF Core + Confluent Kafka client"
        ]
      },
      {
        "step": 2,
        "component": "accounting",
        "what_happened": "Under continuous load from load-generator, memory grows beyond 120Mi",
        "why": ".NET runtime + Kafka consumer buffers + EF Core context need more than 120Mi",
        "evidence": [
          "Load-generator (Locust) continuously generating traffic",
          "Process memory exceeded limit"
        ]
      },
      {
        "step": 3,
        "component": "kubernetes",
        "what_happened": "Kernel/kubelet kills process when exceeds memory limit",
        "why": "Cgroup memory limit enforcement",
        "evidence": [
          "kubectl describe pod shows: lastState.terminated.reason: OOMKilled",
          "exitCode: 137 (128 + 9 SIGKILL)"
        ]
      },
      {
        "step": 4,
        "component": "accounting",
        "what_happened": "Pod restarts, repeats cycle - 44 times over 19 hours",
        "why": "No change to config, same limit causes same issue",
        "evidence": [
          "kube_pod_container_status_restarts_total = 44"
        ]
      }
    ],
    
    "contributing_factors": [
      {
        "factor": "Kafka consumer with EnableAutoCommit: true",
        "description": "Risk of data loss if killed mid-processing - offset committed but DB write incomplete",
        "impact": "high",
        "evidence": "Consumer config uses auto-commit"
      },
      {
        "factor": "Async consumer not on customer path",
        "description": "Why not discovered earlier - checkout still succeeds even if accounting crashes",
        "impact": "medium",
        "evidence": "Customers can place orders successfully despite accounting issues"
      }
    ],
    
    "why_not_other_causes": {
      "memory_leak": {
        "ruled_out": false,
        "reasoning": "Could be contributing but limit is definitely too low regardless"
      },
      "cpu_bottleneck": {
        "ruled_out": true,
        "reasoning": "CPU not saturated"
      },
      "kafka_issues": {
        "ruled_out": true,
        "reasoning": "Kafka itself working fine, other consumers OK"
      }
    }
  }
}
```

---

## 4️⃣ Remediation Actions

```json
{
  "remediation": {
    "actions_taken": [
      {
        "action_number": 1,
        "action_type": "increase_resource_limit",
        "what": "Increased memory limit from 120Mi to 350Mi",
        "how": "helm upgrade --set components.accounting.resources.limits.memory=350Mi",
        "when": "After identifying OOMKilled pattern",
        "duration": "Immediate (helm upgrade time)",
        "result": "Success - 0 restarts after change, memory usage stable at ~350Mi"
      }
    ],
    
    "long_term_fixes": [
      {
        "fix": "Add alert for pod restart count",
        "description": "Grafana alert when restarts > threshold in X minutes - automated detection instead of manual kubectl",
        "timeline": "Backlog - Reliability",
        "status": "proposed"
      },
      {
        "fix": "Review resource limits for all services",
        "description": "Audit all service limits against actual usage patterns",
        "timeline": "Next sprint",
        "status": "proposed"
      }
    ]
  }
}
```

---

## 📝 Notes

- **Detection gap:** No automated alerting on restart count - discovered only through manual observation
- **No customer impact:** Accounting is async consumer, not blocking customer checkout flow
- **Data loss risk:** With auto-commit enabled, order events could be lost if killed during processing
- **Related:** Postmortem also mentions ECR lifecycle policy incident (separate issue, not part of this scenario)

---

**Version:** 1.0  
**Created:** Based on Postmortem 0001 (08/07/2026)  
**Last Updated:** 2026-07-22  
