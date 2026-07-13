file_path = "../docs/ONBOARDING_AND_TESTING_GUIDE.md"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Target section 7
old_section = """## 📈 7. Chuyển Lên Chạy Live Trên Cụm EKS thật

Khi đã test Sandbox thành công và sẵn sàng triển khai thực tế trên cụm EKS:
1. Đảm bảo máy tính của bạn đã kết nối được tới cụm Kubernetes (`kubectl get pods -A` chạy bình thường).
2. Chạy port-forwarding các dịch vụ giám sát:
   ```bash
   # Terminal 1: Port-forward frontend proxy & Jaeger UI
   kubectl -n techx-tf3 port-forward svc/frontend-proxy 8080:8080
   ```
3. Đổi biến môi trường trong file `.env`:
   ```bash
   AIOPS_SIMULATION_MODE=false
   ```
4. Khởi động lại máy chủ Uvicorn. Lúc này hệ thống sẽ tự động quét trực tiếp dữ liệu metric Prometheus và traces Jaeger từ cụm Kubernetes thật!"""

new_section = """## 📈 7. Hướng Dẫn Kết Nối & Chạy Live Trên Cụm EKS Thật (Production Mode)

Khi đã kiểm thử thành công trên Sandbox và muốn chuyển sang bắt lỗi live trên cụm EKS thực tế, hãy thực hiện theo các bước chi tiết sau:

### Bước 7.1: Thiết lập cấu hình kết nối EKS (Kubeconfig)
Đảm bảo bạn đã cấu hình AWS CLI cục bộ và có quyền SRE trên cụm. Chạy lệnh sau để cập nhật kubeconfig nhằm kết nối kubectl tới cụm EKS:
```bash
aws eks update-kubeconfig --region ap-southeast-1 --name techx-capstone-eks
```
Kiểm tra kết nối bằng cách liệt kê các Pods hoạt động trong namespace dự án:
```bash
kubectl get pods -n techx-tf3
```

### Bước 7.2: Mở SSM Tunnel bảo mật (Nếu chạy qua AWS Bastion Host)
Trong trường hợp cụm EKS hoặc các API giám sát nằm trong mạng Private VPC và yêu cầu kết nối bảo mật qua SSM Session Manager (Bastion host):
* **On Windows:**
  ```powershell
  $env:PATH += ";C:\\Program Files\\Amazon\\SessionManagerPlugin\\bin"
  aws ssm start-session --target i-0abcd1234efgh5678 --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["80"],"localPortNumber":["8080"]}'
  ```
* **On Linux/macOS:**
  ```bash
  aws ssm start-session --target i-0abcd1234efgh5678 --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["80"],"localPortNumber":["8080"]}'
  ```

### Bước 7.3: Mở Port-Forwarding cho bộ ba giám sát (Telemetry Services)
Để AIOps Engine có thể lấy dữ liệu thật từ Prometheus, Jaeger và OpenSearch, bạn cần mở **3 tab terminal mới** để thực hiện port-forward các service tương ứng về local máy cá nhân:

* **Tab 1: Ánh xạ Prometheus (Cổng 9090)**
  ```bash
  kubectl -n techx-tf3 port-forward svc/prometheus-server 9090:80
  ```
  *(Cho phép Engine truy cập Prometheus để tính toán SLO burn-rate và Z-Score hạ tầng)*

* **Tab 2: Ánh xạ Jaeger Query (Cổng 16686)**
  ```bash
  kubectl -n techx-tf3 port-forward svc/jaeger-query 16686:16686
  ```
  *(Cho phép Engine truy cập Jaeger API để phân tích cấu trúc vết lỗi cuộc gọi Trace DAG)*

* **Tab 3: Ánh xạ OpenSearch (Cổng 9200)**
  ```bash
  kubectl -n techx-tf3 port-forward svc/opensearch 9200:9200
  ```
  *(Cho phép Engine truy cập Elasticsearch/OpenSearch để kéo log thô phục vụ Drain3)*

### Bước 7.4: Kiểm tra kết nối tới các dịch vụ live
Trước khi chạy Engine, hãy đảm bảo các cổng cục bộ đã thông suốt bằng cách chạy thử cURL:
```bash
# Kiểm tra Prometheus Live API
curl http://localhost:9090/api/v1/query?query=up

# Kiểm tra OpenSearch Live API
curl http://localhost:9200
```

### Bước 7.5: Cập nhật biến môi trường và chạy Engine
Mở file `aiops-engine/.env` và đổi cấu hình từ Sandbox sang Live EKS:
1. Tắt chế độ giả lập:
   ```bash
   AIOPS_SIMULATION_MODE=false
   ```
2. Cập nhật các đường dẫn URL trỏ về cổng port-forward thực tế:
   ```bash
   JAEGER_URL=http://localhost:16686
   PROMETHEUS_URL=http://localhost:9090
   OPENSEARCH_URL=http://localhost:9200
   ```
3. Khởi động lại máy chủ Engine:
   ```bash
   python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

Hệ thống sẽ lập tức quét chỉ số trực tiếp từ EKS thật, vẽ đồ thị RCA và tự động gửi cảnh báo thẻ duyệt sự cố live về Slack của bạn!"""

content = content.replace(old_section, new_section)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: ONBOARDING_AND_TESTING_GUIDE.md updated with detailed live connection steps.")
