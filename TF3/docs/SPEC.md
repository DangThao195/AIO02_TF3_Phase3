# Đặc tả Kỹ thuật (Technical Specification) - TF3 AIOps Engine

## 1. Tổng quan dự án (Project Overview)
**TF3 AIOps Engine** là một hệ thống AI dành cho vận hành (AIOps - Artificial Intelligence for IT Operations) được thiết kế chuyên biệt cho hệ sinh thái TechX Corp Platform. Hệ thống này đóng vai trò như một bộ não giám sát, tự động phát hiện, phân tích và đề xuất phương án khắc phục (remediation) cho các sự cố hệ thống ngay trong thời gian thực.

Mục tiêu chính của AIOps Engine là giảm thiểu thời gian MTTR (Mean Time To Recovery - Thời gian trung bình để phục hồi) thông qua việc tự động hóa quá trình xử lý sự cố.

## 2. Kiến trúc Hệ thống (System Architecture)
Hệ thống được triển khai theo mô hình Microservices trên nền tảng Cloud AWS.
*   **Môi trường triển khai (Environment):** Kubernetes (Amazon EKS)
*   **Namespace:** `techx-tf3`
*   **Khu vực AWS (AWS Region):** `us-east-1` (N. Virginia)
*   **Registry lưu trữ (Container Registry):** Amazon ECR (`197826770971.dkr.ecr.ap-southeast-1.amazonaws.com`)

### 2.1 Các thành phần cốt lõi (Core Components)
1.  **Payment Service (Node.js):** Dịch vụ thanh toán cốt lõi xử lý giao dịch. Đây là mục tiêu chính để giám sát và thực hiện giả lập lỗi.
2.  **AIOps Engine (Python):** Module trí tuệ nhân tạo, phân tích log/metrics để phát hiện bất thường (anomaly detection), tổng hợp dữ liệu và đưa ra cảnh báo.
3.  **OpenFeature / flagd:** Hệ thống quản lý Feature Flag, được sử dụng để tiêm lỗi (Fault Injection) phục vụ cho Chaos Engineering.

## 3. Các tính năng cốt lõi (Core Capabilities)

### 3.1 Phát hiện sự cố (Incident Detection)
*   **Cơ chế:** Engine liên tục thu thập và phân tích các chỉ số (metrics) như CPU, Memory, số lượng kết nối (Connection Pool), tỷ lệ lỗi HTTP 5xx, và độ trễ (Latency).
*   **Xử lý:** Khi phát hiện một tập hợp các chỉ số vượt ngưỡng an toàn (ví dụ: `INCIDENT-2026-004`), Engine sẽ ngay lập tức ghi nhận trạng thái sự cố.

### 3.2 Cảnh báo & Tương tác (Alerting & Notification)
*   Hệ thống được tích hợp sâu với **Slack** thông qua **Block Kit**.
*   Thay vì chỉ gửi cảnh báo văn bản đơn thuần, hệ thống gửi các thẻ thông tin tương tác (Interactive Blocks).
*   Thẻ thông tin bao gồm chi tiết lỗi, phân tích nguyên nhân gốc rễ (Root Cause Analysis), và đặc biệt là các **nút hành động (Action Buttons)** (ví dụ: "Phê duyệt tự động mở rộng - Approve Auto-scaling").

### 3.3 Khắc phục tự động (Automated Remediation)
*   Sau khi quản trị viên (hoặc tư lệnh) nhấn nút phê duyệt trên Slack, hệ thống nhận được Webhook phản hồi.
*   AIOps Engine sẽ thực thi các kịch bản khắc phục (Runbooks) như: tăng số lượng bản sao (replica) qua HPA, khởi động lại Pod, hoặc tự động chặn các IP độc hại.

### 3.4 Giả lập lỗi & Chaos Engineering (Fault Injection)
*   Sử dụng ConfigMap `flagd-config` của Kubernetes để quản lý các cờ tính năng (Feature Flags).
*   Cho phép bật/tắt các lỗi như `paymentFailure` (Lỗi thanh toán), `databaseTimeout` (Chậm cơ sở dữ liệu) ngay lập tức mà không cần deploy lại code.

## 4. Bảo mật & Cấu hình (Security & Configuration)
1.  **Quản lý Bí mật (Secrets Management):** Mọi thông tin nhạy cảm như Slack Webhook URL, API Keys đều được lưu trữ an toàn bằng Kubernetes Secrets (`aiops-engine-secrets`).
2.  **Quản lý Quyền truy cập (IAM & ECR Policy):** 
    *   Hệ thống thiết lập ECR Cross-Account Pull Policy, cho phép tài khoản AWS của đội CDO (`arn:aws:iam::[CDO_ACCOUNT_ID]:root`) có quyền pull các Docker image (như `tf-2-ai-engine`) một cách hợp lệ và bảo mật.
    *   Giới hạn quyền IAM của các Pods theo nguyên tắc quyền tối thiểu (Least Privilege).
