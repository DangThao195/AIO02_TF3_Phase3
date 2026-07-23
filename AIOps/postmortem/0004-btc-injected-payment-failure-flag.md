# Postmortem 0004 — BTC bơm lỗi qua flagd (`paymentFailure`), checkout fail nhanh ~14:22-14:34 14/07/2026

**Ngày:** 14/07/2026
**Người ghi nhận & xử lý:** CDO01 — điều tra theo yêu cầu khẩn từ BTC/tư lệnh
**Mức độ ảnh hưởng:** Cao — khách hàng đặt đơn bị từ chối thanh toán hàng loạt trong ~12 phút, đúng luồng ra tiền. Đây là **sự cố do BTC chủ động bơm vào** (fault injection có kiểm soát qua flagd), không phải bug hệ thống.
**Trạng thái:** ✅ Đã xác định chính xác nguyên nhân, có bằng chứng đầy đủ. Flag đã tự tắt (`off`) tại thời điểm điều tra — hệ thống đã hồi phục, không cần hành động khắc phục thêm ở phía TF (đây không phải lỗi của TF).

---

## When — Khi nào

**14:22:16 → 14:34:00 (14/07/2026), kéo dài ~12 phút.**

- Log lỗi đầu tiên tại `payment`: `2026-07-14 14:22:16.825 +07:00`.
- Log lỗi cuối cùng: `2026-07-14 14:34:00.123 +07:00` (chỉ 1 lỗi lẻ tẻ sau mốc này, coi như đã kết thúc đúng 14:34).
- Khớp gần khít khung giờ user phản ánh (14:15-14:30) mà BTC nêu — sai lệch nhỏ có thể do độ trễ giữa lúc lỗi thật xảy ra và lúc user/TF nhận ra để báo cáo thời gian.
- Query trực tiếp OFREP endpoint của flagd lúc điều tra (~sau 14:34):
  ```json
  {"value":0,"key":"paymentFailure","reason":"STATIC","variant":"off","metadata":{}}
  ```
  → Flag đã về `off`, hệ thống đã tự hồi phục — khớp với việc đây là 1 đợt bơm lỗi có kiểm soát, có giới hạn thời gian, không phải sự cố kéo dài.

## Where — Ở đâu

- **Service phát sinh lỗi:** `payment` — hàm `charge()`, file `src/payment/charge.js:37`.
- **Lan truyền qua:** `checkout` (`PlaceOrder` gọi `payment.charge()`) → `frontend` (`/api/checkout`) → `frontend-proxy` → trả lỗi về client.
- **Endpoint khách hàng thấy lỗi:** `POST /api/checkout` duy nhất.
- **Không ảnh hưởng:** `GET /`, `GET /api/cart`, `POST /api/cart` — toàn bộ vẫn 0 fail trong cùng khung giờ (xem bảng ở mục What).
- **Pod cụ thể có log:** `payment-59dd46cc87-p4zlm`.

## What — Chuyện gì đã xảy ra

`POST /api/checkout` fail hàng loạt (~85% trong 1 đợt Locust quan sát được: 28/33 request) với phản hồi **rất nhanh** (34-59ms, không phải treo/timeout như sự cố Kafka đã xử lý trước đó — xem `docs/postmortem/0003-...md`). Đây là ca **khác hoàn toàn** sự cố Kafka: lần này lỗi xảy ra ngay tức thì tại bước thanh toán, không phải do checkout bị treo chờ.

### Bằng chứng 1 — Locust: fail nhanh, không phải treo

| Endpoint | # Requests | # Fails | Median | 95%ile | 99%ile | Max |
|---|---|---|---|---|---|---|
| GET `/` | 28 | 0 | 11ms | 50ms | 55ms | 55ms |
| GET `/api/cart` | 60 | 0 | 8ms | 12ms | 14ms | 14ms |
| POST `/api/cart` | 111 | 0 | 13ms | 19ms | 98ms | 1563ms |
| **POST `/api/checkout`** | 33 | **28 (~85%)** | 34ms | 49ms | 59ms | 59ms |

→ Toàn bộ request checkout (kể cả fail) đều trả lời trong **dưới 60ms** — không có dấu hiệu hang/timeout. Đây là fail **chủ động** (1 service trong chuỗi chủ động throw error), không phải nghẽn tài nguyên/concurrency.

### Bằng chứng 2 — Jaeger trace (`load-generator: user_checkout_single`, ví dụ trace `7e11ce7...`)

