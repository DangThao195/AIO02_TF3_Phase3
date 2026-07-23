# Scenario: Checkout Kafka Producer Timeout

**Scenario ID:** SCR-002  
**Incident Name:** Checkout Kafka Producer Timeout (Race Condition)  
**Based on:** Postmortem 0003 (14/07/2026)  
**Severity:** Critical  
**SLO Violated:** Yes (checkout ≥99% success)  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-002",
  "incident_name": "Checkout Kafka Producer Timeout (Race Condition)",
  "incident_type": "application_logic_error",
  "affected_services": ["checkout"],
  "affected_infrastructure": [],
  "severity": "critical",
  "slo_violated": true,
  "customer_impact": "High - ~9% checkout requests failed, remaining requests experienced extreme latency (up to 15s timeout)",
  
  "timeline": {
    "detection_method": "Load test observation via Locust",
    "incident_duration": "Ongoing since code change (REL-09) until fixed - not self-recovering",
    "description": "RPS dropped from ~45 to ~2 and never recovered for 4+ hours"
  },
  
  "description": "During load testing with 10 concurrent users, POST /api/checkout experienced ~9% failure rate and extreme latency (15s timeout). Root cause: AsyncProducer shared channel race condition where multiple concurrent PlaceOrder goroutines competed for Kafka ACK signals on shared Successes()/Errors() channels, causing some requests to 'steal' ACKs meant for others. Requests that lost their ACK signal hung until Envoy's 15s default timeout.",
  
  "tags": ["kafka", "concurrency", "race_condition", "golang", "async_producer", "timeout"]
}
```

---

## 2️⃣ Telemetry Behavior

### 2.1. Metrics Schema & Behavior

```json
{
  "metrics_behavior": {
    "checkout_service": {
      "rps": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_kind='SPAN_KIND_SERVER'}[5m]))",
        "unit": "requests/second",
        "baseline": {
          "mean": 45,
          "std_dev": 3,
          "pattern": "stable"
        },
        "during_incident": {
          "behavior": "drop",
          "start_value": 45,
          "drop_value": 2,
          "reasoning": "Most requests timing out at 15s, severely limiting throughput"
        }
      },
      
      "error_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_kind='SPAN_KIND_SERVER',status_code='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_kind='SPAN_KIND_SERVER'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 0.001,
          "std_dev": 0.0005,
          "pattern": "low_stable"
        },
        "during_incident": {
          "behavior": "spike",
          "start_value": 0.001,
          "peak_value": 0.09,
          "reasoning": "~9% requests failed after 15s timeout"
        }
      },
      
      "latency_p95": {
        "metric_path": "histogram_quantile(0.95, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name='checkout',span_kind='SPAN_KIND_SERVER'}[5m])) by (le))",
        "unit": "milliseconds",
        "baseline": {
          "mean": 200,
          "std_dev": 50,
          "pattern": "stable"
        },
        "during_incident": {
          "behavior": "ceiling_hit",
          "peak_value": 15000,
          "max_limit": 15000,
          "reasoning": "P95/P99 both stuck at 15000ms - Envoy default timeout"
        }
      },
      
      "latency_median": {
        "metric_path": "histogram_quantile(0.50, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name='checkout',span_kind='SPAN_KIND_SERVER'}[5m])) by (le))",
        "unit": "milliseconds",
        "baseline": {
          "mean": 100,
          "std_dev": 20,
          "pattern": "stable"
        },
        "during_incident": {
          "behavior": "spike",
          "peak_value": 1200,
          "reasoning": "Even successful requests delayed by contention"
        }
      },
      
      "cpu_usage": {
        "metric_path": "sum(rate(container_cpu_usage_seconds_total{container='checkout'}[5m]))",
        "unit": "cores",
        "baseline": {
          "mean": 0.4,
          "std_dev": 0.05,
          "pattern": "proportional_to_rps"
        },
        "during_incident": {
          "behavior": "stable",
          "mean": 0.15,
          "reasoning": "CPU drops due to lower effective throughput - goroutines mostly waiting"
        }
      },
      
      "memory_usage": {
        "metric_path": "container_memory_working_set_bytes{container='checkout'}",
        "unit": "bytes",
        "baseline": {
          "description": "Normal for checkout workload"
        },
        "during_incident": {
          "behavior": "stable",
          "reasoning": "Memory not the issue"
        }
      }
    },
    
    "other_endpoints": {
      "cart_rps": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='frontend',span_name=~'.*cart.*'}[5m]))",
        "unit": "requests/second",
        "baseline": {
          "description": "Normal cart operations"
        },
        "during_incident": {
          "behavior": "stable",
          "reasoning": "GET /api/cart and POST /api/cart remain fast and healthy"
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
        "description": "Normal order processing logs"
      },
      
      "incident_logs": {
        "description": "No explicit error logs in checkout (goroutines silently waiting on channel select)",
        "patterns": [
          {
            "pattern": "Trace shows 'Incomplete' status",
            "frequency": "high",
            "reasoning": "Traces not flushed because request hung until timeout"
          }
        ]
      }
    },
    
    "frontend_proxy": {
      "incident_logs": {
        "patterns": [
          {
            "pattern": "Upstream timeout after 15000ms",
            "frequency": "high",
            "reasoning": "Envoy cutting connections after 15s default timeout"
          }
        ]
      }
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
        "total_spans": 33,
        "duration_p90": 200,
        "error_rate": 0.001,
        "span_breakdown": [
          {"name": "PlaceOrder", "duration_ms": 180, "order": 1},
          {"name": "payment.charge", "duration_ms": 50, "order": 2},
          {"name": "kafka.publish", "duration_ms": 15, "order": 3}
        ]
      }
    },
    
    "incident_traces": {
      "checkout_flow_timeout": {
        "total_spans": 33,
        "duration_p90": 15000,
        "error_rate": 0.09,
        "status": "Incomplete - many spans not flushed",
        "span_breakdown": [
          {"name": "PlaceOrder", "duration_ms": 15000, "order": 1, "changed": true},
          {"name": "payment.charge", "duration_ms": 50, "order": 2, "changed": false},
          {"name": "kafka.publish", "duration_ms": 14900, "order": 3, "changed": true, "reasoning": "Hung waiting on channel select"}
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
    "summary": "AsyncProducer shared channel race condition",
    "category": "application_concurrency_bug",
    "subcategory": "channel_contention",
    
    "causal_chain": [
      {
        "step": 1,
        "component": "checkout",
        "what_happened": "REL-09 changed Kafka producer from fire-and-forget (NoResponse) to WaitForAll + Idempotent",
        "why": "To ensure no order loss - wait for ACK synchronously",
        "evidence": [
          "Config change: RequiredAcks: WaitForAll, Idempotent: true",
          "Using sarama.AsyncProducer with synchronous wait on Successes()/Errors() channels"
        ]
      },
      {
        "step": 2,
        "component": "checkout",
        "what_happened": "Single AsyncProducer instance shared across all goroutines in pod",
        "why": "Producer created once at startup, stored in checkout service struct",
        "evidence": [
          "KafkaProducerClient is field on checkout struct",
          "Not created per-request"
        ]
      },
      {
        "step": 3,
        "component": "checkout",
        "what_happened": "Multiple concurrent PlaceOrder requests select on same Successes()/Errors() channels",
        "why": "AsyncProducer.Successes() and Errors() are global channels for entire producer",
        "evidence": [
          "Code: select { case <-cs.KafkaProducerClient.Successes() ... }",
          "Go delivers each channel value to exactly ONE waiting goroutine",
          "Request A's ACK can be received by Request B's select"
        ]
      },
      {
        "step": 4,
        "component": "checkout",
        "what_happened": "Request loses its ACK signal, hangs in select until ctx.Done()",
        "why": "Another goroutine stole the ACK meant for this request",
        "evidence": [
          "Latency stuck at 15000ms - exactly Envoy timeout",
          "ctx.Done() triggered when Envoy cuts connection after 15s"
        ]
      },
      {
        "step": 5,
        "component": "frontend-proxy",
        "what_happened": "Envoy returns error to client after 15s",
        "why": "Route catch-all / has no explicit timeout: field, uses 15s default",
        "evidence": [
          "envoy.tmpl.yaml route / has no timeout: configured",
          "Max latency 15017ms matches default exactly"
        ]
      }
    ],
    
    "contributing_factors": [
      {
        "factor": "Only 2 checkout pods at idle",
        "description": "Easy to have ≥2 concurrent requests on same pod triggering race",
        "impact": "high",
        "evidence": "Bug surfaces under modest concurrency (10 Locust users)"
      },
      {
        "factor": "REL-09 only tested with sequential traffic",
        "description": "Bug not discovered because test didn't have concurrent requests",
        "impact": "high",
        "evidence": "Bug hidden until load test with parallel users"
      }
    ],
    
    "why_not_other_causes": {
      "kafka_broker_issue": {
        "ruled_out": true,
        "reasoning": "Kafka itself working fine, ACKs being sent - just consumed by wrong goroutine"
      },
      "network_latency": {
        "ruled_out": true,
        "reasoning": "Latency exactly 15000ms is too precise - this is timeout, not network delay"
      },
      "cpu_bottleneck": {
        "ruled_out": true,
        "reasoning": "CPU usage actually drops during incident due to lower throughput"
      },
      "cart_or_other_services": {
        "ruled_out": true,
        "reasoning": "GET /api/cart, POST /api/cart all remain fast with 0 failures"
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
        "action_type": "code_fix",
        "what": "Replace AsyncProducer with SyncProducer",
        "how": "Changed sarama.NewAsyncProducer → sarama.NewSyncProducer; SendMessage() returns (partition, offset, err) directly for each call - no shared channels",
        "when": "After root cause identified",
        "duration": "Code change + build + deploy cycle",
        "result": "Success - SendMessage() returns result to exact caller, no race condition possible"
      },
      {
        "action_number": 2,
        "action_type": "code_fix",
        "what": "Add Producer.Timeout = 5s",
        "how": "Explicit timeout for Kafka send operation, not dependent on ctx.Done() from HTTP layer",
        "when": "Same fix",
        "duration": "Part of same code change",
        "result": "Success - clearer timeout boundary"
      },
      {
        "action_number": 3,
        "action_type": "code_fix",
        "what": "Update chaos injection branch (kafkaQueueProblems flag)",
        "how": "Fixed chaos injection to use SyncProducer.SendMessage() instead of channel-based approach, preserving BTC fault injection capability",
        "when": "Same fix",
        "duration": "Part of same code change",
        "result": "Success - chaos injection still works, no behavior change for BTC testing"
      }
    ],
    
    "long_term_fixes": [
      {
        "fix": "Load test under concurrency before marking changes 'done'",
        "description": "Any change to sync/async behavior or shared resources must be tested with concurrent load, not just sequential requests",
        "timeline": "Add to testing checklist",
        "status": "lesson learned"
      },
      {
        "fix": "Explicit timeout: for critical Envoy routes",
        "description": "Add timeout: field to important routes instead of relying on 15s invisible default",
        "timeline": "Review and update routes",
        "status": "proposed"
      },
      {
        "fix": "Audit other AsyncProducer usage",
        "description": "Check if any other code synchronously waits on AsyncProducer channels - apply same pattern fix",
        "timeline": "Code audit",
        "status": "proposed"
      }
    ]
  }
}
```

---

## 📝 Notes

- **Key lesson:** Changing from fire-and-forget to synchronous ACK wait is not just a data guarantee change - it's a latency behavior change that requires concurrent load testing
- **AsyncProducer pitfall:** Sarama's AsyncProducer Successes()/Errors() channels are NOT safe for multiple goroutines to wait on synchronously
- **Trace "Incomplete":** Not reliable for pinpointing exact hang location - could be due to spans not flushed before timeout
- **15s significance:** Invisible Envoy default timeout became the visible symptom - explicit timeouts recommended
- **No customer impact on other services:** Only /api/checkout affected, browse/cart remained healthy

---

**Version:** 1.0  
**Created:** Based on Postmortem 0003 (14/07/2026)  
**Last Updated:** 2026-07-22  
