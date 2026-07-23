# Postmortem 0010 — Cutover Kafka→MSK (producer checkout) làm checkout panic → outage (~22:26–22:40 +07, 19/07/2026)

**Ngày:** 19/07/2026 (viết ngay sau khi khắc phục)
**Người xử lý:** CDO02 (Huu Tai Ngo) — Mandate #8, bước 3/3 (Kafka → MSK)
**Mức độ ảnh hưởng:** **CÓ ảnh hưởng khách hàng + CÓ mất dữ liệu (bounded).**
Trong cửa sổ ~14 phút, service `checkout` panic → CrashLoopBackOff → `PlaceOrder` fail. Khách
không hoàn tất được đặt hàng; đơn phát sinh trong cửa sổ bị charge (payment **mock** — không tiền
thật) + ship nhưng **không được ghi vào `accounting`** (panic trước khi publish Kafka) → không nằm
trong Kafka nào → không recover được từ Kafka. Browse/cart và các service khác **không ảnh hưởng**.
Migration Valkey→ElastiCache và Postgres→RDS (đã xong trước đó) **không ảnh hưởng**.
**Trạng thái:** ✅ Đã khắc phục — checkout về Kafka cũ (known good), Healthy, ghi đơn bình thường,
hết panic. 🔴 Kafka→MSK **BLOCKED**, chờ fix code checkout trước khi thử lại.

---

## ✅ CẬP NHẬT 20/07/2026 — ĐÃ XÁC NHẬN ROOT CAUSE (không còn là giả thuyết)