Trace 48.33ms, 10 service, 30 span — chuỗi `frontend-proxy` → `frontend` → `checkout` đều bị đánh dấu lỗi (icon "!" đỏ) ngay từ tầng ngoài cùng, lan từ trong ra (checkout lỗi trước, rồi frontend/frontend-proxy phản ánh lỗi đó lên client) — khớp với việc `checkout.PlaceOrder` gọi `payment.charge()` và nhận lỗi trả về ngay, không phải bị treo.

Jaeger search cùng khung giờ (~14:27-14:34pm) cho thấy hàng loạt trace màu đỏ (error) xen kẽ liên tục, không phải 1-2 trace lẻ tẻ — khớp tỷ lệ fail cao quan sát ở Locust.

![jaeger](./images/image.png)

![jaeger-traces-id](./images/image-1.png)

### Dashboard

![dashboard](./images/dashboard.png)

### Bằng chứng 3 — Log `payment` pod, có timestamp chính xác

```
kubectl logs -n techx-tf3 <payment-pod> --since=25m
```

171 lần log lỗi với nội dung giống hệt nhau:

```
body: 'Payment request failed. Invalid token. app.loyalty.level=gold',
error: {
  type: 'Error',
  message: 'Payment request failed. Invalid token. app.loyalty.level=gold',
  stack: 'Error: Payment request failed. Invalid token. app.loyalty.level=gold\n' +
    '    at module.exports.charge (/usr/src/app/charge.js:37:13)\n' +
    '    at async Object.chargeServiceHandler [as charge] (/usr/src/app/index.js:21:22)'
}
```

Payload đầy đủ của 1 log lỗi:

```javascript
{
  resource: {
    attributes: {
      'process.pid': 1,
      'process.executable.name': '/nodejs/bin/node',
      'process.executable.path': '/nodejs/bin/node',
      'process.command_args': [
        '/nodejs/bin/node',
        '--require=./opentelemetry.js',
        '/usr/src/app/node_modules/thread-stream/lib/worker.js'
      ],
      'process.runtime.version': '22.22.0',
      'process.runtime.name': 'nodejs',
      'process.runtime.description': 'Node.js',
      'process.command': '/usr/src/app/node_modules/thread-stream/lib/worker.js',
      'os.type': 'linux',
      'os.version': '6.12.90-120.164.amzn2023.x86_64',
      'host.name': 'payment-59dd46cc87-p4zlm',
      'host.arch': 'amd64',
      'service.name': 'payment'
    }
  },
  instrumentationScope: { name: 'payment-logger', version: '1.0.0', schemaUrl: undefined },
  timestamp: 1784013736825000,
  traceId: 'dc02421a522f003d60a558c6ffbb1670',
  spanId: '811105799859658c',
  traceFlags: '01',
  severityText: 'warn',
  severityNumber: 13,
  body: 'Payment request failed. Invalid token. app.loyalty.level=gold',
  attributes: {
    err: {
      type: 'Error',
      message: 'Payment request failed. Invalid token. app.loyalty.level=gold',
      stack: 'Error: Payment request failed. Invalid token. app.loyalty.level=gold\n' +
        '    at module.exports.charge (/usr/src/app/charge.js:37:13)\n' +
        '    at process.processTicksAndRejections (node:internal/process/task_queues:105:5)\n' +
        '    at async Object.chargeServiceHandler [as charge] (/usr/src/app/index.js:21:22)'
    }
  }
}
```

#### Tóm tắt thông tin lỗi (Trace Context)

| Thuộc tính | Giá trị | Ý nghĩa |
| :--- | :--- | :--- |
| **Service** | `payment` | Tên dịch vụ (microservice) phát sinh lỗi. |
| **Host / Pod** | `payment-59dd46cc87-p4zlm` | Tên container/pod đang chạy dịch vụ. |
| **Trace ID** | `dc02421a522f003d60a558c6ffbb1670` | ID dùng để trace request xuyên suốt hệ thống. |
| **Span ID** | `811105799859658c` | ID của block thực thi cụ thể gây ra log này. |
| **Mức độ (Severity)** | `warn` (13) | Cảnh báo hệ thống. |
| **Thông báo lỗi** | *Invalid token* | Token thanh toán không hợp lệ (Khách hàng hạng `gold`). |
| **Vị trí lỗi (Stack)** | `charge.js:37:13` | Hàm `charge` trong file `charge.js`. |

### Ảnh hưởng

