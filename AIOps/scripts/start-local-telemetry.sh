#!/bin/bash
echo -e "\033[0;36m=== Starting AIOps Local Telemetry Setup ===\033[0m"

# Get current script directory to resolve paths
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# 1. Start Prometheus port-forward
echo "Starting Prometheus port-forward to local port 9090..."
nohup kubectl port-forward -n techx-tf3 svc/prometheus-server 9090:80 > /dev/null 2>&1 &

# 2. Start Jaeger port-forward
echo "Starting Jaeger port-forward to local port 16686..."
nohup kubectl port-forward -n techx-tf3 svc/jaeger-query 16686:16686 > /dev/null 2>&1 &

# 3. Start local Grafana Container
echo "Checking local Grafana container..."
docker rm -f grafana-local > /dev/null 2>&1

echo "Starting Grafana container on http://localhost:3000..."
docker run -d --name grafana-local -p 3000:3000 \
  -v "$REPO_ROOT/AIE1/techx-corp-chart/grafana/local-provisioning:/etc/grafana/provisioning" \
  grafana/grafana

echo ""
echo -e "\033[0;32m=== Setup Complete! ===\033[0m"
echo "1. Access Grafana at: http://localhost:3000 (Login: admin / admin)"
echo "   - All AIOps dashboards are pre-loaded in the 'AIOps' folder!"
echo "2. Access Jaeger UI at: http://localhost:16686"
echo "3. Raw Prometheus metrics at: http://localhost:9090"
echo "To stop port-forwards, run: killall kubectl"
