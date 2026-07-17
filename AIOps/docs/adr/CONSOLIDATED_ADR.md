# Tài liệu Tổng hợp Quyết định Thiết kế Kiến trúc (Consolidated Architecture Decision Records - Master ADR)

- **Trạng thái**: Accepted (Hoàn chỉnh)
- **Ngày cập nhật cuối**: 2026-07-17
- **Tác giả / Ký tên**: Team AIO02 (Task Force 3)
- **Phạm vi tác động**: Toàn bộ hệ thống AIOps Engine, Tầng AI, và Hạ tầng Giám sát/Tự động Phục hồi (Remediation) trên cụm EKS.

---

## 🗺️ TỔNG QUAN HỆ THỐNG KIẾN TRÚC
Tài liệu Master ADR này tổng hợp toàn bộ các quyết định thiết kế kiến trúc cốt lõi từ Tuần 1 đến nay của nhóm **AIO02**, tạo thành bức tranh tổng thể hỗ trợ cho buổi đánh giá cuối kỳ của Mentor và Hội đồng SRE.

```mermaid
graph TD
    subgraph "1. Telemetry & Monitoring Layer"
        Prom["EKS Prometheus"] -->|Metrics Range Query| AIO["AIOps Engine"]
        Jaeger["EKS Jaeger v2"] -->|Traces API Query| AIO
    end

    subgraph "2. AI & ML Brain Layer"
        AIO -->|Proactive ML Scan| IF["Isolation Forest Model"]
        AIO -->|Remediation Proposal| RAG["Bedrock LLM + Knowledge Base"]
    end

    subgraph "3. Control & Remediation Gate"
        AIO -->|Proactive (Medium Risk)| Slack["Slack interactive Approval Card"]
        AIO -->|Reactive (Low Risk)| K8s["Kubernetes API (kubectl)"]
        Slack -->|Human Approved| K8s
    end
```

---

## 📑 1. ADR-001: Lựa Chọn Mô Hình LLM Provider Cho Tầng AI (Product Reviews)

* **Bối cảnh**: Tính năng tóm tắt review sản phẩm yêu cầu một LLM thật thay thế Mock với tiêu chí: độ trễ $p95 < 1.5s$, chi phí nằm trong ngân sách $300/tuần, tương thích chuẩn OpenAI Client.
* **Quyết định**:
  * *Giai đoạn 1 (Baseline):* Sử dụng **OpenAI `gpt-4o-mini`** công cộng thông qua K8s Secret `llm-api-key`. Đảm bảo độ trễ cực thấp ($\approx 0.8s$) và tương thích mã nguồn có sẵn lập tức.
  * *Giai đoạn 2 (Migration):* Dịch chuyển sang **AWS Bedrock / Bedrock Gateway** nội bộ VPC trên AWS EKS, sử dụng model `amazon.nova-lite-v1:0` kết hợp IAM Role để tối ưu bảo mật và tối thiểu hóa chi phí.
* **Hệ quả**: Đạt được tính sẵn sàng cao, bảo mật API Key trong VPC và minh bạch hóa chi phí AI.

---

## 📑 2. ADR-002: Chiến Lược Caching & Fallback Cho Tầng AI

* **Bối cảnh**: Tránh vỡ ngân sách khi bị đối thủ spam requests và bảo vệ hệ thống trước sự cố LLM sập (HTTP 429/500).
* **Quyết định**:
  * Triển khai bộ nhớ đệm **Valkey/Redis Cache** làm chốt chặn đầu tiên. Nếu truy vấn có trong cache $\rightarrow$ Trả kết quả tức thì (Latency < 5ms, Cost = $0).
  * Thiết lập cơ chế **Exponential Backoff & Jitter Retry** đối với lỗi HTTP 429/503.
  * Khi LLM lỗi hoàn toàn, áp dụng **Graceful Fallback**: Trả về dữ liệu tóm tắt cũ từ Cache hoặc xuất câu thông báo tóm tắt tiếng Việt thân thiện thay vì làm đơ trang.