- Checkout success rate trong cửa sổ ~12 phút: ước tính ~15% (dựa trên mẫu Locust 33 request, 28 fail) — **vi phạm nghiêm trọng** SLO checkout ≥99%.
- Không có rủi ro dữ liệu/tài chính: `payment.charge()` throw lỗi **trước khi** trả về `transactionId`, nên các request bị flag chặn **chưa hề charge thẻ thật** — không có giao dịch "ma" hay thu tiền nhầm. Khách chỉ đơn giản thấy đặt hàng thất bại, có thể thử lại.
- Không liên quan, không chồng lấn với sự cố Kafka đã sửa (postmortem 0003) — 2 sự cố độc lập, xảy ra ở 2 thời điểm khác nhau, có chữ ký triệu chứng khác nhau (treo 15s vs fail nhanh <60ms).

## Why — Vì sao

**Nguyên nhân xác nhận:** flag `paymentFailure` (có sẵn trong catalog flagd, đồng bộ từ nguồn trung tâm BTC) bị bật lên với 1 tỷ lệ % cao trong khung giờ trên, khiến service `payment` chủ động từ chối phần lớn yêu cầu charge thẻ.

`src/payment/charge.js`:

```js
const numberVariant = await OpenFeature.getClient().getNumberValue("paymentFailure", 0);
if (numberVariant > 0) {
  // n% chance to fail with app.loyalty.level=gold
  if (Math.random() < numberVariant) {
    span.setAttributes({'app.loyalty.level': 'gold' });
    throw new Error('Payment request failed. Invalid token. app.loyalty.level=gold');
  }
}
```

Chuỗi text `"Invalid token. app.loyalty.level=gold"` **chỉ có thể** sinh ra từ đúng nhánh này — xác nhận 100% đây là do flag `paymentFailure` (đọc qua OpenFeature/flagd-provider), không phải lỗi thẻ tín dụng thật (những lỗi thẻ khác nằm ở nhánh code phía dưới, thông điệp khác hẳn: "Credit card info is invalid.", "Sorry, we cannot process...", "expired on...").

Catalog `src/flagd/demo.flagd.json` (bản seed cục bộ, tham khảo) định nghĩa `paymentFailure` với các biến thể theo %: `100%, 90%, 75%, 50%, 25%, 10%, off` — giá trị **thật đang chạy** không lấy từ file này mà đồng bộ từ nguồn trung tâm của BTC (`values-flagd-sync.yaml`), nên TF không tự đặt %, chỉ đọc được.

## How to fix — Khắc phục & phòng ngừa

**Không có gì cần dọn dẹp/khắc phục hậu quả cho lần xảy ra vừa rồi** — đây là fault injection có chủ đích của BTC, flag đã tự tắt (`off`), hệ thống đã tự hồi phục hoàn toàn, không có dữ liệu/tài chính bị ảnh hưởng (xem mục Ảnh hưởng). Nhưng vì đây là dạng lỗi BTC **có thể bơm lại bất cứ lúc nào**, việc cần làm là: (1) đóng các khoảng trống về phát hiện/định vị nguyên nhân đã lộ ra qua lần điều tra này, và (2) chủ động thêm khả năng chịu lỗi để lần sau nếu bị bơm lại đúng kiểu này, hệ thống tự chống đỡ được thay vì chỉ biết chờ BTC tắt flag:

1. **Không có alerting tự động cho tỷ lệ lỗi checkout/payment.** Kiểm tra `grafana-alerting` ConfigMap trong cluster hiện **rỗng** (0 alert rule) — chưa có alert nào tự bắn ra khi payment fail tăng đột biến. Phát hiện sự cố lần này hoàn toàn qua: (1) thử đặt đơn thủ công thấy lỗi, (2) chạy Locust thấy tỷ lệ fail cao bất thường trên `/api/checkout`, rồi mới chủ động vào Jaeger/log để tìm nguyên nhân — không phải qua alert tự động.

   Có sẵn 1 dashboard tên `slo-dashboard` trong Grafana (ConfigMap `grafana-dashboard-slo-dashboard`) — chưa xác nhận được có show đúng số liệu payment/checkout success rate theo thời gian thực hay không, cần review riêng.

   **Trạng thái:** chưa triển khai — đang để ở dạng **phương án đề xuất** (không tracked như DoD của ticket incident này, sẽ làm riêng khi có ticket phù hợp). **Phương án đề xuất (15/07):**
   - Alert rule thêm vào `platform-reliability-alerting.yml` (cùng nhóm 4 rule sẵn có: pod restart/OOMKilled/readiness/checkout-unavailable): fire khi checkout success rate < 99% trong 5 phút, dùng đúng query đang chạy ở panel SLO dashboard:
     ```
     1 - (
       (sum(rate(traces_span_metrics_calls_total{service_name="checkout", status_code="STATUS_CODE_ERROR"}[5m])) or vector(0))
       / sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[5m]))
     )
     ```
   - **Lưu ý quan trọng phát hiện được khi thử triển khai (nhưng chưa fix):** `techx-corp-chart/templates/grafana-config.yaml` đang glob `"grafana/provisioning/alerting/*.yaml"`, nhưng cả 2 file rule thật trong repo là đuôi `.yml` (`cart-service-alerting.yml`, `platform-reliability-alerting.yml`) — glob không khớp đuôi file, nên ConfigMap `grafana-alerting` trên cluster **rỗng dù code rule đã viết sẵn đúng cho cả 4 rule cũ**, không chỉ riêng checkout. Đây là root cause thật của việc "0 alert rule" nêu ở trên — cần fix glob (ví dụ đổi thành `*.y*ml`) **trước khi** bất kỳ rule nào ở đây thực sự chạy được trên cluster. Ghi lại ở đây để không mất phát hiện này, xử lý khi có ticket riêng cho hạng mục alerting.

