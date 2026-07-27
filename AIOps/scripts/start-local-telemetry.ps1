Write-Host "=== Starting AIOps Local Telemetry Setup ===" -ForegroundColor Cyan

# 1. Start Prometheus port-forward
Write-Host "Starting Prometheus port-forward to local port 9090..."
Start-Process kubectl -ArgumentList "port-forward -n techx-tf3 svc/prometheus-server 9090:80" -WindowStyle Hidden

# 2. Start Jaeger port-forward
Write-Host "Starting Jaeger port-forward to local port 16686..."
Start-Process kubectl -ArgumentList "port-forward -n techx-tf3 svc/jaeger-query 16686:16686" -WindowStyle Hidden

# 3. Start local Grafana Container
Write-Host "Checking local Grafana container..."
$container = docker ps -a --filter "name=grafana-local" --format "{{.ID}}"
if ($container) {
    Write-Host "Stopping existing grafana-local container..."
    docker rm -f grafana-local | Out-Null
}

Write-Host "Starting Grafana container on http://localhost:3000..."
docker run -d --name grafana-local -p 3000:3000 -v D:\AWS\AIO23\AIO02_TF3_Phase3\AIE1\techx-corp-chart\grafana\local-provisioning:/etc/grafana/provisioning grafana/grafana

Write-Host ""
Write-Host "=== Setup Complete! ===" -ForegroundColor Green
Write-Host "1. Access Grafana at: http://localhost:3000 (Login: admin / admin)"
Write-Host "   - All AIOps dashboards are pre-loaded in the 'AIOps' folder!"
Write-Host "2. Access Jaeger UI at: http://localhost:16686"
Write-Host "3. Raw Prometheus metrics at: http://localhost:9090"
Write-Host "To stop the port-forward background processes, run: Stop-Process -Name kubectl -Force"
