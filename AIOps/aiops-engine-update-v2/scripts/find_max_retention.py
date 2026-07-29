import requests
import time

def find_retention_all():
    end_ts = int(time.time())
    queries = {
        "span_metrics (calls)": 'sum(rate(traces_span_metrics_calls_total[5m]))',
        "container_cpu": 'sum(rate(container_cpu_usage_seconds_total[5m]))',
        "container_memory": 'sum(container_memory_working_set_bytes)',
        "prometheus_build_info": 'prometheus_build_info'
    }
    
    for name, q in queries.items():
        print(f"\nChecking metric: {name}")
        for days_back in range(1, 30):
            t_end = end_ts - (days_back - 1) * 86400
            t_start = end_ts - days_back * 86400
            
            r = requests.get('http://localhost:9090/api/v1/query_range', params={
                'query': q,
                'start': t_start,
                'end': t_end,
                'step': '5m'
            }).json()
            
            res = r.get('data', {}).get('result', [])
            if res and res[0].get('values'):
                vals = res[0]['values']
                earliest = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(vals[0][0]))
                latest = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(vals[-1][0]))
                print(f"  [Day -{days_back}] Data found: {earliest} -> {latest} ({len(vals)} points)")
            else:
                print(f"  [Day -{days_back}] No data")
                break

if __name__ == "__main__":
    find_retention_all()
