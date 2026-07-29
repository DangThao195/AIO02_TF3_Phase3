# Postmortem 0001 — Accounting OOMKilled loop + sự cố tự gây ra khi khắc phục (ECR lifecycle policy xoá nhầm image)

**Ngày:** 08/07/2026
**Người ghi nhận & xử lý:** arthur (CDO02)
**Mức độ ảnh hưởng:** Trung bình (không ảnh hưởng checkout/khách hàng trực tiếp; có rủi ro mất dữ liệu kế toán tạm thời + gián đoạn khả năng deploy lại `accounting` trong ~1 giờ)
**Trạng thái:** ✅ Đã đóng — 20/20 image khôi phục qua CI, `accounting` chạy ổn định 350Mi, 0 restart sau khi vá.

---

## Tóm tắt

Phát hiện `accounting` bị `OOMKilled` lặp lại (44 lần/~19 giờ) do memory limit quá thấp so với tải thật. Trong lúc khắc phục (tăng memory limit + `helm upgrade`), phát hiện thêm sự cố thứ hai: pod mới không pull được image vì phần lớn image trên ECR đã bị **chính lifecycle policy do CDO02 đặt lúc dựng hạ tầng** xoá nhầm.

## Sự cố 1 — `accounting` OOMKilled lặp lại

**Triệu chứng:** `kubectl get pods` cho thấy `accounting` có 44 lần restart trong khi các pod khác ổn định. `kubectl describe pod` xác nhận `lastState.terminated.reason: OOMKilled`, `exitCode: 137`.

**Nguyên nhân gốc:** `techx-corp-chart/values.yaml` đặt `components.accounting.resources.limits.memory: 120Mi` — quá thấp so với tải thật. `accounting` là Kafka consumer (.NET, EF Core + Confluent Kafka client) liên tục nhận sự kiện đơn hàng từ `load-generator` (Locust) đang chạy nền sinh traffic giả lập; dưới tải liên tục, tiến trình .NET vượt trần 120Mi và bị kernel/kubelet kill.

**Vì sao không ai phát hiện sớm hơn:** `accounting` là consumer bất đồng bộ, không nằm trên đường đi của checkout — khách hàng đặt hàng vẫn thành công dù `accounting` chết giữa chừng, nên không có triệu chứng nào lộ ra ở tầng khách hàng. Chỉ phát hiện được nhờ chủ động soi `kubectl get pods` theo cột RESTARTS lúc kiểm tra trạng thái hệ thống định kỳ.

**Rủi ro nếu không xử lý:** Kafka consumer dùng `EnableAutoCommit: true` — nếu tiến trình bị kill giữa lúc đang xử lý (đã commit offset nhưng chưa kịp ghi DB xong), bản ghi kế toán của đơn hàng đó có thể bị mất vĩnh viễn (không retry lại vì offset đã trôi qua).

**Đã xử lý:** Tăng `components.accounting.resources.limits.memory` từ `120Mi` → `350Mi` qua `helm upgrade --set`.

## Sự cố 2 — ECR lifecycle policy xoá nhầm 17/20 image (tự gây ra trong lúc xử lý Sự cố 1)

**Triệu chứng:** Sau khi `helm upgrade` tăng memory limit cho `accounting`, pod mới báo `ImagePullBackOff` — `012619468490.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:d2bc367-accounting: not found`. Pod cũ (120Mi, đang crash loop) vẫn chạy được vì node đã cache sẵn layer image từ trước.

**Nguyên nhân gốc:** Lúc dựng ECR repo (07/07), CDO02 đặt lifecycle policy:
```json
{"rules":[{"selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":15},"action":{"type":"expire"}}]}
```
Policy này **tính gộp toàn bộ repo làm 1 nhóm**, không tách theo từng service (thiếu `tagPrefixList`). Mỗi lần push 1 service tạo ra 3 entry trong ECR (manifest list đa kiến trúc + 2 image riêng amd64/arm64) — với 20 service, tổng số entry vượt xa ngưỡng 15 rất nhanh. ECR tự động "expire" (xoá) các image cũ nhất để đưa tổng số về ≤15, xoá luôn nhiều tag đang được Helm release tham chiếu tới. Kiểm tra lúc phát hiện: chỉ còn 3/20 tag sống sót (`currency`, `flagd-ui`, `frontend`).

**Vì sao đây là lỗi thiết kế, không phải lỗi vận hành:** Ý định ban đầu của lifecycle policy là "giữ 15 bản build gần nhất **của mỗi service**" (tránh phình chi phí lưu trữ qua nhiều lần build lại) — nhưng viết thiếu `tagPrefixList` khiến ECR hiểu thành "giữ 15 image gần nhất **toàn repo**", một hành vi hoàn toàn khác và nguy hiểm hơn nhiều.

**Đã xử lý:**
1. `aws ecr delete-lifecycle-policy` — xoá ngay policy sai để ngừng mất thêm image (khẩn cấp, ưu tiên trước mọi thứ khác).
2. Kích hoạt lại workflow `build-push-ecr.yml` (CI/CD do CDO01 dựng, dùng OIDC role có sẵn) với `image_tag=d2bc367` để build + push lại đúng tag đang được Helm release tham chiếu — không cần đổi gì ở phía Helm/K8s.

**Việc còn treo (chưa làm trong postmortem này):**
- Nếu muốn dùng lại lifecycle policy để kiểm soát chi phí lưu trữ ECR, phải viết lại đúng với `tagPrefixList` cho từng service (hoặc dùng `tagPatternList` theo service name), test kỹ trên môi trường không ảnh hưởng production trước khi áp dụng lại.
- Cân nhắc bật cảnh báo (CloudWatch/EventBridge) khi ECR expire image, để phát hiện sớm hơn nếu việc này lặp lại.

## Bài học

1. **Mọi thay đổi lên tài nguyên dùng chung (ECR, IAM, VPC...) cần test kỹ phạm vi ảnh hưởng trước khi áp dụng** — lifecycle policy tưởng vô hại (dọn dẹp, tiết kiệm chi phí) lại là nguyên nhân gây gián đoạn nghiêm trọng hơn cả sự cố ban đầu đang cố sửa.
2. **Alert dựa trên RESTARTS count nên được tự động hoá** (Grafana alert khi restart > ngưỡng trong X phút) thay vì phải chủ động chạy `kubectl get pods` để phát hiện — đưa vào backlog Reliability.
3. **CI/CD do team khác dựng (CDO01) đáng tin cậy hơn build tay cục bộ** — máy cá nhân thiếu `make`/tooling gây thất bại build local; nên ưu tiên dùng pipeline chung ngay từ đầu thay vì build tay khi cần gấp.
