# Postmortem 0012 — Batch NetworkPolicy Mandate #5 chặn egress managed datastore → checkout + 3 service outage (20/07/2026)

**Ngày:** 20/07/2026 (viết ngay sau khắc phục)
**Người xử lý:** CDO02 (Huu Tai Ngo) — phát hiện & khắc phục trong lúc chạy Mandate #8 bước 3 (Kafka→MSK)
**Nguồn gốc thay đổi:** CDO01 — Mandate #5 (network isolation / security hardening)
**Mức độ ảnh hưởng:** **CÓ ảnh hưởng khách hàng.** `checkout` down ~30 phút (0 pod Ready → PlaceOrder fail);
`product-catalog` / `product-reviews` / `recommendation` down; `cart` hỏng ngầm (không đọc được ElastiCache
nhưng vẫn "Ready"). Browse một phần suy giảm. **Không mất dữ liệu** (đơn không tạo được thì không có gì để mất;
đơn đã có trong RDS/MSK không ảnh hưởng).
**Trạng thái:** ✅ Đã khắc phục — rollback toàn bộ batch policy Mandate #5, cụm Ready trở lại, Mandate #8 hoàn tất.

---

## TL;DR

CDO01 apply tay (kubectl, IAM `cdo-admin-team`) một **batch 20 NetworkPolicy** lúc `14:55:20Z` cho hầu hết
service trong `techx-tf3`. Batch này **chặn egress ra các managed datastore** vì chỉ cho `podSelector` tới
store CŨ in-cluster (postgresql/valkey-cart/kafka pod), **thiếu `ipBlock`** cho RDS/ElastiCache/MSK (đã migrate
ở Mandate #8). Ngoài ra, egress kiểu `podSelector` tới **ClusterIP Service** không được **AWS VPC CNI network
policy** permit → mọi lời gọi service-to-service của các pod có policy bị drop **dù rule đã "allow"**. Hậu quả:
`product-catalog`→RDS, `cart`→ElastiCache, checkout→các dep... đều đứt → outage dây chuyền. Trùng thời điểm
CDO02 đang cutover Kafka producer (PR #276) nên ban đầu **nghi nhầm là do cutover**. Khắc phục: rollback cả
batch (đã backup) → cụm phục hồi → promote nốt cutover MSK.

---

## When — Timeline (UTC)

- **14:55:20Z** — CDO01 (IAM `cdo-admin-team`) `kubectl apply` batch 20 NetworkPolicy Mandate #5 (xác định qua
  EKS audit log: `verb=create ... user=arn:aws:iam::197826770971:user/cdo-admin-team`). VPC CNI
  `eks:network-policy-controller` bắt đầu enforce.
- **~14:58Z** — checkout readiness bắt đầu fail liên tục (`NOT_SERVING`) — pod không đọc được dependency.
  (Trùng lúc CDO02 merge PR #276 cutover producer Kafka→MSK → gây nhiễu chẩn đoán ban đầu.)
- **~15:0x–15:1xZ** — CDO02 giám sát cutover, thấy checkout 0 pod Ready + pod mới kẹt `Init:0/1 wait-for-kafka`
  (`nc kafka:9092` timeout). Ban đầu nghi node event/CNI mới; sau loại trừ dần: pod env-CŨ `s498n` (KAFKA_ADDR=
  kafka:9092, không phải cutover) cũng `NOT_SERVING` → **chứng minh outage KHÔNG do cutover MSK**.
- **~15:1xZ** — Phát hiện `checkout-network-policy` (tuổi 8m) + cả batch 29m. Đọc egress: **thiếu product-catalog +
  MSK**. Patch thêm rule → **vẫn không cứu** (VPC CNI không permit podSelector-egress-tới-ClusterIP).
- Truy EKS audit log → xác định IAM `cdo-admin-team` + giờ apply. Discriminator: `accounting` (KHÔNG có policy)
  khỏe, chỉ pod CÓ policy chết → khẳng định policy là thủ phạm.
- **Xoá `checkout-network-policy`** (kubectl tay, không GitOps → xoá dính). Init qua được (`nc kafka` thông),
  canary MSK nối được MSK (SASL/InitProducerId OK) — nhưng checkout vẫn `NOT_SERVING`.
- Đào tiếp: `product-catalog` down vì `product-catalog-network-policy` egress 5432 chỉ cho `podSelector: postgresql`
  (pod CŨ), **không có ipBlock RDS** → product-catalog không ra RDS. Xoá policy product-catalog/product-reviews/
  recommendation → 3 service Ready lại, nhưng **checkout vẫn down**.
- netcheck pod (danh tính checkout) xác nhận **TCP tới cart/currency/product-catalog/kafka đều OK** → không phải
  block L3/L4 còn lại. Đào ra: `cart` "Ready" nhưng `cart-network-policy` egress 6379 chỉ cho `podSelector:
  valkey-cart` (CŨ), **không có ipBlock ElastiCache** → cart không đọc ElastiCache → `cart.GetCart` lỗi →
  checkout health (gọi cart) fail → `NOT_SERVING`. **cart hỏng ngầm dù Ready.**
- **Quyết định rollback CẢ batch** (whack-a-mole không khả thi, nhiều service "Ready-nhưng-hỏng"). Backup toàn bộ
  policy → xoá 17 policy batch còn lại (đã xoá 3 trước đó = 20 tổng). Giữ policy pre-existing (grafana/kafka/
  postgres/valkey/…, 4–7 ngày tuổi, không thuộc Mandate #5).
- **Cụm Ready trở lại** — checkout 3/3 Ready (cart→ElastiCache thông → GetCart OK). Promote nốt rollout MSK →
  **cutover producer hoàn tất** (MSK offset tăng). Consumer cutover (PR #278) sau đó → Mandate #8 xong.

**Cửa sổ outage checkout: ~14:58Z → khi rollback batch hoàn tất ≈ 30 phút.**

---

## Why — Nguyên nhân gốc

**Batch NetworkPolicy Mandate #5 hỏng hệ thống, 2 khiếm khuyết cộng hưởng:**

1. **Không đồng bộ với Mandate #8 (managed datastore).** Policy viết cho topology CŨ: egress tới datastore chỉ
   khai `podSelector` store in-cluster (`postgresql`/`valkey-cart`/`kafka` pod). Nhưng sau Mandate #8, service nối
   **managed endpoint EXTERNAL** (RDS/ElastiCache/MSK — IP trong VPC, cần `ipBlock`). Egress ra managed store bị
   drop → product-catalog→RDS, cart→ElastiCache, product-reviews→RDS đứt.

2. **`podSelector` egress tới ClusterIP không tương thích AWS VPC CNI network policy.** Lời gọi service-to-service
   đi qua ClusterIP Service; VPC CNI enforcement không permit egress `podSelector` cho đích ClusterIP → traffic bị
   drop **dù rule "allow"**. Vì vậy patch thêm rule (product-catalog/MSK) **không cứu được** — phải gỡ policy.

**Nguyên nhân khuếch đại:**
- **Áp dụng tay, hàng loạt, không qua GitOps/review/canary** giữa giờ, không phối hợp CDO02 (đang cutover). Không
  có bước "1 service thử trước" → 20 policy sai cùng lúc.
- **Readiness nông** ở vài service (vd cart) → hỏng ngầm mà vẫn "Ready", khó thấy blast radius thật.
- **Trùng thời điểm cutover Kafka của CDO02** → nhiễu chẩn đoán (mất thời gian loại trừ cutover trước khi tìm ra policy).

---

## Impact

- **Khách hàng:** ~30 phút không đặt được hàng (checkout 0 pod Ready). product-catalog/product-reviews/
  recommendation down → browse/gợi ý suy giảm.
- **Dữ liệu:** **không mất.** Đơn không tạo được thì không phát sinh; dữ liệu trong RDS/ElastiCache/MSK không bị đụng.
- **Cutover Mandate #8:** bị chậm ~30 phút nhưng **không hỏng** — producer MSK của checkout thực ra nối MSK thành
  công (đã verify); chỉ bị policy chặn dep khiến checkout không Ready. Sau rollback, cutover hoàn tất bình thường.

---

## Detection & Response — Điều làm ĐÚNG / SAI

**Đúng:**
- Loại trừ nhân-quả bằng chứng cứ cứng: pod env-CŨ cũng chết → không phải cutover; `accounting` (không policy) khỏe
  → policy là biến khác biệt; netcheck pod danh tính-checkout → tách L3/L4 khỏi lỗi ứng dụng.
- Dùng **EKS audit log** truy đúng IAM + giờ apply → biết nguồn thay đổi.
- **Backup toàn bộ policy trước khi xoá** → CDO01 dựng lại được (artifact kèm postmortem).
- Rollback cả batch thay vì whack-a-mole khi thấy lỗi hệ thống + service "Ready-nhưng-hỏng".

**Sai / thiếu:**
- (CDO01) Apply batch security tay, hàng loạt, không GitOps/canary, không phối hợp team đang thao tác live.
- (CDO01) Policy không cập nhật theo Mandate #8 + không test trên VPC CNI (podSelector→ClusterIP / thiếu ipBlock).
- (Chung) Thiếu kênh thông báo "đang có thay đổi hạ tầng lớn" giữa CDO01/CDO02 → hai thao tác live chồng nhau.

---

## Action items

1. **[CDO01 — bắt buộc trước khi re-apply]** Viết lại policy Mandate #5: egress ra datastore dùng **`ipBlock`**
   (RDS `…:5432` / ElastiCache `…:6379` / MSK `…:9096` theo CIDR VPC/subnet), **không** `podSelector` store cũ.
   Kiểm chứng egress `podSelector`→ClusterIP trên **AWS VPC CNI network policy** (nhiều khả năng phải dùng ipBlock
   cho service CIDR, hoặc bật đúng chế độ). **Thử 1 service, verify, rồi mới nhân rộng.** Backup ở
   [`artifacts/0012-mandate5-networkpolicies/`](artifacts/0012-mandate5-networkpolicies/).
2. **[CDO01/CDO02] Đưa network policy vào GitOps** (ArgoCD-managed) thay vì kubectl tay → có review + rollback +
   không "mồ côi" khỏi git.
3. **[Chung] Quy ước phối hợp:** thông báo trước khi apply thay đổi hạ tầng diện rộng; không chồng 2 thao tác live
   diện rộng cùng lúc (freeze window).
4. **[CDO02] Readiness sâu hơn cho service có datastore** (vd cart phản ánh được ElastiCache) để "hỏng ngầm" hiện
   ra ở readiness thay vì chỉ lộ khi caller fail.
5. **[Cân nhắc] initContainer `wait-for-kafka`** của checkout hardcode `nc kafka:9092` (kafka CŨ) — sẽ chặn pod khởi
   động nếu kafka cũ không reachable, kể cả khi đã cutover MSK. Nên trỏ theo `KAFKA_ADDR` hoặc bỏ khi retire kafka cũ.

---

## Liên quan

- Postmortem [0010](0010-mandate-08-kafka-producer-cutover-checkout-outage.md) — cutover Kafka producer (cùng Mandate #8).
- Runbook [`mandate-08-managed-cutover.md`](../runbooks/mandate-08-managed-cutover.md) — §6 Kafka cutover.
- ADR [`0009`](../adr/0009-mandate-08-managed-migration-cdo02.md) — managed migration.
- Artifact backup policy: [`artifacts/0012-mandate5-networkpolicies/`](artifacts/0012-mandate5-networkpolicies/).
