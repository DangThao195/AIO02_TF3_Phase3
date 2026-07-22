# Postmortem 0009 — Bump dependency vá bảo mật kéo theo lệch giao thức gRPC `payment` ↔ `flagd`, checkout bị nghi "downtime" trên Jaeger (~16:55–17:54 17/07/2026)

**Ngày:** 17/07/2026 (điều tra ngay trong lúc xảy ra, viết lại theo format chuẩn 18/07)
**Người ghi nhận & xử lý:** CDO01 (Hoang Trong Tan) — phát hiện qua Jaeger (trace checkout hiện "1 Error"); Claude điều tra root cause; fix do truongcongtu318 (PR #217/#218)
**Mức độ ảnh hưởng:** **Không ảnh hưởng khách hàng, không mất dữ liệu.**
`Charge`/`PlaceOrder` success rate = 100% xuyên suốt sự cố. Ảnh hưởng thực tế chỉ gồm: (1) span
lỗi tràn ngập Jaeger gây báo động giả "hệ thống down"; (2) flag `paymentFailure` không resolve
được giá trị thật từ flagd, luôn fallback về default (`off`/`0`) trong suốt cửa sổ ~59 phút.
**Trạng thái:** ✅ Đã khắc phục hoàn toàn qua PR #217 + #218, verify lại 18/07: lỗi về **0**, không
còn phát sinh.

---

## When — Khi nào

**~16:55 → ~17:54 (+07) 17/07/2026** (~09:55–10:54 UTC), kéo dài ~59 phút.

- **16/07 19:03** — commit `3e6db41` "fix(security): remediate payment runtime dependencies" (vá
  nhiều CVE thật trong `@grpc/grpc-js`, các gói `@opentelemetry/*`, `uuid`...) vô tình kéo theo
  bump `@openfeature/flagd-provider` từ `0.13.3` → `0.16.0` như side-effect của lockfile
  regeneration — không nằm trong mục đích/scope commit.
- **17/07 16:55** — PR #215 "chore(deploy): bump 20 images from 43dcf62" merge — pipeline tự động
  PM-113 build lại 20 image (gồm `payment`) từ source đã chứa `3e6db41`, cập nhật digest trong
  `values-prod.yaml`.
- **~16:56 trở đi** — ArgoCD (`syncPolicy.automated: prune+selfHeal`, không gate thủ công) tự
  sync, pod `payment` recreate với image mới, bắt đầu gọi `flagd.evaluation.v2.Service/ResolveFloat`.
- **~17:10 trở đi** — lỗi `12 UNIMPLEMENTED: Received HTTP status code 404` xuất hiện liên tục
  trên span `ResolveFloat` (khớp Prometheus: không có dữ liệu lỗi trước mốc này, xuất hiện và
  duy trì ổn định ~25–42 lỗi/5 phút ngay sau đó).
- **17:02** — PR #207 (Mandate 5, thêm `securityContext` cho `flagd`/`postgresql`) merge —
  **trùng thời điểm nhưng không liên quan nhân quả**, xem mục Why.
- **17:24** — pod `flagd` restart do PR #207 ở trên — không đổi trạng thái lỗi, vì lỗi nằm ở phía
  client `payment`, không phải config/state của server `flagd`.
- **17:50** — PR #217 "fix: align payment flagd provider with runtime" merge — pin
  `@openfeature/flagd-provider` xuống lại `0.13.4`.
- **17:54** — PR #218 "chore(deploy): bump payment image to 68b20e5" merge — đưa image đã fix lên
  `values-prod.yaml`.
- **17:55:29 / 17:55:53** — 2 pod `payment` recreate với image fix (verify trực tiếp bằng
  `kubectl`, digest khớp chính xác diff PR #218) — chỉ ~1 phút sau khi PR #218 merge.
- **18/07** — verify lại: lỗi `ResolveFloat` trong 1 giờ gần nhất = **0**.

## Where — Ở đâu

- **Điểm gãy:** `src/payment/package.json` (dependency `@openfeature/flagd-provider`) — service
  `payment`, namespace `techx-tf3`.
- **Điểm phát lỗi nhìn thấy:** client-span `flagd.evaluation.v2.Service/ResolveFloat` của
  `payment` (gọi từ `charge.js`, `OpenFeature.getClient().getNumberValue("paymentFailure", 0)`),
  đích tới `flagd:8013`.
- **Điểm bị ảnh hưởng chức năng:** flag `paymentFailure` — không resolve được giá trị thật, luôn
  rơi về default `0` (tắt) do provider catch lỗi và fallback êm; `Charge` vẫn luôn thành công nên
  lỗi **không** lộ ra ở log ứng dụng hay ở tầng business, chỉ lộ ở tầng Jaeger span.
- **Nguồn thay đổi:** commit `3e6db41` (vá bảo mật hợp lệ, side-effect ngoài ý muốn), phát tán lên
  production qua PR #215 — pipeline build-image tự động PM-113, đúng quy trình thiết kế, không
  phải thao tác thủ công sai.

## What — Chuyện gì đã xảy ra

Một commit vá bảo mật đúng đắn cho `payment` (fix CVE thật trong `@grpc/grpc-js`, các gói
OpenTelemetry) bị lockfile regeneration kéo theo bump luôn `@openfeature/flagd-provider` —
version `0.16.0` mặc định gọi RPC qua `flagd.evaluation.v2.Service` thay vì `v1`. Server `flagd`
production vẫn pin cứng `ghcr.io/open-feature/flagd:v0.12.9` (phát hành 28/07/2025 — cách dòng
version tương ứng client gần **10 tháng**), chưa implement route `v2` → mọi request `ResolveFloat`
bị Connect-RPC trả `UNIMPLEMENTED`/HTTP 404 ở tầng transport (route không tồn tại, không phải lỗi
logic/permission).

Vì `payment` fallback êm về default khi resolve lỗi, `Charge` không hề fail — sự cố **chỉ lộ ra**
qua việc gần như 100% trace checkout trên Jaeger hiện "1 Error" trên span con, khiến người xem
nhanh dễ đọc nhầm thành downtime hệ thống thật (đúng tình huống ban đầu dẫn tới điều tra này).

### Bằng chứng — Prometheus spanmetrics (cửa sổ trong sự cố)

`sum by (span_name, status_code) (increase(traces_span_metrics_calls_total{service_name=~"payment|checkout"}[30m]))`
(khảo sát nhiều mốc trong cửa sổ 09:55–10:54 UTC):

| Span | ERROR | UNSET (ok) | Ý nghĩa |
|---|---:|---:|---|
| `payment flagd.evaluation.v2.Service/ResolveFloat` | ~25–42 / 5 phút (ổn định, ~100%) | ~0 | Gần như mọi lần resolve flag đều lỗi 404 |
| `payment flagd.evaluation.v2.Service/EventStream` | tăng cục bộ quanh 17:24 (~150) | — | Stream reconnect do `flagd` restart (PR #207) — nhiễu riêng, không phải nguyên nhân |
| `oteldemo.PaymentService/Charge` | **0** | 100% | Thanh toán luôn thành công |
| `oteldemo.CheckoutService/PlaceOrder` | **0** | 100% | Khách hàng không bị ảnh hưởng |

→ Đúng như suy đoán ban đầu từ 2 ảnh Jaeger user gửi: lỗi tập trung 100% ở đúng 1 span con
(`ResolveFloat`), không lan sang bất kỳ span nghiệp vụ nào.

### Bằng chứng — sau fix

`sum(increase(traces_span_metrics_calls_total{service_name="payment",span_name="flagd.evaluation.v2.Service/ResolveFloat",status_code="STATUS_CODE_ERROR"}[1h]))`
tại thời điểm verify (18/07) = **`0`**. Pod `payment` đang chạy digest
`sha256:801b602b7ac4afc3887a27cb3a97b13ea10ce35bce64afe047e3dd2b42ae5f1d` — khớp chính xác diff
PR #218.

## Why — Vì sao

**Nguyên nhân trực tiếp:** client SDK (`@openfeature/flagd-provider@0.16.0`) và server runtime
(`flagd:v0.12.9`) lệch giao thức gRPC evaluation service (`v2` vs `v1`) — không ai chủ động nâng
cấp `flagd-provider` để nói chuyện v2, đây là hệ quả không lường trước của 1 commit vá bảo mật
khác mục đích.

**Nguyên nhân gốc (quy trình):** `3e6db41` là commit vá CVE hợp lệ, nhưng dòng đổi
`@openfeature/flagd-provider: 0.13.3 → 0.16.0` gần như chắc chắn là side-effect của
`npm audit fix`/lockfile regen tự động, không nằm trong ý định commit. `package.json` không pin
exact version cho gói này, và pipeline CI (Trivy scan CVE + Cosign sign + verify digest render)
**không có bước nào kiểm tra tương thích giao thức runtime** giữa client SDK mới build và server
version đang chạy thật trên cluster — nên lỗi không bị chặn ở bất kỳ gate nào trước khi lên
production, chỉ lộ ra khi 2 phía thực sự nói chuyện với nhau.

**Đính chính hướng điều tra ban đầu:** trong lúc điều tra trực tiếp, tôi từng nghi ngờ PR #207
(thêm `securityContext`/`runAsNonRoot` cho `flagd`, merge 17:02 — chỉ cách PR #215 7 phút) là
nguyên nhân hoặc ít nhất là "trigger làm lộ" lỗi. Đã tự loại trừ hoàn toàn bằng
`git merge-base --is-ancestor 3e6db41 43dcf62` (xác nhận PR #215 mang đúng commit gây lỗi) và bằng
nội dung PR #217 tự nêu đúng root cause — PR #207 chỉ trùng thời điểm merge, làm `flagd` restart
lúc 17:24 (gây nhiễu phụ trên `EventStream`, không phải trên `ResolveFloat`), không có quan hệ
nhân quả với sự cố chính.

## How to fix — Khắc phục & phòng ngừa

**Đã khắc phục trên production**, không cần thao tác thêm trên cluster. Các việc rút ra:

1. **Đã làm — PR #217:** pin `@openfeature/flagd-provider` về `0.13.4` (gần nhất bản gốc `0.13.3`
   trước khi bị bump nhầm), regenerate lockfile, verify bằng build thật + `docker run` in ra
   provider version + `rg` xác nhận bundle không còn reference `evaluation.v2`.
2. **Đã làm — PR #218:** bump digest `payment` sang image đã build từ PR #217, đưa fix lên qua
   đúng flow GitOps (không hotfix thủ công ngoài pipeline).
3. **Cần làm — gate CI:** thêm bước "protocol compatibility check" nhẹ vào pipeline PM-113 cho
   riêng `payment` — biến việc verify thủ công của PR #217 (`rg` bundle so với version server
   production) thành gate tự động, tránh lặp lại sự cố tương tự nếu sau này có provider khác nói
   chuyện với 1 service đang pin version cứng.
4. **Cần làm — pin exact version:** khoá `@openfeature/flagd-provider` bằng version chính xác
   (không dùng range) kèm comment nêu rõ lý do (server production đang ở `v0.12.9`, không tự ý
   bump provider mà không đồng thời xét bump server) — cùng tinh thần comment đã có cho gotcha
   `sidecarContainers` trong `values-prod.yaml`.
5. **Cần làm — review riêng dependency chạm SDK giao tiếp trực tiếp:** khi vá bảo mật tự động
   (`npm audit fix`, Dependabot...) cho service có client SDK nói chuyện trực tiếp với 1 service
   khác đang pin version cứng, tách riêng dòng đổi liên quan SDK đó ra khỏi các CVE fix khác khi
   review — 1 dòng version dễ "chìm" trong hàng chục dòng đổi hợp lệ.
6. **Cần làm — alert riêng cho lỗi resolve-flag:** thêm alert
   `increase(traces_span_metrics_calls_total{service_name="payment", span_name="flagd.evaluation.v2.Service/ResolveFloat", status_code="STATUS_CODE_ERROR"}[5m]) > 0`
   tách biệt khỏi alert lỗi business (`Charge`/`PlaceOrder`) — vì client có thể "nuốt" lỗi resolve
   và fallback êm, khiến sự cố chỉ lộ qua Jaeger thay vì alert chủ động, dễ bị đọc nhầm thành
   "hệ thống đang down" (đúng tình huống dẫn tới điều tra này).

---

### Phụ lục — lệnh điều tra đã dùng (tái lập được)

```sh
# 1. Xác nhận version server đang chạy vs client SDK trong code
kubectl -n techx-tf3 get pods -l app.kubernetes.io/name=flagd \
  -o jsonpath='{.items[0].spec.containers[?(@.name=="flagd")].image}'
grep -n '"@openfeature/flagd-provider"' "phase3 - information/techx-corp-platform/src/payment/package.json"

# 2. So lịch sử release flagd server (client 0.16.0 vs server v0.12.9 lệch bao xa)
curl -s "https://api.github.com/repos/open-feature/flagd/releases?per_page=100" \
  | python3 -c "import json,sys; [print(r['tag_name'], r['published_at']) for r in json.load(sys.stdin)]"

# 3. Tìm đúng commit/PR gây lệch version, xác nhận quan hệ ancestor (không suy đoán theo giờ)
git log --oneline -- "phase3 - information/techx-corp-platform/src/payment/package.json"
git show 3e6db41 -- "phase3 - information/techx-corp-platform/src/payment/package.json"
git merge-base --is-ancestor 3e6db41 43dcf62 && echo "PR#215 mang đúng commit gây lỗi"
gh pr view 215 --repo tuu-ngo/Phase3-TF3-Infra-Sentinel --json mergedAt
gh pr view 217 --repo tuu-ngo/Phase3-TF3-Infra-Sentinel --json mergedAt,body
gh pr view 218 --repo tuu-ngo/Phase3-TF3-Infra-Sentinel --json mergedAt

# 4. Ảnh hưởng thật: spanmetrics qua Prometheus (route hợp lệ, exec vào pod grafana đã được
#    NetworkPolicy `prometheus-access` cho phép — không relabel/spoof pod để bypass policy)
kubectl -n techx-tf3 exec deploy/grafana -c grafana -- wget -qO- \
  "http://prometheus:9090/api/v1/query?query=sum(increase(traces_span_metrics_calls_total%7Bservice_name%3D%22payment%22%2Cspan_name%3D%22flagd.evaluation.v2.Service%2FResolveFloat%22%2Cstatus_code%3D%22STATUS_CODE_ERROR%22%7D%5B1h%5D))"

# 5. Verify fix đã lên production đúng pod
kubectl -n techx-tf3 get pods -l app.kubernetes.io/name=payment \
  -o jsonpath='{range .items[*]}{.metadata.name}{"  image:"}{.spec.containers[0].image}{"  start:"}{.status.startTime}{"\n"}{end}'
```

---

*Ký: Claude (agent), theo yêu cầu điều tra + viết postmortem của CDO01. Liên quan: PR #206 (khôi
phục `sidecarContainers` flagd-ui, không liên quan sự cố này), PR #207 (securityContext flagd —
trùng giờ, không liên quan nhân quả), PR #215/#217/#218 (bump lỗi → fix → deploy fix), postmortem
0006/0007/0008 (mẫu format When/Where/What/Why/How to fix).*
