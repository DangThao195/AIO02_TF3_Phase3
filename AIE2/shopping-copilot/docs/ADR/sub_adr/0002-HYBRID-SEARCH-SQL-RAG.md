# ADR 0002: Hybrid Search — SQL + RAG (Knowledge Base) Với Reranker

- **Trạng thái:** Đã phê duyệt
- **Tác giả:** Đặng Thị Ngọc Thảo, Phạm Vũ Khánh Trường - AIE2
- **Ngày tạo:** 2026-07-20

---

## 1. Bối Cảnh

Khi người dùng tìm kiếm sản phẩm, hệ thống cần trả về kết quả chính xác và đầy đủ từ catalog. Có hai nguồn dữ liệu:

1. **PostgreSQL/SQLite** (Flow 1): Dữ liệu có cấu trúc, tìm kiếm theo tên/category/giá bằng SQL LIKE.
2. **Amazon Bedrock Knowledge Base** (Flow 2): Vector search full-text, tìm kiếm ngữ nghĩa, bắt được các truy vấn mơ hồ hoặc dùng từ đồng nghĩa.

Chỉ dùng một nguồn không đủ:
- SQL LIKE bỏ sót sản phẩm khi user dùng từ khác với tên chính xác trong DB.
- KB Vector search không filter được theo giá hay category chính xác.

Ngoài ra, hệ thống chạy trên AWS EKS với tunnel SSM tới RDS (cổng 5433) **không ổn định** — tunnel có thể drop bất cứ lúc nào, gây timeout 30 giây mặc định làm treo toàn bộ eval.

---

## 2. Quyết Định

### 2.1. Kiến trúc Hybrid 2 Flow Chạy Song Song

```
Query
  ├── Flow 1: Intent → SQL Builder → SQLExecutor (PostgreSQL/SQLite) → results_1
  └── Flow 2: Query → KB Client (Bedrock Knowledge Base) → results_2
                                ↓
                          Reranker (merge + score)
                                ↓
                          Top-K results
```

Cả hai flow chạy **song song** (asyncio), kết quả merge và rerank bằng scoring formula.

### 2.2. SQL Builder (Flow 1)

File `src/tools/search_product/flow1/sql_builder.py`:

- Nhận entity từ Intent Parser (product_name, category, price_range).
- Build SQL với LIKE đa điều kiện trên `name`, `description`, `categories`.
- **Category Normalization:** `.rstrip("s")` để khớp cả dạng số ít/số nhiều:
  - "telescopes" → "telescope" → match category "Telescope"
  - "accessories" → "accessorie" → partial match vẫn hoạt động
- WHERE clause kết hợp AND/OR theo mức độ specificity của query.

### 2.3. SQLite Fallback (Resilience)

File `src/tools/search_product/flow1/sql_executor.py`:

- **Primary:** Kết nối PostgreSQL qua SSM tunnel (port 5433), timeout = **2 giây**.
- **Fallback:** Nếu kết nối fail hoặc timeout → tự động chuyển sang SQLite local.
- SQLite được populated từ dữ liệu dump ban đầu, luôn available dù tunnel drop.

> **Lý do timeout 2s (không phải 30s mặc định):** Tunnel SSM hay drop sau 5-10 phút idle. Timeout 30s mặc định làm toàn bộ eval bị block 30s × 60 cases = 30 phút. Timeout 2s giảm penalty xuống còn tối đa 2s mỗi case.

### 2.4. Reranker — Ưu Tiên Kết Quả

File `src/tools/search_product/reranker.py`:

Scoring formula cho mỗi sản phẩm trong kết quả merge:

```
score = category_match_bonus
      + name_exact_match_bonus
      + sql_source_bonus
      + kb_score (normalized 0-1)
```

**Category Priority Fix:** Với query "telescope", reranker ưu tiên sản phẩm có category "Telescope" trước, sau đó mới đến "Accessories". Điều này fix lỗi ordinal context ("cái đầu tiên" → đúng telescope, không phải accessory đầu tiên).

---

## 3. Lý Do Chọn Phương Án

| Lựa chọn | Lý do |
|---|---|
| **Chạy song song** 2 flow | Tổng latency ≈ max(Flow1, Flow2), không phải tổng cộng |
| **SQLite fallback** thay vì chỉ dùng KB | KB có thể lag hoặc offline; SQLite đảm bảo luôn có kết quả |
| **Timeout 2s** cho PostgreSQL | Giảm blast radius khi tunnel drop từ 30s → 2s penalty |
| **Reranker** thay vì chỉ lấy top-K của từng flow | Merge intelligently, tránh duplicate và bias theo một nguồn |
| **`.rstrip("s")`** thay vì stemmer | Đơn giản, không cần dependency, đủ cho catalog tiếng Anh |

---

## 4. Đo Lường & Kết Quả

| Cluster | Pass Rate Before | Pass Rate After Fix |
|---|---|---|
| `single_intent` (search queries) | ~50% | **71.4%** |
| `contextual` (ordinal resolve) | ~25% | **100.0%** |
| `multilingual` (VN queries) | ~33% | **66.7%** |
| `complex_logic` (filter + sort) | ~60% | **80.0%** |

**Tác động lớn nhất:** Category priority fix trong Reranker đưa `contextual` từ 25% lên 100%.

---

## 5. Tài Liệu Liên Quan

- `src/tools/search_product/orchestrator.py` — Flow coordinator
- `src/tools/search_product/flow1/sql_builder.py` — SQL query builder
- `src/tools/search_product/flow1/sql_executor.py` — PostgreSQL + SQLite fallback
- `src/tools/search_product/flow2/kb_client.py` — Bedrock Knowledge Base client
- `src/tools/search_product/reranker.py` — Result merge & reranking
- [ADR 0001](./0001-AGENT-PIPELINE-6-LAYER.md) — Pipeline tổng thể
