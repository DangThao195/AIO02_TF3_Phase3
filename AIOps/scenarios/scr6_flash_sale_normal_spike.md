# Scenario: Flash Sale Traffic Spike (Normal Event)

**Scenario ID:** SCR-006  
**Incident Name:** Flash Sale Traffic Spike - NOT AN INCIDENT  
**Type:** Normal Business Event  
**Severity:** None (Expected Behavior)  
**SLO Violated:** No  

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "SCR-006",
  "incident_name": "Flash Sale Traffic Spike - Normal Event",
  "incident_type": "normal_traffic_pattern",
  "affected_services": ["frontend", "checkout", "product-catalog", "cart"],
  "affected_infrastructure": [],
  "severity": "none",
  "slo_violated": false,
  "customer_impact": "None - System performing as expected under high load",
  
  "timeline": {
    "event_start": "2026-07-25T12:00:00+07:00",
    "event_peak": "2026-07-25T12:15:00+07:00",
    "event_end": "2026-07-25T13:00:00+07:00",
    "duration_minutes": 60,
    "description": "Planned flash sale event - 50% discount on electronics category"
  },
  
  "description": "Scheduled flash sale at noon caused 10x traffic spike. All metrics increased proportionally: RPS, CPU, memory, latency grew but stayed within acceptable ranges. Error rate remained <0.5% (well below 1% SLO threshold). System auto-scaled from 2 to 8 pods as designed. This is NORMAL BEHAVIOR - not an incident. Key indicators: proportional metric growth, error rate stable, gradual ramp-up/down, planned event in calendar.",
  
  "tags": ["flash_sale", "traffic_spike", "normal_behavior", "autoscaling", "false_positive_prevention"]
}
```

---

## 2️⃣ Telemetry Behavior

### 2.1. Metrics Schema & Behavior

```json
{
  "metrics_behavior": {
    "frontend_service": {
      "rps": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='frontend',span_kind='SPAN_KIND_SERVER'}[5m]))",
        "unit": "requests/second",
        "baseline": {
          "mean": 50,
          "std_dev": 5,
          "pattern": "stable"
        },
        "during_event": {
          "behavior": "gradual_spike_then_gradual_decline",
          "ramp_up_duration_minutes": 15,
          "peak_value": 500,
          "peak_duration_minutes": 30,
          "ramp_down_duration_minutes": 15,
          "spike_pattern": "smooth_curve",
          "reasoning": "10x traffic increase due to flash sale announcement, users rushing to get deals"
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
        "during_event": {
          "behavior": "slight_increase_but_stable",
          "mean": 0.004,
          "peak_value": 0.005,
          "reasoning": "Minor increase due to volume, but stays well below 1% SLO - system handling load properly"
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
        "during_event": {
          "behavior": "proportional_increase",
          "peak_value": 350,
          "reasoning": "Latency increases with load but stays under 500ms budget - queuing theory in action, not bottleneck"
        }
      },
      
      "cpu_usage": {
        "metric_path": "sum(rate(container_cpu_usage_seconds_total{container='frontend'}[5m]))",
        "unit": "cores",
        "baseline": {
          "mean": 0.4,
          "std_dev": 0.05,
          "pattern": "proportional_to_rps"
        },
        "during_event": {
          "behavior": "proportional_spike_with_scaling",
          "initial_spike": 3.5,
          "after_autoscale": 1.8,
          "reasoning": "CPU spikes initially, then HPA scales out 2→8 pods, per-pod CPU drops to healthy level"
        }
      },
      
      "memory_usage": {
        "metric_path": "sum(container_memory_working_set_bytes{container='frontend'}) / sum(container_spec_memory_limit_bytes{container='frontend'})",
        "unit": "ratio",
        "baseline": {
          "mean": 0.35,
          "std_dev": 0.03,
          "pattern": "stable"
        },
        "during_event": {
          "behavior": "slight_increase_stable",
          "peak_value": 0.42,
          "reasoning": "Slight increase for connection pools, no memory leak pattern"
        }
      },
      
      "pod_count": {
        "metric_path": "count(kube_pod_status_phase{pod=~'frontend.*',phase='Running'})",
        "unit": "count",
        "baseline": {
          "mean": 2,
          "pattern": "stable"
        },
        "during_event": {
          "behavior": "autoscale_up_then_down",
          "ramp_up": "2 → 4 → 6 → 8 pods over 10 minutes",
          "stable_at_peak": 8,
          "ramp_down": "8 → 6 → 4 → 2 pods over 20 minutes after event",
          "reasoning": "HPA working correctly: scale out on CPU>70%, scale in on CPU<50% with cooldown"
        }
      }
    },
    
    "checkout_service": {
      "rps": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_kind='SPAN_KIND_SERVER'}[5m]))",
        "unit": "requests/second",
        "baseline": {
          "mean": 4.5,
          "std_dev": 0.5,
          "pattern": "stable"
        },
        "during_event": {
          "behavior": "gradual_spike",
          "peak_value": 35,
          "reasoning": "Higher conversion rate during flash sale - proportional to browse traffic"
        }
      },
      
      "error_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',status_code='STATUS_CODE_ERROR'}[5m])) / sum(rate(traces_span_metrics_calls_total{service_name='checkout'}[5m]))",
        "unit": "ratio",
        "baseline": {
          "mean": 0.001,
          "std_dev": 0.0005
        },
        "during_event": {
          "behavior": "stable",
          "mean": 0.002,
          "reasoning": "Error rate stays <0.5%, well within SLO ≥99%"
        }
      }
    },
    
    "product_catalog_service": {
      "cache_hit_rate": {
        "metric_path": "sum(rate(redis_hits_total[5m])) / (sum(rate(redis_hits_total[5m])) + sum(rate(redis_misses_total[5m])))",
        "unit": "ratio",
        "baseline": {
          "mean": 0.85,
          "pattern": "stable"
        },
        "during_event": {
          "behavior": "slight_drop_then_recover",
          "initial_drop": 0.75,
          "recovery_to": 0.92,
          "reasoning": "Initial cache misses on sale items, then cache warms up - normal cache behavior"
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
    "all_services": {
      "normal_logs": {
        "rate": "Standard operational logging"
      },
      
      "during_event": {
        "rate": "Increased log volume proportional to traffic (10x)",
        "level_distribution": {
          "INFO": 0.92,
          "WARN": 0.05,
          "ERROR": 0.03
        },
        "patterns": [
          {
            "pattern": "INFO: Processing request order_id=<uuid>",
            "frequency": "high",
            "reasoning": "More requests = more logs, but same ratio as baseline"
          },
          {
            "pattern": "INFO: HPA triggered scale-out event: 2→4 pods",
            "frequency": "occasional",
            "reasoning": "Autoscaling working as designed"
          },
          {
            "pattern": "WARN: High CPU utilization 75%, triggering scale-out",
            "frequency": "low",
            "reasoning": "Expected warning during load spike, not an error"
          }
        ],
        "no_error_spike": true,
        "note": "Log volume increases but error rate stays constant - healthy system under load"
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
        "error_rate": 0.001
      }
    },
    
    "during_event": {
      "checkout_flow_under_load": {
        "total_spans": 30,
        "duration_p90": 350,
        "error_rate": 0.002,
        "note": "All spans present and healthy, just slower due to queuing - no missing spans, no timeouts"
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
    "summary": "NOT AN INCIDENT - Planned flash sale event causing expected traffic spike",
    "category": "normal_business_event",
    "subcategory": "planned_marketing_campaign",
    
    "why_this_is_NOT_an_incident": [
      {
        "indicator": "Planned event",
        "evidence": "Flash sale scheduled in marketing calendar for 2026-07-25 12:00-13:00",
        "reasoning": "Predictable, time-bounded event with known start/end"
      },
      {
        "indicator": "Proportional metric changes",
        "evidence": "RPS 10x → CPU 10x → latency 2.3x (expected under queuing theory)",
        "reasoning": "All metrics scale together - indicates load, not failure"
      },
      {
        "indicator": "Error rate stable",
        "evidence": "Error rate 0.2% → 0.4%, stays well below 1% SLO threshold",
        "reasoning": "System handling requests successfully, not failing"
      },
      {
        "indicator": "Gradual ramp-up and ramp-down",
        "evidence": "15-minute ramp-up, 30-minute peak, 15-minute ramp-down",
        "reasoning": "Smooth curves indicate organic user behavior, not system failure"
      },
      {
        "indicator": "Auto-scaling working",
        "evidence": "HPA scaled 2→8 pods, CPU per pod returned to healthy levels",
        "reasoning": "System self-healing through designed capacity mechanisms"
      },
      {
        "indicator": "No timeout patterns",
        "evidence": "P99 latency 450ms, no requests hitting timeout thresholds",
        "reasoning": "Slower but not broken - queuing, not bottleneck"
      },
      {
        "indicator": "All downstream services healthy",
        "evidence": "Payment, shipping, Kafka all showing proportional load increase, no errors",
        "reasoning": "Entire system scaling together harmoniously"
      }
    ],
    
    "contrast_with_real_incidents": {
      "vs_oomkilled": {
        "difference": "Flash sale: all metrics proportional. OOMKilled: memory ceiling hit, restarts, disproportionate",
        "key_signal": "No pod restarts, memory grows but stays under limit"
      },
      "vs_kafka_timeout": {
        "difference": "Flash sale: latency gradual 150ms→350ms. Kafka timeout: latency jumps to 15000ms",
        "key_signal": "Latency increase proportional to load, not stuck at timeout ceiling"
      },
      "vs_payment_flag": {
        "difference": "Flash sale: error rate 0.2%→0.4%. Flag injection: error rate 0.2%→85%",
        "key_signal": "Error rate slight increase but stays <1%, not catastrophic spike"
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
        "action_type": "monitoring",
        "what": "Observed system behavior during flash sale",
        "how": "Real-time dashboard monitoring, no intervention needed",
        "when": "During event 12:00-13:00",
        "result": "System performed within expected parameters, auto-scaling handled load"
      },
      {
        "action_number": 2,
        "action_type": "none_required",
        "what": "No remediation needed - system working as designed",
        "result": "Event completed successfully, system scaled back down automatically"
      }
    ],
    
    "observations_for_model_training": [
      {
        "observation": "Traffic correlation across services",
        "description": "When RPS increases, check if ALL services see proportional increase - indicates load, not failure",
        "ml_feature": "cross_service_correlation_coefficient"
      },
      {
        "observation": "Time-bounded event",
        "description": "Anomaly with clear start/end time matching business calendar = likely planned event",
        "ml_feature": "event_calendar_alignment"
      },
      {
        "observation": "Smooth curves vs sharp edges",
        "description": "Gradual ramp-up/down (15+ min) = organic. Instant spike/drop (<1 min) = failure",
        "ml_feature": "metric_change_rate_derivative"
      },
      {
        "observation": "Error rate absolute vs relative",
        "description": "Absolute errors may increase (2→20 errors/min) but rate stays constant (0.2%) = healthy scale",
        "ml_feature": "error_rate_vs_absolute_count"
      },
      {
        "observation": "Auto-scaling response",
        "description": "If HPA triggers and metrics stabilize after scale-out, system is healthy",
        "ml_feature": "autoscaling_event_correlation"
      }
    ]
  }
}
```

---

## 📝 Notes for Model Training

### Key Distinguishing Features (vs Real Incidents):

1. **Metric Proportionality**
   - ✅ Normal: RPS ×10 → CPU ×10 → Latency ×2.3 (sublinear, expected)
   - ❌ Incident: RPS ×1 → CPU ×1 → Latency ×125 (disproportionate)

2. **Error Rate Behavior**
   - ✅ Normal: 0.2% → 0.4% (doubling but <1% SLO)
   - ❌ Incident: 0.2% → 9% or 85% (catastrophic)

3. **Temporal Pattern**
   - ✅ Normal: Smooth 15min ramp, 30min plateau, 15min decline
   - ❌ Incident: Instant spike, no recovery, or stuck at ceiling

4. **Calendar Alignment**
   - ✅ Normal: Matches planned event timestamp exactly
   - ❌ Incident: No correlation with planned events

5. **Cross-Service Behavior**
   - ✅ Normal: All services scale together proportionally
   - ❌ Incident: One service diverges (error spike, restart loop, etc.)

6. **Recovery Pattern**
   - ✅ Normal: Auto-scales, self-stabilizes, graceful decline
   - ❌ Incident: Needs intervention, or doesn't recover

### Label for Training:
```json
{
  "is_anomaly": true,
  "is_incident": false,
  "category": "planned_event",
  "severity": "none",
  "requires_alert": false,
  "reasoning": "Metrics deviate from baseline but within expected bounds for planned traffic event"
}
```

---

**Version:** 1.0  
**Created:** 2026-07-22  
**Purpose:** False positive prevention training data  
**Last Updated:** 2026-07-22  
