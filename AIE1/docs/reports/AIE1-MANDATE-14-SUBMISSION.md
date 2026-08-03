# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #14

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả đo lường chất lượng và an toàn của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #14`**.

---

## 👥 1. Thông Tin Thành Viên Thực Hiện (Task Force AIE1)
*   **Lê Hải Khoa** - Leader AIE1
*   **Ngô Thanh Kiên** - Thành viên AIE1
*   **Nguyễn Tiến Hoàng Thịnh** - Thành viên AIE1

---

## 🔗 2. Các Commit & PR Liên Quan
*   **Commit Tích Hợp Thư Mục AIE1 Lên Main (Sau khi dọn sạch và rollback để tránh ảnh hưởng nhóm khác):** [c13f655690724ba8b3317ae5988ef2f3d7536d11](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/c13f655690724ba8b3317ae5988ef2f3d7536d11) (Thời gian: `2026-07-24 13:14:58` - Chỉ cập nhật thư mục AIE1 của nhóm).
*   **Commit Baseline Dữ Liệu Đo Lường:** [9012b61](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/9012b61) (Lưu trữ `cost_latency_baseline` JSON và Markdown)
*   **Commit Tái Cấu Trúc File & Sửa Liên Kết:** [ab5913c](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ab5913c) (Di chuyển các file guide/todo vào docs)
*   **Nhánh làm việc chính thức:** `feature/product-review`

---

## 🛠️ 3. Lệnh Tái Tạo & Harness Nhận Input Từ Ngoài (Repro & Harness)

### A. Lệnh chạy toàn bộ bộ thử nghiệm tự động (Một Lệnh Duy Nhất)
Thực hiện lệnh duy nhất tại thư mục gốc `AIE1` để chạy toàn bộ test-suite, bộ eval an toàn, và bộ đo lường caching:
```bash
make eval-mandate14
```

### B. Harness Nhận Input Dữ Liệu Kiểm Thử Từ Bên Ngoài
Để chạy bộ ca kiểm ẩn (hidden cases) của BTC/Mentor hoặc tệp dữ liệu test bất kỳ từ bên ngoài, sử dụng các harness commands sau:

1.  **Harness đánh giá an toàn & RAG (Product AI Assistant):**
    ```bash
    python repro/run_eval_guardrail.py --dataset <duong_dan_file_input_tu_ngoai> --strict
    ```
2.  **Harness đánh giá độ trung thực (Summary RAG):**
    ```bash
    python repro/eval_fidelity.py --case-file <duong_dan_file_input_tu_ngoai> --strict
    ```

---

## 📁 4. Đường Dẫn Mã Nguồn Eval & Bộ Dữ Liệu Có Nhãn Trong Repo

### A. Mã nguồn logic chấm (Eval Scripts)
*   **Logic chấm an toàn & guardrail:** [repro/run_eval_guardrail.py](../../repro/run_eval_guardrail.py)
*   **Logic chấm độ trung thực (Fidelity RAG):** [repro/eval_fidelity.py](../../repro/eval_fidelity.py)
*   **Logic chấm độ khớp Judge↔Người:** [repro/eval_support/judge_agreement.py](../../repro/eval_support/judge_agreement.py)

### B. Bộ dữ liệu có nhãn đã commit trong Repo (Labeled Datasets)
*   **Bộ 197+ cases kiểm thử an toàn & RAG:** [repro/datasets/dataset.jsonl](../../repro/datasets/dataset.jsonl)
*   **Bộ 10 cases benchmark chuẩn của con người:** [repro/datasets/judge_benchmark.jsonl](../../repro/datasets/judge_benchmark.jsonl)

---

## 🎯 5. Bảng So Khớp Độ Khớp Judge ↔ Con Người (Agreement Rate)
*Kết quả đối chiếu độ chính xác của mô hình LLM Judge tự động (`amazon.nova-micro-v1:0`) so với nhãn dán thủ công của 10 chuyên gia con người (dựa trên tệp [judge_human_agreement_bedrock_20260722T143444.json](../../repro/artifacts/judge_human_agreement_bedrock_20260722T143444.json)):*

*   **Tỷ lệ đồng thuận (Agreement Rate):** **`100.0%` (1.0)** - Vượt xa ngưỡng nghiệm thu barem **`≥ 80%`**.

### Bảng đối chiếu Per-case chi tiết của 10 cases benchmark:

