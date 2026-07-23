# AIOps Scenario Format - Data Generation Template

**Version:** 1.0  
**Purpose:** Standardized format để define incidents phục vụ training data generation  
**Date:** 2026-07-22  

---

## 📝 Cấu Trúc Scenario

Mỗi scenario bao gồm **4 sections chính**:

1. **Incident Metadata** - Thông tin cơ bản về sự cố
2. **Telemetry Behavior** - Hành vi metrics/logs trong sự cố
3. **Root Cause Information** - Nguyên nhân gốc rễ
4. **Remediation Actions** - Cách xử lý sự cố

---

## 1️⃣ Incident Metadata

```json
{
  "scenario_id": "INC-009",
  "incident_name": "PostgreSQL Connection Pool Exhaustion",
  "incident_type": "resource_saturation",
  "affected_services": ["checkout"],
  "affected_infrastructure": ["postgres"],
  "severity": "critical",
  "slo_violated": true,
  "customer_impact": "High - Checkout failures during peak hours",
  
  "timeline": {
    "detection_time": "2026-01-15T14:23:00Z",
    "resolution_time": "2026-01-15T14:31:00Z",
    "duration_minutes": 8,
    "incident_phases": {
      "normal": "0-59 minutes",
      "degradation": "60-65 minutes",
      "critical": "65-75 minutes",
      "recovery": "76-85 minutes"
    }
  },
  
  "description": "During peak shopping hours, checkout service experienced high error rates (5.2%) and extreme latency (3.5s). Root cause was PostgreSQL connection pool reaching max capacity (99/100 connections), causing new requests to queue and timeout.",
  
  "tags": ["database", "connection_pool", "saturation", "auto_healable"]
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
          "mean": 4.5,
          "std_dev": 0.5,
          "pattern": "stable_with_noise"
        },
        "during_incident": {
          "behavior": "stable",
          "mean": 4.5,
          "std_dev": 0.5,
          "reasoning": "RPS không thay đổi - không phải traffic surge"
        }
      },
      
      "error_rate": {
        "metric_path": "sum(rate(traces_span_metrics_calls_total{service_name='checkout',span_kind='SPAN_KIND_SERVER',status_code='STATUS_CODE_ERROR'}[5m]))",
        "unit": "errors/second",
        "baseline": {
          "mean": 0.0045,
          "std_dev": 0.001,
          "pattern": "low_stable"
        },
        "during_incident": {
          "behavior": "gradual_spike",
          "start_value": 0.0045,
          "peak_value": 0.234,
          "spike_pattern": "exponential_growth",
          "growth_rate": 0.003,
          "reasoning": "Requests timeout khi không lấy được connection"
        }
      },
      
      "latency_p90": {
        "metric_path": "histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name='checkout',span_kind='SPAN_KIND_SERVER'}[5m])) by (le))",
        "unit": "milliseconds",
        "baseline": {
          "mean": 120,
          "std_dev": 15,
          "pattern": "diurnal"
        },
        "during_incident": {
          "behavior": "step_spike",
          "start_value": 120,
          "peak_value": 3500,
          "spike_pattern": "immediate_jump",
          "reasoning": "Connection wait time 4.8s + query time"
        }
      },
      
      "cpu_usage": {
        "metric_path": "sum(rate(container_cpu_usage_seconds_total{container='checkout'}[5m]))",
        "unit": "cores",
        "baseline": {
          "mean": 0.3,
          "std_dev": 0.05,
          "pattern": "proportional_to_rps"
        },
        "during_incident": {
          "behavior": "stable",
          "mean": 0.32,
          "std_dev": 0.05,
          "reasoning": "CPU không phải bottleneck - chỉ chờ database"
        }
      },
      
      "memory_usage": {
        "metric_path": "sum(container_memory_working_set_bytes{container='checkout'}) / sum(container_spec_memory_limit_bytes{container='checkout'})",
        "unit": "ratio",
        "baseline": {
          "mean": 0.45,
          "std_dev": 0.02,
          "pattern": "stable"
        },
        "during_incident": {
          "behavior": "stable",
          "mean": 0.46,
          "std_dev": 0.02,
          "reasoning": "Memory không leak"
        }
      }
    },
    
    "postgres_database": {
      "active_connections": {
        "metric_path": "pg_stat_database_numbackends{datname='checkout_db'}",
        "unit": "connections",
        "baseline": {
          "mean": 45,
          "std_dev": 5,
          "pattern": "proportional_to_traffic"
        },
        "during_incident": {
          "behavior": "ceiling_hit",
          "start_value": 45,
          "peak_value": 99,
          "max_limit": 100,
          "spike_pattern": "gradual_increase_then_stuck",
          "reasoning": "Connection pool cạn kiệt - stuck at max"
        }
      },
      
      "connection_wait_time": {
        "metric_path": "pg_stat_activity_wait_event_time{wait_event='ClientRead'}",
        "unit": "milliseconds",
        "baseline": {
          "mean": 2,
          "std_dev": 1,
          "pattern": "low_stable"
        },
        "during_incident": {
          "behavior": "spike",
          "start_value": 2,
          "peak_value": 4800,
          "spike_pattern": "exponential_growth",
          "reasoning": "Requests chờ connection available"
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
        "rate": "10-15 logs/second",
        "level_distribution": {
          "INFO": 0.85,
          "WARN": 0.10,
          "ERROR": 0.05
        },
        "sample_patterns": [
          "INFO: Processing order request order_id=<uuid>",
          "INFO: Payment validated successfully",
          "INFO: Order created successfully order_id=<uuid>"
        ]
      },
      
      "incident_logs": {
        "rate": "40-50 logs/second",
        "level_distribution": {
          "INFO": 0.40,
          "WARN": 0.15,
          "ERROR": 0.45
        },
        "error_patterns": [
          {
            "pattern": "ERROR: Failed to acquire database connection: Connection pool timeout",
            "frequency": "high",
            "starts_at": "minute 60",
            "reasoning": "Primary symptom - connection pool exhausted"
          },
          {
            "pattern": "ERROR: DatabaseConnectionException: Could not open JDBC Connection for transaction",
            "frequency": "high",
            "starts_at": "minute 62",
            "reasoning": "Spring framework wrapper around connection error"
          },
          {
            "pattern": "WARN: HikariPool-1 - Connection is not available, request timed out after 30000ms",
            "frequency": "medium",
            "starts_at": "minute 61",
            "reasoning": "Connection pool library warning"
          },
          {
            "pattern": "ERROR: Transaction rolled back due to database connection failure",
            "frequency": "medium",
            "starts_at": "minute 63",
            "reasoning": "Downstream effect - transactions failing"
          }
        ],
        "stack_trace_snippet": "at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:197)\nat com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:162)\nat org.springframework.jdbc.datasource.DataSourceTransactionManager.doBegin"
      }
    },
    
    "postgres_database": {
      "normal_logs": {
        "rate": "5-8 logs/minute",
        "sample_patterns": [
          "LOG: checkpoint complete",
          "LOG: autovacuum: processing database"
        ]
      },
      
      "incident_logs": {
        "rate": "25-30 logs/minute",
        "error_patterns": [
          {
            "pattern": "FATAL: sorry, too many clients already",
            "frequency": "high",
            "starts_at": "minute 60",
            "reasoning": "PostgreSQL rejecting new connections"
          },
          {
            "pattern": "LOG: remaining connection slots are reserved for superuser connections",
            "frequency": "medium",
            "starts_at": "minute 61",
            "reasoning": "Max connections reached"
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
        "total_spans": 8,
        "duration_p50": 85,
        "duration_p90": 120,
        "duration_p99": 180,
        "error_rate": 0.001,
        "span_breakdown": [
          {"name": "checkout.createOrder", "duration_ms": 15, "order": 1},
          {"name": "db.query.insert_order", "duration_ms": 25, "order": 2},
          {"name": "payment.validate", "duration_ms": 30, "order": 3},
          {"name": "db.query.update_inventory", "duration_ms": 20, "order": 4}
        ]
      }
    },
    
    "incident_traces": {
      "checkout_flow_degraded": {
        "total_spans": 8,
        "duration_p50": 2800,
        "duration_p90": 3500,
        "duration_p99": 4200,
        "error_rate": 0.052,
        "span_breakdown": [
          {"name": "checkout.createOrder", "duration_ms": 15, "order": 1, "changed": false},
          {"name": "connection_pool.acquire", "duration_ms": 4800, "order": 2, "changed": true, "reasoning": "NEW SPAN - waiting for connection"},
          {"name": "db.query.insert_order", "duration_ms": 25, "order": 3, "changed": false},
          {"name": "payment.validate", "duration_ms": 30, "order": 4, "changed": false}
        ],
        "error_traces": {
          "error_type": "DatabaseConnectionException",
          "error_message": "Connection pool timeout after 30000ms",
          "error_span": "connection_pool.acquire",
          "stack_trace_included": true
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
    "summary": "PostgreSQL connection pool exhausted",
    "category": "resource_saturation",
    "subcategory": "connection_pool_depletion",
    
    "causal_chain": [
      {
        "step": 1,
        "component": "postgres",
        "what_happened": "Connection pool reached max capacity (99/100)",
        "why": "Slow connection release + sustained traffic",
        "evidence": [
          "pg_stat_database_numbackends = 99",
          "max_connections config = 100",
          "No idle connections available"
        ]
      },
      {
        "step": 2,
        "component": "checkout",
        "what_happened": "New requests wait for available connections",
        "why": "All connections in use, requests queue up",
        "evidence": [
          "connection_wait_time spike to 4800ms",
          "Log: 'Connection pool timeout'",
          "Trace: connection_pool.acquire span = 4.8s"
        ]
      },
      {
        "step": 3,
        "component": "checkout",
        "what_happened": "Requests timeout and fail with 5xx errors",
        "why": "Wait time exceeds application timeout (30s)",
        "evidence": [
          "error_rate: 0.1% → 5.2%",
          "latency_p90: 120ms → 3500ms",
          "Log: 'DatabaseConnectionException'"
        ]
      },
      {
        "step": 4,
        "component": "checkout",
        "what_happened": "SLO violated - customer impact",
        "why": "Error rate exceeds threshold",
        "evidence": [
          "SLO burn rate 5m: 37.44 (threshold: 14.4)",
          "Error budget depleting rapidly"
        ]
      }
    ],
    
    "contributing_factors": [
      {
        "factor": "Long-running database queries",
        "description": "/api/order/history endpoint runs expensive queries, holding connections longer",
        "impact": "medium",
        "evidence": "pg_stat_statements shows queries with 2-3s duration"
      },
      {
        "factor": "Connection leak in order history feature",
        "description": "Some code paths not properly releasing connections",
        "impact": "high",
        "evidence": "Active connections slowly growing over 24h before incident"
      },
      {
        "factor": "Peak traffic hour",
        "description": "Incident occurred during 2pm peak shopping time",
        "impact": "low",
        "evidence": "RPS was stable, not a surge"
      }
    ],
    
    "why_not_other_causes": {
      "cpu_bottleneck": {
        "ruled_out": true,
        "reasoning": "CPU usage stable at 0.3 cores, no spike observed"
      },
      "memory_leak": {
        "ruled_out": true,
        "reasoning": "Memory usage stable at 45%, no growth pattern"
      },
      "network_issue": {
        "ruled_out": true,
        "reasoning": "Other services using same network healthy, no packet loss"
      },
      "database_slow_query": {
        "ruled_out": false,
        "reasoning": "Contributing factor but not root cause - pool exhaustion is primary"
      },
      "traffic_surge": {
        "ruled_out": true,
        "reasoning": "RPS stable at 4.5 req/s, no change during incident"
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
        "action_type": "scale_resource",
        "what": "Increased PostgreSQL max_connections from 100 to 200",
        "how": "kubectl patch configmap postgres-config -n techx-tf3 --type merge -p '{\"data\":{\"max_connections\":\"200\"}}' && kubectl rollout restart statefulset/postgres",
        "when": "2026-01-15T14:26:00Z (3 minutes after detection)",
        "duration": "45 seconds to complete",
        "result": "Success - error rate dropped from 5.2% to 0.3% within 90 seconds"
      },
      {
        "action_number": 2,
        "action_type": "restart_service",
        "what": "Rolling restart checkout service to release leaked connections",
        "how": "kubectl rollout restart deployment/checkout -n techx-tf3",
        "when": "2026-01-15T14:28:00Z (after action #1 partial success)",
        "duration": "120 seconds rolling restart",
        "result": "Success - error rate dropped to 0.1% (baseline)"
      },
      {
        "action_number": 3,
        "action_type": "circuit_breaker",
        "what": "Enable circuit breaker for /api/order/history endpoint",
        "how": "Feature flag toggle via Flagd: ENABLE_ORDER_HISTORY_CIRCUIT_BREAKER=true",
        "when": "2026-01-15T14:29:00Z (preventive measure)",
        "duration": "5 seconds",
        "result": "Success - reduced database query load by 35%"
      }
    ],
    
    "long_term_fixes": [
      {
        "fix": "Code review and fix connection leaks",
        "description": "Audit all database access code, ensure proper try-with-resources",
        "timeline": "1 week",
        "jira": "TECH-1234"
      },
      {
        "fix": "Optimize /api/order/history queries",
        "description": "Add pagination, limit history to 3 months, add caching",
        "timeline": "2 weeks",
        "jira": "TECH-1235"
      },
      {
        "fix": "Implement connection pool monitoring alerts",
        "description": "Alert when active connections > 80% of max",
        "timeline": "3 days",
        "jira": "TECH-1236"
      }
    ]
  }
}
```

