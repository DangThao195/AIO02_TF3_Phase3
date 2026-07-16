# ADR 0004: Thiết kế hệ thống Đánh giá Độ trung thực của văn bản tóm tắt

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Thịnh (AIE1) & Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-15

---

## 1. Bối cảnh
Khi sử dụng mô hình ngôn ngữ lớn thực tế để tạo bản tóm tắt các đánh giá sản phẩm, hệ thống đối mặt với nguy cơ xảy ra hiện tượng ảo giác — tức là mô hình tự tạo ra các thông tin không có thực hoặc mâu thuẫn trực tiếp với nội dung đánh giá gốc của khách hàng trong cơ sở dữ liệu. Việc hiển thị một bản tóm tắt sai lệch cho khách hàng sẽ gây ảnh hưởng nghiêm trọng đến uy tín thương hiệu và tính chính xác của dữ liệu.

Do đó, chúng tôi cần một cơ chế tự động kiểm tra và đánh giá độ trung thực của bản tóm tắt ngay sau khi mô hình tạo ra và trước khi phản hồi về phía giao diện người dùng.

---

## 2. Quyết định
Chúng tôi quyết định thiết kế và tích hợp một bộ đánh giá độ trung thực nội tuyến hoạt động như một chốt chặn chất lượng ngay sau cuộc gọi LLM tạo tóm tắt:

1. **Khởi chạy Fidelity Judge nội tuyến:**
   * Ngay sau khi nhận kết quả tóm tắt từ mô hình chính, server sẽ thực hiện một cuộc gọi thứ hai tới mô hình đánh giá — mặc định sử dụng **AWS Bedrock Nova Micro `amazon.nova-micro-v1:0`** để tối ưu hóa thời gian phản hồi và chi phí.
   * Đầu vào của Judge bao gồm: ID sản phẩm, danh sách các đánh giá gốc từ PostgreSQL và bản tóm tắt ứng viên vừa được tạo.

2. **Quy tắc Kiểm duyệt Nghiêm ngặt:**
   * Yêu cầu mô hình Judge phân tích và trả về kết quả định dạng JSON chứa các trường: `approved`, `unsupported_claims` (số lượng thông tin không có bằng chứng đối chiếu), và `contradicted_claims` (số lượng thông tin mâu thuẫn trực tiếp với đánh giá gốc).
   * Bản tóm tắt chỉ được duyệt khi số lượng thông tin không bằng chứng và thông tin mâu thuẫn đều bằng 0.

3. **Cơ chế Xử lý khi Bác bỏ:**
   * Nếu bộ đánh giá trả về `approved: false` (phát hiện có lỗi ảo giác hoặc sai lệch thông tin), hệ thống sẽ lập tức loại bỏ bản tóm tắt đó và trả về một thông báo lỗi tiếng Anh cố định cho client: `"The summary cannot be verified. Please try again later."` thay vì đẩy thông tin sai lệch lên storefront.

---

## 3. Chi tiết Thiết kế

Cấu trúc gợi ý nhắc lệnh hệ thống cho Judge được thiết lập cố định để ép định dạng đầu ra:
```text
You are a strict factuality judge for product-review summaries.
Your only job is to detect hallucinations.
Compare the candidate summary against the provided raw reviews.
Return JSON only with these fields:
{
  "approved": true | false,
  "unsupported_claims": integer,
  "contradicted_claims": integer,
  "reason": string
}
```

Quy trình hoạt động trong mã nguồn:
1. Gọi mô hình chính tạo tóm tắt ứng viên.
2. Kiểm tra nếu câu trả lời không phải là thông điệp ngoài luồng hoặc không có thông tin, tiến hành gọi hàm `evaluate_summary_fidelity` trong `guardrails/evaluator.py`.
3. Khởi tạo client kết nối với Bedrock hoặc OpenAI tương ứng, chạy prompt đánh giá với nhiệt độ bằng 0.0 để đảm bảo tính nhất quán.
4. Trích xuất và phân tích cú pháp JSON từ phản hồi của Judge để kiểm tra các chỉ số lỗi.
5. Nếu không đạt yêu cầu chất lượng, ghi nhận cảnh báo vào log hệ thống để phục vụ kiểm toán và trả về thông báo từ chối xác thực.

