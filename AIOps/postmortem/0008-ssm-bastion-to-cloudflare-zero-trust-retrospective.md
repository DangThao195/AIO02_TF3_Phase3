# Postmortem 0008 — Retrospective: chuyển truy cập ops từ SSM bastion sang Cloudflare Zero Trust (REL-17)

> **Ghi chú thể loại:** đây **không phải** postmortem sự cố (không có outage khách hàng). Đây là
> **retrospective / decision record** cho một thay đổi hạ tầng truy cập, viết theo cùng bộ khung
> để lưu cùng chuỗi postmortem — mô tả *vì sao đổi*, *ưu/nhược*, *đánh đổi*, *rủi ro còn lại*, và
> *chuỗi sự cố nhỏ trong lúc triển khai* (5 bug liên tiếp — phần có tính "postmortem" thật sự).

**Ngày:** 14–15/07/2026 (triển khai), viết 17/07/2026
**Người thực hiện & ghi nhận (ký):** CDO02 (Reliability + Cost Optimization)
**Backlog:** REL-17
**Trạng thái:** ✅ Live, ổn định. SSM bastion **giữ nguyên** làm đường break-glass (không gỡ).

---

## 1. Bối cảnh — vì sao cần đổi

Sau **Mandate #1** (network exposure), TF3 đã đóng toàn bộ cổng ops khỏi internet: EKS API
**private-only**, các UI vận hành (Grafana, Jaeger, ArgoCD) không còn route public qua Envoy/
CloudFront (CloudFront trả `403` cho `/grafana`, `/jaeger`...). Đúng về bảo mật, nhưng để lại
**một đường truy cập ops duy nhất: SSM bastion port-forward**, và đường đó tạo ma sát lớn:

- **Tunnel tự đứt** sau ~10–20 phút idle → phải mở lại liên tục giữa lúc đang điều tra sự cố.
- **Mỗi người cần IAM user + biết `kubectl` + biết mở SSM session** → thành viên không làm
  platform (AIE, người viết báo cáo, mentor) gần như không tự xem được Grafana.
- **Không có UI-level access** — phải port-forward từng Service, nhớ port, gõ lệnh.
- Không scale cho việc **mentor/BTC muốn tự xem** observability trong buổi review.

Vấn đề cần giải, phát biểu trung lập: *"secure remote access tới ops UI của một cluster
private, cho một nhóm người không đồng đều về kỹ năng hạ tầng, không được mở lại bề mặt tấn
công, và trong ngân sách."*

## 2. Thay đổi đã làm

Triển khai **Cloudflare Zero Trust** (Tunnel + Access) song song với SSM bastion:

- `cloudflared` chạy như **Deployment trong cluster**, **dial OUT** tới edge Cloudflare (không
  mở inbound port nào — giữ đúng posture 0-inbound của bastion).
- Hostname riêng cho từng UI: `grafana.arthur-ngo.org`, `jaeger.arthur-ngo.org/jaeger/ui/`,
  `argocd.arthur-ngo.org`, và `kubectl.arthur-ngo.org` (cho kubectl — vẫn cần IAM).
- **Cloudflare Access** bắt **SSO (Google) + MFA trước** khi cho vào tunnel; allowlist theo
  email, áp cho **cả** app kubectl lẫn **mọi** route UI (`modules/cloudflare-access`).
- Terraform-managed: module `cloudflare-access` + biến trong `production.auto.tfvars`.

**Nguyên tắc giữ lại:** SSM bastion (`module access`) **không bị gỡ** — đóng vai break-glass
đến khi đường mới được kiểm chứng ổn định trong vận hành hằng ngày (ghi rõ trong comment module).

## 3. Vì sao chọn Cloudflare — so với các lựa chọn khác

Bốn tiêu chí quyết định: **(a) không mở inbound**, **(b) identity-aware trước khi chạm service**,
**(c) zero-client cho người dùng**, **(d) chi phí thấp**. Cloudflare thỏa cả bốn; mỗi lựa chọn
khác thiếu ít nhất một.