---

## 📊 Data Generation Guide

### Sử dụng Scenario để Generate Training Data

```python
#!/usr/bin/env python3
"""
Generate training data from scenario definition.
Usage: python generate_data.py scenarios/INC-009.json
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def load_scenario(path):
    with open(path, 'r') as f:
        return json.load(f)

def generate_metric_timeseries(metric_config, total_minutes, interval_seconds):
    """Generate time series data for a single metric based on behavior."""
    
    # Calculate sample count
    samples_per_minute = 60 // interval_seconds
    total_samples = total_minutes * samples_per_minute
    
    # Initialize array
    values = np.zeros(total_samples)
    
    # Parse incident phases from timeline
    baseline = metric_config['baseline']
    incident = metric_config['during_incident']
    
    # Normal period (0-59 minutes)
    normal_samples = 59 * samples_per_minute
    values[:normal_samples] = np.random.normal(
        loc=baseline['mean'],
        scale=baseline['std_dev'],
        size=normal_samples
    )
    
    # Incident period behavior
    incident_start = 60 * samples_per_minute
    incident_end = 75 * samples_per_minute
    incident_samples = incident_end - incident_start
    
    behavior = incident['behavior']
    
    if behavior == 'stable':
        # No change during incident
        values[incident_start:incident_end] = np.random.normal(
            loc=incident['mean'],
            scale=incident['std_dev'],
            size=incident_samples
        )
    
    elif behavior == 'gradual_spike':
        # Gradual increase
        start_val = incident['start_value']
        peak_val = incident['peak_value']
        
        if incident.get('spike_pattern') == 'exponential_growth':
            # Exponential growth curve
            x = np.linspace(0, 1, incident_samples)
            growth = (np.exp(4 * x) - 1) / (np.exp(4) - 1)  # Normalize to [0,1]
            values[incident_start:incident_end] = start_val + growth * (peak_val - start_val)
        else:
            # Linear growth
            values[incident_start:incident_end] = np.linspace(
                start_val, peak_val, incident_samples
            )
    
    elif behavior == 'step_spike':
        # Immediate jump
        values[incident_start:incident_end] = incident['peak_value']
    
    elif behavior == 'ceiling_hit':
        # Gradual increase until hitting ceiling
        start_val = incident['start_value']
        peak_val = incident['peak_value']
        
        # First half: gradual increase
        half = incident_samples // 2
        values[incident_start:incident_start+half] = np.linspace(
            start_val, peak_val, half
        )
        # Second half: stuck at ceiling
        values[incident_start+half:incident_end] = peak_val
    
    # Recovery period (76-85 minutes)
    recovery_start = 76 * samples_per_minute
    recovery_samples = total_samples - recovery_start
    
    # Gradual return to baseline
    values[recovery_start:] = np.linspace(
        values[incident_end-1],
        baseline['mean'],
        recovery_samples
    )
    
    return values

def generate_logs(scenario, total_minutes):
    """Generate log entries based on scenario log patterns."""
    
    logs = []
    
    for service_name, log_config in scenario['logs_behavior'].items():
        normal = log_config['normal_logs']
        incident = log_config['incident_logs']
        
        # Normal period logs
        for minute in range(60):
            log_count = np.random.randint(
                int(normal['rate'].split('-')[0]),
                int(normal['rate'].split('-')[1].split()[0])
            )
            
            for _ in range(log_count):
                level = np.random.choice(
                    list(normal['level_distribution'].keys()),
                    p=list(normal['level_distribution'].values())
                )
                
                pattern = np.random.choice(normal['sample_patterns'])
                
                logs.append({
                    'timestamp': f"2026-01-15T14:{minute:02d}:{np.random.randint(0,60):02d}Z",
                    'service': service_name,
                    'level': level,
                    'message': pattern
                })
        
        # Incident period logs
        for minute in range(60, 76):
            log_count = np.random.randint(
                int(incident['rate'].split('-')[0]),
                int(incident['rate'].split('-')[1].split()[0])
            )
            
            for _ in range(log_count):
                level = np.random.choice(
                    list(incident['level_distribution'].keys()),
                    p=list(incident['level_distribution'].values())
                )
                
                if level == 'ERROR' and minute >= 60:
                    # Use incident error patterns
                    pattern_obj = np.random.choice(incident['error_patterns'])
                    message = pattern_obj['pattern']
                else:
                    message = "Normal log message"
                
                logs.append({
                    'timestamp': f"2026-01-15T14:{minute:02d}:{np.random.randint(0,60):02d}Z",
                    'service': service_name,
                    'level': level,
                    'message': message
                })
    
    return pd.DataFrame(logs)

def main():
    scenario = load_scenario('scenarios/INC-009.json')
    
    # Configuration
    total_minutes = 85
    interval_seconds = 30
    
    # Generate timestamps
    timestamps = pd.date_range(
        start=scenario['timeline']['detection_time'],
        periods=total_minutes * (60 // interval_seconds),
        freq=f'{interval_seconds}s'
    )
    
    # Generate metrics
    df_metrics = pd.DataFrame({'timestamp': timestamps})
    
    for service_name, metrics in scenario['metrics_behavior'].items():
        for metric_name, metric_config in metrics.items():
            col_name = f"{service_name}_{metric_name}"
            df_metrics[col_name] = generate_metric_timeseries(
                metric_config,
                total_minutes,
                interval_seconds
            )
    
    # Save metrics
    output_path = f"datametric/{scenario['scenario_id']}_metrics.csv"
    df_metrics.to_csv(output_path, index=False)
    print(f"✅ Generated metrics: {output_path}")
    
    # Generate logs
    df_logs = generate_logs(scenario, total_minutes)
    log_output = f"datametric/{scenario['scenario_id']}_logs.json"
    df_logs.to_json(log_output, orient='records', indent=2)
    print(f"✅ Generated logs: {log_output}")
    
    # Generate anomaly labels
    labels = []
    for i, ts in enumerate(timestamps):
        minute = i // (60 // interval_seconds)
        if 60 <= minute < 76:
            label = -1  # Anomaly
        else:
            label = 1   # Normal
        
        labels.append({
            'timestamp': str(ts),
            'label': label,
            'phase': 'anomaly' if label == -1 else 'normal'
        })
    
    label_output = f"datametric/{scenario['scenario_id']}_labels.json"
    with open(label_output, 'w') as f:
        json.dump(labels, f, indent=2)
    print(f"✅ Generated labels: {label_output}")

if __name__ == '__main__':
    main()
```

