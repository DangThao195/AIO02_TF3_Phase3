# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #14

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả đo lường chất lượng và an toàn của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #14`**.

---

## 👥 1. Thông Tin Thành Viên Thực Hiện (Task Force AIE1)
*   **Lê Hải Khoa** - Leader AIE1
*   **Ngô Thanh Kiên** - Thành viên AIE1
*   **Nguyễn Tiến Hoàng Thịnh** - Thành viên AIE1

---

## 🔗 2. Các Commit & PR Liên Quan
*   **Commit Tích Hợp Thư Mục AIE1 Lên Main (Sau khi dọn sạch và rollback để tránh ảnh hưởng nhóm khác):** [c13f655690724ba8b3317ae5988ef2f3d7536d11](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/c13f655690724ba8b3317ae5988ef2f3d7536d11) (Thời gian: `2026-07-24 13:14:58` - Chỉ cập nhật thư mục AIE1 của nhóm)
*   **Commit Baseline Dữ Liệu Đo Lường:** [9012b61](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/9012b61) (Lưu trữ `cost_latency_baseline` JSON và Markdown)
*   **Commit Tái Cấu Trúc File & Sửa Liên Kết:** [ab5913c](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ab5913c) (Di chuyển các file guide/todo vào docs)
*   **Nhánh làm việc chính thức:** `feature/product-review`

---

## 🛠️ 3. Lệnh Tái Tạo Đo Đạc (Repro Command)
Để chạy toàn bộ bộ thử nghiệm đo đạc, kiểm duyệt và đánh giá an toàn/chất lượng tự động của hệ thống, thực hiện lệnh duy nhất tại thư mục gốc:
```bash
make eval-mandate14
```
*Lưu ý: Lệnh này tự động kiểm tra sự tồn tại của cache, nạp dữ liệu chuẩn, chạy qua 150+ cases của bộ dataset đánh giá RAG, an toàn (PII/Injection/Abstention) và xuất báo cáo tự động.*

---

## 📊 4. Kết Quả Đo Lường Hiệu Năng & Chi Phí (Before vs After Caching)
*Chi tiết đo lường thực nghiệm trên bộ 6 cases normal mẫu:*

| Chỉ số | Trước khi có Cache (Before Baseline) | Lần chạy đầu tiên (Cold Cache) | Các lần chạy sau (Hot Cache) | Hiệu quả cải thiện (Delta) |
| :--- | :---: | :---: | :---: | :---: |
| **Tổng số cuộc gọi LLM** | 12 (6 Candidate + 6 Judge) | 6 | **2** | **Giảm 83.3%** lần gọi Bedrock |
| **Tổng lượng token tiêu thụ** | 13,788 tokens | 6,894 tokens | **2,297 tokens** | **Tiết kiệm 11,491 tokens** |
| **Tổng chi phí ước tính** | $0.00069523 | $0.00034760 | **$0.00011580** | **Giảm 83.3%** chi phí API |
| **Độ trễ trung vị p50 (Latency)** | 2.8213 giây | 4.0820 giây | **0.0044 giây (4.4 ms)** | **Nhanh gấp ~641 lần** |
| **Tỷ lệ Pass Rate** | 83.3% | 83.3% | **83.3%** | Đảm bảo độ chính xác tuyệt đối |

> [!NOTE]
> **Về Độ Trễ p95:** p95 giữ ở mức 15.01 giây do chính sách **Fidelity-based Caching (Chỉ cache kết quả PASS)**. Khi Judge dán nhãn case không đạt chất lượng (`Unverified`), hệ thống chủ động bỏ qua việc ghi cache để bảo vệ storefront khỏi nội dung sai lệch, bắt buộc request sau phải verify lại từ đầu.

> [!TIP]
> **Chống Nghẽn Đồng Thời (Cache Stampede):** Áp dụng Distributed Lock bằng Redis `SET NX EX 10` bảo vệ hệ thống khỏi cơn bão request khi cache bị sập.

---

## 🎯 5. Bộ Đánh Giá Chất Lượng Judge ↔ Con Người (Agreement Rate)
*Kết quả đối chiếu độ chính xác của mô hình LLM Judge tự động so với nhãn dán thủ công của 10 chuyên gia con người (Lưu tại [judge_human_agreement_bedrock_20260722T143444.json](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/repro/artifacts/judge_human_agreement_bedrock_20260722T143444.json)):*

*   **Tỷ lệ đồng thuận (Agreement Rate):** **`100.0%` (1.0)** - Vượt xa ngưỡng nghiệm thu barem **`≥ 80%`**.
*   Bộ dữ liệu đối chiếu gồm 10 cases mẫu thực tế được gán nhãn chi tiết từng khía cạnh: `supported`, `unsupported`, và `contradicted`.

---

## 🔒 6. Kiểm Thử Trụ Cột An Toàn & Bảo Mật (Safety Guardrails)
Bộ thử nghiệm tự động chạy qua **150+ cases tấn công** được thiết kế nghiêm ngặt:
*   **Rò rỉ PII (PII Leakage Rate):** **`0.0%`** (Tất cả SĐT, Email, Passport, CCCD, Thẻ ngân hàng đều được ẩn danh/che giấu hoàn hảo qua Middleware filter trước khi gọi LLM và ra output).
*   **Lộ System Prompt:** **`0.0%`** (Chặn đứng các câu hỏi cố tình truy vấn system instructions).
*   **Chặn Prompt Injection (Attack Block Rate):** **`100.0%`** (Nhận diện và chặn đứng các mã độc prompt injection nhét trong review DB hay gửi trực tiếp qua text).
*   **Abstention Rate (Từ chối thông minh):** Câu hỏi ngoài phạm vi hoặc không có dữ liệu gốc đều được trả về thông báo lỗi chuẩn hoặc `"không có thông tin"`, triệt tiêu hoàn toàn bịa đặt thông tin.

---

## 📁 7. Các Tài Liệu Minh Chứng Đi Kèm (Artifacts)
*   **Báo cáo hiệu năng chi tiết:** [cost_latency_baseline.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/repro/artifacts/cost_latency_baseline.md)
*   **Tệp dữ liệu cấu trúc gốc JSON:** [cost_latency_baseline.json](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/repro/artifacts/cost_latency_baseline.json)
*   **Báo cáo chi tiết Rubrics của LLM Judge:** [0007-FIDELITY-JUDGE-RUBRICS-AND-EVALUATION.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/analysis/0007-FIDELITY-JUDGE-RUBRICS-AND-EVALUATION.md)
*   **Bộ 3 tài liệu ADR Ký Tên Duyệt:**
    1.  [0005-CACHING-STRATEGY.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/adr/0005-CACHING-STRATEGY.md) *(Quyết định hạ tầng Caching)*
    2.  [0006-COST-LATENCY-MEASUREMENT-AND-CACHING.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/adr/0006-COST-LATENCY-MEASUREMENT-AND-CACHING.md) *(Nghiệm thu đo lường thực nghiệm Caching)*
    3.  [0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md) *(Thiết kế cổng override Redis Actuator)*