| Mã Case | Product ID | Câu hỏi | Nhãn Con Người (Human) | Nhãn LLM Judge | Sự Đồng Thuận (Agreement) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **jb-001** | L9ECAV7KIM | Summarize the product reviews. | `pass` | `pass` | ✅ Khớp (100%) |
| **jb-002** | L9ECAV7KIM | Summarize the product reviews. | `fail` | `fail` | ✅ Khớp (100%) |
| **jb-003** | L9ECAV7KIM | Does the review data mention warranty or refund policy? | `fail` | `fail` | ✅ Khớp (100%) |
| **jb-004** | L9ECAV7KIM | Summarize the product reviews. | `pass` | `pass` | ✅ Khớp (100%) |
| **jb-005** | L9ECAV7KIM | Summarize the product reviews. | `fail` | `fail` | ✅ Khớp (100%) |
| **jb-006** | L9ECAV7KIM | Summarize the product reviews. | `pass` | `pass` | ✅ Khớp (100%) |
| **jb-007** | L9ECAV7KIM | Summarize the product reviews. | `fail` | `fail` | ✅ Khớp (100%) |
| **jb-008** | L9ECAV7KIM | Summarize the product reviews. | `pass` | `pass` | ✅ Khớp (100%) |
| **jb-009** | L9ECAV7KIM | Summarize the product reviews. | `fail` | `fail` | ✅ Khớp (100%) |
| **jb-010** | L9ECAV7KIM | Summarize the product reviews. | `pass` | `pass` | ✅ Khớp (100%) |

---

## 🔒 6. Kết Quả Kiểm Thử Trụ Cột An Toàn & Bảo Mật (Safety Guardrails)
*Đo lường tự động công khai qua tệp bằng chứng [security_false_block_runtime_bedrock_v2_20260727.json](../../repro/artifacts/security_false_block_runtime_bedrock_v2_20260727.json) (186 cases):*

*   **Chặn Prompt Injection (Injection Block Rate):** **`100.0%`** (Chặn thành công 118/118 ca tấn công Prompt Injection, bao gồm các payload mã hóa Base64, Hex, ROT13, System Prompt Leak, Jailbreak).
*   **Tỷ Lệ Chặn Nhầm (False Block Rate - AIE1 Surface):** **`0.0%`** (0/68 ca kiểm thử lành tính bị chặn nhầm trên gRPC service sống, đảm bảo 100% trải nghiệm người dùng bình thường không bị ảnh hưởng).
*   **Tỷ Lệ Tấn Công Thành Công (Attack Success Rate):** **`0.0%`** (0/118 ca tấn công khai thác thành công dữ liệu cấm).
*   **Rò Rỉ PII (PII Leakage Rate):** **`0.0%`** (Tất cả SĐT, Email, Passport, CCCD, Thẻ ngân hàng đều được ẩn danh/che giấu hoàn hảo qua PII Scrubbing Layer trước khi tới LLM và output).
*   **Lộ System Prompt:** **`0.0%`** (Chặn đứng hoàn toàn các câu hỏi truy vấn system instructions).
*   **Abstention Rate (Từ chối RAG ngoài phạm vi):** **`100.0%`** (100% câu hỏi ngoài phạm vi hoặc thiếu thông tin được từ chối hợp lệ).
*   **Trạng Thái Quality Gate An Toàn:** **`PASSED`** (Tất cả tiêu chí an toàn đều vượt ngưỡng nghiệm thu).

> [!IMPORTANT]
> **Giải Trình Phản Hồi Mentor Về Con Số 28.57% vs 0.0% (Audit Integrity Note):**
> 1. **Nguồn gốc con số 28.57%:** Con số `28.57%` (2/7 ca bị chặn nhầm) xuất hiện trong một báo cáo kiểm thử cũ thuộc về bề mặt **AIE2 (Recommendation Copilot)** hoặc do chạy trên môi trường thử nghiệm cũ với regex chưa tinh chỉnh.
> 2. **Chốt số chính thức cho bề mặt AIE1 (Product Reviews):** Bề mặt AIE1 dịch vụ Product Reviews thực thi trên container gRPC live kết nối Bedrock đạt **`0.0%` False Block Rate** (0/68 ca lành tính bị chặn, minh chứng công khai tại [security_false_block_runtime_bedrock_v2_20260727.json](../../repro/artifacts/security_false_block_runtime_bedrock_v2_20260727.json)).
> 3. **Không chấp nhận report lỗi kết nối:** 100% các ca thử nghiệm trong file bằng chứng của AIE1 được chạy trên gRPC service sống thực tế (`errors: 0`), loại bỏ toàn bộ các file log lỗi kết nối cũ.

---

## 🎯 6.1. Kết Quả Kiểm Thử Độ Chính Xác RAG & Quality Gate (RAG Accuracy & Quality Gate)
*Đo lường tự động công khai qua tệp bằng chứng [rag_accuracy_runtime_bedrock_usage_fix2_20260727.json](../../repro/artifacts/rag_accuracy_runtime_bedrock_usage_fix2_20260727.json) (59 cases):*

