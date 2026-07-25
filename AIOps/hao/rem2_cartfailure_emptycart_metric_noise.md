---
remediation_id: REM-002
source_postmortem: postmortem/0005-btc-injected-cart-failure-flag.md
incident_class: metric_attribution_artifact   # KHÔNG phải resource/logic incident — là lỗi cách đo, không phải lỗi hệ thống
signature:
  culprit_service: cart
  affected_span: "oteldemo.CartService/EmptyCart"
  topology: "checkout -> cart (client-span EmptyCart)"
  tier: tier-1-adjacent                 # cart tier-1, nhưng RPC cụ thể này (EmptyCart) không nằm trên đường ra tiền
  detect_markers:
    dashboard_symptom: "panel Checkout Success Rate tụt <99%"
    ground_truth_check: "PlaceOrder span error_count == 0 trong cùng cửa sổ"
  log_markers: ["Wasn't able to connect to redis", "Can't access cart storage"]
  metric_pattern: "error tăng CHỈ ở span EmptyCart (client-span, service_name=checkout); PlaceOrder/Charge/publish-orders = 0 lỗi; request rate tổng ổn định (không sập traffic)"

verified_action:
  action_type: none
  target: null
  rationale: >
    Đây là false alarm ở TẦNG DASHBOARD, không phải sự cố nghiệp vụ. `checkout/main.go:401`
    chủ động nuốt lỗi EmptyCart (`_ = cs.emptyUserCart(...)`) nên PlaceOrder KHÔNG BAO GIỜ fail vì
    lý do này. Root cause thật là: panel "Checkout Success Rate" đang đo tỷ lệ lỗi trên TỔNG span
    do service checkout phát ra (gồm cả client-span EmptyCart), không phải tỷ lệ đơn đặt thành công.
    Bất kỳ hành động mutate nào (scale cart, restart cart, failover valkey) đều VÔ NGHĨA vì valkey-cart
    thật sự khỏe (0 restart, log sạch) — lỗi hoàn toàn do flag giả lập.
  rollback_plan: null   # không có action nên không cần rollback
  do_not_do:
    - "Restart/scale cart — valkey-cart không hề down, action này không giải quyết gì và tốn 1 lượt rate-limit action vô ích"
    - "Toggle/tắt flag cartFailure — vi phạm RULES §8 (disqualify), và flag tự hết theo thời gian BTC đặt"
    - "Đổi handling lỗi ở checkout thành retry EmptyCart — vô nghĩa vì lỗi không ảnh hưởng response cho khách"

confidence_evidence:
  observed_count: 1
  outcome: "Flag tự tắt sau ~14 phút, cart pod healthy xuyên suốt, PlaceOrder giữ 100% thành công cả trong lúc panel đỏ"
  verified_by_telemetry: true
  root_cause_certainty: high
  disambiguation_rule: >
    Để phân biệt case này (false-alarm) với sự cố thật (vd postmortem 0004), CHECK BẮT BUỘC trước khi
    tạo incident/page người: so `error_count` của span nghiệp vụ chính (`PlaceOrder`) với `error_count`
    của span client phụ (`EmptyCart`/các client-span khác cùng service_name). Nếu PlaceOrder = 0 lỗi
    trong khi chỉ 1 client-span phụ tăng → đây là ứng viên metric-noise, HẠ severity xuống info/suppress
    thay vì critical.
  false_positive_risk: "cao nếu KHÔNG áp disambiguation_rule ở trên — đây chính là lý do case này cần vào KB"

blast_radius:
  services_impacted: []                 # action = none, zero mutation
  customer_facing: false                # đã verify PlaceOrder 100% ok
  data_risk: none

risk_tier_recommendation: LOW_auto_suppress
# Đây là dạng "hành động đúng = KHÔNG hành động, và KHÔNG page". Không cần chờ assess_risk/whitelist mới —
# chỉ cần correlator/alert_emitter áp disambiguation_rule ở trên TRƯỚC khi tạo AlertEvent, không phải
# trước khi remediation — tức là sửa ở tầng phát hiện/gom nhóm, không phải tầng hành động.
---

# REM-002 — `cartFailure` (BTC inject) chỉ làm SAI LỆCH dashboard, không phải sự cố thật

## Vì sao case này đáng đưa vào KB dù "action = none"
Đây là kiểu KB entry quan trọng nhất cho Mandate #22: nó **ngăn hệ thống hành động sai** thay vì
đề xuất một hành động đúng. Một AIOps engine tự tin nhưng không có case dạng này rất dễ:
- Page người/tạo incident cho 1 sự cố không tồn tại (alert fatigue — đúng thứ Mandate #15 cấm).
- Tệ hơn: nếu confidence-engine thấy "checkout success rate < SLO" và tự động scale/restart `cart`,
  đó là **auto-mitigate sai** — tốn 1 lượt rate-limit action (3 action/incident/giờ) cho việc vô ích,
  và nếu BTC cố tình bơm case như vậy ngay sau 1 sự cố thật để kiểm tra "có bị che (masking) không"
  (đúng yêu cầu Mandate #15 mục 2), hệ thống cần phân biệt được.

## Root cause thật
`checkout` gọi `cart.EmptyCart` ở cuối `PlaceOrder` nhưng **chủ động bỏ qua lỗi** của bước này
(`_ = cs.emptyUserCart(...)` — dòng 401). Khi flag `cartFailure=true`, chỉ đúng RPC `EmptyCart` bị
route sang store giả lập lỗi; `GetCart`/`AddItem` vẫn dùng store thật. Vì `EmptyCart` là client-span
mang `service_name=checkout`, lỗi của nó cộng vào tổng số span lỗi của `checkout` — kéo tụt panel
dashboard dù không đơn nào thật sự fail.

## Điều kiện để KB entry này được match đúng (tránh áp nhầm)
CHỈ áp dụng "action=none" khi **cả 3** đúng:
1. `PlaceOrder` error_count = 0 trong cùng cửa sổ (không phải suy đoán — query trực tiếp).
2. Toàn bộ error tập trung ở đúng 1 client-span phụ (`EmptyCart`), không lan sang `Charge`/`ShipOrder`/`publish orders`.
3. `valkey-cart` pod healthy (0 restart, log sạch) — nếu valkey-cart thật sự down, đây KHÔNG còn là
   case này (đó là sự cố thật, cần scale/failover, không phải "none").

Nếu chỉ 1 điều kiện sai → không match, phải xử lý như incident thật, không được mặc định "none".