---

## 4. Đo lường & Chứng minh bằng Bộ Đánh giá Độc lập (Offline Evaluation)

Để đáp ứng yêu cầu "Chứng minh bằng eval, không bằng lời" từ Chỉ thị số 6 và tài liệu AI Feature, chúng tôi xây dựng và triển khai một bộ đánh giá ngoại tuyến (offline evaluation) độc lập để kiểm tra độ trung thực một cách toàn diện và tự động.

### 4.1. Quy trình chạy & Tái tạo Đánh giá
Bộ đánh giá được cài đặt trong [eval_fidelity.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/repro/eval_fidelity.py). Luồng xử lý như sau:
1. **Trích xuất Ground Truth**: Lấy toàn bộ review gốc của sản phẩm trực tiếp từ PostgreSQL.
2. **Sinh Tóm tắt Ứng viên**: Gọi gRPC `AskProductAIAssistant` (sử dụng model chính Bedrock Nova Lite qua LiteLLM proxy) để tạo tóm tắt.
3. **Bộ lọc Logic (Rule-based Heuristics)**: Chạy các kiểm tra logic cứng để phát hiện sớm các lỗi định dạng hoặc sai số số liệu trước khi gọi LLM.
4. **LLM-as-a-Judge**: Gọi LLM Judge độc lập (Groq `llama-3.3-70b-versatile` - sử dụng nhà cung cấp khác để tránh thiên kiến tự đánh giá) để bóc tách các claims và so sánh thực tế với Ground Truth.
5. **Xuất báo cáo**: Ghi toàn bộ kết quả chi tiết của phiên chạy vào artifact JSON tại `repro/artifacts/`.

Lệnh chạy tái tạo:
```bash
python repro/eval_fidelity.py --all-products
```

### 4.2. Bộ Chỉ số & Ngưỡng Chất lượng (Metrics & Thresholds)

Hệ thống đánh giá sử dụng bộ chỉ số kết hợp giữa kiểm tra định tính bằng LLM Judge và kiểm tra định lượng bằng luật cứng (Rule-based):

| Nhóm Chỉ số | Tên Chỉ số (Metric) | Diễn giải & Ý nghĩa | Ngưỡng đạt (Target) | Cơ chế kiểm duyệt |
| :--- | :--- | :--- | :---: | :--- |
| **Fidelity & Factuality** (Định tính - LLM Judge) | `overall_score` | Điểm tổng hợp độ trung thực (thang 1-5) | $\ge 4$ | Nhỏ hơn 4 sẽ đánh dấu Thất bại |
| | `unsupported_claims` | Số lượng khẳng định tự bịa, không có trong review gốc | $= 0$ | Bắt buộc bằng 0 để chống ảo giác |
| | `contradicted_claims` | Số lượng khẳng định mâu thuẫn trực tiếp với review gốc | $= 0$ | Bắt buộc bằng 0 để chống sai lệch fact |
| | `claim_precision` | Tỷ lệ khẳng định đúng trên tổng số khẳng định của tóm tắt | $\ge 0.8$ | Đảm bảo phần lớn thông tin là có cơ sở |
| | `aspect_coverage` | Mức độ bao phủ các khía cạnh chính của tập review gốc | $\ge 0.6$ | Đảm bảo tính đầy đủ, không thiên vị |
| | `sentiment_alignment` | Độ tương thích tone cảm xúc (cờ nhị phân 0/1) | $= 1$ | Khớp tone cảm xúc với Ground Truth |
| **Logic Heuristics** (Định lượng - Rule-based) | `unsupported_age_claim` | Tự ý đưa thông tin về độ tuổi khi review gốc không nói | `False` | Tự động đánh rớt nếu có claim tuổi bịa |
| | `average_rating_mismatch` | Lệch điểm số trung bình so với điểm thật trong DB | `False` | Sai số cho phép tối đa là $\pm 0.05$ |
| | `sentiment_conflict` | Tone tóm tắt trái ngược hoàn toàn với điểm số DB | `False` | Chặn ví dụ: điểm TB $\ge 4.0$ nhưng tóm tắt tiêu cực |
| | `product_id_echo` | Rò rỉ mã ID nội bộ sản phẩm trong tóm tắt | `False` | Cảnh báo bảo mật hệ thống |
| **Format & Length** (Định lượng - Rule-based) | `sentence_count` | Tổng số câu trong văn bản tóm tắt | $\le 2$ câu | Đảm bảo tính cô đọng theo SLO |
| | `word_count` | Tổng số từ trong văn bản tóm tắt | $\le 80$ từ | Tránh verbosity và tối ưu token cost |

