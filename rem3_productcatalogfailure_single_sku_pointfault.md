---
remediation_id: REM-003
source_postmortem: postmortem/0011-btc-injected-productcatalogfailure-checkout-degradation.md
incident_class: chaos_injection_deterministic_pointfault
signature:
  culprit_service: product-catalog
  affected_rpc: "ProductCatalogService/GetProduct"
  scope: "1 SKU cố định (hardcode trong code), KHÔNG phải toàn bộ catalog"
  topology: "checkout -> product-catalog (PlaceOrder fail) VÀ frontend -> product-catalog (browse fail)"
  tier: tier-1                          # product-catalog nằm trên đường checkout thật (khác REM-002)
  detect_markers:
    error_pattern: "tỷ lệ lỗi GIỮ MỨC ỔN ĐỊNH suốt cửa sổ (không tăng/giảm dần)"
    log_signature: "Error: Product Catalog Fail Feature Flag Enabled"
    grpc_code: INTERNAL
  metric_pattern: >
    error_rate GetProduct và error_rate PlaceOrder có quan hệ NHÂN-QUẢ 1:1 (số PlaceOrder lỗi ==
    số GetProduct lỗi tương ứng cho đúng SKU đó) — đây là chữ ký phân biệt với lỗi hạ tầng
    (connection pool/saturation) vốn thường có tỷ lệ tăng dần (ramp), không phẳng ngay từ đầu.

verified_action:
  action_type: none
  target: null
  rationale: >
    `checkProductFailure()` là boolean flag (on/off) nhắm CỨNG đúng 1 SKU (`OLJCESPC7Z`) trong code —
    khi bật, 100% request cho SKU đó fail, KHÔNG có yếu tố xác suất. Retry với xác suất y hệt sẽ
    LUÔN fail lại (khác paymentFailure ở REM-004/postmortem-0004 vốn là flag theo % nên retry có
    ý nghĩa thống kê). Scale/restart product-catalog cũng vô ích — service khỏe, không phải vấn đề
    tài nguyên/tải, DB (postgresql) chưa từng bị chạm (nhánh lỗi return TRƯỚC khi query DB).
  rollback_plan: null
  do_not_do:
    - "Retry GetProduct(OLJCESPC7Z) khi flag còn on — retry chỉ tốn latency, tỷ lệ thành công thêm = 0%"
    - "Scale product-catalog — không phải vấn đề saturation/tải, service_name error rate không tương quan CPU/memory/connection"
    - "Restart product-catalog pod — không sửa gì (flag đọc lại vẫn on ngay khi pod mới lên, restart chỉ gây gián đoạn thêm 1 lượt cho các SKU khác đang chạy tốt)"
  contrast_with: "REM-004 (postmortem 0004, paymentFailure) — flag % nên retry CÓ tác dụng; đây (flag boolean nhắm 1 SKU) retry VÔ tác dụng. Hai case trông giống nhau ở bề mặt (đều BTC-injected qua flagd) nhưng cần 2 hành vi auto khác nhau."

confidence_evidence:
  observed_count: 1
  outcome: "Flag tự tắt sau ~24 phút, hệ tự hồi phục, không có hành động nào của TF cần thiết"
  verified_by_telemetry: true
  root_cause_certainty: high
  disambiguation_rule: >
    Trước khi propose action "retry" cho bất kỳ lỗi liên quan flagd nào, PHẢI xác định flag đó là
    kiểu % (probabilistic — retry hợp lý) hay kiểu boolean nhắm entity cụ thể (deterministic —
    retry vô nghĩa). Cách phân biệt nhanh bằng telemetry, KHÔNG cần đọc source code từng lần: nếu
    error_rate cho cùng 1 key/entity (SKU/user) giữ 100% xuyên suốt cửa sổ mà không dao động →
    deterministic; nếu error_rate dao động quanh 1 mức %/thời gian → probabilistic.
  false_positive_risk: "trung bình — nếu match nhầm với pattern paymentFailure (REM-004) và đề xuất retry, hệ sẽ tốn latency vô ích nhưng KHÔNG gây hại dữ liệu (an toàn ở mức chấp nhận được, chỉ lãng phí, không phải rủi ro)"

