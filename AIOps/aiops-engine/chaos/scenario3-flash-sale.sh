#!/bin/bash
# Scenario 3: Giả lập đợt Flash Sale / Black Friday (Tăng tải gấp 5 lần, Zero Errors)

echo "=== [SCENARIO 3] Kích hoạt đợt tăng tải Flash Sale (Scale load-generator replicas = 5) ==="
kubectl -n techx-tf3 scale deploy/load-generator --replicas=5

echo "Đợt Flash Sale đang diễn ra trong 10 phút. Kiểm tra kênh Slack AIOps Bot (Yêu cầu: TẮT TIẾNG 100%, Zero False Alarms)..."
sleep 600

echo "=== [SCENARIO 3] Kết thúc Flash Sale. Hạ tải về bình thường (replicas = 1) ==="
kubectl -n techx-tf3 scale deploy/load-generator --replicas=1