| Lựa chọn | Đánh giá | Vì sao loại |
|---|---|---|
| **Giữ SSM bastion** (status quo) | 0-inbound, IAM-based | Tunnel tự đứt, cần IAM+kubectl mỗi người, không UI — chính ma sát cần xóa |
| **Public LB + IP allowlist** | Đơn giản | **Mở inbound** (bề mặt tấn công); allowlist vỡ khi đổi mạng/WFH; **không có identity layer** |
| **AWS ALB + Cognito/OIDC** | AWS-native | Vẫn cần **ALB public** (mở inbound); phải dựng+quản Cognito user pool; nhiều Terraform hơn cho cùng kết quả |
| **AWS Client VPN** | AWS-native, mã hoá | **Tốn tiền liên tục** (~$0.05/h endpoint + $0.05/h/connection); cần **cài VPN client**; là **network-level** access ("vào mạng rồi tin") — không phải zero-trust thật |
| **Tailscale / WireGuard ZTNA** | Zero-trust tốt | Cần **cài client** trên mọi máy; đội đã có tài khoản Cloudflare (DNS) → Cloudflare thêm ít bộ phận chuyển động hơn |
| **Self-host Teleport / Pomerium / oauth2-proxy** | Zero-trust, kiểm soát cao | **Tự dựng = thêm một component phải vận hành + một SPOF mới** — đúng loại độ phức tạp đã tránh ở vụ PgBouncer |
| **✅ Cloudflare Zero Trust** | | Thỏa cả 4 tiêu chí; free tier tới 50 user; tunnel outbound giữ 0-inbound |

**Một câu chốt:** Cloudflare cho **identity-aware + không-mở-inbound + zero-client + $0** cùng lúc;
mỗi lựa chọn khác thiếu ít nhất một trong bốn — hoặc mở inbound, hoặc tốn tiền, hoặc phải cài
client, hoặc tự dựng thêm một thứ để hỏng.

## 4. Ưu điểm (đã đạt)

1. **Giữ posture 0-inbound.** `cloudflared` gọi ra ngoài; không LB public, không đổi security
   group, không mở port. Attacker quét IP không thấy gì để tấn công.
2. **Zero Trust thật — identity trước, không phải mạng trước.** Cloudflare Access ép SSO+MFA
   trước tunnel; quyền scope **per-application** thay vì IAM cả cluster. Tin danh tính đã xác
   thực, không tin vị trí mạng.