blast_radius:
  services_impacted: []                 # action = none
  customer_facing: true                 # LƯU Ý: khác REM-002 — sự cố này CÓ ảnh hưởng khách thật (không đặt được đơn có SKU đó, không xem được trang SKU đó)
  data_risk: none                       # abort trước Payment/Shipping/Kafka publish — không đơn ma, không mất dữ liệu

risk_tier_recommendation: LOW_observe_and_escalate_if_prolonged
# Khác REM-002 (suppress hoàn toàn): case này CÓ ảnh hưởng khách thật nên vẫn cần tạo alert/incident
# (không suppress), chỉ là verified_action = none. Nếu muốn escalate, escalate là "báo SRE xác nhận
# đây có phải BTC inject hay lỗi catalog thật" — không phải escalate để chờ duyệt 1 action mutate,
# vì không có action nào đáng làm.
---

# REM-003 — `productCatalogFailure`: point-fault 1 SKU, retry vô nghĩa (đối lập với REM-004)

## Vì sao case này quan trọng cho bộ nhớ của confidence-engine
Đây là ví dụ rõ nhất cho việc **2 sự cố "nhìn giống nhau" (cùng cơ chế BTC bơm qua flagd, cùng làm
checkout tụt SLO) nhưng cần 2 quyết định auto-mitigate trái ngược nhau**:

| | postmortem 0004 (`paymentFailure`) | postmortem 0011 (`productCatalogFailure`) — case này |
|---|---|---|
| Kiểu flag | % xác suất (`numberVariant`) | boolean, nhắm cứng 1 SKU |
| Retry có ích? | **Có** — 3 lần retry, xác suất fail liên tiếp giảm mạnh (0.75³ ≈ 42% nếu flag ở mức 75%) | **Không** — retry lại đúng key đó luôn fail 100% khi flag còn on |
| Phạm vi ảnh hưởng | Toàn bộ checkout (mọi giỏ hàng) | Chỉ giỏ/trang chứa đúng 1 SKU |
| Hành động đúng | Thêm retry ở checkout (chưa implement — xem gap trong postmortem 0004) | Không hành động, chỉ quan sát |

Nếu confidence-engine chỉ học "thấy flagd-inject → đề xuất retry" từ 1 case rồi áp cho case kia,
sẽ sai. KB cần lưu **cả 2 signature riêng biệt**, không gộp chung thành 1 "incident_type: flagd_injection".

## Cách phân biệt bằng telemetry (không cần đọc source code mỗi lần)
- **Flag %**: error_rate dao động quanh 1 mức phần trăm ổn định nhưng KHÔNG phải 0% hay 100%
  tuyệt đối (vd ~85% ở postmortem 0004).
- **Flag boolean nhắm entity**: error_rate cho đúng entity đó là gần như tuyệt đối trong cửa sổ,
  nhưng tỷ lệ trên TOÀN traffic phụ thuộc entity đó chiếm bao nhiêu % traffic ngẫu nhiên
  (ở đây ~15.3% checkout vì `load-generator` chọn giỏ ngẫu nhiên, không phải vì flag "yếu" — bản
  thân request chạm đúng SKU đó luôn fail 100%).

## Ảnh hưởng khách thật — khác REM-002
Không giống REM-002 (chỉ sai dashboard, khách không bị ảnh hưởng), case này **có** ảnh hưởng khách
thật: khách có giỏ chứa SKU đó không đặt được đơn, và trang chi tiết SKU đó cũng lỗi (ảnh hưởng cả
browse). Vẫn đúng để tạo alert/incident — chỉ là hành động đi kèm là "quan sát + xác nhận nguồn
BTC", không phải "tự sửa".
