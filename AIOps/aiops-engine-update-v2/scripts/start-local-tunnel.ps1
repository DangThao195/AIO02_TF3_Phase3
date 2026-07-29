# Script Port-Forward từ EKS Cluster về Localhost (Tự động nạp AWS Credentials)
Param(
    [string]$Namespace = "techx-tf3"
)

# NOTE: Credentials are loaded from AWS CLI profile or environment variables.
# Do NOT hardcode credentials here. Configure via `aws configure` or set env vars before running.
$KeyId     = if ($env:AWS_ACCESS_KEY_ID)     { $env:AWS_ACCESS_KEY_ID }     else { Read-Host "Enter AWS_ACCESS_KEY_ID" }
$SecretKey = if ($env:AWS_SECRET_ACCESS_KEY) { $env:AWS_SECRET_ACCESS_KEY } else { Read-Host "Enter AWS_SECRET_ACCESS_KEY" }
$Region    = if ($env:AWS_DEFAULT_REGION)    { $env:AWS_DEFAULT_REGION }    else { "ap-southeast-1" }

# Thiết lập biến môi trường AWS phiên làm việc hiện tại
$env:AWS_ACCESS_KEY_ID = $KeyId
$env:AWS_SECRET_ACCESS_KEY = $SecretKey
$env:AWS_DEFAULT_REGION = $Region

Write-Host "🚀 Đang khởi tạo Port-Forward từ EKS Cluster ($Namespace) về Localhost..." -ForegroundColor Green

# 1. Grafana (Port 3000 -> 80)
Start-Process powershell -ArgumentList "-NoExit -Command `$env:AWS_ACCESS_KEY_ID='$KeyId'; `$env:AWS_SECRET_ACCESS_KEY='$SecretKey'; `$env:AWS_DEFAULT_REGION='$Region'; kubectl port-forward svc/grafana 3000:80 -n $Namespace"

# 2. Prometheus (Port 9090 -> 9090)
Start-Process powershell -ArgumentList "-NoExit -Command `$env:AWS_ACCESS_KEY_ID='$KeyId'; `$env:AWS_SECRET_ACCESS_KEY='$SecretKey'; `$env:AWS_DEFAULT_REGION='$Region'; kubectl port-forward svc/prometheus 9090:9090 -n $Namespace"

# 3. Jaeger (Port 16686 -> 16686)
Start-Process powershell -ArgumentList "-NoExit -Command `$env:AWS_ACCESS_KEY_ID='$KeyId'; `$env:AWS_SECRET_ACCESS_KEY='$SecretKey'; `$env:AWS_DEFAULT_REGION='$Region'; kubectl port-forward svc/jaeger 16686:16686 -n $Namespace"

# 4. OpenSearch (Port 9200 -> 9200)
Start-Process powershell -ArgumentList "-NoExit -Command `$env:AWS_ACCESS_KEY_ID='$KeyId'; `$env:AWS_SECRET_ACCESS_KEY='$SecretKey'; `$env:AWS_DEFAULT_REGION='$Region'; kubectl port-forward svc/opensearch 9200:9200 -n $Namespace"

Write-Host "✅ Đã tự động nạp AWS Creds và mở các tiến trình Port-Forward:" -ForegroundColor Cyan
Write-Host "   - Grafana:    http://localhost:3000" -ForegroundColor Yellow
Write-Host "   - Prometheus: http://localhost:9090" -ForegroundColor Yellow
Write-Host "   - Jaeger:     http://localhost:16686" -ForegroundColor Yellow
Write-Host "   - OpenSearch: http://localhost:9200" -ForegroundColor Yellow