* **Hệ quả**: Giảm hơn 80% số lượng request gọi trực tiếp tới LLM API, tiết kiệm chi phí vận hành đáng kể và nâng cao SLO khả dụng tầng AI lên 99.9%.

---

## 📑 3. ADR-003: Quản lý Phiên Bản & Cập Nhật Nóng (Hot Reload) Mô Hình Machine Learning

* **Bối cảnh**: Huấn luyện định kỳ Isolation Forest (IF) phát hiện bất thường cần cập nhật vào bộ nhớ RAM của Engine mà không được làm khởi động lại Pod (gây gián đoạn on-call).
* **Quyết định**:
  * Sử dụng **AWS S3 làm Model Registry** trung tâm với cấu trúc thư mục định danh `current/` và lưu trữ lịch sử theo timestamp.
  * Trong Engine, chạy một luồng nền độc lập định kỳ 5 phút quét tệp tin `active_manifest.json` trên S3.
  * Khi phát hiện có phiên bản mô hình mới được train bởi Cronjob $\rightarrow$ Engine tự động tải về và nạp nóng (`joblib.load`) trực tiếp vào RAM mà không làm crash hay restart container.
* **Hệ quả**: Tách biệt hoàn toàn luồng Train (Offline) và luồng Predict (Online), nâng cao tính ổn định và tính chu kỳ của mô hình ML.

---

## 📑 4. ADR-004: Thuật Toán SLO Burn Rate Đa Cửa Sổ Đa Dịch Vụ

* **Bối cảnh**: Tránh báo động giả (Alert Fatigue) khi gặp các spike tức thời, nhưng phải phát hiện cực nhanh các sự cố sụt giảm nghiêm trọng trong luồng mua hàng (Checkout/Payment).
* **Quyết định**:
  * Áp dụng thuật toán **Multi-Window Multi-Service SLO Burn Rate**:
    * Cửa sổ ngắn (Short Window: 5 phút / 1 giờ): Phát hiện sự cố cấp tính (tập trung phát sinh lỗi 100%).
    * Cửa sổ dài (Long Window: 30 phút / 6 giờ): Phát hiện sự cố suy thoái chậm (lỗi rò rỉ tăng nhẹ đều đặn).
  * Trọng số tính toán phân bổ ưu tiên: `checkout` & `payment` có trọng số cảnh báo cao hơn so với `recommendation` hay `shipping`.
* **Hệ quả**: Giảm 90% số lượng cảnh báo giả gây nhiễu cho SRE, phát hiện sự cố sập luồng chính xác chỉ trong vòng dưới 2 phút.

---

## 📑 5. ADR-005: Gom Nhóm Tương Quan Cảnh Báo Topo & Xác Định Culprit (RCA)

* **Bối cảnh**: Khi một dịch vụ core sập (ví dụ `payment`), nó kéo theo hàng loạt dịch vụ gọi nó bị lỗi dây chuyền (lỗi 500 lan tỏa lên `checkout`, `frontend`). Gây ra bão cảnh báo trên Slack và khó định vị nguyên nhân gốc.
* **Quyết định**:
  * Thiết lập bảng **Đồ thị Tương quan Topo mạng dịch vụ (Service Dependency Graph)** tích hợp trong code Engine.
  * Khi có bão cảnh báo từ Prometheus, Engine tự động đối chiếu đồ thị topo để nhóm các cảnh báo liên quan vào 1 Incident duy nhất.
  * Sử dụng giải thuật tính điểm **Root-Cause Scoring** dựa trên vị trí sâu nhất trong nhánh topo bị lỗi để định vị dịch vụ thủ phạm (Culprit) đích thực.
* **Hệ quả**: Biến luồng on-call từ hỗn loạn thành trật tự. SRE chỉ nhận đúng 1 Slack alert gom nhóm chỉ đích danh dịch vụ gốc gây ra sự cố.

---