---

### 4.3. Kết quả Đánh giá Baseline chi tiết

Dưới đây là kết quả đo lường thực tế trên **10 sản phẩm có review trong database** (được ghi nhận tại [fidelity_eval_all_products_v2.json](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/repro/artifacts/fidelity_eval_all_products_v2.json)), thể hiện chi tiết chất lượng của model chính Bedrock Nova Lite:

#### A. Chỉ số Tổng hợp (Aggregated Metrics)
* **Tổng số ca thử nghiệm**: `10`
* **Overall Pass Rate (Đạt cả Fidelity & Format)**: **`80.0%`** (8/10)
* **Fidelity Pass Rate (Chỉ số Trung thực)**: **`80.0%`** (8/10)
* **Format Pass Rate (Chỉ số Định dạng)**: **`100.0%`** (10/10)

| Chỉ số chất lượng trung bình (Average)            | Kết quả thực tế (Actual) | Trạng thái đối chiếu                  |
| :------------------------------------------------ | :----------------------: | :------------------------------------ |
| **Điểm Fidelity trung bình (Avg Score)**          |     **`4.6 / 5.0`**      | Khá cao, phản ánh đúng thực tế        |
| **Độ chính xác khẳng định (Avg Claim Precision)** |       **`94.2%`**        | Rất tốt, tỷ lệ thông tin nhiễu thấp   |
| **Độ bao phủ khía cạnh (Aspect Coverage Avg)**    |       **`89.0%`**        | Tóm tắt bao quát đầy đủ thông tin gốc |
| **Mức độ đồng thuận cảm xúc (Sentiment Rate)**    |       **`100.0%`**       | Hoàn toàn trùng khớp về mặt cảm xúc   |
| **Tỷ lệ claim bịa (Unsupported Claim Rate)**      |       **`2.94%`**        | Thấp, nhưng vẫn cần triệt tiêu        |
| **Tỷ lệ claim mâu thuẫn (Contradiction Rate)**    |       **`2.94%`**        | Thấp, cần được xử lý triệt để         |

