# Post-Mortem Report: Sự cố Thanh toán do Dư chấn Đạo chích Tấn công
**Mã sự cố:** `INCIDENT-2026-004`  
**Độ ưu tiên:** 🔴 CRITICAL  
**Thời điểm phát hiện:** 2026-07-14 16:30:00 (Local Time)  
**Thời điểm khắc phục (Remediation):** 2026-07-14 16:45:00 (Local Time)  
**Task Force:** TF-3 (AIOps & Infrastructure)  

---

## 🔍 1. Tóm tắt Sự cố (Executive Summary)
Vào lúc 16:30 ngày 14/07/2026, hệ thống giám sát radar AIOps phát hiện dư chấn sụt giảm nghiêm trọng đối với luồng thanh toán và checkout của nhóm khách hàng VIP (Loyalty Level: Gold/Platinum). Nhiều người dùng báo lỗi không thể hoàn tất thanh toán (lỗi gRPC status code 13). Tỉ lệ checkout thành công (SLI) sụt giảm mạnh từ 99.8% xuống còn **91.2%**, đe dọa nghiêm trọng SLO cam kết.

---

## 📈 2. Đánh giá Chỉ số SLO (SLO Violation)
*   **SLO Đặt hàng thành công:** Cam kết $\ge 99.0\%$
*   **Thực tế (SLI):** **91.2%** (Giảm nhanh)
*   **Tốc độ tiêu hao (Burn-rate):** **28.8x** (Cực kỳ nguy cấp, sẽ cháy hết ngân sách lỗi sau 1.5 giờ nếu không xử lý).

---

## 🔬 3. Định vị Nguyên nhân gốc (Root Cause Analysis - RCA)
*   **Thủ phạm:** Dịch vụ `payment-service` bị quá tải kết nối và rò rỉ token do đợt quét tải tấn công quét qua hệ thống.
*   **Bằng chứng Logs (Drain3 templates):**
    ```log
    [Error] Connection timeout to Payment Gateway (AWS Bedrock)
    [Error] Database connection pool exhausted (current: 50/50)
    rpc error: code = Unknown desc = Payment request failed. Invalid token. app.loyalty.level=gold
    ```
*   **Phân tích kỹ thuật:** Kẻ tấn công thực hiện quét API liên tục, kích hoạt cơ chế lỗi `paymentFailure` của OpenFeature/flagd, làm cạn kiệt Connection Pool của Database (50/50 connection) và dẫn đến lỗi timeout kết nối tới AWS Bedrock Gateway.

---

## 💡 4. Đề xuất Khắc phục & Thực thi (Remediation Actions)
*   **Hành động tự động:** Kích hoạt Auto-Remediation tăng số lượng bản sao `payment` deployment từ 1 lên **3 replicas** nhằm chia tải kết nối Database và giảm nghẽn.
*   **Bán kính ảnh hưởng (Blast Radius):** Rất thấp, việc scale up không gây Downtime hệ thống.
*   **Kịch bản hoàn tác (Rollback Plan):** Khi tải và dư chấn quét qua đi, hệ thống tự động scale down về lại 1 replica để tối ưu chi phí hạ tầng.

---

## 📊 5. Evidence Thu thập (Bằng chứng Vận hành)
*   **Dashboard Grafana:** SLO Dashboard ghi nhận tỉ lệ Success Rate giảm đột ngột tại endpoint `/api/checkout`.
*   **Prometheus Alert:** Alert Manager tự động phát tín hiệu cảnh báo mức độ tiêu hao ngân sách lỗi (SLO Burn-rate Monitor).
*   **Jaeger Trace:** Phát hiện nhiều span lỗi màu đỏ tại gRPC method `oteldemo.PaymentService/Charge` với attribute `app.loyalty.level=gold`.
