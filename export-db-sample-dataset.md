# Runbook — Export mẫu dữ liệu DB cho AIO02

**Mục đích:** trích **schema + mẫu nhỏ có data** từ RDS Postgres `techx-tf3` để bàn giao
cho nhóm khác (AIO02) phân tích, **không** bê toàn bộ ~128k đơn hàng ra ngoài.

**Cập nhật:** 24/07/2026 · **Người giữ:** CDO02

---

## Nguyên tắc trước khi làm

- Đây là **export dữ liệu production ra file cho nhóm khác** — thao tác bàn giao dữ liệu,
  cần chủ đích rõ ràng. Mặc định lấy **mẫu nhỏ**, không full dump.
- **Credential không đi qua bên thứ ba.** Connection string đọc trực tiếp từ secret trong
  cluster, chỉ tồn tại trong biến môi trường của phiên chạy. Không hardcode, không commit,
  không dán ra kênh chung.
- **Quét PII trước khi gửi** (bước 5) — bắt buộc, kể cả với data synthetic từ load-gen.
- RDS sau Mandate #8 là managed (`techx-tf3-postgres...:5432`, `sslmode=require`), chứa 3
  nhóm bảng: accounting (đơn hàng), product-catalog, product-reviews.

**Yêu cầu máy chạy:** `psql` + `pg_dump` (Postgres client ≥ 14). Kiểm tra `pg_dump --version`.
Chưa có thì cài `postgresql-client`, hoặc chạy qua `docker run --network host -it postgres:16`.

---

## 1. Mở tunnel tới RDS (terminal riêng, giữ mở)

Khác tunnel EKS — lần này trỏ vào host RDS, cổng 5432:

```bash
export AWS_PROFILE=techx-new; export MSYS_NO_PATHCONV=1
BASTION_ID=$(aws ec2 describe-instances --region ap-southeast-1 \
  --filters "Name=tag:Name,Values=techx-corp-tf3-bastion" "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" --output text)
aws ssm start-session --target "$BASTION_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host="techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com",portNumber="5432",localPortNumber="5432" \
  --region ap-southeast-1
```

> Tunnel tự đóng sau ~10–20 phút idle. Mất kết nối giữa chừng thì mở lại.

## 2. Lấy connection string từ secret

Chạy trong terminal của bạn, **không in ra kênh chung**:

```bash
export AWS_PROFILE=techx-new
export RAW="$(kubectl -n techx-tf3 get secret techx-tf3-postgres-conn -o jsonpath='{.data.libpq}' | base64 -d)"
CONN="$RAW host=127.0.0.1 port=5432 sslmode=require"
```

`RAW` giữ nguyên user/dbname/password từ secret; ta chỉ ép host/port về tunnel local.

## 3. Xem trước để chọn cỡ mẫu (tuỳ chọn nhưng nên làm)

```bash
psql "$CONN" -c "select schemaname, tablename from pg_tables where schemaname='public' order by 1,2"
psql "$CONN" -c "select relname, n_live_tup from pg_stat_user_tables order by n_live_tup desc"
```

## 4. Dump schema + mẫu

Mặc định 200 dòng/bảng (tuần tự). Đổi cỡ mẫu bằng biến `SAMPLE`:

```bash
SAMPLE=${SAMPLE:-200}
OUT="techx-db-sample-$(date +%Y%m%d).sql"

# 4a. Schema (không data)
pg_dump "$CONN" --schema-only --no-owner --no-privileges --schema=public > "$OUT"

# 4b. Mẫu data từng bảng
echo -e "\n-- ===== SAMPLE DATA (<= $SAMPLE rows/table) =====" >> "$OUT"
for t in $(psql "$CONN" -At -c "select tablename from pg_tables where schemaname='public' order by 1"); do
  echo -e "\n-- table: $t\nCOPY public.\"$t\" FROM stdin;" >> "$OUT"
  psql "$CONN" -At -c "\copy (select * from public.\"$t\" limit $SAMPLE) to stdout" >> "$OUT" 2>/dev/null || true
  echo '\.' >> "$OUT"
done

echo "xong: $OUT ($(wc -l < "$OUT") dòng)"
```

**Chọn kiểu mẫu theo mục đích:**

| Mục đích của AIO02 | `limit` nên dùng |
|---|---|
| Hiểu cấu trúc + xem data mẫu để code | `limit 200` (tuần tự, như trên) |
| Phân tích / thống kê trên data thật | đổi thành `order by random() limit 1000` — đại diện hơn, vì 200 dòng đầu của bảng đơn hàng 128k không phản ánh phân bố |

## 5. ⚠️ Quét PII trước khi gửi — BẮT BUỘC

Bảng accounting chứa đơn hàng, có thể có email/địa chỉ/thẻ (dù data synthetic từ load-gen):

```bash
grep -iE 'email|address|card|phone|street|zip|ssn' "$OUT" | head -20
```

Nếu có trường nhạy cảm mà AIO02 không cần: bỏ cột đó khỏi `select`, hoặc để các bảng đó
**schema-only** (bỏ khỏi vòng lặp 4b). Đây là data production ra ngoài — quét một lượt là
mức trách nhiệm tối thiểu.

## 6. Bàn giao

Gửi file `.sql` cho AIO02 qua kênh nội bộ. **Không commit file dump vào repo** (nó là data,
không phải code; và có thể chứa PII). Xoá file local sau khi bàn giao xong nếu không cần giữ.

---

## Ghi chú

- **Engine của AIO02 đọc Prometheus/Jaeger/OpenSearch, không đọc Postgres trực tiếp** — nếu
  họ cần DB dump cho mục đích khác (seed môi trường test, RCA offline), xác nhận lại mục đích
  để chọn đúng phạm vi trước khi export.
- ElastiCache (giỏ hàng) và MSK (event stream) là store khác, không nằm trong runbook này —
  cần thì hỏi CDO02.
- Runbook này chỉ mô tả **mẫu nhỏ**. Full dump toàn bộ đơn hàng là quyết định riêng, cần
  cân nhắc PII/bảo mật kỹ hơn — đừng mặc định làm full.