---

## 📁 File Organization

```
scenarios/
├── infrastructure/
│   ├── INC-001-cpu-spike.json
│   ├── INC-002-memory-leak.json
│   ├── INC-009-connection-pool.json
│   └── INC-015-disk-full.json
│
├── application/
│   ├── INC-003-null-pointer.json
│   ├── INC-010-deadlock.json
│   └── INC-018-cache-stampede.json
│
├── network/
│   ├── INC-005-packet-loss.json
│   └── INC-012-dns-failure.json
│
└── data/
    ├── INC-007-kafka-lag.json
    └── INC-014-redis-eviction.json

datametric/
├── INC-009_metrics.csv          # Generated metrics time series
├── INC-009_logs.json            # Generated log entries
├── INC-009_labels.json          # Anomaly labels for training
└── INC-009_traces.json          # Optional: trace data
```

---

## 🎯 Metric Behavior Patterns

### Pattern Types

```json
{
  "behavior_patterns": {
    "stable": {
      "description": "Metric không thay đổi đáng kể",
      "use_case": "CPU/Memory khi không phải bottleneck",
      "parameters": ["mean", "std_dev"]
    },
    
    "gradual_spike": {
      "description": "Tăng dần theo thời gian",
      "use_case": "Error rate tích tụ, memory leak",
      "parameters": ["start_value", "peak_value", "spike_pattern"],
      "spike_patterns": ["linear", "exponential_growth", "logarithmic"]
    },
    
    "step_spike": {
      "description": "Thay đổi đột ngột tức thì",
      "use_case": "Latency khi hit bottleneck, connection timeout",
      "parameters": ["start_value", "peak_value"]
    },
    
    "ceiling_hit": {
      "description": "Tăng dần rồi stuck ở giới hạn",
      "use_case": "Connection pool, thread pool exhaustion",
      "parameters": ["start_value", "peak_value", "max_limit"]
    },
    
    "oscillating": {
      "description": "Dao động lên xuống",
      "use_case": "GC pressure, retry storms",
      "parameters": ["amplitude", "frequency", "baseline"]
    },
    
    "drop": {
      "description": "Giảm đột ngột",
      "use_case": "RPS drop khi service down, availability",
      "parameters": ["start_value", "drop_value"]
    }
  }
}
```