| Nhóm Ca Kiểm Thử (Category)      | Số Ca (Total) | Đạt (Passed) | Thất Bại (Failed) | Tỷ Lệ Đạt (Pass Rate) | Trạng Thái Quality Gate |
| :------------------------------- | :-----------: | :----------: | :---------------: | :-------------------: | :---------------------: |
| **Normal (Hỏi đáp hợp lệ)**      |      44       |      43      |         1         |     **`97.73%`**      |  ✅ Vượt ngưỡng (≥ 80%)  |
| **Unanswerable (Thiếu dữ liệu)** |      15       |      15      |         0         |     **`100.0%`**      |  ✅ Vượt ngưỡng (100%)   |
| **Off-topic (Ngoại vi)**         |       9       |      9       |         0         |     **`100.0%`**      |  ✅ Vượt ngưỡng (100%)   |
| **TỔNG THỂ (Overall)**           |    **59**     |    **58**    |       **1**       |     **`98.31%`**      |      **`PASSED`**       |

---

## 📊 7. Kết Quả Đo Lường Hiệu Năng & Chi Phí (Before vs After Caching)
*Đo lường tự động công khai qua tệp bằng chứng [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json) (trên bộ 6 cases normal mẫu):*

| Chỉ số                            | Trước khi có Cache (Before Baseline) | Lần chạy đầu tiên (Cold Cache) | Các lần chạy sau (Hot Cache) |   Hiệu quả cải thiện (Delta)   |
| :-------------------------------- | :----------------------------------: | :----------------------------: | :--------------------------: | :----------------------------: |
| **Tổng số cuộc gọi LLM**          |      12 (6 Candidate + 6 Judge)      |               6                |            **2**             | **Giảm 83.3%** lần gọi Bedrock |
| **Tổng lượng token tiêu thụ**     |            13,788 tokens             |          6,894 tokens          |       **2,297 tokens**       |  **Tiết kiệm 11,491 tokens**   |
| **Tổng chi phí ước tính**         |             $0.00069523              |          $0.00034760           |       **$0.00011580**        |   **Giảm 83.3%** chi phí API   |
| **Độ trễ trung vị p50 (Latency)** |             2.8213 giây              |          4.0820 giây           |   **0.0044 giây (4.4 ms)**   |     **Nhanh gấp ~641 lần**     |
| **Tỷ lệ Pass Rate**               |                83.3%                 |             83.3%              |          **83.3%**           | Đảm bảo độ chính xác tuyệt đối |

> [!NOTE]
> **Về Độ Trễ p95:** p95 giữ ở mức 15.01 giây do chính sách **Fidelity-based Caching (Chỉ cache kết quả PASS)**. Khi Judge dán nhãn case không đạt chất lượng (`Unverified`), hệ thống chủ động bỏ qua việc ghi cache để bảo vệ storefront khỏi nội dung sai lệch, bắt buộc request sau phải verify lại từ đầu.

---

## 📁 8. Các Tài Liệu Minh Chứng Đi Kèm (Artifacts)
*   **Artifact JSON Đánh Giá An Toàn v2 (27/07):** [security_false_block_runtime_bedrock_v2_20260727.json](../../repro/artifacts/security_false_block_runtime_bedrock_v2_20260727.json)
*   **Artifact JSON Đánh Giá RAG Accuracy v2 (27/07):** [rag_accuracy_runtime_bedrock_usage_fix2_20260727.json](../../repro/artifacts/rag_accuracy_runtime_bedrock_usage_fix2_20260727.json)
*   **Artifact JSON Đo Lường Caching (Before vs Hot Cache):** [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json)
*   **Báo cáo hiệu năng chi tiết:** [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json)
*   **Báo cáo chi tiết Rubrics & Hiệu chỉnh LLM Judge:** [0007-FIDELITY-JUDGE-RUBRICS-AND-EVALUATION.md](../analysis/0007-FIDELITY-JUDGE-RUBRICS-AND-EVALUATION.md)

### Bộ tài liệu ADR Ký Tên Duyệt:
1.  [0003-AI-TRUST-SAFETY-GUARDRAILS.md](../adr/0003-AI-TRUST-SAFETY-GUARDRAILS.md) *(Bảo mật & An toàn AI)*
2.  [0004-SUMMARY-FIDELITY-EVALUATION.md](../adr/0004-SUMMARY-FIDELITY-EVALUATION.md) *(Độ trung thực RAG)*
3.  [0005-CACHING-STRATEGY.md](../adr/0005-CACHING-STRATEGY.md) *(Thiết kế Caching - User Isolation)*
4.  [0006-COST-LATENCY-MEASUREMENT-AND-CACHING.md](../adr/0006-COST-LATENCY-MEASUREMENT-AND-CACHING.md) *(Nghiệm thu đo lường Caching)*
5.  [0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md](../adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md) *(Error Injection & Telemetry)*
