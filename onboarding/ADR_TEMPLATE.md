# ADR-NNN: [Tiêu đề quyết định — động từ + đối tượng]

> Template Nygard (2011) — deliverable bắt buộc theo RULES.md (ADR/decision log có ký).
> Khi nào cần ADR: quyết định ảnh hưởng >1 nhóm, chi phí đảo ngược > 1 người-tháng,
> hoặc chắc chắn sẽ bị hỏi lại ở Ops Review / Service Health Readout.
> **≥ 2 alternatives có pros/cons là BẮT BUỘC** — ADR không có phương án bị loại
> là bản ghi quảng cáo, không phải bản ghi quyết định. Lưu tại `docs/adr/ADR-NNN-<slug>.md`.

| | |
|---|---|
| **Status** | Proposed / Accepted / Deprecated / Superseded by ADR-MMM |
| **Ngày** | YYYY-MM-DD |
| **Người quyết + ký** | |
| **Liên quan** | INC-x, C-contract, backlog item |

## Context

Tình huống và ràng buộc ép phải quyết định (SLO nào đang đau, budget bao nhiêu, RULES cấm gì).
Viết sao cho người mới vào TF đọc xong hiểu VÌ SAO lúc đó phải chọn. Số liệu > tính từ.

## Decision

Chọn gì — một câu chủ động: "Chúng tôi sẽ …". Kèm phạm vi (service nào, môi trường nào)
và điều kiện xét lại (khi metric X vượt Y thì mở lại ADR này).

## Alternatives considered (≥ 2)

### Phương án A — [tên] (ĐÃ CHỌN)
- ✅ Pros:
- ❌ Cons / trade-off chấp nhận:
- Chi phí (hạ tầng + công engineer — thiếu công engineer là hụt 3–5×, W3-D3):

### Phương án B — [tên] (loại)
- ✅ Pros:
- ❌ Cons — vì sao thua A (định lượng nếu được):

### Phương án C — [tên] (loại)
- ✅ Pros:
- ❌ Cons:

## Consequences

- Tích cực (đo được bằng gì — metric/SLI nào sẽ chứng minh quyết định đúng):
- Tiêu cực chấp nhận (nợ kỹ thuật tạo ra, ai gánh, đến bao giờ):
- Việc phát sinh (backlog item mới, runbook cần cập nhật, KB cần re-ingest):

---

### Ví dụ đã áp dụng trong TF3 (tham khảo khi viết)

**ADR: Topology-aware RCA thay vì rank theo alert count** — count-based ranking chọn nhầm
victim trong retry storm (service hạ nguồn bắn NHIỀU alert hơn thủ phạm). Chọn fusion
`0.6×structural + 0.4×timestamp-order` (`rca_assistant.score_candidates`). Trade-off chấp
nhận: phải nuôi DEPENDENCY_MAP đồng bộ với ARCHITECTURE.md + tốn thêm compute per-incident.
Bằng chứng: `ai-engine/chaos/scoreboard.md` exp09 (retry-storm) RCA top-1 đúng thủ phạm.
