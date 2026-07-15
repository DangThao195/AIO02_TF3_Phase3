# Postmortem — [INC-x · tiêu đề ngắn] (BLAMELESS)

> Template chuẩn Google SRE (W3-D3). **Blameless bắt buộc**: viết về HỆ THỐNG và QUY TRÌNH,
> không về cá nhân. "Pipeline config cho phép YAML sai lọt qua" ✅ — "X push config sai" ❌.
> Blame culture = người ta giấu lỗi = bug sống lâu hơn = outage sau to hơn.
> Deliverable bắt buộc theo RULES.md (postmortem/COE có ký tên). Lưu tại `incidents/<INC-x>/postmortem.md`.

| | |
|---|---|
| **Trạng thái** | Draft / Reviewed / Signed |
| **Ngày sự cố** | YYYY-MM-DD |
| **Người viết** | (on-call, không phải "người gây ra") |
| **Người review/ký** | |
| **Severity** | SEV-1/2/3 |

## 1. Tóm tắt (2–4 câu)

Chuyện gì xảy ra, ai bị ảnh hưởng, đã xử lý bằng gì. Không thuật ngữ nội bộ — người ngoài đội đọc hiểu được.

## 2. Impact

- % user / request bị ảnh hưởng:
- Doanh thu / đơn hàng ước tính:
- **Error budget đã đốt:** x% của budget 30 ngày (SLO nào, số liệu từ đâu)
- Thông báo ra ngoài (nếu có):

## 3. Timeline (UTC — tối thiểu 8 event)

> Đủ chuỗi: trigger → symptom → alert → ack → diagnosis → mitigation → recovery → verify.
> Nguồn: `incidents/<id>/evidence-pack.md` + audit log + Slack + probe log.

| UTC | Sự kiện | Nguồn |
|---|---|---|
| hh:mm:ss | (trigger) | |
| hh:mm:ss | (symptom đầu tiên trên telemetry / synthetic probe) | |
| hh:mm:ss | (alert fired — tier nào, burn-rate bao nhiêu) | |
| hh:mm:ss | (on-call ack) | |
| hh:mm:ss | (root cause xác định — evidence pack H#) | |
| hh:mm:ss | (mitigation — action gì, ai approve) | |
| hh:mm:ss | (recovery — SLI về baseline) | |
| hh:mm:ss | (verify-loop xác nhận / probe steady-state lại) | |

**MTTD:** ___ · **MTTA:** ___ · **MTTR:** ___

## 4. Root cause (kỹ thuật)

Giải thích cơ chế lỗi. Sự cố đa nguyên nhân → dùng **causal tree** (nhiều nhánh đồng thời),
KHÔNG ép vào 5-Whys tuyến tính (bài học GitHub 2018: network blip 43s + failover logic +
consistency-first policy = compound failure).

## 5. Contributing factors

- Môi trường / cấu hình:
- Quy trình (thiếu canary? thiếu readiness? thiếu guardrail?):
- Thiết kế hệ thống (SPOF? noise floor che anomaly?):

## 6. Detection — phát hiện thế nào, sớm hơn được không?

- Ai/cái gì phát hiện đầu tiên (layer-2 anomaly? burn-rate? khách hàng?):
- Có thể phát hiện sớm hơn bằng gì (tín hiệu nào ĐÃ có trong telemetry mà chưa ai nhìn):

## 7. Response — cái gì chạy tốt, cái gì hỏng, đâu là may mắn

- Chạy tốt:
- Hỏng/chậm:
- **May mắn** (thứ cứu mình lần này nhưng KHÔNG lặp lại được — phải liệt kê trung thực):

## 8. Action items (bắt buộc có owner + due date — không có 2 thứ này = không đóng postmortem)

| # | Hành động | Loại (prevent/detect/mitigate/process) | Owner | Due | Ưu tiên |
|---|---|---|---|---|---|
| 1 | | | | | P0/P1/P2 |

## 9. Bài học đưa vào Knowledge Base

Sau khi ký: append entry mới vào `onboarding/INCIDENT_HISTORY.md` (đúng format 5 field:
Khi nào / Triệu chứng / Nguyên nhân gốc / Đã xử / Bài học còn treo) rồi chạy lại ingestion
job của Bedrock KB (`TF3/terraform` → output `ingestion_command`) để RCA assistant học được sự cố này.

---
**Ký xác nhận root cause:** ____________ · Ngày: ____________
