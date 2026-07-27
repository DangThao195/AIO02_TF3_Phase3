# Scenario: Payment Feature Flag Injection

**Scenario ID:** SCR-003  
**Incident Name:** Payment Failure Flag Injection (BTC Chaos)  
**Based on:** Postmortem 0004 (14/07/2026)  
**Severity:** Critical  
**SLO Violated:** Yes (checkout ≥99% success)  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-003",
  "incident_name": "Payment Failure Flag Injection (BTC Chaos)",
  "incident_type": "chaos_injection",
  "affected_services": ["payment", "checkout"],
  "affected_infrastructure": ["flagd"],
  "severity": "critical",
  "slo_violated": true,
  "customer_impact": "High - ~85% checkout requests failed with fast payment rejection during 12-minute window",
  
  "timeline": {
    "detection_time": "2026-07-14T14:22:16+07:00",
    "resolution_time": "2026-07-14T14:34:00+07:00",
    "duration_minutes": 12,
    "description": "Flag paymentFailure enabled by BTC for chaos testing, automatically disabled after time window"
  },
  
  "description": "BTC enabled paymentFailure feature flag via flagd, causing payment service to reject ~85% of charge requests with 'Invalid token' errors. Unlike timeout scenarios, requests failed fast (34-59ms) at payment validation step. Flag automatically returned to 'off' after test window. No actual financial transactions affected (payment mock).",
  
  "tags": ["feature_flag", "chaos_engineering", "btc_injection", "payment", "flagd"]
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
          "behavior": "stable",
          "mean": 45,
          "reasoning": "Traffic continues, but requests fail at payment step"
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
          "peak_value": 0.85,
          "reasoning": "~85% requests failed (28/33 observed in load test)"
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
          "behavior": "drop",
          "peak_value": 49,
          "reasoning": "Fast failure at payment step - no timeout/hang"
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
          "behavior": "drop",
          "peak_value": 34,
          "reasoning": "Fail-fast behavior characteristic of flag injection"
        }
      }
    },
    
    "other_endpoints": {
      "cart_error_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='frontend',span_name=~'.*cart.*',status_code='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='frontend',span_name=~'.*cart.*'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 0.001
        },
        "during_incident": {
          "behavior": "stable",
          "mean": 0,
          "reasoning": "Cart operations unaffected - 0 failures"
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
    "payment_service": {
      "normal_logs": {
        "rate": "5-10 logs/second",
        "level_distribution": {
          "INFO": 0.90,
          "WARN": 0.05,
          "ERROR": 0.05
        }
      },
      
      "incident_logs": {
        "rate": "40-50 logs/second during window",
        "level_distribution": {
          "INFO": 0.20,
          "WARN": 0.75,
          "ERROR": 0.05
        },
        "log_count": "171 error logs during 12-minute window",
        "error_patterns": [
          {
            "pattern": "Payment request failed. Invalid token. app.loyalty.level=gold",
            "frequency": "high",
            "source": "charge.js:37",
            "reasoning": "Flag-triggered rejection - exact string only possible from paymentFailure flag branch"
          }
        ],
        "log_example": {
          "timestamp": "1784013736825000",
          "traceId": "dc02421a522f003d60a558c6ffbb1670",
          "spanId": "811105799859658c",
          "severityText": "warn",
          "body": "Payment request failed. Invalid token. app.loyalty.level=gold",
          "host": "payment-59dd46cc87-p4zlm",
          "stack_trace": "Error: Payment request failed. Invalid token. app.loyalty.level=gold\n    at module.exports.charge (/usr/src/app/charge.js:37:13)"
        }
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
        "total_spans": 30,
        "duration_p90": 200,
        "error_rate": 0.001,
        "span_breakdown": [
          {"name": "PlaceOrder", "duration_ms": 180, "status": "OK"},
          {"name": "payment.charge", "duration_ms": 50, "status": "OK"}
        ]
      }
    },
    
    "incident_traces": {
      "checkout_flow_payment_fail": {
        "total_spans": 30,
        "duration_p90": 49,
        "error_rate": 0.85,
        "span_breakdown": [
          {"name": "PlaceOrder", "duration_ms": 48, "status": "ERROR", "changed": true},
          {"name": "payment.charge", "duration_ms": 10, "status": "ERROR", "changed": true, "reasoning": "Immediate rejection due to flag"}
        ],
        "error_details": {
          "error_message": "Payment request failed. Invalid token. app.loyalty.level=gold",
          "error_type": "Error",
          "error_span": "payment.charge"
        }
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
    "summary": "paymentFailure feature flag enabled by BTC for chaos injection",
    "category": "chaos_injection",
    "subcategory": "feature_flag_controlled",
    
    "causal_chain": [
      {
        "step": 1,
        "component": "flagd",
        "what_happened": "BTC enabled paymentFailure flag with high percentage (likely 75-90%)",
        "why": "Controlled chaos injection to test system resilience",
        "evidence": [
          "Query OFREP during incident would show paymentFailure != off",
          "Query after incident shows paymentFailure = off (auto-disabled)"
        ]
      },
      {
        "step": 2,
        "component": "payment",
        "what_happened": "Payment service reads flag via OpenFeature, randomly rejects requests",
        "why": "Code implements: if (Math.random() < numberVariant) throw error",
        "evidence": [
          "charge.js line 37: OpenFeature.getClient().getNumberValue('paymentFailure', 0)",
          "Error message exact match: 'Invalid token. app.loyalty.level=gold' only from this branch"
        ]
      },
      {
        "step": 3,
        "component": "payment",
        "what_happened": "Payment throws error BEFORE actual credit card validation",
        "why": "Flag check happens at start of charge() function, before real payment processing",
        "evidence": [
          "Stack trace shows error at charge.js:37 - early in function",
          "No actual credit card charges occurred (mock payment)"
        ]
      },
      {
        "step": 4,
        "component": "checkout",
        "what_happened": "PlaceOrder receives gRPC error from payment, returns error to customer",
        "why": "Payment error propagates up call chain",
        "evidence": [
          "Jaeger shows error bubbling: payment → checkout → frontend → frontend-proxy",
          "85% checkout requests failed during window"
        ]
      },
      {
        "step": 5,
        "component": "flagd",
        "what_happened": "Flag automatically disabled after test window",
        "why": "BTC controlled injection with time limit",
        "evidence": [
          "System self-recovered at 14:34",
          "Query after incident: paymentFailure = off"
        ]
      }
    ],
    
    "contributing_factors": [
      {
        "factor": "High flag percentage (estimated 75-90%)",
        "description": "BTC set failure rate high enough to significantly impact metrics",
        "impact": "high",
        "evidence": "85% failure rate observed in load test"
      }
    ],
    
    "why_not_other_causes": {
      "actual_payment_gateway_issue": {
        "ruled_out": true,
        "reasoning": "Error message unique to flag branch - real payment errors have different messages"
      },
      "credit_card_validation": {
        "ruled_out": true,
        "reasoning": "Error thrown BEFORE card validation code - randomized by Math.random(), not based on card data"
      },
      "kafka_issue": {
        "ruled_out": true,
        "reasoning": "Completely different incident - this fails at payment, not Kafka publish"
      },
      "infrastructure_problem": {
        "ruled_out": true,
        "reasoning": "Cart and other endpoints remained healthy with 0 failures"
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
        "what": "No action needed - flag self-disabled",
        "how": "BTC controlled injection automatically disabled after test window",
        "when": "2026-07-14T14:34:00+07:00",
        "duration": "Automatic",
        "result": "System self-recovered, checkout success rate returned to baseline"
      }
    ],
    
    "long_term_fixes": [
      {
        "fix": "Add alerting for checkout/payment error rate spike",
        "description": "Alert when checkout success rate < 99% in 5-minute window - discovered manually this time, should be automatic",
        "timeline": "Add to grafana-alerting ConfigMap",
        "status": "proposed",
        "notes": "Current issue: grafana-alerting ConfigMap empty due to glob mismatch (*.yaml vs *.yml files)"
      },
      {
        "fix": "Dashboard for flag status visibility",
        "description": "Quick way to query all flagd flags (curl OFREP or flagd-ui) to identify which flags are active during incidents",
        "timeline": "Create ops dashboard or script",
        "status": "proposed"
      },
      {
        "fix": "Add retry logic in checkout for payment errors",
        "description": "Retry payment.charge() 1-2 times on failure - probabilistic flag (75%) means retry likely succeeds (0.75^3 = 42% all fail)",
        "timeline": "Code enhancement",
        "status": "proposed",
        "reasoning": "Would convert ~85% failure to ~42% with 2 retries, significantly reducing customer impact"
      },
      {
        "fix": "DO NOT: Change HTTP status to hide errors",
        "description": "Rejected proposal to return 400 instead of 500 - gaming metrics without fixing real issue",
        "status": "rejected",
        "reasoning": "Misrepresents failure as customer error when it's system error; doesn't help customer complete order"
      }
    ]
  }
}
```

---

## 📝 Notes

- **Key characteristic:** Fast failure (34-59ms) vs timeout scenarios (15000ms) - diagnostic signal
- **No financial impact:** Payment is mock, no real credit card charges
- **Fault injection by design:** This is BTC testing system resilience, not a system bug
- **Can recur:** BTC can enable flag again anytime - need detection + mitigation ready
- **SLO violation clear:** ~85% failure far below 99% SLO threshold
- **Other services unaffected:** Browse, cart operations remained at 0% error rate

---

**Version:** 1.0  
**Created:** Based on Postmortem 0004 (14/07/2026)  
**Last Updated:** 2026-07-22  
