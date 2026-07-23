# Scenario: Kafka Recreate Rollout Order Event Loss

**Scenario ID:** SCR-004  
**Incident Name:** Kafka Recreate Rollout Order Event Loss  
**Based on:** Postmortem 0007 (16/07/2026)  
**Severity:** Medium  
**SLO Violated:** No (customers not impacted)  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-004",
  "incident_name": "Kafka Recreate Rollout Order Event Loss",
  "incident_type": "infrastructure_change",
  "affected_services": ["kafka", "checkout"],
  "affected_infrastructure": ["kafka"],
  "severity": "medium",
  "slo_violated": false,
  "customer_impact": "None - PlaceOrder succeeded for customers. Data loss: ~22 order events lost to accounting/fraud-detection during Kafka downtime window",
  
  "timeline": {
    "detection_time": "2026-07-16T22:12:00+07:00",
    "resolution_time": "2026-07-16T22:15:00+07:00",
    "duration_minutes": 3,
    "incident_phases": {
      "trigger": "PR #145 merge at 22:12",
      "kafka_down": "22:12-22:15 (~3 minutes)",
      "recovery": "Kafka back Running, publish resumed"
    }
  },
  
  "description": "PR #145 added security hardening (allowPrivilegeEscalation: false, capabilities.drop: [ALL], seccompProfile: RuntimeDefault) to all workload pod templates. For Kafka (single-replica, PVC RWO, strategy: Recreate), any template change triggers downtime by design. During ~3-minute window (pod killed → scheduled → EBS attached → ready), checkout producer failed with connection refused. ~22 order events dropped permanently (no retry/DLQ in code).",
  
  "tags": ["kafka", "recreate", "deployment", "data_loss", "single_replica", "security_hardening"]
}
```

---

## 2️⃣ Telemetry Behavior

### 2.1. Metrics Schema & Behavior

```json
{
  "metrics_behavior": {
    "checkout_service": {
      "placeorder_success_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_name='oteldemo.CheckoutService/PlaceOrder',status_code!='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_name='oteldemo.CheckoutService/PlaceOrder'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 1.0,
          "std_dev": 0,
          "pattern": "perfect"
        },
        "during_incident": {
          "behavior": "stable",
          "mean": 1.0,
          "reasoning": "PlaceOrder calls succeeded - customers got order confirmation"
        }
      },
      
      "kafka_publish_success_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_name='publish orders',status_code!='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_name='publish orders'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 1.0,
          "std_dev": 0,
          "pattern": "perfect"
        },
        "during_incident": {
          "behavior": "drop",
          "start_value": 1.0,
          "drop_value": 0.954,
          "reasoning": "~22 publish failures out of ~477 orders in 30-min window = ~4.6% loss concentrated in 3-min downtime"
        }
      },
      
      "kafka_publish_errors": {
        "metric_path": "sum(increase(traces_span_metrics_calls_total{service_name='checkout',span_name='publish orders',status_code='STATUS_CODE_ERROR'}[30m]))",
        "unit": "count",
        "baseline": {
          "mean": 0,
          "std_dev": 0,
          "pattern": "zero"
        },
        "during_incident": {
          "behavior": "spike",
          "peak_value": 22,
          "reasoning": "Exactly 22 publish failures during Kafka downtime window"
        }
      }
    },
    
    "kafka_infrastructure": {
      "pod_restarts": {
        "metric_path": "kube_pod_container_status_restarts_total{pod=~'kafka.*'}",
        "unit": "count",
        "baseline": {
          "mean": 0
        },
        "during_incident": {
          "behavior": "increment",
          "change": "+1",
          "reasoning": "Recreate strategy forces pod replacement"
        }
      },
      
      "pod_ready": {
        "metric_path": "kube_pod_status_ready{pod=~'kafka.*'}",
        "unit": "boolean",
        "baseline": {
          "mean": 1
        },
        "during_incident": {
          "behavior": "drop_then_recover",
          "drop_duration_seconds": 180,
          "reasoning": "Pod not ready for ~3 minutes during recreation"
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
    "checkout_service": {
      "normal_logs": {
        "description": "Normal publish success logs"
      },
      
      "incident_logs": {
        "error_patterns": [
          {
            "pattern": "kafka: client has run out of available brokers to talk to: dial tcp 172.20.162.93:9092: connect: connection refused",
            "frequency": "22 occurrences",
            "reasoning": "172.20.162.93 = Kafka Service ClusterIP, TCP connection refused during pod recreation"
          }
        ]
      }
    },
    
    "kubernetes_events": {
      "patterns": [
        {
          "pattern": "ReplicaSet kafka-6b98c4888b created (revision 26)",
          "timing": "22:12",
          "reasoning": "New ReplicaSet due to pod template change"
        },
        {
          "pattern": "FailedScheduling: ~25 seconds",
          "timing": "22:12-22:13",
          "reasoning": "Cluster resource constraints + PV node affinity"
        },
        {
          "pattern": "AttachVolume: EBS volume attach",
          "timing": "22:13",
          "reasoning": "RWO PVC must detach from old node and attach to new"
        },
        {
          "pattern": "startup probe fail: dial tcp 10.0.25.7:9092: connection refused",
          "timing": "22:14",
          "reasoning": "Pod starting, Kafka not yet ready"
        },
        {
          "pattern": "Pod Ready",
          "timing": "22:15",
          "reasoning": "Kafka fully operational"
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
      "checkout_with_publish": {
        "span_breakdown": [
          {"name": "PlaceOrder", "status": "OK"},
          {"name": "payment.charge", "status": "OK"},
          {"name": "publish orders", "status": "OK"}
        ]
      }
    },
    
    "incident_traces": {
      "checkout_publish_failed": {
        "span_breakdown": [
          {"name": "PlaceOrder", "status": "OK", "changed": false, "reasoning": "Customer still got order confirmation"},
          {"name": "payment.charge", "status": "OK", "changed": false},
          {"name": "publish orders", "status": "ERROR", "changed": true, "reasoning": "Kafka connection refused"}
        ],
        "note": "PlaceOrder succeeds despite publish failure - code swallows error"
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
    "summary": "Kafka single-replica with Recreate strategy + pod template change = guaranteed downtime",
    "category": "infrastructure_architecture",
    "subcategory": "stateful_service_downtime",
    
    "causal_chain": [
      {
        "step": 1,
        "component": "kubernetes",
        "what_happened": "PR #145 merged - adds security hardening to all pod templates",
        "why": "Security best practices - correct change to make",
        "evidence": [
          "Diff: allowPrivilegeEscalation: false, capabilities.drop: [ALL], seccompProfile: RuntimeDefault",
          "Image unchanged (58b13f2-kafka)"
        ]
      },
      {
        "step": 2,
        "component": "argocd",
        "what_happened": "ArgoCD auto-sync triggers Kafka Deployment rollout",
        "why": "Pod template changed, Kubernetes creates new ReplicaSet",
        "evidence": [
          "ReplicaSet kafka-6b98c4888b (revision 26) created",
          "Old ReplicaSet kafka-55948d947f"
        ]
      },
      {
        "step": 3,
        "component": "kubernetes",
        "what_happened": "Kafka pod killed immediately (strategy: Recreate)",
        "why": "Single-replica + RWO PVC requires Recreate - cannot do RollingUpdate",
        "evidence": [
          "Deployment strategy: Recreate in values.yaml",
          "PVC with RWO (ReadWriteOnce) can only attach to one node"
        ]
      },
      {
        "step": 4,
        "component": "kubernetes",
        "what_happened": "New pod scheduling delayed ~25s, then EBS attach, then KRaft bootstrap",
        "why": "Cluster resource constraints + PV node affinity + stateful startup time",
        "evidence": [
          "FailedScheduling events for ~25 seconds",
          "Total downtime ~3 minutes"
        ]
      },
      {
        "step": 5,
        "component": "checkout",
        "what_happened": "Producer.SendMessage() fails with 'connection refused'",
        "why": "Kafka Service ClusterIP exists but no backend pod ready",
        "evidence": [
          "Error: dial tcp 172.20.162.93:9092: connect: connection refused",
          "172.20.162.93 = kafka Service ClusterIP"
        ]
      },
      {
        "step": 6,
        "component": "checkout",
        "what_happened": "sendToPostProcessor() logs error but doesn't retry, doesn't use DLQ",
        "why": "Code design: log + set span error, continue (main.go:687-693)",
        "evidence": [
          "22 'publish orders' span errors",
          "PlaceOrder() doesn't check return value from sendToPostProcessor"
        ]
      },
      {
        "step": 7,
        "component": "accounting/fraud-detection",
        "what_happened": "22 orders never arrive at consumers",
        "why": "Events never published to Kafka, lost permanently",
        "evidence": [
          "Accounting ledger missing 22 orders that were charged/shipped",
          "No way to recover from Kafka (events never written)"
        ]
      }
    ],
    
    "contributing_factors": [
      {
        "factor": "No process to flag stateful template changes",
        "description": "PR reviewed for security content, but no one flagged that touching Kafka template = planned downtime",
        "impact": "high",
        "evidence": "PR merged during business hours without awareness of Kafka restart consequence"
      },
      {
        "factor": "No retry/DLQ in checkout publish path",
        "description": "From REL-09: producer is now sync + WaitForAll (errors visible), but no retry logic",
        "impact": "high",
        "evidence": "Trade-off accepted in REL-09 - now quantified: 22 orders lost in 3 minutes"
      }
    ],
    
    "why_not_other_causes": {
      "btc_flag_injection": {
        "ruled_out": true,
        "reasoning": "Query flagd: all flags 'off'. Error signature matches Kafka downtime timeline exactly"
      },
      "kafka_broker_failure": {
        "ruled_out": true,
        "reasoning": "Intentional rollout, not broker crash - pod replaced due to template change"
      },
      "network_issue": {
        "ruled_out": true,
        "reasoning": "TCP connection refused at exact time of pod recreation - not network partition"
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
        "action_type": "none_required",
        "what": "No cluster action needed - Kafka already recovered",
        "how": "System self-recovered when new Kafka pod became Ready",
        "when": "2026-07-16T22:15:00+07:00",
        "duration": "Automatic after ~3 minutes",
        "result": "Kafka Running, publish resumed successfully"
      }
    ],
    
    "long_term_fixes": [
      {
        "fix": "PR process for stateful template changes",
        "description": "Any PR changing pod template of postgres/valkey/kafka must: (a) note 'causes restart, downtime ~X min' in PR description, (b) merge off-peak hours, (c) reviewer must verify this",
        "timeline": "Immediate - add to team process",
        "status": "proposed"
      },
      {
        "fix": "CI check for stateful template changes",
        "description": "Automated comment on PR if diff touches stateful workload blocks in values-prod.yaml",
        "timeline": "CI enhancement",
        "status": "proposed"
      },
      {
        "fix": "Reconcile 22 missing orders in accounting",
        "description": "Query Jaeger for traces with 'publish orders' ERROR span in 15:12-15:15 UTC window, extract app.order.id",
        "timeline": "Audit task",
        "status": "proposed"
      },
      {
        "fix": "Migrate to MSK multi-broker (Mandate #8)",
        "description": "Real fix: eliminate single-replica SPOF - MSK with 3 brokers has no downtime on pod changes",
        "timeline": "In progress - deadline 2026-07-20",
        "status": "blocked by postmortem 0010 issues"
      },
      {
        "fix": "Alert on producer publish errors",
        "description": "Alert: increase(traces_span_metrics_calls_total{service_name='checkout',span_name='publish orders',status_code='STATUS_CODE_ERROR'}[5m]) > 0",
        "timeline": "Add to alerting",
        "status": "proposed"
      }
    ]
  }
}
```

---

## 📝 Notes

- **No customer-facing failure:** PlaceOrder succeeded, customers got confirmation - only backend data loss
- **Data loss quantified:** 22 orders = ~4.6% in 30-min window, concentrated in 3-min downtime
- **By-design downtime:** Not a bug - architectural constraint of single-replica RWO stateful service
- **Second occurrence:** Similar data loss on 2026-07-14 during PVC cutover - pattern established
- **Real fix is architectural:** MSK multi-broker eliminates this failure mode entirely
- **Detection gap:** Discovered via manual Jaeger inspection - should have been automatic alert

---

**Version:** 1.0  
**Created:** Based on Postmortem 0007 (16/07/2026)  
**Last Updated:** 2026-07-22  
