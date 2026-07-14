#!/usr/bin/env bash
# Kiểm tra: raw metric có data chưa · rule đã nạp chưa · lịch sử/retention đủ chưa · traffic có không.
# Chạy sau khi SSM tunnel mở + kubectl trỏ đúng cluster techx-corp-tf3.
#
#   bash check-metrics-data.sh
#
# Không sửa gì trên cluster — chỉ query (read-only).
set -uo pipefail

NS="${NS:-techx-tf3}"
POD=$(kubectl get pod -n "$NS" -l app.kubernetes.io/name=prometheus -o name 2>/dev/null | head -1)
[ -z "$POD" ] && POD=$(kubectl get pod -n "$NS" -o name 2>/dev/null | grep -i prometheus | head -1)
if [ -z "$POD" ]; then echo "❌ không tìm thấy pod Prometheus trong ns $NS"; exit 1; fi
Q() { kubectl exec -n "$NS" "$POD" -- wget -qO- "http://localhost:9090$1" 2>/dev/null; }
echo "Prometheus pod: $POD"
echo "──────────────────────────────────────────────"

echo "1) RAW metric có data chưa? (traces_span_metrics_calls_total)"
RAW=$(Q "/api/v1/query?query=sum(traces_span_metrics_calls_total)")
echo "   $RAW" | grep -q '"value"' && echo "   ✅ CÓ data raw" || echo "   ❌ raw metric RỖNG — check OTel collector/scrape"

echo "2) Có TRAFFIC không? (rate 5m > 0 = load-generator đang chạy)"
RATE=$(Q "/api/v1/query?query=sum(rate(traces_span_metrics_calls_total[5m]))")
VAL=$(echo "$RATE" | grep -o '"value":\[[^]]*\]' | grep -o '"[0-9.e+-]*"' | tail -1 | tr -d '"')
echo "   rate = ${VAL:-0} req/s"
awk "BEGIN{exit !(${VAL:-0} > 0)}" && echo "   ✅ có traffic" || echo "   ⚠️ traffic = 0 → SLI sẽ = 0. Bật load-generator ở /loadgen/"

echo "3) Recording rules đã NẠP chưa?"
RULES=$(Q "/api/v1/rules")
if echo "$RULES" | grep -q "techx_sli"; then
  echo "   ✅ đã nạp (thấy group techx_sli)"
else
  echo "   ❌ CHƯA nạp (groups rỗng) → CDO chạy HANDOFF-CDO-recording-rules.md"
fi

echo "4) SLI recording rule ra số chưa?"
SLI=$(Q "/api/v1/query?query=sli:checkout_error:ratio_rate5m")
echo "$SLI" | grep -q '"value"' && echo "   ✅ SLI có giá trị" || echo "   ❌ SLI rỗng (rule chưa nạp hoặc chưa đủ data)"

echo "5) LỊCH SỬ / retention đủ cho cửa sổ dài?"
TSDB=$(Q "/api/v1/status/tsdb")
MINT=$(Q "/api/v1/query?query=(time()-timestamp(min_over_time(up[7d])))/86400" 2>/dev/null)
echo "   → kiểm cửa sổ 1h (rule cần ≥1h lịch sử):"
H1=$(Q "/api/v1/query?query=sli:checkout_error:ratio_rate1h")
echo "$H1" | grep -q '"value"' && echo "     ✅ cửa sổ 1h có data" || echo "     ⚠️ cửa sổ 1h chưa đủ lịch sử (Prometheus mới deploy → chờ tích data)"
echo "   → cửa sổ 6h/3d cần Prometheus chạy ≥6h/3 ngày mới có."
echo "   (C1 yêu cầu retention ≥7 ngày — CDO cấu hình --storage.tsdb.retention.time)"

echo "6) Bucket latency đủ đuôi cho p95/p99?"
BUCKETS=$(Q "/api/v1/query?query=count(count%20by%20(le)(traces_span_metrics_duration_milliseconds_bucket{service_name=\"frontend\"}))")
echo "   $(echo "$BUCKETS" | grep -o '"value":\[[^]]*\]' | tail -1) bucket boundaries"
echo "   (nếu p95/p99 luôn kẹt ở giá trị cao nhất → thiếu bucket đuôi, báo CDO thêm)"

echo "──────────────────────────────────────────────"
echo "TÓM TẮT: raw data + traffic là điều kiện có SLI; rule chưa nạp thì SLI rỗng;"
echo "cửa sổ dài cần lịch sử tích đủ. Sửa theo từng dòng ❌/⚠️ ở trên."