### Correlation Patterns

```json
{
  "correlation_examples": {
    "positive_correlation": {
      "description": "Cả 2 metrics tăng cùng nhau",
      "example": "RPS ↑ và CPU ↑ (normal load)",
      "metrics": ["rps", "cpu_usage"],
      "correlation_coefficient": 0.85
    },
    
    "negative_correlation": {
      "description": "Metric này tăng, metric kia giảm",
      "example": "Error rate ↑ và Success rate ↓",
      "metrics": ["error_rate", "success_rate"],
      "correlation_coefficient": -0.95
    },
    
    "no_correlation_suspicious": {
      "description": "Không correlation khi đáng lẽ phải có",
      "example": "RPS stable nhưng Error rate ↑ (anomaly signal)",
      "metrics": ["rps", "error_rate"],
      "correlation_coefficient": 0.05,
      "anomaly_indicator": true
    },
    
    "lagged_correlation": {
      "description": "Metric B tăng sau Metric A một khoảng delay",
      "example": "Kafka lag ↑ → 5 phút sau → Latency ↑",
      "metrics": ["kafka_lag", "latency"],
      "lag_seconds": 300
    }
  }
}
```

---

## 📝 Template Checklist

Khi viết scenario mới, đảm bảo có đủ:

### ✅ Metadata Section
- [ ] scenario_id unique
- [ ] incident_name descriptive
- [ ] affected_services list đầy đủ
- [ ] timeline với các phases rõ ràng
- [ ] description ngắn gọn, dễ hiểu

