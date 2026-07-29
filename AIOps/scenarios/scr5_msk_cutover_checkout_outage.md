# Scenario: MSK Cutover Checkout Outage

**Scenario ID:** SCR-005  
**Incident Name:** MSK Cutover Checkout Outage (Producer Client Bug)  
**Based on:** Postmortem 0010 (19/07/2026)  
**Severity:** Critical  
**SLO Violated:** Yes (checkout ≥99% success)  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-005",
  "incident_name": "MSK Cutover Checkout Outage (Producer Client Bug)",
  "incident_type": "configuration_error",
  "affected_services": ["checkout"],
  "affected_infrastructure": ["kafka", "msk"],
  "severity": "critical",
  "slo_violated": true,
  "customer_impact": "Critical - ~14 minutes complete checkout outage. Orders attempted during window were charged (mock) + shipped but NOT recorded in accounting (panic before Kafka publish)",
  
  "timeline": {
    "detection_time": "2026-07-19T22:27:00+07:00",
    "resolution_time": "2026-07-19T22:40:00+07:00",
    "duration_minutes": 14,
    "incident_phases": {
      "pre_flight": "22:00 - MSK pre-flight checks all green",
      "canary_start": "22:08 - Rollout canary 20% weight",
      "canary_no_traffic": "22:12 - Canary receives no traffic (gRPC pinning)",
      "promote_100": "22:26 - Promote to 100% MSK",
      "outage_start": "22:27 - Checkout panic CrashLoopBackOff",
      "revert_start": "22:32 - Revert PR #262",
      "recovery": "22:40 - Checkout back on old Kafka, healthy"
    }
  },
  
  "description": "Mandate #8 MSK migration: cutover checkout producer from in-cluster Kafka to MSK. When promoted to 100%, checkout failed to create Kafka producer due to bug: KAFKA_ADDR env contained CSV of 3 brokers ('b-1:9096,b-2:9096,b-3:9096'), but code wrapped entire string as single broker address. sarama.Dial() failed with 'too many colons in address'. Checkout lacked fail-fast - pod became Ready despite nil producer. Every PlaceOrder hit nil pointer panic → CrashLoopBackOff. Root cause: missing strings.Split() on broker CSV.",
  
  "tags": ["msk", "migration", "panic", "nil_pointer", "fail_fast", "configuration", "golang"]
}
```

---

## 2️⃣ Telemetry Behavior

### 2.1. Metrics Schema & Behavior

```json
{
  "metrics_behavior": {
    "checkout_service": {
      "pod_ready_count": {
        "metric_path": "sum(kube_pod_status_ready{pod=~'checkout.*'})",
        "unit": "count",
        "baseline": {
          "mean": 2,
          "pattern": "stable"
        },
        "during_incident": {
          "behavior": "drop",
          "drop_value": 0,
          "reasoning": "All pods CrashLoopBackOff - none Ready"
        }
      },
      
      "pod_restart_count": {
        "metric_path": "sum(kube_pod_container_status_restarts_total{pod=~'checkout.*'})",
        "unit": "count",
        "baseline": {
          "mean": 0
        },
        "during_incident": {
          "behavior": "rapid_increase",
          "rate": "Multiple restarts per minute",
          "reasoning": "Panic on every startup → crash → restart loop"
        }
      },
      
      "placeorder_success_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_name='oteldemo.CheckoutService/PlaceOrder',status_code!='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_name='oteldemo.CheckoutService/PlaceOrder'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 1.0
        },
        "during_incident": {
          "behavior": "drop",
          "drop_value": 0,
          "reasoning": "No healthy pods to serve requests"
        }
      }
    },
    
    "msk_infrastructure": {
      "msk_offset": {
        "metric_path": "kafka_topic_partition_current_offset{topic='orders'}",
        "unit": "offset",
        "baseline": {
          "description": "Continuously increasing as orders published"
        },
        "during_incident": {
          "behavior": "stuck",
          "value": 0,
          "reasoning": "MSK orders topic never received any messages - producer failed to connect"
        }
      }
    },
    
    "old_kafka": {
      "kafka_offset": {
        "metric_path": "kafka_topic_partition_current_offset{topic='orders'}",
        "unit": "offset",
        "baseline": {
          "description": "Increasing normally before cutover"
        },
        "during_incident": {
          "behavior": "stopped",
          "reasoning": "After promote to 100% MSK, no traffic to old Kafka (intentional cutover)"
        },
        "after_revert": {
          "behavior": "resumed",
          "reasoning": "After rollback, offset starts increasing again"
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
        "description": "Normal startup and order processing logs"
      },
      
      "incident_logs": {
        "error_patterns": [
          {
            "pattern": "nil pointer panic at sendToPostProcessor (main.go:693)",
            "frequency": "every PlaceOrder call",
            "reasoning": "Producer = nil, calling SendMessage() on nil panics"
          },
          {
            "pattern": "panic: runtime error: invalid memory address or nil pointer dereference",
            "frequency": "high",
            "reasoning": "cs.KafkaProducerClient is nil"
          }
        ],
        "note": "Initial logs after PR #269 added stderr logging revealed actual error"
      },
      
      "stderr_logs_after_fix": {
        "error_patterns": [
          {
            "pattern": "client/metadata got error from broker -1 while fetching metadata: dial tcp: address b-1...:9096,b-2...:9096,b-3...:9096: too many colons in address",
            "frequency": "at startup",
            "reasoning": "Root cause exposed - entire CSV string passed as single address"
          },
          {
            "pattern": "kafka: client has run out of available brokers to talk to",
            "frequency": "at startup",
            "reasoning": "No valid brokers parsed, producer creation fails"
          }
        ]
      }
    },
    
    "kubernetes_events": {
      "patterns": [
        {
          "pattern": "Pod checkout-xxx-xxx Back-off restarting failed container",
          "frequency": "continuous",
          "reasoning": "CrashLoopBackOff due to panic"
        },
        {
          "pattern": "Readiness probe failed",
          "frequency": "after panic",
          "reasoning": "gRPC server may start but pod crashes immediately on first request"
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
      "checkout_flow": {
        "total_spans": 30,
        "duration_p90": 200,
        "error_rate": 0.001,
        "span_breakdown": [
          {"name": "PlaceOrder", "status": "OK"},
          {"name": "payment.charge", "status": "OK"},
          {"name": "kafka.publish", "status": "OK"}
        ]
      }
    },
    
    "incident_traces": {
      "no_traces": {
        "description": "No traces generated - pods crash before completing any request",
        "reasoning": "Panic occurs immediately when PlaceOrder tries to publish, no span export"
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
    "summary": "CSV broker addresses passed as single string to sarama, missing strings.Split()",
    "category": "application_configuration_bug",
    "subcategory": "string_parsing_error",
    
    "causal_chain": [
      {
        "step": 1,
        "component": "checkout",
        "what_happened": "KAFKA_ADDR env set to CSV of 3 MSK brokers: 'b-1...:9096,b-2...:9096,b-3...:9096'",
        "why": "MSK has 3 brokers, need all for redundancy",
        "evidence": [
          "PR #262: KAFKA_ADDR set to MSK bootstrap servers",
          "MSK deployment standard: 3 brokers across 3 AZs"
        ]
      },
      {
        "step": 2,
        "component": "checkout",
        "what_happened": "Code passes []string{os.Getenv('KAFKA_ADDR')} to sarama.NewSyncProducer",
        "why": "Developer assumed single broker string, wrapped in slice",
        "evidence": [
          "checkout/main.go: CreateKafkaProducer takes KAFKA_ADDR as single string",
          "[]string{addr} creates slice with ONE element = entire CSV string"
        ]
      },
      {
        "step": 3,
        "component": "sarama",
        "what_happened": "sarama.Dial() tries to connect to 'b-1:9096,b-2:9096,b-3:9096' as single address",
        "why": "sarama receives malformed address in brokers slice",
        "evidence": [
          "Error: 'dial tcp: address b-1...:9096,b-2...:9096,b-3...:9096: too many colons in address'",
          "net.Dial expects 'host:port', gets 'host:port,host:port,host:port'"
        ]
      },
      {
        "step": 4,
        "component": "sarama",
        "what_happened": "NewSyncProducer returns error, producer = nil",
        "why": "Cannot parse broker address, connection fails before TLS/SASL handshake",
        "evidence": [
          "Producer creation fails at network layer",
          "TLS/SASL/idempotent all correct but never reached"
        ]
      },
      {
        "step": 5,
        "component": "checkout",
        "what_happened": "CreateKafkaProducer returns nil, code logs error but continues",
        "why": "No fail-fast: pod starts gRPC server despite failed producer creation",
        "evidence": [
          "Code: logger.Error(err) then continue",
          "No os.Exit(1), no readiness check for producer"
        ]
      },
      {
        "step": 6,
        "component": "checkout",
        "what_happened": "Pod becomes Ready with nil producer",
        "why": "Readiness only checks gRPC port :8080, doesn't validate Kafka connection",
        "evidence": [
          "Kubernetes marks pod Ready",
          "Pod receives traffic"
        ]
      },
      {
        "step": 7,
        "component": "checkout",
        "what_happened": "PlaceOrder calls cs.KafkaProducerClient.SendMessage() on nil",
        "why": "Producer never initialized, field = nil",
        "evidence": [
          "Panic: nil pointer dereference at sendToPostProcessor",
          "main.go:693"
        ]
      },
      {
        "step": 8,
        "component": "checkout",
        "what_happened": "Process crashes, Kubernetes restarts, repeat",
        "why": "No panic recovery, process exits, CrashLoopBackOff",
        "evidence": [
          "Pod restart count rapidly increasing",
          "Back-off restarting failed container"
        ]
      },
      {
        "step": 9,
        "component": "argo-rollouts",
        "what_happened": "Cannot abort/undo - 100% promote made MSK revision 'stable'",
        "why": "After promote --full to 100%, no old revision to roll back to",
        "evidence": [
          "kubectl argo rollouts abort/undo both failed",
          "Rollout uses workloadRef, ArgoCD owns template"
        ]
      }
    ],
    
    "contributing_factors": [
      {
        "factor": "Code only tested with single-broker Kafka",
        "description": "In-cluster Kafka has 1 broker (kafka:9092), bug hidden until MSK with 3 brokers",
        "impact": "critical",
        "evidence": "[]string{addr} works for single broker, breaks for CSV"
      },
      {
        "factor": "gRPC connection pinning prevented canary validation",
        "description": "Canary at 20% weight received no traffic due to HTTP/2 connection reuse",
        "impact": "high",
        "evidence": "MSK offset stayed at 0 during canary phase, couldn't validate client path"
      },
      {
        "factor": "Lack of fail-fast",
        "description": "Most critical: pod should crash/fail readiness if KAFKA_ADDR set but producer fails",
        "impact": "critical",
        "evidence": "This turned config error into 14-minute outage instead of safe rollout block"
      },
      {
        "factor": "Pre-flight only validated server-side",
        "description": "kafka-console-producer proved MSK + SCRAM work, but didn't test checkout's sarama client",
        "impact": "high",
        "evidence": "Idempotent producer, TLS config, SCRAM implementation all worked - just address parsing failed"
      }
    ],
    
    "why_not_other_causes": {
      "tls_issue": {
        "ruled_out": true,
        "reasoning": "After fix, TLS handshake succeeded. Error was before TLS layer - at TCP dial"
      },
      "scram_authentication": {
        "ruled_out": true,
        "reasoning": "After fix, SASL authentication succeeded. Never reached auth due to address parse error"
      },
      "idempotent_producer_acl": {
        "ruled_out": true,
        "reasoning": "After fix, InitProducerId succeeded (ProducerId:8130). ACLs were correct"
      },
      "msk_configuration": {
        "ruled_out": true,
        "reasoning": "MSK itself healthy, kafka-console-producer/consumer worked fine"
      },
      "network_connectivity": {
        "ruled_out": true,
        "reasoning": "TCP connection to individual brokers worked in pre-flight. Issue was parsing 3 addresses as 1"
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
        "action_type": "rollback",
        "what": "Revert PR #262 via emergency PR #265",
        "how": "Git revert checkout KAFKA_ADDR back to kafka:9092 (old Kafka), merge, ArgoCD sync",
        "when": "2026-07-19T22:32:00+07:00",
        "duration": "~8 minutes (revert + merge + sync + rollout promote)",
        "result": "Success - checkout back on old Kafka, pods Running, publish resumed"
      },
      {
        "action_number": 2,
        "action_type": "diagnosis",
        "what": "Create isolated checkout pod with MSK env + stderr logging (PR #269)",
        "how": "Build image with stderr logging, run pod outside Service to diagnose without affecting traffic",
        "when": "2026-07-20 (post-incident)",
        "duration": "Investigation phase",
        "result": "Successfully captured actual error: 'too many colons in address'"
      }
    ],
    
    "long_term_fixes": [
      {
        "fix": "Parse KAFKA_ADDR as CSV (PR #271)",
        "description": "Change []string{os.Getenv('KAFKA_ADDR')} to strings.Split(os.Getenv('KAFKA_ADDR'), ',') with trim and empty filter",
        "timeline": "Completed",
        "status": "merged",
        "verification": "Isolated pod with fix: all 3 brokers registered, SASL succeeded, idempotent InitProducerId succeeded"
      },
      {
        "fix": "Add fail-fast on producer creation failure (PR #269)",
        "description": "If KAFKA_ADDR set and CreateKafkaProducer returns error → os.Exit(1) before starting gRPC server",
        "timeline": "Completed",
        "status": "merged",
        "result": "Future config errors will block rollout safely instead of causing outage"
      },
      {
        "fix": "Add stderr logging for Kafka errors (PR #269)",
        "description": "Log Kafka errors to stderr (visible via kubectl logs) in addition to OTel pipeline",
        "timeline": "Completed",
        "status": "merged",
        "result": "Diagnosis possible even if OTel pipeline unavailable"
      },
      {
        "fix": "Add nil-guard in sendToPostProcessor (PR #269)",
        "description": "Check if producer != nil before calling SendMessage()",
        "timeline": "Completed",
        "status": "merged",
        "result": "Defense-in-depth: prevents panic even if fail-fast somehow bypassed"
      },
      {
        "fix": "Update runbook: test client in isolation before cutover",
        "description": "For gRPC services, canary weight doesn't validate client path. Must test with isolated pod first.",
        "timeline": "Documentation update",
        "status": "completed"
      },
      {
        "fix": "Retry MSK cutover with all fixes",
        "description": "Reattempt Kafka → MSK migration with PR #271 + #269 fixes deployed",
        "timeline": "After verification",
        "status": "blocked until fixes verified on old Kafka"
      }
    ]
  }
}
```

---

## 📝 Notes

- **Root cause surprise:** Not TLS/SASL/ACL/protocol issues - simple string parsing bug
- **Hidden by single-broker setup:** []string{addr} works fine for "kafka:9092", breaks for "b1:9096,b2:9096,b3:9096"
- **Fail-fast critical lesson:** Config error became outage because pod started despite broken producer
- **Canary ineffective for gRPC:** Connection pinning means low-weight canary gets no traffic to validate
- **Data loss bounded:** Orders during outage charged+shipped but not recorded in accounting (panic before publish)
- **Rollback complexity:** Promote 100% made abort/undo ineffective - needed git revert + full redeploy
- **Pre-flight limitations:** Console tools validated server-side, missed client library-specific issues
- **MSK migration blocked:** Must fix code before retry, Kafka→MSK cutover postponed

---

**Version:** 1.0  
**Created:** Based on Postmortem 0010 (19/07/2026)  
**Last Updated:** 2026-07-22  
