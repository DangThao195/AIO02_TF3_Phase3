# C3 — RCA Evidence Pack Contract

| Trường | Giá trị |
|---|---|
| Version | 1.0.0 |
| Producer | **AIO02** (RCA Assistant trong AI engine) |
| Consumer | **Cả TF3** — người trực đang xử sự cố + người viết postmortem/COE |
| Kênh giao | File markdown trong repo TF (`TF3/incidents/<incident_id>/evidence-pack.md`) + link trong kênh chat |
| Trạng thái | Draft — chờ CDO review |

## Mục đích

Khi có incident, việc tốn thời gian nhất là **đào bằng chứng**: mở Grafana, lục Jaeger,
viết query OpenSearch, dựng timeline. RCA Assistant tự làm phần đào đó và giao một
**Evidence Pack** trong vòng 30 phút kể từ khi incident mở — để:
1. Người trực xử nhanh hơn (mọi evidence một chỗ).
2. Postmortem/COE ký tên (deliverable bắt buộc, RULES §7) viết từ dữ liệu thật,
   không viết từ trí nhớ.

**Ranh giới quan trọng:** Evidence Pack là *bằng chứng + giả thuyết*. **Kết luận root cause
là của con người** — người ký postmortem chịu trách nhiệm, không phải AI.

---

## INPUT — thứ kích hoạt và nuôi Evidence Pack

| Input | Nguồn | Ghi chú |
|---|---|---|
| Trigger | Alert C2 severity `critical`/`warning` được ack, hoặc người trực gọi tay `/rca <service> <from> <to>` | CDO có thể tự gọi bất cứ lúc nào |
| Metrics window | Prometheus (C1), ±30 phút quanh `starts_at` | Tự chụp |
| Traces | Jaeger (C1): exemplar traces lỗi + traces thành công cùng route để so sánh | Tự chụp |
| Logs | OpenSearch (C1): error/warn của các service trong `probable_blast_radius` | Tự chụp |
| Deploy/change events | **CDO cung cấp:** log thay đổi hạ tầng (helm upgrade, config change, scale) — cách đơn giản nhất: mọi thay đổi đều post 1 dòng vào kênh #tf3-changes theo format `[change] <ai> <cái gì> <lúc nào>` | **Đây là nghĩa vụ input duy nhất của CDO trong contract này.** Không có change log thì mục "thay đổi gần nhất" trong pack sẽ trống |

## OUTPUT — Evidence Pack (thứ TF nhận được)

### Cấu trúc file (template cố định)

```markdown
# Evidence Pack — <incident_id>
Sinh tự động bởi AI engine lúc <timestamp>. Trạng thái: DRAFT — cần người xác nhận.

## 1. Tóm tắt 3 dòng
- Cái gì: <SLI nào vỡ, từ lúc nào, mức độ>
- Ảnh hưởng khách: <ước tính % request lỗi × thời lượng; luồng nào (checkout/browse/cart)>
- Error budget: <đã đốt bao nhiêu % budget của cửa sổ 24h / tuần>

## 2. Timeline (UTC+7)
| Thời điểm | Sự kiện | Nguồn |
|---|---|---|
| 09:38 | kafka consumer lag bắt đầu tăng | prometheus |
| 09:41 | checkout success rớt dưới 99% | prometheus |
| 09:42 | alert TF3-...-0042 fired | ai-engine |
| 09:44 | ack bởi <người trực> | chat |

## 3. Thay đổi gần nhất trước sự cố (từ #tf3-changes)
<liệt kê hoặc "không có thay đổi trong 6h trước">

## 4. Bằng chứng
### Metrics: <ảnh/link panel + PromQL>
### Traces: <3-5 trace ID lỗi tiêu biểu + 1 trace thành công để so sánh, kèm nhận xét span nào chậm/lỗi>
### Logs: <top error signature (gộp theo template), tần suất, service>

## 5. Giả thuyết nguyên nhân (xếp theo độ tin)
| # | Giả thuyết | Bằng chứng ủng hộ | Bằng chứng chống | Cách xác minh |
|---|---|---|---|---|
| H1 | ... | ... | ... | ... |
| H2 | ... | ... | ... | ... |

## 6. Hành động đã/đang làm
<link các remediation record từ C6>

## 7. Người xác nhận root cause: ________ (ký tên — bắt buộc trước khi đóng incident)
```

### SLA của producer

| Cam kết | Ngưỡng |
|---|---|
| Pack v1 (mục 1, 2, 4) sẵn sàng | ≤ 30 phút từ khi alert được ack |
| Cập nhật pack khi incident còn mở | Mỗi 30 phút hoặc khi có tín hiệu mới đáng kể |
| Giả thuyết (mục 5) | Luôn ≥ 2 giả thuyết — chống anchor bias; ghi rõ bằng chứng *chống* chứ không chỉ ủng hộ |
| Đánh dấu độ tin | Mọi kết luận máy sinh đều gắn `DRAFT` cho tới khi người ký mục 7 |

### Nghĩa vụ của consumer

- Người trực dùng pack thì phản hồi nhanh: giả thuyết nào đúng/sai (giúp engine học).
- Người viết postmortem **phải** điền mục 7 — postmortem không có người ký = vi phạm RULES §7.
- CDO duy trì kỷ luật post `[change]` vào #tf3-changes (input duy nhất được yêu cầu).

## Failure modes

| Tình huống | Hành vi |
|---|---|
| Nguồn telemetry chậm/mù | Pack vẫn ra đúng hạn, mục thiếu ghi rõ `⚠ evidence không đầy đủ: <lý do>` — không treo, không đoán bừa |
| Incident do BTC inject qua flagd | Pack vẫn phân tích như sự cố thật (đúng luật chơi); mục giả thuyết được phép ghi "khả năng incident được inject" kèm bằng chứng hành vi, nhưng cách xử vẫn là fallback/containment |
| RCA Assistant chết | Người trực dùng template trống (file `evidence-pack-template.md`) đào tay — template chính là fallback |

## Tiêu chí nghiệm thu

- [ ] Chạy thử trên 1 sự cố lịch sử (tái hiện từ `onboarding/INCIDENT_HISTORY.md`): pack ra trong 30 phút, người CDO đọc hiểu không cần hỏi AIO.
- [ ] Template trống tồn tại làm fallback.
- [ ] Kênh #tf3-changes có và cả TF đã thống nhất format `[change]`.
- [ ] ADR ký tên.
