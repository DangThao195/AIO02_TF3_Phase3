# TF3 — Phase 3: TechX Corp Service Takeover

Đây là repo vận hành chung của **TF3** (AIO02, CDO01, CDO02) cho Phase 3 của chương trình.
File này được Claude Code tự động đọc ở đầu mỗi phiên làm việc trong thư mục này — mục đích
là để **không phải giải thích lại bối cảnh dự án từ đầu mỗi lần mở chat mới**. Giữ file này
cập nhật; nó có giá trị bằng đúng mức nó phản ánh đúng thực tế hiện tại.

## Bối cảnh (không đổi trong suốt 3 tuần)

Phase 3 không phát brief. TF3 tiếp quản một storefront thương mại điện tử microservice
đang "sống" (TechX Corp), phải tự đánh giá, tự ưu tiên, vận hành dưới ràng buộc thật
(ngân sách, SLO, sự cố do BTC bơm vào), và bảo vệ mọi quyết định bằng ADR/postmortem ký tên.
Chi tiết đầy đủ: [`phase3 - information/RULES.md`](phase3%20-%20information/RULES.md).

**Đọc trước khi làm bất cứ việc gì kỹ thuật trong repo này:**
- [`phase3 - information/RULES.md`](phase3%20-%20information/RULES.md) — luật chơi, đặc biệt mục Luật chơi (điều khoản disqualify)
- [`phase3 - information/onboarding/ARCHITECTURE.md`](phase3%20-%20information/onboarding/ARCHITECTURE.md)
- [`phase3 - information/onboarding/SLO.md`](phase3%20-%20information/onboarding/SLO.md)
- [`phase3 - information/onboarding/BUDGET.md`](phase3%20-%20information/onboarding/BUDGET.md)
- [`phase3 - information/onboarding/INCIDENT_HISTORY.md`](phase3%20-%20information/onboarding/INCIDENT_HISTORY.md)

## Luật cấm tuyệt đối — disqualify nếu vi phạm

- **Không** gỡ, đổi hướng, hay refactor để service ngừng đọc flag từ `flagd` — đây là cách
  BTC bơm sự cố. Xử lý sự cố bằng fallback/retry/containment, không phải tắt cơ chế.
- **Không** đổi TOKEN/URI trong `values-flagd-sync.yaml` sang nguồn khác, không bỏ nó ra
  khỏi lệnh `helm upgrade`.