3. **Zero-client, UX cho cả người không rành hạ tầng.** Chỉ cần trình duyệt + đăng nhập Google →
   1 link vào Grafana/Jaeger/ArgoCD. Mở đường cho mentor/BTC tự xem observability (PR #174, #233).
4. **Tách bạch UI khỏi IAM.** Route UI đi **thẳng tới Service in-cluster** — không đụng EKS API,
   không IAM trong đường đó. Thêm email cho ai đó = cho xem UI, **không** cấp quyền cluster
   (kubectl vẫn cần IAM riêng). Least-privilege đúng nghĩa.
5. **Chi phí $0** ở quy mô đội (free tier ≤50 user) — trong khi Client VPN tốn tiền liên tục,
   Cognito/ALB tốn công dựng.
6. **Không tự đứt như SSM tunnel** — session_duration cấu hình được, không cần mở lại giữa chừng.
7. **IaC + auditable.** Toàn bộ qua Terraform module + tfvars + PR review; đổi allowlist là 1
   dòng, có lịch sử ai thêm ai lúc nào.

## 5. Nhược điểm & rủi ro còn lại (nói thẳng, không giấu)

1. **Thêm một trust anchor / SaaS bên thứ ba.** Cloudflare giờ nằm trên đường truy cập ops.
   Cloudflare down, hoặc account/token Cloudflare bị chiếm → mất đường ops (hoặc tệ hơn, kẻ lạ
   vào được). **Giảm thiểu:** (a) chỉ là **ops plane**, không phải đường khách vào sản phẩm
   (khách đi CloudFront riêng — Cloudflare không nằm trên luồng ra tiền); (b) **giữ SSM bastion
   làm break-glass** — Cloudflare hỏng vẫn còn đường IAM vào cluster. Không bỏ hết trứng một giỏ.
2. **Domain cá nhân `arthur-ngo.org`.** Đang tạm dùng domain cá nhân để làm nhanh — **nợ kỹ thuật
   đã ghi nhận**; production thật phải là domain tổ chức. Cùng nhóm với việc **Cloudflare API token
   cần rotate sau bài tập** (ghi trong CLAUDE.md mục rủi ro, file token trong Downloads cần xoá).
3. **Phụ thuộc Google SSO cho danh tính.** Google down = không đăng nhập được. Chấp nhận được cho
   ops plane; break-glass SSM không phụ thuộc Google.
4. **NetworkPolicy phải nuôi thêm.** Mỗi UI mở cho cloudflared cần rule NetworkPolicy đúng
   (đã dính bug — mục 6); thêm UI mới là thêm một rule phải nhớ.
5. **Chưa gỡ được bastion → đang chạy 2 đường song song.** Đúng về an toàn (break-glass) nhưng
   là 2 bề mặt phải bảo trì/audit. Quyết định có ý thức: chưa gỡ đến khi đường mới đủ chín.

## 6. Chuỗi 5 sự cố khi triển khai (phần "postmortem" thật — bài học debug theo tầng)

Triển khai hỏng 5 lần liên tiếp, **mỗi lần một tầng khác nhau**, lỗi tầng trước **che** lỗi tầng
sau (phải sửa xong mới lộ cái kế). Đây là giá trị học thuật lớn nhất của đợt này:

| # | Triệu chứng | Nguyên nhân | Tầng | PR |
|---|---|---|---|---|
| 1 | `ImagePullBackOff` | Tag image cloudflared sai + thiếu securityContext (Kyverno) | Image | #100 |
| 2 | `CrashLoopBackOff` | Liveness probe trỏ endpoint `/metrics` nhưng quên cờ `--metrics` → endpoint không tồn tại → probe fail → **pod khỏe bị chính probe giết** | Probe | #104 |
| 3 | Grafana `502` | NetworkPolicy Grafana deny-all, cloudflared không nằm trong allowlist | Network | #106 |
| 4 | Vẫn `502` | Allow đúng nguồn nhưng **sai port**: ghi `80` (Service) trong khi NetworkPolicy soi ở **pod port `3000`** (áp sau DNAT) | Network (sâu) | #108 |
| 5 | Redirect về `localhost:3000` | Grafana `root_url` mặc định → tự dựng link redirect về địa chỉ nội bộ | App config | #109 |

Bổ trợ: fix `values.schema.json` cho `imageOverride.digest` cứu ArgoCD `ComparisonError` (#99);
follow-up mở NetworkPolicy Jaeger UI cho cloudflared (#156).

**Bài học phương pháp:** debug theo **thứ tự đường đi request** — image tải được → pod sống →
mạng thông → app cấu hình đúng. Mỗi tầng một PR riêng để audit được. "Probe cấu hình sai còn tệ
hơn không có probe" (bug #2) và "NetworkPolicy dùng **container port**, không phải Service port"
(bug #4) là hai điểm dễ vấp nhất.

## 7. Đánh đổi đã cân (tóm tắt)

- **SaaS dependency vs UX/bảo mật:** chấp nhận thêm Cloudflare làm trust anchor để đổi lấy
  zero-client + identity-aware + 0-inbound; giảm thiểu bằng break-glass SSM + Cloudflare không
  nằm trên luồng khách.
- **2 đường song song vs đơn giản:** giữ bastion (thêm bề mặt audit) để đổi lấy đường thoát khi
  Cloudflare sự cố — không gỡ vội.
- **Domain cá nhân vs làm nhanh:** chấp nhận nợ kỹ thuật (domain + token rotate) để có đường ops
  dùng được ngay trong tuần; đã ghi rõ để trả nợ sau.
- **Cloudflare vs AWS-native:** bỏ tính "một nhà cung cấp" để lấy giải pháp rẻ hơn + bảo mật hơn
  (AWS-native vẫn phải mở inbound hoặc tốn tiền). Chọn công cụ đúng việc, ghi rõ trade-off.

## 8. Việc còn mở / khuyến nghị

1. **Quyết định số phận bastion:** giữ break-glass hay gỡ — sau khi đường Cloudflare đủ chín, ra
   quyết định có ký (ADR) thay vì để lửng.
2. **Nâng REL-17 thành ADR có ký** — quyết định này đủ lớn (trust anchor mới + đổi mô hình access)
   để xứng một ADR chính thức, không chỉ retrospective này.

## 9. Bằng chứng (PR)

- REL-17 core: backlog #93, feat #96.
- Chuỗi debug triển khai: #99, #100, #103, #104, #106, #108, #109.
- Follow-up: #156 (NetworkPolicy Jaeger UI), #174 (thêm email SSO), #233 (thêm 4 email mentor).
- Runbook vận hành: [`docs/runbooks/cloudflare-zero-trust-access.md`](../runbooks/cloudflare-zero-trust-access.md).
- Terraform: `infra/modules/cloudflare-access/`, `infra/live/production/production.auto.tfvars`.

---

*Ký: CDO02. Liên quan: Mandate #1 (đóng ops public — tiền đề), backlog REL-17,
runbook cloudflare-zero-trust-access, CLAUDE.md (mục rủi ro: token rotate, domain cá nhân).*
