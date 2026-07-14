# tools/search/README.md

# Multi-Strategy Search Module — LLM-synthesized DB queries (updated)

Tài liệu này mô tả cập nhật cho mô-đun tìm kiếm: thay vì quét toàn bộ database hoặc tải toàn bộ catalog khi DB lớn, hệ thống sẽ sử dụng LLM để sinh các truy vấn (query templates / parameter sets / synonyms đa ngôn ngữ) và gọi các API DB chuyên biệt để trả về tập kết quả nhỏ, có thể xử lý tiếp bằng các chiến lược ranking và (tuỳ chọn) LLM rerank.

Mục tiêu chính:
- Tránh full-table scan / tải toàn bộ DB khi dataset lớn.
- Dùng LLM để mở rộng/sinh variant truy vấn (synonym multilingual VN↔EN), không để LLM trả về kết quả trực tiếp từ embedding.
- Định nghĩa rõ 5 API/handler DB cần thiết để giao tiếp an toàn, có thể tối ưu index và hạn chế I/O.

## Kiến trúc (tóm tắt)

Input query (Tiếng Việt / Tiếng Anh / Mixed)
       ↓
- Phase 1: Query Analyzer
       - Regex & rule parse (price range, sort, filters)
       - LLM (cached) để sinh query variants và synonyms (VN↔EN)
       ↓
- Phase 2: DB Query Layer (gọi API nhẹ, trả list size nhỏ)
       - Gọi 1..N DB handlers (see "DB API" below)
       ↓
- Phase 3: Merge, Dedup, Rule-based Score
       - Gộp pool, loại trùng theo `product_id`, apply rule scores
       ↓
- Phase 4: Optional LLM Rerank (chỉ khi pool > threshold)
       - LLM làm final re-ranking / answer shaping

## Vì sao chọn approach này
- LLM chỉ sinh truy vấn (parameterized), không quét toàn bộ DB.
- DB handlers có thể tối ưu bằng index, limit, pagination, trả về tập nhỏ (N ≪ total rows).
- Giảm chi phí I/O và latency trên DB lớn; vẫn duy trì khả năng xử lý ngôn ngữ tự nhiên phong phú.

## DB API (mới) — bắt buộc

Ghi chú: tất cả hàm DB trả về danh sách sản phẩm/records tối đa với `limit` bắt buộc và hỗ trợ `filters`/`sort`.

- `db_query_variants(query_variants: List[QueryVariant], filters: Dict, limit: int) -> List[Product]`
       - Mục đích: nhận một tập biến thể truy vấn (do LLM sinh ra), chạy từng truy vấn dưới dạng parameterized SQL / stored procedure / gRPC call, merge sơ bộ kết quả, trả list (có thể kèm score từ DB như text_rank)
       - Yêu cầu: mỗi truy vấn phải map trực tiếp tới truy vấn được index hóa (WHERE trên indexed columns) để tránh scan.

- `db_query_conditions(conditioned_query: ConditionedQuery, limit: int) -> List[Product]`
       - Mục đích: chạy các truy vấn có điều kiện phức tạp (price range, category_id, attributes) do analyzer chuyển thành cấu trúc điều kiện. Trả kết quả đã lọc.
       - Yêu cầu: hỗ trợ pagination, trả về `total_estimate` nếu DB hỗ trợ (useful để decide rerank/LLM fallback).

- `db_execute_text_search(text_query: str, limit: int) -> List[Product]`
       - Mục đích: gọi full-text / trigram / search index (nếu có) với `text_query` được sanitize; phù hợp cho fuzzy/name searches.
       - Yêu cầu: đảm bảo `limit` nhỏ, use text-indexed path, không fallback vào table scan.

Ngoài 3 API trên, thêm 2 hàm helper để phục vụ tìm kiếm chi tiết và mapping:

- `get_category(category_hint: str) -> List[Category]`
       - Trả về các category suggestions / canonical category ids từ hint (dùng cho filter và để LLM sinh queries theo category_id thay vì text).

