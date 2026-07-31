# PM-0016 — Báo cáo tổng hợp: Product Reviews lỗi dưới tải, đã fix gì / còn gì / phần liên quan AIO02

**Ngày:** 28/07/2026 · **Người tổng hợp:** CDO02 (qua Claude Code) · **Đối tượng đọc:** team CDO02 + AIO02

**Tài liệu gốc đầy đủ (kỹ thuật, log/số liệu chi tiết):**
[`docs/postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md`](postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md)

---

## Tóm tắt 1 dòng

Widget "Product Reviews" bị lỗi timeout dưới tải cao. Đã fix xong phần **lỗi hiển thị sai** (báo lỗi đúng
thay vì báo sai/im lặng) và **giảm bớt** rủi ro nghẽn tài nguyên. **Chưa fix xong phần gốc** — cả 2 nguyên
nhân sâu hơn (hạ tầng scale chậm + **AWS Bedrock tự giới hạn tốc độ**) đều chưa xử lý dứt điểm, cái thứ 2
thuộc phạm vi **AIO02**.

---

## 1. Chuyện gì đã xảy ra

Trong lúc chạy load test, gọi API lấy review sản phẩm bị lỗi `DEADLINE_EXCEEDED` (quá 500ms). Điều tra
thấy: HPA phát hiện tải tăng và tạo thêm pod `product-reviews`, nhưng pod mới mất **70-80 giây** để sẵn
sàng (chờ hạ tầng dựng node mới + tải image + khởi động app) — trong lúc đó 2 pod cũ phải gánh hết tải và
một số request bị timeout. Không có bằng chứng khách hàng thật bị ảnh hưởng (đây là traffic load test),
và không có bằng chứng storefront/checkout downtime.

Thêm 1 vấn đề kiến trúc phát hiện được: `product-reviews` dùng **chung 1 nhóm luồng xử lý** cho cả API đọc
review (nhanh) và API hỏi AI (chậm, gọi Bedrock) — nghĩa là nếu nhiều người hỏi AI cùng lúc, request đọc
review có thể bị "xếp hàng" phía sau.

---

## 2. Đã fix xong (đang chạy thật trên production, đã verify bằng tải thật)

| # | Đã fix | Chi tiết | Bằng chứng |
|---|---|---|---|
| 1 | **Lỗi hiển thị sai khi dependency timeout** | Trước: lỗi timeout bị code cũ nuốt mất, có nguy cơ hiển thị "chưa có review" (sai) trong khi thực ra dịch vụ đang lỗi. Giờ: phân loại đúng, trả `503` rõ ràng, widget hiển thị "không tải được" (đúng), không làm sập cả trang. | Test thật (server giả timeout) + xác nhận qua tải thật 500 user: log/Locust ghi nhận `503` đúng loại, không còn `500` mù. |
| 2 | **Giảm rủi ro AI chiếm hết tài nguyên xử lý** | Giới hạn tối đa 4 request AI chạy đồng thời trong nhóm luồng dùng chung — khi vượt, trả ngay "AI đang bận" thay vì giữ tài nguyên. | Log thật dưới tải 500 user cho thấy cơ chế này hoạt động đúng (hàng trăm lần shed tải thành công). **Lưu ý: đây là giảm thiệt hại, KHÔNG PHẢI cô lập triệt để** — xem mục 3. |
| 3 | Vá 2 lỗ hổng bảo mật HIGH (không liên quan sự cố này, chặn build) | `brace-expansion`, `postcss` — dependency cũ có CVE, đã bump version. | CI Trivy gate pass. |

PR liên quan: #531 (fix chính), #533 (CVE), #535/#538 (deploy image), #543/#545 (pre-scale tạm thời cho
load test, đã revert).

---

## 3. CHƯA fix — vẫn là nguyên nhân gốc

| # | Vấn đề | Vì sao chưa fix được | Ai xử lý |
|---|---|---|---|
| 1 | **Pod mới mất 70-80s để sẵn sàng khi scale** | Đây là giới hạn hạ tầng (Kubernetes/Karpenter phải dựng node mới từ đầu), không phải bug code. Cách né duy nhất hiện tại là **pre-scale thủ công trước khi biết trước sẽ có tải** (đã áp dụng tạm cho lần test vừa rồi, không phải giải pháp thường trực). | CDO02 — cần việc riêng (P3 kiến trúc / cân nhắc capacity buffer) |
| 2 | **AI và đọc review vẫn dùng chung 1 nhóm luồng xử lý** | Fix ở mục 2.2 chỉ giới hạn *thời gian* AI chiếm tài nguyên sau khi đã được nhận vào, KHÔNG ngăn được việc request đọc review phải xếp hàng phía sau một loạt request AI đã nộp trước đó nếu backlog đủ lớn. Cách fix triệt để là **tách hẳn AI ra một service/luồng xử lý riêng** (đã lên kế hoạch, chưa làm — việc lớn, cần đổi routing + canary). | CDO02 |
| 3 | **Deadline 500ms chưa được xem lại theo số liệu thật** | Cần đo p95/p99 thật trước khi quyết định có nên đổi deadline không (tránh đổi mù dẫn tới che giấu vấn đề thay vì giải quyết). | CDO02 |

---

## 4. Phần liên quan AIO02 — AWS Bedrock tự giới hạn tốc độ (throttle)

Đây là phát hiện **mới, ngoài phạm vi điều tra ban đầu**, tìm được khi chạy load test 500 user để kiểm
chứng fix.

**Quan sát:** widget "Ask AI" mất **15-25 giây** để trả lời dưới tải cao (gần chạm ngưỡng timeout 15s cấu
hình cho path này). Log thật của `product-reviews` trong đúng cửa sổ đó:

```
WARNING [guardrails.fallback] - Retrying __main__.call_candidate_bedrock in 0.4s seconds as it raised
ThrottlingException: An error occurred (ThrottlingException) when calling the Converse operation
(reached max retries: 4): Too many requests, please wait before trying again.
```

**Nghĩa là:** khi nhiều người hỏi AI cùng lúc, **AWS Bedrock tự chặn bớt request** (rate limit ở tài khoản/
model, không phải lỗi code bên mình). Code đã có sẵn cơ chế retry + fallback (trả "AI đang bận" cho người
dùng thay vì lỗi thẳng), nên **người dùng không thấy lỗi cứng**, nhưng trải nghiệm AI chậm/kém dưới tải là
thật.

**Cần AIO02 xác nhận/xử lý:**
- Kiểm tra quota/giới hạn TPS hiện tại của model `amazon.nova-lite-v1:0` (và judge `amazon.nova-micro-v1:0`)
  đang cấp cho tài khoản/region đang dùng.
- Cân nhắc xin tăng quota nếu muốn AI assistant chịu được tải tương đương ~500 user đồng thời mà không
  throttle.
- Nếu quota không tăng được, cân nhắc retry/backoff strategy phù hợp hơn ở phía code (hiện đang dùng
  `tenacity`, max 4 lần retry) — việc này CDO02 có thể hỗ trợ sửa code nếu AIO02 quyết định thông số mới.

---

## 5. Tóm tắt trạng thái

- **Đã fix:** lỗi hiển thị sai (mục quan trọng nhất của postmortem gốc) + giảm rủi ro nghẽn tài nguyên.
- **Chưa fix — CDO02 xử lý tiếp:** tách AI ra service riêng (P3 đầy đủ), xem lại deadline (P5).
- **Chưa fix — cần AIO02:** AWS Bedrock throttle dưới tải cao.
- Incident **chưa đóng chính thức** — xem tiêu chí đóng đầy đủ ở tài liệu gốc §8.
