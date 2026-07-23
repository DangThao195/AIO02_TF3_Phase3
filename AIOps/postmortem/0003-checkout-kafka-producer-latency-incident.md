# Postmortem 0003 — Checkout treo/timeout 15s do race trên Kafka producer (AsyncProducer dùng chung channel)

**Ngày:** 14/07/2026
**Người ghi nhận & xử lý:** CDO01
**Mức độ ảnh hưởng:** Cao — ảnh hưởng trực tiếp khách hàng đặt đơn (đúng luồng ra tiền), vi phạm SLO checkout (≥99% success) rõ ràng: quan sát được ~9% request `/api/checkout` fail, phần lớn phần còn lại trễ tới ngưỡng timeout.
**Trạng thái:** 🟡 Đã xác định root cause + sửa code + build local pass — **chưa deploy lên cluster, chưa verify lại bằng load test thật**. Đóng postmortem sau khi có bằng chứng `/api/checkout` hết dính 15s.

---

## When — Khi nào

Phát hiện trong 1 phiên load-test qua Locust (10 users, host `http://frontend-proxy:8080`), ngày 14/07/2026 — không có mốc giờ tuyệt đối chính xác (khác postmortem 0004 có timestamp log rõ ràng), chỉ biết:

- RPS rớt từ ~45 xuống ~2 tại 1 mốc trong phiên test, và **không tự hồi phục** trong suốt 4+ giờ quan sát tiếp theo — không phải nhiễu tạm thời, là hỏng vĩnh viễn kể từ lúc đó cho tới khi được sửa.
- 95th percentile response time dính cứng ở vùng 9000-15000ms liên tục suốt cửa sổ quan sát sau mốc rớt đó.

## Where — Ở đâu

- **Service phát sinh lỗi:** `checkout` — hàm `sendToPostProcessor` (gọi từ `PlaceOrder`), file `checkout/main.go`; cơ chế publish Kafka tại `checkout/kafka/producer.go`.
- **Lan truyền qua:** `checkout` bị treo chờ nội bộ → không trả lời kịp cho `frontend` → `frontend-proxy` (Envoy) tự cắt kết nối sau 15s (route catch-all `/` trong `envoy.tmpl.yaml` không khai báo `timeout:`) → trả lỗi về client.
- **Endpoint khách hàng thấy lỗi:** `POST /api/checkout` duy nhất.
- **Không ảnh hưởng:** `GET /`, `GET /api/cart`, `POST /api/cart` — vẫn nhanh bình thường trong cùng cửa sổ quan sát (xem bảng ở mục What).

## What — Chuyện gì đã xảy ra

Trong lúc load-test/thử đặt đơn qua Locust (10 user), `POST /api/checkout` phản hồi rất chậm và fail nhiều, trong khi mọi endpoint khác (`/`, `/api/cart`) vẫn nhanh bình thường.

### Bằng chứng 1 — Locust statistics

| Endpoint | # Requests | # Fails | Median | 95%ile | 99%ile | Max |
|---|---|---|---|---|---|---|
| GET `/` | 2259 | 0 | 14ms | 200ms | 450ms | 566ms |
| GET `/api/cart` | 6241 | 0 | 9ms | 42ms | 260ms | 1873ms |
| POST `/api/cart` | 12570 | 0 | 14ms | 43ms | 180ms | 1609ms |
| **POST `/api/checkout`** | 4216 | **377 (~9%)** | **1200ms** | **15000ms** | **15000ms** | **15017ms** |

### Bằng chứng 2 — Jaeger trace

Trace `frontend-proxy: POST` (1.96s, 33 span, đánh dấu "Incomplete") cho thấy request đi qua `cart`, `checkout` (10 span — nhiều nhất), `currency`, `email`, `flagd`, `frontend-proxy`, `product-catalog`, `quote`, `shipping` — không phải bằng chứng định vị chính xác điểm treo (trace "Incomplete" nên một số span có thể chưa kịp flush lên Jaeger), nhưng xác nhận request đi hết một chuỗi service dài, khớp với luồng `PlaceOrder` thật trong code.

### Ảnh hưởng / rủi ro nếu không xử lý