- `get_full_product_name(product_id_or_partial: str) -> Optional[str]`
       - Trả về tên sản phẩm đầy đủ / canonical cho một id hoặc partial identifier — hữu ích khi user tìm kiếm đúng sản phẩm (autocomplete, exact match)

Tóm lại: 3 hàm query (variants/conditions/text_search) + 2 helper (category / fullname) = 5 endpoints nhẹ, an toàn, tối ưu.

## Integration points với hệ thống hiện tại
- QueryAnalyzer: tuỳ chỉnh để xuất `QueryVariant[]` cho `db_query_variants` thay vì cố gắng lấy tất cả sản phẩm bằng cách quét.
- Strategies:
       - FullCatalogStrategy: giữ nguyên nhưng chỉ dùng khi catalog đã được cache bộ nhớ nhỏ hoặc DB size chấp nhận được.
       - DirectDBStrategy: chuyển sang gọi `db_query_variants` / `db_query_conditions` / `db_execute_text_search`.
       - SynonymExpansionStrategy: giờ LLM sinh biến thể (VN↔EN) và lưu vào `synonym_cache`.
- Existing helper functions in codebase: tích hợp trực tiếp (không thay đổi) — README này giả định các hàm hỗ trợ (cache, DB client, LLM wrapper) đã có sẵn.

## Caching & Rate / Cost considerations
- Cache LLM-produced query variants by query-hash (TTL ~ 24h) để giảm chi phí LLM.
- Cache `get_category` và synonym map vĩnh viễn hoặc dài hạn.
- DB handlers phải enforce `limit` thấp (e.g., 50) và trả `total_estimate` nếu được.

## Scoring / Merge rules (tóm tắt)
- Dedup theo `product_id`.
- Score components: exact name, keyword in name, category match, fuzzy name, price proximity, boosted if user-specified filters match.
- Sau merge, nếu pool > 5 (configurable) thì gọi LLM rerank.

## Pseudocode — orchestrator (ý tưởng)

```py
def search_pipeline(user_query):
              sq = analyzer.parse(user_query)
              variants = llm.synthesize_query_variants(sq)  # cached
              # call DB in parallel but each call limited
              results_a = db_query_variants(variants['variants'], filters=sq.filters, limit=50)
              results_b = db_query_conditions(sq.conditioned, limit=50)
              results_c = db_execute_text_search(sq.text_for_search, limit=50)
              merged = ranker.merge_and_score([results_a, results_b, results_c], sq)
              if len(merged) > rerank_threshold:
                            merged = llm_reranker.rerank(merged, user_query)
              return merged[:top_k]
```

## Examples & Prompts (LLM)
- Prompt to LLM should be constrained and deterministic: give explicit output schema (list of query variants, each variant: field_filters, keywords_en, keywords_vn, sql_template_name)
- Example: "From the user query, produce up to 8 parameterized query variants: {filters:{price_min,price_max}, keywords:['telescope','kính thiên văn'], category_id:..., prefer_match:'name|category'}"

## Debugging & Observability
- Log: produced query variants, DB calls (which template used + returned count + total_estimate), cache hits/misses, rerank calls and costs.
- Metrics: queries/sec, LLM calls, avg DB rows returned, pct queries that triggered rerank.

## Migration notes
- Nếu DB nhỏ: keep FullCatalogStrategy as primary (fast, in-memory).
- If DB large: switch FullCatalog to read-only cached snapshot or disable and rely on DB handlers described above.

## Next steps
- Implement/validate the 5 DB handlers in the data access layer and add unit tests for query templates.
- Add guarded LLM prompts with strict output schema.
- Instrument metrics for DB row counts and LLM call frequency.

---
Mô-đun này là phần của AI Shopping Copilot (AIO02) — TF3 Phase 3. Nếu muốn, tôi có thể mở PR mẫu với patch tích hợp orchestrator pseudocode vào `tools/search/orchestrator.py`.
