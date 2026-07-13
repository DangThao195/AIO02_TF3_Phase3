# Hướng Dẫn Deploy Hệ Thống Chạy Real LLM (AWS Bedrock) Trên AWS EKS

Tài liệu này lưu giữ chi tiết các bước để cấu hình và triển khai (deploy) bình thường toàn bộ hệ thống TechX Corp Platform sử dụng mô hình AI thật (AWS Bedrock Nova Lite via LiteLLM Service) trên Kubernetes EKS Cluster.

---

## BƯỚC 1: Khởi tạo/Kiểm tra Kubernetes Secret chứa API Key

Trước hết, bạn cần đảm bảo API Key Bedrock (chuỗi bắt đầu bằng `ABSK...`) đã được tạo an toàn trong EKS Cluster:

### 1. Kiểm tra xem Secret đã tồn tại chưa:
```bash
# Thay <namespace_cua_TF> bằng namespace EKS của bạn (ví dụ: techx-tf1)
kubectl -n <namespace_cua_TF> get secret llm-api-key
```

### 2. Nếu chưa có, chạy lệnh sau để tạo mới (Thay thế giá trị ABSK bằng Key thực tế do BTC cấp):
```bash
kubectl -n <namespace_cua_TF> create secret generic llm-api-key \
  --from-literal=key=<REAL_ABSK_KEY_PROVIDED_BY_BTC>
```

---

## BƯỚC 2: Cấu hình tệp Helm Values [deploy/values-aio-llm.yaml](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/deploy/values-aio-llm.yaml)

Đảm bảo nội dung tệp **[deploy/values-aio-llm.yaml](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/deploy/values-aio-llm.yaml)** đã trỏ đúng Service LiteLLM nội bộ và đúng model Nova Lite:

```yaml
# deploy/values-aio-llm.yaml
components:
  product-reviews:
    envOverrides:
      - name: LLM_BASE_URL
        value: http://litellm-service:4000/v1        # Service LiteLLM chạy trong cluster EKS
      - name: LLM_MODEL
        value: amazon.nova-lite-v1:0                 # Cấu hình model Nova Lite chính xác
      - name: OPENAI_API_KEY
        valueFrom: { secretKeyRef: { name: llm-api-key, key: key } }
```

---

## BƯỚC 3: Chạy Lệnh Nâng Cấp Triển Khai (Helm Upgrade)

Di chuyển vào thư mục gốc của dự án (`XBrain-Phase3`) trên EKS client terminal và chạy lệnh deploy kết hợp các tệp values:

```bash
# Chạy nâng cấp Helm (thay <namespace_cua_TF> bằng namespace EKS thực tế của bạn)
helm upgrade --install techx-corp ./techx-corp-chart -n <namespace_cua_TF> \
  -f deploy/values-observability.yaml \
  -f deploy/values-flagd-sync.yaml \
  -f deploy/values-aio-llm.yaml
```

> [!IMPORTANT]
> Phải luôn đính kèm `-f deploy/values-flagd-sync.yaml` để flagd đồng bộ trạng thái sự cố từ BTC, nếu không hệ thống sẽ bị coi là vi phạm quy chế.

---

## BƯỚC 4: Kiểm tra Trạng Thái Hoạt Động

### 1. Kiểm tra các Pod đã Running và Ready:
```bash
kubectl -n <namespace_cua_TF> get pods
```

### 2. Xem log của Pod `product-reviews` nếu có sự cố:
```bash
kubectl -n <namespace_cua_TF> logs deployment/product-reviews -c product-reviews
```

---

## BƯỚC 5: Truy Cập Thử Nghiệm

Thực hiện Port-forward cổng proxy frontend để truy cập giao diện storefront từ trình duyệt máy cá nhân:

```bash
kubectl -n <namespace_cua_TF> port-forward svc/frontend-proxy 8080:8080
```
* Mở trình duyệt và truy cập: **`http://localhost:8080`**
* Vào trang chi tiết sản phẩm và xác nhận tính năng tóm tắt review bằng AI hoạt động ổn định.