### ✅ Metrics Section
- [ ] Ít nhất 5-7 metrics per service
- [ ] Mỗi metric có metric_path (PromQL query)
- [ ] Baseline với mean, std_dev, pattern
- [ ] Incident behavior với reasoning
- [ ] Unit đo lường rõ ràng

### ✅ Logs Section
- [ ] Normal logs với rate và level distribution
- [ ] Incident logs với error patterns
- [ ] Frequency (high/medium/low) cho mỗi pattern
- [ ] Reasoning tại sao log xuất hiện

### ✅ Root Cause Section
- [ ] Causal chain với ít nhất 3-4 steps
- [ ] Mỗi step có evidence cụ thể
- [ ] Contributing factors nếu có
- [ ] Why_not_other_causes để phân biệt

### ✅ Remediation Section
- [ ] Ít nhất 1-3 actions
- [ ] Command cụ thể có thể execute
- [ ] Duration và result expected
- [ ] Long-term fixes nếu có

---

## 💡 Best Practices

### 1. Metrics Realism
```json
// ❌ BAD: Unrealistic variance
{
  "baseline": {
    "mean": 100,
    "std_dev": 50  // Too high - 50% variance unrealistic
  }
}

// ✅ GOOD: Realistic variance
{
  "baseline": {
    "mean": 100,
    "std_dev": 10  // 10% variance realistic
  }
}
```

