# Báo Cáo Phân Tích 4 Điểm Nghẽn Lớn Trong Hệ Thống Đánh Giá AI Summary

Tài liệu này lưu trữ phân tích chi tiết về các lỗi logic, lỗ hổng kiến trúc và điểm nghẽn kỹ thuật trong hệ thống đánh giá chất lượng tóm tắt (Fidelity Evaluation) hiện tại của dự án, được đúc rút từ tài liệu thiết kế và dữ liệu chạy thực tế.

---

## 📌 Tổng Quan Dữ Liệu Phân Tích
*   **Tài liệu tham chiếu:** [AI_BASELINE_EVAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AI_BASELINE_EVAL.md)
*   **Dữ liệu thực tế:** Các kết quả kiểm thử trong thư mục [repro/artifacts](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/artifacts) bao gồm:
    *   [fidelity_eval_all_products_v2.json](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/artifacts/fidelity_eval_all_products_v2.json) (Chạy thật trên 10 sản phẩm)
    *   [fidelity_eval_L9ECAV7KIM_inaccurate.json](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/artifacts/fidelity_eval_L9ECAV7KIM_inaccurate.json) (Giả lập lỗi ảo giác)

---

## 🚨 Chi Tiết 4 Điểm Nghẽn Lớn Của Hệ Thống

### 1. Bất nhất dữ liệu tham chiếu (Ground Truth Mismatch)
> [!WARNING]
> **Mức độ ảnh hưởng:** Nghiêm trọng (Gây ra lỗi False Positive hàng loạt khi scale hệ thống).

*   **Hiện trạng:** Luồng sinh summary (`AskProductAIAssistant`) sử dụng **toàn bộ reviews gốc** có trong database của sản phẩm để tóm tắt. Tuy nhiên, luồng đánh giá (`repro/eval_fidelity.py`) lại sinh ra `fact_sheet` giới hạn cứng chỉ chứa tối đa **6 reviews** (3 tích cực nhất + 3 tiêu cực nhất) làm Ground Truth gửi cho LLM Judge đối chiếu.
*   **Hậu quả:** Khi số lượng review thực tế của một sản phẩm tăng lên (ví dụ: 20-50 reviews), LLM Generator sẽ tóm tắt thông tin từ toàn bộ dữ liệu. Nhưng LLM Judge chỉ đối chiếu với 6 reviews trong `fact_sheet`. Bất kỳ thông tin chính xác nào nằm từ review thứ 7 trở đi đều bị Judge gắn cờ là `unsupported_claims` (ảo giác) do không tìm thấy bằng chứng trong Fact Sheet.

### 2. Hiện tượng Judge "Hyper-Strict" phản phản ứng thái quá với dải số (False Positives)
> [!IMPORTANT]
> **Mức độ ảnh hưởng:** Cao (Làm giảm tỷ lệ Pass thực tế của hệ thống từ 100% xuống 80%).

*   **Hiện trạng:** Bộ đánh giá đang đánh đồng việc **LLM sử dụng ngôn từ tự nhiên để viết dải số khái quát** với **lỗi ảo giác factual**.
*   **Minh chứng từ kết quả chạy thực tế:**
    *   **Sản phẩm `6E92ZMYYFZ`:** Summary viết rating trung bình là `4.7-5.0` (Thực tế là `4.8`). Rule-based báo lỗi `average_rating_mismatch` vì lệch quá sai số `0.05`. LLM Judge báo `contradicted` vì *"not explicitly 4.7-5.0 range"*.
    *   **Sản phẩm `L9ECAV7KIM`:** Summary viết rating trung bình khoảng `4.5-5.0` (Thực tế là `4.6`). LLM Judge báo `unsupported` vì *"score is actually 4.6, which is more precise than the given range"*.
*   **Hậu quả:** Hệ thống đánh giá bị quá nhạy cảm với các lỗi trình bày vô hại, khiến lập trình viên mất nhiều thời gian debug các case thực chất đã đạt chuẩn chất lượng.

### 3. Thiếu cơ chế dẫn chứng nguồn tin có cấu trúc (Structured Attribution)
> [!NOTE]
> **Mức độ ảnh hưởng:** Trung bình (Ảnh hưởng tới tốc độ debug offline của lập trình viên).

*   **Hiện trạng:** LLM Judge hiện tại chỉ trả về số lượng các lỗi (`supported_claims`, `unsupported_claims`, `contradicted_claims`) và một chuỗi lý do chung chung (`reason`). Các chuỗi `evidence` đi kèm các claim chưa được chuẩn hóa hoặc liên kết trực tiếp với định danh của review gốc (Review ID hoặc Review Index) một cách có cấu trúc.
*   **Hậu quả:** Khi chạy kiểm thử offline và phát hiện một summary bị lỗi factual, lập trình viên không thể tự động truy vết ngược lại xem claim đó đang lấy từ câu nào hay review nào trong tập dữ liệu gốc, gây khó khăn cho việc cải tiến prompt.

### 4. Đánh giá chất lượng (Fidelity Eval) bị cô lập khỏi luồng Runtime (Fallback & Guardrails)
> [!IMPORTANT]
> **Mức độ ảnh hưởng:** Cao (Ảnh hưởng trực tiếp đến chất lượng sản phẩm hiển thị tới khách hàng cuối).

*   **Hiện trạng:** Cơ chế Fallback được thiết kế tại [MỤC 5](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AI_BASELINE_EVAL.md#L767-L834) rất tốt, nhưng nó mới chỉ hoạt động khi **LLM API gặp sự cố kỹ thuật** (Exception, timeout, rate limit). Nó hoàn toàn bỏ qua kết quả đánh giá chất lượng của bộ Fidelity Eval.
*   **Hậu quả:** Nếu LLM trả về thành công (HTTP 200) nhưng nội dung summary bị ảo giác hoặc sai lệch thông tin nghiêm trọng (Fidelity score = 1 hoặc 2), hệ thống vẫn hiển thị bản tóm tắt lỗi đó cho người dùng mà không kích hoạt cơ chế Fallback (để chuyển hướng sang static summary hoặc thông báo thân thiện). Hệ thống chỉ tự bảo vệ khi "sập hệ thống kỹ thuật" chứ chưa tự bảo vệ khi "lỗi nội dung".

---

## 🛠️ Đề xuất Hướng Giải Quyết Đóng Góp Cho Mentor

| Điểm Nghẽn                    | Giải Pháp Kỹ Thuật Đề Xuất                                                                                                                                   |
| :---------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Bất nhất dữ liệu**          | Gom cụm thông tin (Clustering) hoặc trích xuất từ khóa/claims tự động từ toàn bộ reviews thay vì chỉ lấy cứng 6 reviews tích cực/tiêu cực nhất.              |
| **Hyper-Strict trên số liệu** | Tách phần hiển thị rating trung bình ra khỏi LLM (Code backend tự tính toán và hiển thị widget UI). Cấm LLM tự viết điểm số vào summary.                     |
| **Thiếu dẫn chứng**           | Yêu cầu LLM Judge trả về output dạng JSON có cấu trúc gồm: `[claim_text] -> [source_review_id] -> [exact_quote]`.                                            |
| **Cô lập Runtime**            | Tích hợp một bộ lọc chất lượng siêu nhẹ (như rule-based sentiment/rating mismatch hoặc LLM judge bất đồng bộ) làm Gatekeeper trước khi lưu/hiển thị summary. |
