# Priority Backlog - Phase 3 Week 1 (TF3 / Team AIO02)

Danh sách hạng mục công việc ưu tiên của **Trụ AI (Team AIO02)** trong Task Force 3 được xếp hạng theo công thức:
$$\text{Mức ưu tiên} = \text{Rủi ro (Khả năng xảy ra} \times \text{Mức nghiêm trọng)} \times \text{Tác động Business (SLO / Doanh thu / Chi phí)}$$

---

## 📋 Danh Sách Backlog Ưu Tiên (P1 $\rightarrow$ P7)

| Thứ tự | Hạng mục Công việc | Trụ | Mức Rủi ro | Tác động Business | Effort | Thời gian dự kiến |
|---|---|---|---|---|---|---|
| **P1** | **Fallback + Retry khi LLM lỗi 429/Timeout** | AIE / Reliability | **CAO** (BTC chắc chắn bật `llmRateLimitError`) | Giữ trải nghiệm khách, chống treo trang storefront | THẤP (~2h code) | **Tuần 1 (Hoàn thành)** |
| **P2** | **Eval + Chặn tóm tắt sai lệch (Faithfulness Check)** | AIE / Quality | **CAO** (BTC chắc chắn bật `llmInaccurateResponse`) | Bảo vệ SLO Cứng AI: "Không bao giờ hiển thị tóm tắt sai" | TRUNG BÌNH | **Tuần 1 (Bắt đầu) $\rightarrow$ Tuần 2** |
| **P3** | **Cache tóm tắt theo `product_id` (In-Memory)** | AIE / Cost | **TRUNG BÌNH** (Lãng phí token) | Tiết kiệm ~80% chi phí LLM, giảm latency từ 1.4s xuống <50ms | THẤP (~10 dòng Python) | **Tuần 1 (Hoàn thành)** |
| **P4** | **Tăng Replica `product-reviews` lên $\ge 2$** | AIE / Infra | **TRUNG BÌNH** (SPOF pattern như INC-2) | Đảm bảo AI Feature available khi node fail / deploy | RẤT THẤP (1 dòng values) | **Tuần 1 (Hoàn thành)** |
| **P5** | **Guardrail Prompt-Injection từ Review** | AIE / Security | **TRUNG BÌNH** (Chống tấn công độc hại) | Bảo vệ an toàn sản phẩm, chặn lộ System Prompt / PII | TRUNG BÌNH | **Tuần 2** |
| **P6** | **Thiết kế Khung Trợ lý AI (Shopping Copilot)** | AIE / Feature | **THẤP** ở Tuần 1 (Đầu ra cuối kỳ) | Tính năng AI Agentic mới nhất tăng tỷ lệ chuyển đổi giỏ hàng | CAO (Nhiều tuần) | **Tuần 1 (Thiết kế) $\rightarrow$ Tuần 2-3 (Build)** |
| **P7** | **AIOps - Telemetry & Alert Tự Động Tầng AI** | AIOps / Ops | **THẤP** ở Tuần 1 | Giảm MTTD/MTTR khi sự cố tầng AI xảy ra | TRUNG BÌNH | **Tuần 2 - 3** |

---

## 🚫 Các Hạng Mục Cố Ý Bỏ Trong Tuần 1 (Descope & Trade-off)

1. **Shopping Copilot Full Build**:
   - *Lý do descope*: Khung Agentic AI yêu cầu kết nối multi-tool và guardrail phức tạp. Nếu vội vã build trong Tuần 1 sẽ dẫn tới rủi ro vỡ SLO và không đủ thời gian đo Baseline.
2. **Deploy Valkey riêng (`valkey-llm-cache`)**:
   - *Lý do descope*: Tuần 1 ưu tiên In-Memory Dict để zero-infra overhead và tránh rủi ro OOM cho `valkey-cart`. Chỉ nâng cấp sang Valkey riêng ở Tuần 2-3 khi `product-reviews` scale $\ge 3$ replicas.
3. **Multi-AZ cho PostgreSQL**:
   - *Lý do descope*: Chi phí Multi-AZ gấp đôi sẽ ngay lập tức làm TF3 vượt trần ngân sách AWS $300/tuần.