Nguyên nhân trực tiếp ở "Tầng 1" bên dưới liệt kê 4 giả thuyết (idempotent ACL / SCRAM / TLS /
ProtocolVersion). **Tất cả đều SAI.** Sau khi thêm stderr logging (PR #269) và chạy **pod checkout
cô lập** (image mới + env MSK, ngoài Service — đúng action item #1), log stderr lộ lỗi sarama chính
xác mà `otelslog`→OpenSearch đã che trong sự cố:

```
client/metadata got error from broker -1 while fetching metadata:
dial tcp: address b-1...:9096,b-2...:9096,b-3...:9096: too many colons in address
kafka: client has run out of available brokers to talk to
```

**Root cause thật:** `checkout/main.go` truyền `[]string{os.Getenv("KAFKA_ADDR")}` — nhét **cả chuỗi
CSV 3 bootstrap broker của MSK vào MỘT phần tử** của slice broker. sarama `net.Dial` nguyên chuỗi
`"b-1:9096,b-2:9096,b-3:9096"` → lỗi `too many colons in address` → `NewSyncProducer` fail **trước
cả** bước TLS/SASL handshake. Kafka in-cluster cũ chỉ có **1 broker** (`kafka:9092`) nên
`[]string{addr}` chạy đúng — bug ẩn hoàn toàn cho tới khi lên MSK (nhiều broker).

**Fix (PR #271):** tách `KAFKA_ADDR` trên dấu phẩy thành `[]string` broker (trim, bỏ rỗng).

**Đã verify (pod cô lập, image có fix `efb7eff…`):** cả 3 broker `registered #1/#2/#3`;
`SASL authentication succeeded`; TLS `Connected to broker`; idempotent
`successful init producer id ProducerId:8130`; `ApiVersionsRequest V3 supports 63 APIs`. Nghĩa là
TLS + SCRAM + idempotent + ProtocolVersion **đều đúng từ đầu** — chỉ có bug parse địa chỉ broker.
MSK `orders` offset vẫn `0:0/1:0/2:0` (pod cô lập không produce, `InitProducerId` không ghi topic).

**Kèm theo (cùng đợt fix, PR #269):** đã thêm **fail-fast** (`KAFKA_ADDR` set mà tạo producer lỗi →
`os.Exit(1)` trước khi mở gRPC server → pod không bao giờ Ready → rollout đứng an toàn, không outage)
+ **stderr logging** (lỗi Kafka đọc được qua `kubectl logs`, không lệ thuộc OTel pipeline) +
**nil-guard** trong `sendToPostProcessor`. Ba lớp này khiến một lỗi config Kafka tương lai **không thể
lặp lại thành outage** như 0010.

→ Bài học "Tầng 2" (thiếu fail-fast là thứ biến config-error thành outage) **vẫn nguyên giá trị** — đó
mới là lỗi vận hành chính. Root cause trực tiếp chỉ là 1 dòng parse thiếu `strings.Split`.

---

## When — Timeline (giờ +07)

- **~22:00** — Pre-flight Kafka hoàn tất, **tất cả xanh**: MSK ACTIVE + SCRAM associated; TCP pod→MSK
  9096 OK (sau khi đã fix SG node ở postmortem/PR trước); pod `mskcli` M5-compliant (uid 1000
  appuser) kết nối MSK SASL_SSL OK; tạo topic `orders` (3 partition, RF=3, min.insync=2); **probe
  PRODUCE + CONSUME bằng SCRAM user thành công** (kafka-console-producer/consumer).
- **~22:10** — Scale `checkout` **Deployment = 0** (để chỉ Rollout serve → cutover đi qua canary
  SLO-gate). checkout còn 2 pod Rollout (HPA 2-8), healthy.
- **22:02 (merge) → ~22:08 (ArgoCD sync)** — Merge **PR #262** (producer switch: `checkout`
  `KAFKA_ADDR`→MSK, `KAFKA_SECURITY_PROTOCOL=SASL_SSL`, SASL user/pass từ secret). Rollout bắt đầu
  canary revision 20 (weight 20%, ActualWeight 33%).
- **~22:12** — Phát hiện **canary KHÔNG nhận traffic**: MSK `orders` offset = 0, log canary rỗng,
  trong khi Kafka cũ vẫn tăng (đơn đi qua pod stable). Nguyên nhân: **gRPC connection pinning** —
  frontend giữ kết nối HTTP/2 lâu dài tới pod stable, canary chỉ nhận traffic khi pod cũ chết.
- **~22:15** — Pause rollout (chặn auto lên 100%). Restart `frontend` để ép kết nối gRPC mới sang
  canary → **vẫn không được** (chỉ ~2 pod frontend × ít kết nối, phân bổ xác suất trượt canary).
- **~22:26** — Kết luận: không thể validate client-side ở weight thấp với gRPC. Quyết định
  **promote 100%** (ép tất cả checkout→MSK) + theo dõi MSK offset sát + rollback nhanh nếu 0.
- **~22:27** — checkout 100% MSK-env. **MSK offset vẫn = 0.** Log checkout: **nil pointer panic**
  tại `sendToPostProcessor` (`main.go:693`) → `PlaceOrder` (`main.go:447`). Pod CrashLoopBackOff.
  → **`CreateKafkaProducer` (sarama→MSK) fail lúc startup → producer = nil → panic.** Checkout outage.
- **~22:29** — `kubectl argo rollouts abort` + `undo` **KHÔNG cứu được**: promote 100% khiến revision
  MSK trở thành **stable**, không còn revision cũ để abort về; Rollout dùng `workloadRef` nên undo
  không revert được template (ArgoCD sở hữu template Deployment).
- **22:32 (revert commit) / 22:33 (merge #265)** — Revert #262 (PR #265 khẩn) → ArgoCD sync → checkout
  Deployment template về `KAFKA_ADDR=kafka:9092` (Kafka cũ, known good).
- **~22:40** — `promote --full` rollout về old-kafka → checkout 2 pod old-kafka Running, hết panic,
  Kafka cũ offset tăng lại (ghi đơn bình thường), LAG=0. **Khôi phục hoàn tất.**

**Cửa sổ outage: ~22:26 → ~22:40 (+07) ≈ 14 phút.**

---

## What — Chuyện gì đã xảy ra

Bước cuối của Mandate #8 là cutover Kafka→MSK, làm **producer trước** (checkout) rồi consumer sau
(accounting/fraud), theo runbook. Khi đổi env checkout sang MSK và đẩy toàn bộ pod sang MSK (100%),
`checkout` **không tạo được Kafka producer** (sarama→MSK fail lúc khởi động). Do code checkout
**không fail-fast**, pod vẫn "Ready" nhưng mỗi `PlaceOrder` gọi vào producer `nil` → **panic** →
process crash → CrashLoopBackOff → checkout ngừng phục vụ đặt hàng.

---

## Why — Nguyên nhân gốc (2 tầng)

**Tầng 1 — Nguyên nhân trực tiếp (chưa xác định chính xác):**
`sarama.NewSyncProducer(brokers, config)` với TLS + SASL/SCRAM-SHA-512 tới MSK **trả về lỗi lúc
startup** → `CreateKafkaProducer` trả `nil`. Log lỗi cụ thể **không capture được** (pod crash bị
rollback xoá trước khi đọc). Các giả thuyết cần kiểm chứng (theo thứ tự khả năng):
- **Idempotent producer**: code bật `Producer.Idempotent = true`. Idempotent producer cần gọi
  `InitProducerId` + có thể cần quyền `IdempotentWrite` cấp cluster. Probe dùng console-producer
  **không idempotent** → không chứng minh được đường idempotent. ← nghi ngờ hàng đầu.
- **SCRAM client**: `XDGSCRAMClient` tự implement (xdg-go/scram) — có thể lệch so với server.
- **TLS**: code chỉ set `tls.Config{MinVersion: TLS12}`, không set RootCAs (dựa CA hệ thống). Image
  `distroless/static-debian12` CÓ sẵn ca-certificates nên **ít khả năng** là TLS-CA, nhưng chưa loại trừ.
- **Protocol version** sarama (`config.Version`) lệch với MSK 3.9.x.

**Tầng 2 — Nguyên nhân khiến lỗi config biến thành OUTAGE (nghiêm trọng hơn, và là bài học chính):**
`checkout/main.go` khi `CreateKafkaProducer` lỗi chỉ `logger.Error(err)` **rồi chạy tiếp** —
**KHÔNG fail-fast**. Pod vẫn khởi động gRPC server, readiness (gRPC :8080) **không** kiểm tra producer
→ pod thành **Ready** dù producer = nil. Đến `PlaceOrder`, `cs.KafkaProducerClient.SendMessage()` gọi
trên nil → **panic** (không có recovery interceptor) → crash process.

→ Nếu checkout **fail-fast** (crash startup hoặc fail readiness khi producer lỗi mà `KAFKA_ADDR` set),
thì pod MSK-env sẽ **không bao giờ Ready** → `maxUnavailable:0` giữ pod cũ → **rollout đứng khựng an
toàn, KHÔNG outage**. Đây là điểm đáng lẽ phải audit + sửa TRƯỚC khi cutover.

**Nguyên nhân phụ trợ — vì sao không phát hiện sớm ở weight thấp:**
- **gRPC connection pinning**: canary Argo Rollouts không có traffic router (L7) → traffic chia theo
  connection (L4/kube-proxy). Frontend giữ kết nối gRPC lâu dài với pod stable → canary gần như
  không nhận `PlaceOrder` → không produce vào MSK → **canary không test được đường client**. Kết hợp
  với việc checkout nuốt lỗi produce (`SendMessage` err chỉ log, không return — xem cả postmortem
  0003 kafka-producer-latency), canary SLO-gate `checkout-slo` **không bắt được** lỗi produce.
- **Probe chỉ validate server-side**: probe dùng kafka-console-producer chứng minh MSK + SCRAM user
  có quyền produce/consume — nhưng **không** chứng minh client sarama của checkout (idempotent, TLS,
  SCRAM impl) hoạt động. Chính đường client này fail.

---

## Impact — Ảnh hưởng

- **Khách hàng:** trong ~14 phút, `PlaceOrder` fail (checkout crash) → không hoàn tất đặt hàng được.
  Browse/cart/các service khác bình thường.
- **Dữ liệu (mất, bounded):** `PlaceOrder` charge payment (mock, không tiền thật) + ship **trước** khi
  publish Kafka (thứ tự trong code); panic xảy ra ở bước publish → đơn trong cửa sổ bị **charge-mock +
  ship nhưng KHÔNG ghi vào `accounting`**, khách thấy lỗi. Vì không vào Kafka nào → **không recover
  từ Kafka được**. Số lượng giới hạn trong cửa sổ outage.
- **Migration khác:** Valkey→ElastiCache ✅ và Postgres→RDS ✅ **không ảnh hưởng** (checkout đọc/ghi
  cart & order-stream tách biệt; sự cố chỉ ở đường Kafka của checkout).

---

## Detection & Response — Phát hiện & xử lý

- **Phát hiện:** theo dõi chủ động **MSK `orders` offset** (không dựa vào checkout success-rate vì
  checkout nuốt/không surface lỗi produce). Offset = 0 sau khi promote 100% + log panic → xác định
  ngay là produce fail.
- **Xử lý:** abort/undo không hiệu quả (workloadRef + promote-100%-thành-stable) → revert #262 qua PR
  khẩn #265 → ArgoCD sync → `promote --full` về old-kafka (known good) → phục hồi ~14 phút sau khi
  outage bắt đầu.

---

## Điều làm ĐÚNG / SAI

**Đúng:**
- Pre-flight kỹ (MSK/SCRAM/topic/probe) → loại trừ được nhóm lỗi server-side + hạ tầng.
- Chọn tín hiệu đúng để giám sát (**MSK offset**, không phải checkout success-rate) → phát hiện lỗi
  ngay dù checkout không surface.
- Giữ Kafka cũ chạy (đường lui) → revert được về known-good nhanh.
- Scale Deployment=0 để cutover qua Rollout (ý định đúng, dù canary vô hiệu vì gRPC).

**Sai / thiếu:**
- **Không audit fail-fast của checkout trước cutover** — đây là lỗi chính khiến config-error thành
  outage.
- Tin rằng canary SLO-gate sẽ bảo vệ, trong khi gRPC pinning + nuốt-lỗi-produce làm nó vô hiệu.
- Không capture log lỗi sarama trước khi rollback (mất bằng chứng root-cause trực tiếp).

---

## Action items — TRƯỚC khi thử lại Kafka→MSK

1. ✅ **[Chẩn đoán — XONG]** Đã dựng pod `checkout` MSK-env **cô lập** (image có stderr logging) →
   log lộ đúng lỗi `too many colons in address`. Root cause xác định (xem block CẬP NHẬT ở đầu file).
2. ✅ **[Fix code — XONG, PR #269] Fail-fast:** `KAFKA_ADDR` set mà `CreateKafkaProducer` lỗi →
   `os.Exit(1)` trước khi mở gRPC server → pod không bao giờ Ready → rollout đứng an toàn, không outage.
   Kèm **stderr logging** (đọc lỗi Kafka qua `kubectl logs`) + **nil-guard** trong `sendToPostProcessor`.
3. 🟡 **[Fix code — một phần] Không nuốt lỗi produce:** đã tee lỗi `SendMessage` ra stderr (PR #269)
   để hiện trong `kubectl logs` khi cutover. **Chưa** đổi ngữ nghĩa `PlaceOrder` để fail RPC khi produce
   lỗi (mở rộng scope + rủi ro) → bù bằng **giám sát MSK offset tăng** làm cổng cutover. Còn mở.
4. ✅ **[Root cause sarama — XONG, PR #271] Không phải ACL/SCRAM/TLS/version:** bug thật là truyền cả
   chuỗi CSV broker vào 1 phần tử slice. Fix = `strings.Split(KAFKA_ADDR, ",")`. Đã verify pod cô lập:
   SASL + TLS + idempotent `InitProducerId` (ProducerId 8130) đều OK.
5. **[Quy trình]** Với service gRPC + Argo Rollouts: canary **không** validate được đường client ở
   weight thấp (connection pinning). Cần chiến lược khác: test đường client bằng pod cô lập trước (đã
   đưa vào runbook §6.0), và xem việc chuyển producer như thao tác "tất-cả-hoặc-không" có giám sát MSK
   offset + rollback nhanh.
6. ✅ **[Rebuild — XONG]** Image checkout có cả 3 fix đã build+scan+sign (`efb7eff…`, PR bump #272).
   Retry producer cutover chỉ tiến hành **sau** khi merge #272 (prod có binary fixed trên old-kafka).

---

## Trạng thái Mandate #8 sau sự cố

- 🟢 Valkey → ElastiCache — XONG (không ảnh hưởng).
- 🟢 Postgres → RDS — XONG (không ảnh hưởng).
- 🔴 Kafka → MSK — **BLOCKED**. MSK + topic `orders` còn nguyên (offset 0, chưa dùng). checkout/
  accounting/fraud vẫn trên Kafka cũ. Chờ fix code checkout (action items) trước khi thử lại.

---

## Liên quan

- Postmortem 0003 (`checkout-kafka-producer-latency`) — cùng service, lịch sử nuốt/không-surface lỗi produce.
- Postmortem 0007 (`kafka-recreate-rollout-order-event-loss`) — mất order-event khi Kafka thay đổi.
- Runbook `docs/runbooks/mandate-08-managed-cutover.md` §6 (Kafka cutover) — cần bổ sung bước fail-fast + chẩn đoán client trước.
- ADR `docs/adr/0009-mandate-08-managed-migration-cdo02.md`.
