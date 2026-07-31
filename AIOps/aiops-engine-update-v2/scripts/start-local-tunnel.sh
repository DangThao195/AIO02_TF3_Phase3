#!/bin/bash
# Script Port-Forward từ EKS Cluster về Localhost (Bash / Linux / macOS)
NAMESPACE="${1:-techx-tf3}"

echo "🚀 Đang khởi tạo Port-Forward từ EKS Cluster ($NAMESPACE) về Localhost..."

kubectl port-forward svc/prometheus 9090:9090 -n $NAMESPACE &
PID_PROM=$!

kubectl port-forward svc/jaeger 16686:16686 -n $NAMESPACE &
PID_JAEGER=$!

kubectl port-forward svc/opensearch 9200:9200 -n $NAMESPACE &
PID_OPENSEARCH=$!

echo "✅ Đã kết nối Port-Forward thành công:"
echo "   - Prometheus: http://localhost:9090"
echo "   - Jaeger:     http://localhost:16686"
echo "   - OpenSearch: http://localhost:9200"
echo "Nhấn [Ctrl+C] để tắt tất cả kết nối."

trap "kill $PID_PROM $PID_JAEGER $PID_OPENSEARCH 2>/dev/null" EXIT
wait