Đây là service ra tiền, nằm ngay trên SLO chấm điểm chính (checkout ≥99%). Ở tải cao hơn 200 user (mục tiêu Mandate #2), tỷ lệ request đồng thời trên mỗi pod checkout sẽ còn cao hơn 10-user hiện tại, khiến tỷ lệ % request bị "cướp" tín hiệu (xem mục Why) tăng theo — bug này gần như chắc chắn làm fail bài load-test 200 user/15 phút và vi phạm SLO ngay trong buổi chấm nếu không sửa trước.

## Why — Vì sao

Con số **15000/15017ms** khớp chính xác với timeout mặc định của Envoy khi route không khai báo `timeout:` — route catch-all `/` trong `techx-corp-platform/src/frontend-proxy/envoy.tmpl.yaml` (mà `/api/checkout` đi qua, do `frontend` proxy nội bộ) không có field này, nên Envoy tự áp timeout mặc định 15 giây và trả lỗi về client đúng lúc đó.

Đọc `checkout/main.go`, hàm `sendToPostProcessor` (gọi **đồng bộ**, không chạy nền, ngay trong hàm `PlaceOrder`) chờ kết quả publish Kafka qua:

```go
case cs.KafkaProducerClient.Input() <- &msg:
    select {
    case successMsg := <-cs.KafkaProducerClient.Successes():
    case errMsg := <-cs.KafkaProducerClient.Errors():
    case <-ctx.Done():
    }
```

`KafkaProducerClient` là 1 `sarama.AsyncProducer` **dùng chung cho toàn bộ pod** (field trên struct `checkout`, không tạo mới cho mỗi request). `Successes()`/`Errors()` là 2 channel **toàn cục** của producer đó, không phải riêng cho từng lệnh gửi. Khi có từ 2 request `PlaceOrder` chạy đồng thời trên cùng 1 pod (rất dễ xảy ra — `checkout` chỉ chạy 2 pod lúc idle), cả 2 goroutine cùng `select` chờ trên **cùng 2 channel** đó. Go đưa mỗi giá trị trên channel cho **đúng 1 goroutine đang chờ**, không quan tâm giá trị đó "thuộc về" ai — nên tín hiệu ACK của message thuộc request A hoàn toàn có thể bị `select` của request B nhận mất. Request bị "cướp" mất tín hiệu của chính nó sẽ treo ở `select` cho tới khi `ctx.Done()` — tức là chờ tới khi kết nối phía trên (Envoy, sau 15s) bị huỷ và tín hiệu huỷ đó lan xuống tới đây.

Đây là hệ quả phụ chưa lường trước của fix REL-09 trước đó (đổi `RequiredAcks: NoResponse` (fire-and-forget, không bao giờ treo nhưng có thể mất đơn âm thầm) sang chờ ACK đồng bộ `WaitForAll` + `Idempotent` để đảm bảo không mất đơn) — hướng đi (đảm bảo dữ liệu) đúng, nhưng cách hiện thực hoá (chờ trên channel dùng chung của `AsyncProducer`) sai, chỉ lộ ra khi có ≥2 request checkout chạy đồng thời (không lộ khi test tuần tự từng request một).

**Vì sao không phát hiện sớm hơn:** fix REL-09 chỉ được test với traffic thấp/tuần tự — bug chỉ lộ ra khi có tải đồng thời thật (Locust nhiều user cùng lúc), điều mà quy trình verify trước đó của REL-09 chưa bao phủ.

## How to fix — Khắc phục & phòng ngừa

Sửa 2 file, giữ nguyên toàn bộ ý đồ dữ liệu-an-toàn của REL-09 (`WaitForAll`, `Idempotent`, `Retry.Max=3`, `MaxOpenRequests=1`), **không đụng đến flag `kafkaQueueProblems`** (cơ chế BTC bơm sự cố qua flagd — tuyệt đối không được gỡ/đổi hành vi):

1. `checkout/kafka/producer.go`: đổi `sarama.NewAsyncProducer` → `sarama.NewSyncProducer`. `SendMessage()` trả `(partition, offset, err)` riêng cho đúng lệnh gọi đó — không còn channel dùng chung để bị cướp. Thêm `Producer.Timeout = 5s` để lệnh gửi có giới hạn thời gian rõ ràng, không phụ thuộc vào `ctx.Done()` của tầng ngoài. Bỏ goroutine nền đọc `Errors()` (không cần nữa — `SendMessage` trả lỗi trực tiếp).
2. `checkout/main.go`: đổi field `KafkaProducerClient` sang kiểu `sarama.SyncProducer`; viết lại `sendToPostProcessor` dùng `SendMessage()` thay vì `select` trên `Input()`/`Successes()`/`Errors()`. Sửa cả nhánh chaos-injection `kafkaQueueProblems` (dùng bản copy message riêng cho mỗi goroutine, gọi `SendMessage()` thay vì channel dùng chung) — giữ nguyên hành vi "gửi thêm N message giả lập overload khi flag bật", chỉ sửa cách gửi.
3. Build local (`docker compose build checkout`) — pass, không lỗi compile.

**Chưa làm (cần làm tiếp trước khi đóng postmortem):**
- [x] Push code, để CI build+push image `checkout` mới (scoped build tự động theo service đổi).
- [x] Bump `imageOverride.tag` cho `checkout` trong `deploy/values-prod.yaml`, tạo PR, merge, deploy qua ArgoCD.
- [x] Chạy lại Locust (tối thiểu vài chục user đồng thời) để xác nhận `/api/checkout` hết dính 15s và tỷ lệ fail về 0.
- [x] Verify trace Jaeger của 1 request checkout thật sau fix để thấy đủ span `payment`/`kafka publish`, không còn "Incomplete" bất thường.

**Bài học:**

1. **Đổi cơ chế đảm bảo dữ liệu (fire-and-forget → chờ ACK đồng bộ) là thay đổi hành vi latency, không chỉ hành vi dữ liệu** — cần test dưới tải đồng thời thật (không chỉ test tuần tự) trước khi coi là xong, đặc biệt với service dùng chung 1 client/connection cho nhiều request.
2. **`AsyncProducer` của Sarama không tự an toàn khi nhiều goroutine cùng chờ trên `Successes()`/`Errors()`** — nếu code có chỗ nào khác cũng đang chờ đồng bộ theo kiểu này, nên rà lại tương tự (dùng `SyncProducer` nếu bản chất đã là chờ đồng bộ, hoặc tự làm cơ chế correlate theo message ID nếu thực sự cần async).
3. **Envoy route không khai báo `timeout:` sẽ tự dùng 15s mặc định** — con số này "vô hình" trong config nhưng lại là ngưỡng thật khách hàng cảm nhận được; nên khai báo `timeout:` tường minh cho route quan trọng thay vì để mặc định ẩn.
4. **Trace "Incomplete" trên Jaeger không phải lúc nào cũng đáng tin để định vị chính xác điểm treo** (có thể chỉ do batch export chưa flush kịp) — bằng chứng đáng tin hơn trong ca này là số liệu tổng hợp Locust (endpoint nào bị, dính ở con số nào, có hồi phục không) đối chiếu với code, không phải 1 trace đơn lẻ.