### 2. Clear Reasoning
```json
// ❌ BAD: No reasoning
{
  "during_incident": {
    "behavior": "spike",
    "peak_value": 3500
  }
}

// ✅ GOOD: Clear reasoning
{
  "during_incident": {
    "behavior": "spike",
    "peak_value": 3500,
    "reasoning": "Connection wait time 4.8s + query execution time 200ms"
  }
}
```

### 3. Complete Evidence Chain
```json
// ❌ BAD: Missing evidence
{
  "what_happened": "Error rate increased"
}

// ✅ GOOD: Evidence included
{
  "what_happened": "Error rate increased from 0.1% to 5.2%",
  "evidence": [
    "error_rate metric: 0.001 → 0.052",
    "Log pattern: 'Connection pool timeout' (450 occurrences)",
    "Trace: 52% of spans have DatabaseConnectionException"
  ]
}
```

---

## 📚 Example Scenarios

Xem các file mẫu trong repository:

1. **INC-009-connection-pool.json** - Connection pool exhaustion (infrastructure)
2. **INC-007-kafka-lag.json** - Kafka consumer lag (data)
3. **INC-003-memory-leak.json** - Memory leak (application)
4. **INC-005-packet-loss.json** - Network packet loss (network)

---

## 🔄 Version Control

```json
{
  "metadata": {
    "version": "1.2.0",
    "created_date": "2026-01-15",
    "last_updated": "2026-07-22",
    "changelog": [
      {
        "version": "1.2.0",
        "date": "2026-07-22",
        "changes": ["Added trace behavior section", "Updated metric schemas"]
      },
      {
        "version": "1.1.0",
        "date": "2026-06-10",
        "changes": ["Refined log patterns", "Added correlation examples"]
      },
      {
        "version": "1.0.0",
        "date": "2026-01-15",
        "changes": ["Initial scenario from production incident"]
      }
    ]
  }
}
```

---

**END OF FORMAT GUIDE**

**Version:** 1.0  
**Last Updated:** 2026-07-22  
**Maintained by:** AIOps Task Force 3  