2. **Chưa có cách tra cứu nhanh "flag nào đang bật".** Lần này phải suy luận ngược từ log message + đọc code mới ra chính xác flag nào; nên có 1 lệnh/dashboard xem nhanh toàn bộ giá trị flag hiện tại (vd script `curl` OFREP cho từng flag trong catalog, hoặc dùng `flagd-ui` — hiện đã riêng tư theo Mandate #1, cần đi qua port-forward).

3. **Log lỗi ra `kubectl logs` chỉ có ở `payment` (Node.js).** `checkout` (Go) không in gì ra stdout (log qua OTel exporter thuần), nên khi debug sự cố phải biết đi thẳng vào service nào thật sự log ra console thay vì đoán mò; nên rà lại xem log của `checkout`/các service Go khác có đang đi đúng chỗ (OpenSearch qua otel-collector) để lúc cần vẫn tra được, không chỉ dựa vào `kubectl logs`.

4. **Nếu bị bơm lại đúng `paymentFailure` lần nữa — chịu tải tốt hơn bằng retry ở `checkout`, không phải che số liệu ở `frontend`.**

   Có đề xuất trong team: bắt (try-catch) lỗi gRPC từ `payment` ngay ở `frontend`, trả về HTTP 400 kèm thông báo kiểu "thanh toán thất bại, vui lòng kiểm tra lại thẻ" thay vì để lỗi lan ra thành 500 — mục đích là giữ sạch chỉ số SLO. **Đề xuất này không nên làm, vì 2 lý do:**
   - Thông báo "kiểm tra lại thẻ" là **sai sự thật**: đọc `charge.js` thì nhánh `paymentFailure` throw lỗi **trước khi** code chạm tới bước validate thẻ — lỗi hoàn toàn ngẫu nhiên (`Math.random() < numberVariant`), không liên quan gì tới thẻ khách nhập. Bảo khách "thẻ có vấn đề" trong khi thẻ hoàn toàn hợp lệ là đánh lừa khách về nguyên nhân thật.
   - Đổi mã HTTP không làm đơn hàng được tạo — SLO checkout đo việc khách có đặt được đơn hay không, không phải đo "response có phải 5xx hay không". Đổi 500 thành 400 chỉ làm dashboard trông đẹp hơn về mặt hình thức trong khi khách **vẫn không mua được hàng** — đây là che số liệu (gaming metric), không phải fix. Nếu BTC/mentor đối chiếu số đơn tạo thành công thật với báo cáo, phát hiện lỗi hệ thống bị dán nhãn thành lỗi khách hàng để giữ số đẹp sẽ phản tác dụng nặng hơn nhiều so với báo cáo trung thực (như postmortem này).

   **Cách sửa đúng, cùng tinh thần "khách không thấy lỗi xấu" nhưng không gian dối và thật sự cứu được đơn hàng:**
   - Thêm **retry** ở `checkout` khi gọi `payment.charge()` thất bại (1-2 lần, có backoff ngắn). Vì lỗi này là xác suất theo từng lần gọi (không phải luôn luôn fail), retry có xác suất tốt để thành công ở lần sau — ví dụ flag ở mức 75% thì 1 lần gọi có ~75% khả năng fail, nhưng fail liên tiếp cả 3 lần chỉ còn ~42% (0.75³) — tức là **retry cứu được phần lớn đơn hàng thật**, thay vì chỉ đổi cách hiển thị lỗi.
   - Nếu retry hết vẫn fail, trả thông báo **trung thực**: "Hệ thống thanh toán đang gặp sự cố, vui lòng thử lại sau" — không đổ lỗi cho thẻ khách.
   - Trường hợp retry hết mà vẫn fail thì vẫn tính là fail trong SLO — đúng bản chất, không che giấu con số.