#### B. Bảng kết quả chi tiết từng sản phẩm
| Product ID | Trạng thái | Fidelity | Format | Điểm số | Claims | Unsupported | Contradicted | Độ chính xác | Coverage | Số từ | Lý do Thất bại (nếu có) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `0PUK6V6EV0` | `PASS` | `True` | `True` | `5` | `4` | `0` | `0` | `1.00` | `1.0` | `49` | _None_ |
| `1YMWWN1N4O` | `PASS` | `True` | `True` | `5` | `4` | `0` | `0` | `1.00` | `1.0` | `43` | _None_ |
| `2ZYFJ3GM2N` | `PASS` | `True` | `True` | `5` | `4` | `0` | `0` | `1.00` | `0.9` | `52` | _None_ |
| `66VCHSJNUP` | `PASS` | `True` | `True` | `4` | `2` | `0` | `0` | `1.00` | `0.8` | `38` | _None_ |
| `6E92ZMYYFZ` | **`FAIL`** | `False` | `True` | `4` | `3` | `0` | `1` | `0.67` | `0.8` | `43` | `contradicted_claims_present`, `average_rating_mismatch` |
| `9SIQT8TOJO` | `PASS` | `True` | `True` | `5` | `3` | `0` | `0` | `1.00` | `1.0` | `48` | _None_ |
| `HQTGWGPNH4` | `PASS` | `True` | `True` | `5` | `3` | `0` | `0` | `1.00` | `0.8` | `49` | _None_ |
| `L9ECAV7KIM` | **`FAIL`** | `False` | `True` | `4` | `4` | `1` | `0` | `0.75` | `0.8` | `45` | `unsupported_claims_present`, `claim_precision_below_threshold` |
| `LS4PSXUNUM` | `PASS` | `True` | `True` | `5` | `3` | `0` | `0` | `1.00` | `1.0` | `53` | _None_ |
| `OLJCESPC7Z` | `PASS` | `True` | `True` | `4` | `4` | `0` | `0` | `1.00` | `0.8` | `51` | _None_ |

#### C. Phân tích nguyên nhân các trường hợp Thất bại (Failure Analysis)
* **Sản phẩm `6E92ZMYYFZ`**: LLM sinh tóm tắt chứa số liệu điểm trung bình không chính xác, gây ra cảnh báo `average_rating_mismatch` và bị LLM Judge gán nhãn `contradicted_claims`.
* **Sản phẩm `L9ECAV7KIM`**: LLM đưa ra một khẳng định không hề được nhắc đến trong bất kỳ review gốc nào (ảo giác nhẹ), dẫn tới có `1 unsupported_claim` và kéo `claim_precision` xuống `75%` (dưới ngưỡng yêu cầu `80%`).

---

### 4.4. Cơ chế tích hợp CI/CD để Kiểm soát Chất lượng (Regression Gate)
Để đảm bảo mọi thay đổi về prompt hay logic code trong tương lai không làm suy giảm chất lượng tóm tắt:
1. **Tự động hóa**: Cấu hình bước chạy `python repro/eval_fidelity.py --all-products` như một phần bắt buộc trong CI workflow (Pull Request check).
2. **Tiêu chí thông qua (CI/CD Quality Gate)**:
   * `Fidelity Pass Rate` $\ge 80\%$
   * `Overall Pass Rate` $\ge 80\%$
   * `Contradiction Rate` và `Unsupported Claim Rate` $< 5\%$
3. **Hành động**: Bất kỳ bản build hoặc PR nào làm suy thoái các chỉ số này dưới ngưỡng baseline sẽ bị CI đánh lỗi đỏ và chặn merge tự động.

---

## 5. Hệ quả
* **Bảo vệ Chất lượng Dữ liệu:** Đảm bảo 100% các bản tóm tắt hiển thị trên storefront đều trung thực và bám sát ý kiến của khách hàng thực tế, loại bỏ hoàn toàn các lỗi ảo giác nguy hại.
* **Tác động đến Độ trễ:** Việc thêm một cuộc gọi LLM thứ hai làm tăng tổng thời gian phản hồi của API. Để giảm thiểu tác động này:
   * Chúng tôi lựa chọn mô hình Nova Micro có kích thước nhỏ và tốc độ xử lý nhanh nhất.
   * Áp đặt giới hạn thời gian chờ nghiêm ngặt (timeout = 3.0 giây) cho cuộc gọi Judge.
* **Xử lý Sự cố**: Nếu cuộc gọi tới Judge bị lỗi hoặc quá thời gian chờ, hệ thống sẽ kích hoạt cơ chế Fallback tầng 2 để trả về kết quả an toàn.