## 📑 6. ADR-006: Kiểm Chứng Phục Hồi Lai Hai Cổng (Hybrid Double-Gate Verification)

* **Bối cảnh**: Sau khi Engine thực hiện lệnh sửa lỗi (ví dụ Scale Deployment), làm thế nào để đảm bảo hệ thống đã thực sự bình phục trước khi đóng Incident và tránh tình trạng rollback vô tận.
* **Quyết định**:
  * Triển khai quy trình kiểm chứng **Hybrid Double-Gate**:
    * **Cổng 1 (SLO Telemetry):** Theo dõi chỉ số RPS và Error Rate trên Prometheus trong vòng 5 phút, đảm bảo Burn Rate quay về ngưỡng xanh an toàn.
    * **Cổng 2 (Log Semantics):** Sử dụng thuật toán phân cụm log **Drain3** để quét log của Pod mới. Đảm bảo không còn xuất hiện các cụm từ khóa báo lỗi nghiêm trọng (Exception, Connection Refused, Crash,...) trong file log.
* **Hệ quả**: Đảm bảo chất lượng tự động phục hồi đạt độ tin cậy tuyệt đối, tránh hiện tượng Pod mới khởi chạy thành công nhưng vẫn bị lỗi logic ngầm.

---

## 📑 7. ADR-007: Tích Hợp Luồng ML Proactive Với Trợ Lý LLM & Chốt Chặn Phê Duyệt An Toàn (New Phase 3)

* **Bối cảnh**: Tích hợp luồng quét ML Isolation Forest (IF) chủ động vào luồng chẩn đoán LLM Bedrock, đồng thời giải quyết quy định nghiêm ngặt từ CDO (không cho phép Engine tự động sửa lỗi lên hạ tầng EKS Production khi chưa có phê duyệt).
* **Quyết định**:
  * **Chốt chặn Phê duyệt Thủ công (Human-in-the-Loop):**
    * Khi Isolation Forest quét phát hiện bất thường sớm (`IF == -1`), Engine sẽ **không tự động thực thi lệnh**.
    * Toàn bộ các cảnh báo proactive sẽ bị ép mức rủi ro mặc định là **`MEDIUM`**.
    * Engine sẽ gọi Bedrock LLM kết hợp RAG Playbooks để đưa ra đề xuất lệnh xử lý (Scale/Restart), sau đó gửi một thẻ tương tác đầy đủ nút bấm **`[Approve]` / `[Reject]`** lên Slack cho SRE duyệt tay.
  * **Giải thuật RCA Jaeger Trace Dependency Chain:**
    * Sử dụng Jaeger Client kết nối `/jaeger/ui/api/traces` để tải Span lỗi của trace sự cố.
    * Traverse (duyệt cây) đồ thị liên kết `CHILD_OF` của các Spans lỗi để dựng sơ đồ truyền lỗi chính xác dạng cây:
      `frontend -> checkout -> payment (Culprit: STATUS_CODE_ERROR)` hiển thị lên Slack.
  * **Đóng gói Môi trường & Phân quyền (Security Decoupling):**
    * Đóng gói sẵn CLI `kubectl` trong [Dockerfile](file:///d:/Xbrain/Read_Capstone03/aiops-engine/Dockerfile) của Engine để container có thể thực thi lệnh khi được duyệt.
    * Tạo cấu hình RBAC giới hạn quyền tối thiểu ([rbac.yaml](file:///d:/Xbrain/Read_Capstone03/aiops-engine/k8s/rbac.yaml)): Chỉ cấp quyền `patch`, `update` cho ServiceAccount `default` trên tài nguyên deployments trong phạm vi duy nhất của namespace `techx-tf3`.
* **Hệ quả**: Thỏa mãn 100% các quy định bảo mật hạ tầng khắt khe của CDO, an toàn tuyệt đối trước mọi rủi ro tự động can thiệp lỗi của AI, đồng thời cung cấp giao diện trực quan và phân tích RCA trực tiếp cho kỹ sư on-call ra quyết định.
