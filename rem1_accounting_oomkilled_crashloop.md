---
remediation_id: REM-001
source_postmortem: postmortem/0001-accounting-oomkill-and-ecr-lifecycle-incident.md
incident_class: resource_saturation
signature:
  culprit_service: accounting
  topology: leaf                       # accounting không có downstream nào phụ thuộc (DEPENDENCY_MAP: chỉ accounting -> kafka)
  tier: non-tier-1                     # async consumer, không nằm trên đường checkout/cart/frontend/payment
  detect_markers:
    k8s_reason: OOMKilled
    exit_code: 137
    restart_count_5m: ">=3"            # 44 lần/19h trong case gốc — ngưỡng thực tế nên đặt thấp hơn nhiều để bắt sớm
  log_markers: []                       # OOMKilled không có log app — chỉ thấy qua k8s event/describe, KHÔNG dựa vào log
  metric_pattern: "container_memory_working_set_bytes tiệm cận container_spec_memory_limit_bytes trước khi kill, KHÔNG spike đột ngột"

verified_action:
  action_type: patch-resource-limit     # ⚠️ CHƯA có trong ActionType enum hiện tại (chỉ có scale/restart/cache-flush/breaker-force/toggle-tf-flag)
  target: deployment/accounting
  parameters:
    resource: memory
    from_limit: "120Mi"
    to_limit: "350Mi"
  rationale: "Memory limit đặt thấp hơn tải thật của .NET Kafka consumer dưới traffic liên tục từ load-generator. Đây không phải leak — sau patch 350Mi, 0 restart, ổn định lâu dài."
  rollback_plan: "kubectl patch deployment/accounting -n techx-tf3 --type merge -p '{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"accounting\",\"resources\":{\"limits\":{\"memory\":\"120Mi\"}}}]}}}}' (khôi phục nếu 350Mi gây vấn đề khác, ví dụ chèn ép node)"
  fallback_safe_action: scale            # nằm sẵn trong whitelist hiện tại — dùng khi patch-resource-limit chưa được thêm vào ActionType
  fallback_note: "Scale +1 replica KHÔNG sửa root cause (mỗi pod vẫn cùng limit 120Mi) — chỉ là containment tạm để giảm số message/pod trong lúc chờ người duyệt patch thật. Không tự tin dùng scale làm giải pháp cuối."

confidence_evidence:
  observed_count: 1
  outcome: "0 restart sau patch, chạy ổn định (verify bằng kubectl get pods theo cột RESTARTS)"
  verified_by_telemetry: true
  root_cause_certainty: high            # exitCode 137 + OOMKilled reason là tín hiệu k8s xác định, không suy luận
  confounders_ruled_out:
    - "Không phải memory leak: nếu là leak, tăng limit chỉ trì hoãn OOM chứ không về 0 restart lâu dài — case này ổn định lâu dài sau patch nên là undersized limit, không phải leak"
  false_positive_risk: low

blast_radius:
  services_impacted: [accounting]
  customer_facing: false               # checkout thành công dù accounting chết (async consumer, không trên critical path)
  downstream_of_accounting: []          # leaf node — an toàn nhất có thể trong toàn hệ thống
  data_risk: "có (thấp xác suất) — EnableAutoCommit=true nghĩa là nếu pod bị kill giữa lúc xử lý (đã commit offset, chưa ghi DB), bản ghi kế toán của đơn đó có thể mất. Đây là lý do action phải nhanh (giảm cửa sổ crash), không phải lý do trì hoãn action."

risk_tier_recommendation: LOW_with_gate
# Lý do không thẳng LOW/auto-execute hoàn toàn: action_type patch-resource-limit chưa nằm trong whitelist code.
# Khi đã thêm ActionType.PATCH_RESOURCE_LIMIT + bound an toàn (vd chỉ cho tăng, tối đa 3x, chỉ non-tier-1),
# case này đủ điều kiện auto-execute: non-tier-1 + leaf + idempotent + root cause certainty cao + đã verify 1 lần.
---

# REM-001 — Accounting CrashLoopBackOff do OOMKilled (memory limit undersized)

## Root cause
`accounting` (Kafka consumer, .NET/EF Core) nhận sự kiện đơn hàng liên tục; memory limit
`120Mi` trong `techx-corp-chart/values.yaml` thấp hơn nhu cầu thật dưới tải liên tục →
kernel/kubelet OOMKill lặp lại (44 lần/19h quan sát được).

## Vì sao đây là ứng viên tự tin, blast radius thấp
- **Leaf node**: không service nào downstream phụ thuộc `accounting` (xem `DEPENDENCY_MAP`) — hỏng
  cũng không lan ngang.
- **Không trên critical path**: checkout vẫn thành công dù `accounting` crash — không chạm SLO
  checkout/cart/browse.
- **Tín hiệu xác định, không suy luận**: `exitCode: 137` + `reason: OOMKilled` là sự thật từ k8s API,
  không phải suy đoán từ log/metric gián tiếp — root cause certainty cao ngay từ 1 lệnh
  `kubectl describe pod`.
- **Đã verify bằng telemetry thật**: patch lên 350Mi → 0 restart, ổn định lâu dài (không phải "tưởng đỡ
  rồi lại OOM" — đã loại trừ khả năng leak).

## Vì sao chưa auto-execute được ngay hôm nay
`action_type: patch-resource-limit` không nằm trong `WHITELIST` hiện tại của `remediation.py`
(chỉ có `SCALE/RESTART/CACHE_FLUSH/BREAKER_FORCE/TOGGLE_TF_FLAG`). Cần:
1. Thêm `ActionType.PATCH_RESOURCE_LIMIT` vào enum + whitelist.
2. Giới hạn cứng: chỉ cho **tăng** limit (không cho giảm), trần tối đa (vd 3× giá trị hiện tại),
   chỉ áp dụng cho service `tier != tier-1`.
3. Cho tới lúc đó, nếu cần containment ngay, dùng `scale` (+1 replica) như stopgap — **không phải
   fix thật**, chỉ giảm tải/pod tạm thời trong lúc chờ người duyệt patch.

## Kịch bản test đề xuất (để đưa vào bộ chaos_validate / hidden scenario)
Bơm: giữ nguyên memory limit thấp, tăng tải Kafka consumer (nhiều message/s hơn baseline) →
detector phải bắt được xu hướng `memory_usage` tiệm cận limit (không phải bắt SAU khi đã bị kill —
bắt được sớm ở IsolationForest/rolling-mean trước khi restart_count tăng là điểm cộng).
