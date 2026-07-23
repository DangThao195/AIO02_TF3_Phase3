# Postmortem 0007 — Rollout security-hardening giữa giờ làm Kafka Recreate, checkout mất ~22 sự kiện đơn hàng (~22:12–22:15 16/07/2026)

**Ngày:** 16/07/2026 (điều tra ngay trong tối, viết 17/07)
**Người ghi nhận & xử lý:** CDO02 — điều tra từ span lỗi trên Jaeger (`orders publish`, checkout)
**Mức độ ảnh hưởng:** **Không ảnh hưởng khách hàng, có mất dữ liệu nghiệp vụ giới hạn.**
`PlaceOrder` lỗi = **0** (không đơn nào fail với khách); nhưng **~22 sự kiện đơn hàng** publish
vào Kafka thất bại trong cửa sổ ~2–3 phút và bị **drop vĩnh viễn** (code không retry/DLQ) →
22 đơn này **không bao giờ đến `accounting`/`fraud-detection`**. Sổ kế toán thiếu 22 đơn so với
đơn đã charge/ship thật.
**Trạng thái:** ✅ Hệ đã tự hồi phục (Kafka Running, publish sạch lỗi). Không cần khắc phục trên
cluster. Đây là **sự cố tự gây** (rollout của chính team), không phải BTC — đã loại trừ bằng
query flagd (mọi flag `off`). Việc còn lại là vá quy trình (mục How to fix).

---

## When — Khi nào

**~22:12 → ~22:15 (+07) 16/07/2026** (~15:12–15:15 UTC), kéo dài ~2–3 phút.

- 22:12 — PR #145 (`mandate-5/integration`) merge vào `main`.
- ~22:12–13 — ArgoCD auto-sync; Deployment `kafka` nhận template mới → ReplicaSet mới
  `kafka-6b98c4888b` (revision 26); pod cũ bị giết trước theo `strategy: Recreate`.
- Events pod mới (đo từ cluster): ~25s `FailedScheduling` → Scheduled → AttachVolume (EBS)
  → container start → startup probe fail 1 nhịp (`dial tcp 10.0.25.7:9092: connection refused`)
  → Ready.
- Trong cửa sổ đó checkout producer lỗi: `kafka: client has run out of available brokers to
  talk to: dial tcp 172.20.162.93:9092: connect: connection refused` (172.20.162.93 = ClusterIP
  của Service `kafka` — connection refused tầng TCP, không phải lỗi logic).
- Thời điểm điều tra (~22:20): Kafka `1/1 Running`, checkout logs sạch, publish thành công trở lại.

## Where — Ở đâu

- **Điểm gãy:** Deployment `kafka` (single-replica, PVC RWO, `strategy: Recreate`) — namespace
  `techx-tf3`.
- **Điểm phát lỗi nhìn thấy:** client-span `orders publish` (producer) của `checkout`
  ([`main.go:686`](../../phase3%20-%20information/techx-corp-platform/src/checkout/main.go) —
  `SyncProducer.SendMessage`).
- **Điểm mất dữ liệu:** `sendToPostProcessor` (`main.go:687-693`) — khi `SendMessage` trả lỗi,
  code **chỉ log + set span error rồi bỏ qua** (không retry, không buffer, không DLQ), và caller
  (`main.go:440`) không nhận error → message mất vĩnh viễn, `PlaceOrder` vẫn trả thành công.