- flagd sync token/AWS creds/LLM API key: **không bao giờ** commit giá trị thật vào file
  tracked. Xem quy tắc chi tiết ở [README.md](README.md#quy-tắc-khi-làm-việc-với-secret-thật-aws-creds-flagd-sync-token-llm-api-key).

## Cấu trúc TF3

| Nhóm | Vai trò | Trụ (cập nhật sau khi draft chính thức chốt) |
|---|---|---|
| AIO02 | Tầng AI: AIOps (vận hành bằng AI) + AIE (AI trong sản phẩm) | ngoài 4 trụ core |
| CDO01 | Platform/hạ tầng | *(điền sau khi confirm)* |
| CDO02 | Platform/hạ tầng | Reliability + Performance Efficiency *(dự định, cần xác nhận với CDO01 trong buổi draft)* |

Auditability là trụ chung, luân phiên theo tuần giữa CDO01/CDO02 — cập nhật ai cầm chính
tuần nào ở mục Trạng thái bên dưới.

## Trạng thái hiện tại

> Cập nhật mục này mỗi tuần (gợi ý: người cầm Auditability tuần đó chịu trách nhiệm cập nhật).

- **Baseline deploy**: ✅ Đã deploy 07/07 — VPC + EKS (`techx-corp-tf3`, `ap-southeast-1`) dựng bằng
  Terraform (`infra/`), image build/push bởi CDO01 lên ECR `techx-corp` (tag `d2bc367`), Helm
  release `techx-corp` trong namespace `techx-tf3`. 28/28 pod Running, storefront + AI review
  verify OK, flagd sync token đã kết nối nguồn trung tâm BTC.
  - Lưu ý triển khai: **không dùng** `values-observability.yaml` + `values-app-stamp.yaml` cùng lúc
    (2 file này dành cho 2 lần deploy tách namespace riêng — dùng chung sẽ tắt hết pod). Deploy
    baseline chỉ cần chart mặc định (đã tự bật cả app + observability) + `values-flagd-sync.yaml`.
- **Backlog ưu tiên**: *(chưa dựng / link file khi có)*
- **Hạ tầng**: Terraform state ở S3 `techx-corp-tf3-terraform-state` (lock: DynamoDB
  `techx-corp-tf3-terraform-lock`). `infra/terraform.tfvars` (gitignored, không commit) cần điền
  IP + IAM ARN của từng thành viên TF3 muốn `kubectl` — hiện chỉ có của arthur (CDO02).
- **CI/CD**: secret-scanning đã bật (gitleaks pre-commit hook + GitHub Actions gate trên
  `push`/`PR` vào `main`) — xem [README.md](README.md). Branch protection cho `main`
  (require PR + status check `gitleaks`) **đã đề xuất, cần bật thủ công trên GitHub**.
- **Mandates đang mở**: xem [`phase3 - information/mandates/`](phase3%20-%20information/mandates/) — trống lúc đầu, BTC thả vào khi có hiệu lực.

## Phát hiện kỹ thuật đã xác nhận qua đọc code (không phải suy đoán)

Đây là những điểm yếu cụ thể đã soi trực tiếp trong `techx-corp-chart/values.yaml` và code
service dưới `techx-corp-platform/src/`, dùng làm bằng chứng cho backlog Reliability/Performance:

- **`default.replicas: 1` áp dụng cho toàn bộ ~18 service**, không service nào override —
  mọi service là SPOF ở tầng pod, không riêng `cart` (khớp INC-2 trong lịch sử sự cố).
- **Không có `readinessProbe`/`livenessProbe` nào được cấu hình** cho bất kỳ component nào
  trong chart (khớp INC-3).
- **Không có `requests` (chỉ có `limits`, chỉ memory, không CPU)**; một số memory limit rất
  thấp (`checkout`, `product-catalog`, `currency`, `shipping`: 20Mi).
- **Health check giả trên toàn hệ thống**: `checkout`, `product-catalog`, `recommendation`,
  `currency`, `product-reviews`, `ad`, `payment` đều trả "SERVING" cố định, không kiểm tra
  dependency (DB/Kafka/Redis) thật. Thêm probe vô nghĩa cho tới khi sửa các hàm `Check()` này.
- **`product-catalog` (Go)**: mở DB qua `database/sql` nhưng không set
  `MaxOpenConns`/`MaxIdleConns` — mặc định unlimited, có thể làm cạn `max_connections` của
  Postgres khi tải cao (khớp INC-1, góc nhìn khác: thiếu trần phía client thay vì pool nhỏ).
- **`product-reviews` (Python)**: `psycopg2.connect()` mở mới cho **mỗi request**, không hề
  có connection pool — đây là service đứng sau tính năng AI chủ lực (tóm tắt review).
- **`checkout.PlaceOrder`**: charge thẻ (`chargeCard`) xảy ra **trước** khi gọi
  `shipOrder`; nếu `shipOrder` lỗi sau khi đã charge thành công, hàm trả lỗi ngay,
  **không có logic hoàn tiền/rollback** — khách bị trừ tiền nhưng đơn coi như thất bại.
- **Envoy (`frontend-proxy`) có filter `envoy.filters.http.fault`** cấu hình sẵn
  (delay injection qua header, `max_active_faults: 100`) — coi đây là hạ tầng nhạy cảm
  tương tự flagd, đừng gỡ khi tối ưu Envoy.
- 3 service dùng chung 1 Postgres instance (`product-catalog`, `product-reviews`,
  `accounting`), 1 Valkey instance (`cart`), 1 Kafka broker (`checkout` producer →
  `accounting` + `fraud-detection` consumer) — không có datastore nào có replica.

## Quy ước làm việc trong repo này

- Không push thẳng `main` — làm nhánh + PR (`gitleaks` status check phải xanh).
- Cài hook secret-scanning sau khi clone: `bash scripts/setup-hooks.sh`.
- ADR cho mọi quyết định hạ tầng lớn, postmortem ký tên sau mỗi sự cố — thư mục lưu:
  *(chưa tạo `docs/adr/` và `docs/postmortem/` — tạo khi bắt đầu có quyết định thật)*.

## Hướng dẫn cho Claude Code ở các phiên sau

- Luôn ưu tiên đọc file này trước, sau đó mới đọc sâu vào `phase3 - information/` nếu cần
  chi tiết luật/kiến trúc/SLO.
- Nếu người dùng nói "trụ của mình", "team mình", ngầm hiểu là CDO02 trừ khi họ nói khác.
- Khi thực hiện thay đổi hạ tầng thật (Helm, K8s, CI), luôn nhắc nhở về luật flagd/secret ở
  trên trước khi hành động — vi phạm là disqualify cho cả TF, không chỉ 1 nhóm.
- Cập nhật mục "Trạng thái hiện tại" mỗi khi có tiến triển lớn (deploy xong, backlog chốt,
  pillar draft chốt chính thức, mandate mới xuất hiện) — đừng để file này lạc hậu so với
  thực tế, vì đây là nguồn thông tin đầu tiên mọi phiên chat mới sẽ đọc.