- **Nguồn thay đổi:** PR #145 thêm security hardening vào pod template của **toàn bộ workload**.
  Diff thực tế giữa 2 ReplicaSet kafka (old `55948d947f` vs new `6b98c4888b`) chỉ gồm 3 field:
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`.
  Image **không đổi** (`58b13f2-kafka`).

## What — Chuyện gì đã xảy ra

Một PR hardening bảo mật (nội dung đúng, nên làm) đổi pod template của mọi workload cùng lúc.
Với các Deployment thường (RollingUpdate + `maxUnavailable: 0`, Mandate #3) việc này **zero
downtime** — frontend-proxy v.v. roll êm. Nhưng **Kafka là ngoại lệ cấu trúc**: single-replica
+ PVC RWO ⇒ bắt buộc `Recreate` ⇒ **mọi thay đổi template = một lần downtime chắc chắn**
(giết pod cũ → schedule pod mới → attach EBS → KRaft bootstrap). Lần này cửa sổ ~2–3 phút,
kéo dài thêm bởi ~25s FailedScheduling (cluster đang chật CPU/memory — Karpenter vừa
consolidate — và PV node affinity giới hạn node stateful).

Trong cửa sổ đó, mỗi `PlaceOrder` vẫn hoàn tất (charge → ship → response OK cho khách) nhưng
bước publish sự kiện đơn sang Kafka fail và bị nuốt.

### Bằng chứng — Prometheus spanmetrics (cửa sổ 30 phút phủ sự cố)

`sum by (span_name, status_code) (increase(traces_span_metrics_calls_total{service_name="checkout"}[30m]))`:

| Span | ERROR | UNSET (ok) | Ý nghĩa |
|---|---:|---:|---|
| `oteldemo.CheckoutService/PlaceOrder` | **0** | ~477 | Không đơn nào fail với khách |
| `oteldemo.PaymentService/Charge` | 0 | ~477 | Thanh toán bình thường |
| `publish orders` | **~22** | ~455 | ~22 sự kiện đơn không vào được Kafka |

→ ~477 đơn đặt thành công, chỉ ~455 sự kiện đến Kafka: **thiếu ~22 sự kiện** (≈4.6% trong cửa sổ
30'), tập trung đúng 2–3 phút Kafka down.

### Bằng chứng — loại trừ BTC

Query OFREP flagd tại thời điểm điều tra: **toàn bộ flag `off`** (kể cả `kafkaQueueProblems`,
`paymentFailure`, `cartFailure`). Chữ ký lỗi cũng khác hẳn fault-injection: đây là TCP
connection refused tới Service ClusterIP đúng lúc pod bị thay — khớp 100% timeline rollout.

## Why — Vì sao

**Nguyên nhân trực tiếp:** thay đổi pod template của workload `Recreate` single-replica trong
giờ có traffic ⇒ downtime by-design.

**Nguyên nhân gốc (quy trình):** đội chưa có quy ước rằng *"PR chạm pod template của
postgres/valkey/kafka = một lần planned-failover"*. Runbook
[`stateful-node-planned-maintenance.md`](../runbooks/stateful-node-planned-maintenance.md)
(PR #117) đã nói thẳng single-replica RWO có downtime ~30–60s+/lần và yêu cầu làm off-peak —
nhưng nó được viết cho **bảo trì node**, chưa ai nối nó vào **rollout do PR**. PR #145 review
đúng về nội dung security nhưng không ai flag hệ quả "template change → Kafka restart giữa giờ".

**Vì sao mất hẳn 22 sự kiện (không chỉ trễ):** REL-09 đã làm producer **sync + WaitForAll** để
lỗi *hiện ra* thay vì âm thầm — đúng mục đích, và lần này nó hiện ra thật (span error). Nhưng
đường xử lý lỗi dừng ở "log + span": không retry (broker down thì retry trong-request cũng vô
ích), không buffer/DLQ → hiển thị được nhưng không cứu được. Trade-off này đã ngầm chấp nhận
từ REL-09; sự cố này cho nó một con số cụ thể: 22 đơn/3 phút down.

## How to fix — Khắc phục & phòng ngừa

**Không có gì phải sửa trên cluster** — hệ đã hồi phục. Các việc rút ra:

1. **Quy ước PR cho stateful (làm ngay, $0):** PR nào đổi pod template của
   `postgres`/`valkey-cart`/`kafka` (image, env, securityContext, resources, volume...) phải:
   (a) ghi rõ trong mô tả PR *"gây restart <datastore>, downtime dự kiến ~X phút"*;
   (b) merge/sync **ngoài giờ cao điểm** theo tinh thần runbook planned-failover;
   (c) reviewer bắt buộc check mục này. Cân nhắc thêm CI check: diff đụng block stateful trong
   `values-prod.yaml` → comment cảnh báo tự động lên PR.
2. **Đối soát 22 đơn thiếu ở accounting (nếu cần cho audit):** order ID lấy được từ Jaeger —
   lọc trace có span `orders publish` ERROR trong cửa sổ 15:12–15:15 UTC 16/07, đọc
   `app.order.id` trên span cha `PlaceOrder` cùng trace. Ghi nhận số này vào sổ theo dõi thay vì
   sửa ngược DB accounting (đơn demo, giá trị chính là bài học đo đếm được).
3. **Không thêm retry/buffer cho publish lúc này (quyết định có ý thức):** broker single-replica
   down thì retry ngắn vô ích, còn buffer bền tại checkout là một mini-Kafka tự chế — độ phức tạp
   sai chỗ. Đường sửa thật là **xóa cửa sổ downtime ở tầng broker**: MSK multi-broker
   (**Mandate #8**, ADR 0009, đang triển khai — hạn 20/07). Sự cố này là bằng chứng định lượng
   mới nhất cho quyết định đó: 2 lần trong 3 ngày (cutover PVC 14/07, rollout 16/07) Kafka
   single-replica + Recreate biến một thay đổi thường thành mất dữ liệu nghiệp vụ.
4. **Alert cho producer-loss (nối tiếp postmortem 0004/0005):** thêm alert
   `increase(traces_span_metrics_calls_total{service_name="checkout", span_name="publish orders",
   status_code="STATUS_CODE_ERROR"}[5m]) > 0` — mức cảnh báo cao hơn loại "span phụ" (EmptyCart,
   0005) vì đây là **mất dữ liệu thật**, không phải lỗi được nuốt an toàn. Lần này phát hiện nhờ
   tình cờ xem Jaeger; lẽ ra phải là alert chủ động.

---

### Phụ lục — lệnh điều tra đã dùng (tái lập được)

```sh
export AWS_PROFILE=techx-new
# 1. Trạng thái + tuổi pod kafka (pod mới ~4 phút -> vừa bị thay)
kubectl -n techx-tf3 get pods -o wide | grep kafka
# 2. Vì sao thay: ReplicaSet mới + events
kubectl -n techx-tf3 get rs | grep kafka
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp | grep -i kafka
# 3. Cái gì đổi: diff template 2 RS (old vs new) -> chỉ 3 field securityContext
kubectl -n techx-tf3 get rs kafka-<old> -o json > old.json
kubectl -n techx-tf3 get rs kafka-<new> -o json > new.json   # rồi diff phần .spec.template
# 4. Ảnh hưởng: spanmetrics qua Prometheus
kubectl -n techx-tf3 port-forward svc/prometheus 9091:9090 &
curl -s http://localhost:9091/api/v1/query --data-urlencode \
  "query=sum by (span_name,status_code) (increase(traces_span_metrics_calls_total{service_name='checkout'}[30m]))"
# 5. Loại trừ BTC: đọc flag (read-only, KHÔNG đụng flagd)
kubectl -n techx-tf3 run flagcheck --rm -i --restart=Never --image=curlimages/curl:8.11.1 --command -- \
  curl -s -X POST http://flagd:8016/ofrep/v1/evaluate/flags -H "Content-Type: application/json" -d '{"context":{}}'
```

*Ký: CDO02. Liên quan: ADR 0007 (residual risk Recreate/single-replica), ADR 0009 + Mandate #8
(xóa SPOF tầng dữ liệu), REL-09 (producer sync/WaitForAll), postmortem 0004/0005 (khung alert),
runbook `stateful-node-planned-maintenance.md`.*
