# AIE1 Local Runtime Trace Report

Snapshot date: 2026-07-14
Report scope: local host-run verification for AIE1 `product-reviews` after the Bedrock-direct runtime update and offline fidelity-eval alignment.

## 1. Executive summary

Tai thoi diem snapshot nay, AIE1 co 2 luong can tach ro:
1. Runtime serving path trong `techx-corp-platform/src/product-reviews/product_reviews_server.py`
2. Offline evaluation path trong `repro/eval_fidelity.py`

Ket qua chay local cuoi cung:
- Runtime serving path: PASS
- Runtime inaccurate-summary rejection path: PASS
- Offline evaluator path: PASS sau khi sua parser DB, Bedrock judge, artifact metadata, va invalid-run aggregation

Kien truc cuoi cung duoc xac nhan local:
- Candidate model: `amazon.nova-lite-v1:0`
- Runtime factuality judge: `amazon.nova-micro-v1:0`
- Offline evaluator judge: `amazon.nova-micro-v1:0`
- Database local dung: `otel`
- Host-run gRPC port: `8085`

## 2. Local infrastructure used for the run

Cac dependency da chay san bang Docker trong local stack:

```text
product-catalog   Up   0.0.0.0:50333->3550/tcp
postgresql        Up   0.0.0.0:50319->5432/tcp
flagd             Up   0.0.0.0:50326->8013/tcp
otel-collector    Up   0.0.0.0:50318->4317/tcp
llm               Up   0.0.0.0:50329->8000/tcp
product-reviews   Up   0.0.0.0:50328->3551/tcp
```

Luu y quan trong:
- Container Docker `product-reviews` map ra port `50328` KHONG duoc dung trong trace Bedrock direct nay.
- Trace trong file nay duoc tao bang mot process host-run rieng, bind vao `localhost:8085`.
- Luong runtime moi chay tren host-run process, khong phai tren image Docker cu.

## 3. Runtime environment used for the host-run service

Process `product_reviews_server.py` duoc start voi cac env thuc su sau:

```text
OTEL_SERVICE_NAME=product-reviews
PRODUCT_REVIEWS_PORT=8085
DB_CONNECTION_STRING=host=localhost user=otelu password=otelp dbname=otel port=50319
PRODUCT_CATALOG_ADDR=localhost:50333
FLAGD_HOST=localhost
FLAGD_PORT=50326
LLM_PROVIDER=bedrock
LLM_MODEL=amazon.nova-lite-v1:0
AWS_REGION=us-east-1
JUDGE_PROVIDER=bedrock
JUDGE_MODEL=amazon.nova-micro-v1:0
JUDGE_REGION=us-east-1
JUDGE_TIMEOUT_SECONDS=3.0
LLM_HOST=localhost
LLM_PORT=50329
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:50318
```

Secret handling:
- AWS credentials duoc inject qua environment variables luc chay local.
- Secret khong duoc ghi lai trong file nay.

## 4. High-level architecture

Phan nay khong chi mo ta luong bang so do, ma con chi ro moi nut trong so do dang lam gi, input/output cua no la gi, va map voi file/ham nao trong code.

### 4.1 Runtime serving path

```text
Client
-> gRPC ProductReviewService.AskProductAIAssistant
-> product_reviews_server.py
   -> input guardrail
   -> fetch_product_reviews (Postgres)
   -> fetch_product_info (product-catalog)
   -> normalize_reviews_for_context
   -> candidate LLM call (Bedrock Nova Lite)
   -> output_filter
   -> runtime evaluator / llm-as-a-judge (Bedrock Nova Micro)
      -> approved: return summary to client
      -> rejected: return safe fallback
```

#### 4.1.1 Runtime path step-by-step with evidence

1. `Client -> gRPC ProductReviewService.AskProductAIAssistant`
   - Day la diem vao cua request summary.
   - Input cua request gom 2 field chinh:
     - `product_id`
     - `question`
   - Evidence trong code:
     - `ProductReviewService.AskProductAIAssistant(...)`
     - file `techx-corp-platform/src/product-reviews/product_reviews_server.py`

2. `AskProductAIAssistant -> get_ai_assistant_response(...)`
   - Method gRPC khong xu ly business logic truc tiep, ma chuyen toan bo xu ly sang `get_ai_assistant_response(request_product_id, question)`.
   - Day la ham trung tam cua toan bo runtime AI summary.
   - Evidence trong code:
     - `def get_ai_assistant_response(request_product_id, question):`
     - file `techx-corp-platform/src/product-reviews/product_reviews_server.py`

3. `input guardrail`
   - Buoc dau tien trong runtime la kiem tra `question` cua user qua `check_input(question)`.
   - Muc tieu:
     - chan prompt injection co ban
     - chan input nguy hiem
     - khong cho request xau di sau vao LLM path
   - Neu fail:
     - service tra blocked reason ngay
     - khong goi candidate LLM
   - Evidence trong code:
     - import `check_input` tu `guardrails/input_filter.py`
     - `input_check = check_input(question)` trong `get_ai_assistant_response(...)`

4. `fetch_product_reviews (Postgres)`
   - Sau khi input hop le, runtime lay raw reviews that cua san pham tu Postgres.
   - Muc tieu:
     - dung reviews that lam grounding cho candidate summary
     - dong thoi dung lai chinh reviews nay cho factuality judge
   - Output cua buoc nay la payload review tho, chua sanitize.
   - Evidence trong code:
     - `reviews_json = fetch_product_reviews(request_product_id)`
     - DB helper nam o `techx-corp-platform/src/product-reviews/database.py`

5. `fetch_product_info (product-catalog)`
   - Runtime goi them `product-catalog` qua gRPC de lay thong tin metadata cua san pham.
   - Muc tieu:
     - cho candidate model them context ve san pham
     - giam kha nang summary bi mo ho hoac generic
   - Output la product info JSON/string dua vao prompt.
   - Evidence trong code:
     - `product_info_json = fetch_product_info(request_product_id)`
     - `def fetch_product_info(product_id):`
     - file `techx-corp-platform/src/product-reviews/product_reviews_server.py`

6. `normalize_reviews_for_context`
   - Day la buoc chuyen doi quan trong nhat truoc khi vao Bedrock.
   - Ham nay nhan payload reviews tho va tao ra 2 ban du lieu:
     - `safe_reviews_json`: du lieu dua vao prompt cho candidate
     - `raw_reviews_for_judge`: du lieu co cau truc dua vao runtime evaluator
   - Ham nay dong thoi:
     - parse payload list/tuple/dict
     - skip malformed rows
     - skip invalid score
     - chay `check_input(...)` tren description cua tung review
     - thay noi dung nguy hiem bang placeholder policy-safe
   - Neu buoc nay parse sai, ca candidate va judge deu bi anh huong.
   - Evidence trong code:
     - `def normalize_reviews_for_context(function_response_raw):`
     - file `techx-corp-platform/src/product-reviews/product_reviews_server.py`

7. `candidate LLM call (Bedrock Nova Lite)`
   - Sau khi co product info va filtered reviews, runtime build grounded prompt cho Bedrock.
   - Candidate model hien tai la `amazon.nova-lite-v1:0`.
   - Muc tieu cua candidate:
     - sinh summary ngan gon 1-2 cau
     - chi dua tren product info + reviews da cung cap
   - Runtime call Bedrock direct bang `boto3 bedrock-runtime`, khong di qua OpenAI-compatible proxy trong host-run trace nay.
   - Buoc nay da duoc boc retry/fallback qua `@with_fallback`.
   - Evidence trong code:
     - `def build_bedrock_user_prompt(...)`
     - `def call_candidate_bedrock(system_prompt, user_prompt):`
     - `@with_fallback`
     - file `techx-corp-platform/src/product-reviews/product_reviews_server.py`

8. `output_filter`
   - Output text tu candidate khong di thang den client.
   - No di qua `post_process_output(...)`.
   - Ham nay lam 3 viec:
     - map `OUT_OF_SCOPE` thanh thong diep an toan cho user
     - map `NO_INFO` thanh thong diep `Khong co thong tin trong danh gia.`
     - neu la summary binh thuong thi chay `filter_output(...)`
   - Day la output cuoi cung truoc khi factuality gate duyet.
   - Evidence trong code:
     - `def post_process_output(result):`
     - `from guardrails.output_filter import filter_output`
     - file `techx-corp-platform/src/product-reviews/product_reviews_server.py`

9. `runtime evaluator / llm-as-a-judge (Bedrock Nova Micro)`
   - Sau `output_filter`, runtime moi goi factuality evaluator.
   - Day la thay doi kien truc quan trong nhat cua AIE1:
     - khong chi guardrail truoc LLM
     - ma con co guard o sau output cuoi
   - Judge model hien tai la `amazon.nova-micro-v1:0`.
   - Runtime evaluator nhan 3 dau vao quan trong:
     - `product_id`
     - `raw_reviews_for_judge`
     - `summary_text` da qua `output_filter`
   - Muc tieu cua evaluator runtime:
     - chi tap trung bat hallucination
     - dem `unsupported_claims`
     - dem `contradicted_claims`
     - quyet dinh `approved` hay `rejected`
   - Runtime evaluator cung duoc boc retry/fallback qua `@with_fallback`.
   - Evidence trong code:
     - `def call_summary_judge(product_id, raw_reviews, summary_text):`
     - `evaluate_summary_fidelity(...)`
     - file `techx-corp-platform/src/product-reviews/guardrails/evaluator.py`

10. `approved -> return summary to client`
   - Neu evaluator tra:
     - `approved = true`
     - `unsupported_claims = 0`
     - `contradicted_claims = 0`
   - Runtime log approval va tra summary cho client.
   - Evidence trong log that:
     - `Summary approved by evaluator for product_id:L9ECAV7KIM judge_provider=bedrock judge_model=amazon.nova-micro-v1:0 unsupported=0 contradicted=0`

11. `rejected -> return safe fallback`
   - Neu evaluator thay summary sai lech factual:
     - runtime khong tra summary sai cho client
     - runtime tra fallback an toan
   - Day la co che dap ung SLO `khong hien thi tom tat sai lech`.
   - Evidence trong log that:
     - `Summary rejected by evaluator for product_id:L9ECAV7KIM ... unsupported=4 contradicted=0 ...`
   - Evidence trong response that:
     - `Hien tai khong the xac minh noi dung tom tat, vui long thu lai sau.`

#### 4.1.2 Runtime path operational notes

- Candidate va judge deu la network-bound calls, nen phan `fallback.py` rat quan trong.
- `MAX_RETRIES = 3` nam trong `guardrails/fallback.py`.
- Retry chi thuc su co hieu luc vi runtime da boc cac call sau bang `@with_fallback`:
  - `call_candidate_chat(...)`
  - `call_candidate_bedrock(...)`
  - `call_summary_judge(...)`
- Neu khong boc decorator nay, retry 3 lan chi ton tai tren giay, khong phai behavior that.

### 4.2 Offline evaluation path

```text
repro/eval_fidelity.py
-> read raw reviews from Postgres
-> call live gRPC AskProductAIAssistant
-> build fact_sheet
-> run deterministic rule checks
-> call LLM judge
-> aggregate case result
-> save JSON artifact
```

#### 4.2.1 Offline path step-by-step with evidence

1. `read raw reviews from Postgres`
   - Offline eval bat dau bang viec lay review that tu DB lam ground truth.
   - Day la su that de doi chieu candidate summary.
   - Evidence trong code:
     - `get_raw_reviews_from_db(product_id)`
     - `open_db_connection()`
     - file `repro/eval_fidelity.py`

2. `call live gRPC AskProductAIAssistant`
   - Khac voi unit test gia, offline eval khong tu viet summary.
   - No goi runtime service that qua gRPC de lay candidate summary do he thong dang phuc vu sinh ra.
   - Y nghia:
     - offline eval dang danh gia he thong dang chay that
     - khong chi danh gia mot ham local trong script
   - Evidence trong code:
     - `get_ai_summary_via_grpc(product_id, timeout_seconds)`
     - `ProductReviewServiceStub(channel)`
     - file `repro/eval_fidelity.py`

3. `build fact_sheet`
   - Sau khi co raw reviews, script rut ra mot ban su that cau truc.
   - Fact sheet gom cac field kieu:
     - `review_count`
     - `average_score`
     - `rating_distribution`
     - positive/negative aspects
   - Muc tieu:
     - giam tai cho judge
     - giup deterministic checks va judge co cung mot ban tom tat ground truth
   - Evidence trong code:
     - `build_fact_sheet(...)`
     - file `repro/eval_fidelity.py`

4. `run deterministic rule checks`
   - Truoc khi goi judge, offline eval chay cac check cung.
   - Cac check nay bat cac loi ro rang nhu:
     - summary rong
     - qua dai
     - rating mismatch
     - sentiment mismatch ro rang
     - claim ve age/use-case khong co trong review
   - Day la lop danh gia co quy tac, khong phu thuoc model judge.
   - Evidence trong code:
     - `run_rule_checks(...)`
     - file `repro/eval_fidelity.py`

5. `call LLM judge`
   - Sau deterministic checks, script goi judge de cham semantic fidelity.
   - Hien tai script da ho tro 2 nhanh:
     - `judge_provider=openai`
     - `judge_provider=bedrock`
   - Trong local stack moi, nhanh Bedrock duoc dung de goi `amazon.nova-micro-v1:0` qua `boto3`.
   - Judge tra ve cac field quan trong:
     - `overall_score`
     - `supported_claims`
     - `unsupported_claims`
     - `contradicted_claims`
     - `claim_precision`
     - `aspect_coverage`
     - `sentiment_alignment`
   - Evidence trong code:
     - `judge_fidelity(...)`
     - file `repro/eval_fidelity.py`

6. `aggregate case result`
   - Sau khi co rule checks va judge result, script tong hop thanh mot `case result`.
   - Buoc nay quyet dinh:
     - `fidelity_passed`
     - `format_passed`
     - `passed`
     - `failure_reasons`
   - Day la buoc de bien nhieu signal thanh mot verdict cuoi cung cho tung product.
   - Evidence trong code:
     - `aggregate_case_result(...)`
     - file `repro/eval_fidelity.py`

7. `save JSON artifact`
   - Sau khi chay xong case hoac suite, script ghi artifact JSON.
   - Artifact nay la bang chung de audit, benchmark, va report.
   - Artifact local clean sau cung trong run nay la:
     - `repro/artifacts/fidelity_eval_20260714T152508Z.json`
   - Evidence trong code:
     - `main()` build `report = {...}` va ghi file output
     - file `repro/eval_fidelity.py`

#### 4.2.2 Offline path operational notes

- Offline eval khong nam tren request path cua user.
- Vai tro cua no la:
  - benchmark he thong
  - tao artifact cho bao cao
  - regression testing khi doi model/prompt/guardrail
- Runtime evaluator va offline evaluator khong trung nhau:
  - runtime evaluator = gate hep, bao ve user
  - offline evaluator = bo cham rong hon, dung cho audit va do luong

### 4.3 Why both paths exist

Hai luong nay cung dung reviews that, candidate summary that, va judge model, nhung phuc vu 2 muc tieu khac nhau:

1. Runtime path
   - muc tieu: chan summary sai truoc khi den user
   - uu tien: an toan serving, latency, fallback

2. Offline eval path
   - muc tieu: do luong va audit toan bo he thong
   - uu tien: metric, artifact, benchmark, pass/fail theo suite

Noi ngan gon:
- Runtime path tra loi cau hoi: `co nen cho user thay summary nay khong?`
- Offline eval path tra loi cau hoi: `he thong summary hien tai dat chat luong den muc nao tren tap du lieu nay?`
## 5. Files directly involved

### Runtime files
- `techx-corp-platform/src/product-reviews/product_reviews_server.py`
- `techx-corp-platform/src/product-reviews/database.py`
- `techx-corp-platform/src/product-reviews/guardrails/input_filter.py`
- `techx-corp-platform/src/product-reviews/guardrails/output_filter.py`
- `techx-corp-platform/src/product-reviews/guardrails/fallback.py`
- `techx-corp-platform/src/product-reviews/guardrails/evaluator.py`
- `techx-corp-platform/src/product-reviews/test_client.py`

### Offline evaluator files
- `repro/eval_fidelity.py`
- `repro/artifacts/fidelity_eval_20260714T152508Z.json`

## 6. Runtime code map

Phan nay map file -> ham -> vai tro de debug nhanh.

### 6.1 `product_reviews_server.py`
- `call_candidate_chat(...)`: OpenAI-compatible candidate call, co retry/fallback qua `@with_fallback`
- `call_candidate_bedrock(...)`: Bedrock direct candidate call, co retry/fallback qua `@with_fallback`
- `call_summary_judge(...)`: runtime evaluator call, co retry/fallback qua `@with_fallback`
- `normalize_reviews_for_context(...)`: parse va sanitize payload review cho prompt va cho judge
- `post_process_output(...)`: xu ly `OUT_OF_SCOPE`, `NO_INFO`, va `output_filter`
- `get_ai_assistant_response(...)`: ham trung tam cua runtime AI summary
- `fetch_product_info(...)`: goi gRPC sang `product-catalog`
- `check_feature_flag(...)`: doc flag tu flagd, co ho tro env override `FORCE_FLAG_*`

### 6.2 `guardrails/fallback.py`
- `MAX_RETRIES = 3`
- `with_fallback(...)`: retry 3 lan cho transient errors, sau do moi fallback
- `handle_exception(...)`: map exception sang thong diep fallback an toan

### 6.3 `guardrails/evaluator.py`
- `JUDGE_SYSTEM_PROMPT`: rubric hẹp, chi tap trung bat hallucination
- `_build_prompt(...)`: build raw-reviews + candidate summary cho judge
- `evaluate_summary_fidelity(...)`: chay judge theo `judge_provider=openai|bedrock`

### 6.4 `repro/eval_fidelity.py`
- `parse_db_conn_string(...)`: parse ca 2 format connection string
- `open_db_connection(...)`: mo Postgres connection theo config local
- `judge_fidelity(...)`: OpenAI judge hoac Bedrock judge
- `aggregate_case_result(...)`: chot `fidelity_passed`, `format_passed`, `passed`
- `summarize_suite(...)`: aggregate toan bo run
- `evaluate_one_product(...)`: pipeline offline cho 1 product
- `main(...)`: chon provider, run cases, ghi artifact

## 7. Runtime trace: normal summary request

### 7.1 Request used

```text
product_id = L9ECAV7KIM
question   = Can you summarize the product reviews?
port       = 8085
```

### 7.2 Actual client path

Client test dung file:
- `techx-corp-platform/src/product-reviews/test_client.py`

Client mo channel gRPC toi:
- `localhost:8085`

### 7.3 Detailed step-by-step trace

1. `test_client.py` mo gRPC channel toi `localhost:8085`.
2. `ProductReviewService.AskProductAIAssistant` nhan request va goi `get_ai_assistant_response(request_product_id, question)`.
3. `check_input(question)` duoc chay truoc. Cac cau hoi nguy hiem se bi chan tai day.
4. Runtime xac dinh `LLM_PROVIDER=bedrock`, nen vao nhanh Bedrock direct thay vi OpenAI-compatible path.
5. `fetch_product_reviews(product_id)` lay review that tu Postgres.
6. `normalize_reviews_for_context(...)` chuyen payload DB thanh 2 ban:
   - `safe_reviews_json`: dua vao prompt cho model sinh summary
   - `raw_reviews_for_judge`: dua vao runtime evaluator de doi chieu factuality
7. `fetch_product_info(product_id)` goi sang `product-catalog` de lay metadata san pham.
8. `check_feature_flag("llmInaccurateResponse")` duoc goi. Trong normal path, gia tri la `False`.
9. `build_bedrock_user_prompt(...)` tao grounded prompt tu:
   - question
   - product info JSON
   - filtered product reviews JSON
10. `call_candidate_bedrock(...)` goi `amazon.nova-lite-v1:0` qua `boto3 bedrock-runtime`.
11. Output candidate di qua `post_process_output(...)`:
   - neu model tra `OUT_OF_SCOPE` -> map thanh thong diep an toan
   - neu model tra `NO_INFO` -> map thanh thong diep `Khong co thong tin...`
   - neu la summary binh thuong -> di qua `output_filter`
12. Neu output sau filter khong phai `OUT_OF_SCOPE_MESSAGE` va khong phai `NO_INFO_MESSAGE`, runtime goi `call_summary_judge(...)`.
13. `call_summary_judge(...)` goi `evaluate_summary_fidelity(...)` voi:
   - `judge_provider=bedrock`
   - `judge_model=amazon.nova-micro-v1:0`
14. Judge doc raw reviews that + candidate summary va tra ve:
   - `approved=true`
   - `unsupported_claims=0`
   - `contradicted_claims=0`
15. Runtime log nhan approval va tra summary cho client.

### 7.4 Retry/fallback behavior on this path

Trong normal path nay, retry/fallback khong bi kich hoat, nhung cac diem goi network sau deu da duoc boc boi `@with_fallback`:
- `call_candidate_chat(...)`
- `call_candidate_bedrock(...)`
- `call_summary_judge(...)`

Y nghia:
- Neu candidate/judge gap loi tam thoi (timeout, throttling, service unavailable), he thong se retry toi da 3 lan.
- Chi khi retry that bai moi tra fallback string.

### 7.5 Client response captured

```text
The reviews highlight the kit's effectiveness on various optics and surfaces, praising its gentle and residue-free cleaning.
```

### 7.6 Runtime log excerpt captured

```text
Product reviews service started, listening on port 8085
Receive AskProductAIAssistant for product id:L9ECAV7KIM, question: Can you summarize the product reviews?
product_catalog_stub.GetProduct returned: 'id: "L9ECAV7KIM" ...'
Using env override for feature flag llmInaccurateResponse: False
llmInaccurateResponse feature flag: False
Summary approved by evaluator for product_id:L9ECAV7KIM judge_provider=bedrock judge_model=amazon.nova-micro-v1:0 unsupported=0 contradicted=0
Returning an AI assistant response: 'The reviews highlight the kit's effectiveness on various optics and surfaces, praising its gentle and residue-free cleaning.'
```

### 7.7 Conclusion for normal runtime trace

Runtime path da chay thanh cong end-to-end:
- Postgres -> product-catalog -> Bedrock Nova Lite -> output_filter -> Bedrock Nova Micro -> client response.

## 8. Runtime trace: inaccurate summary rejection path

### 8.1 Goal

Kiem tra negative-control path: summary sai phai bi chan truoc khi tra ve cho user.

### 8.2 How the inaccurate path was triggered

Local env override duoc dung:

```text
FORCE_FLAG_LLMINACCURATERESPONSE=true
```

Override nay tranh phu thuoc vao state that cua flagd trong local test.

### 8.3 Why a fixed inaccurate fixture was required

Neu chi prompt model "intentionally make the answer inaccurate" thi Bedrock van co the sinh ra mot summary gan dung.

Vi muc tieu test la deterministic negative control, runtime duoc sua de khi:
- `llmInaccurateResponse=true`
- `product_id=L9ECAV7KIM`

thi se dung mot inaccurate fixture co dinh.

### 8.4 Inaccurate fixture used

```text
Customers are largely disappointed with this cleaning kit, citing its ineffectiveness on most optical surfaces. Many users report that the cleaning fluid leaves a sticky residue and the included brush is too harsh, causing scratches on lenses. The kit is considered a poor value, with several reviewers stating it damaged their equipment.
```

### 8.5 Detailed step-by-step trace

1. Request van la `Can you summarize the product reviews?`.
2. `check_feature_flag("llmInaccurateResponse")` doc duoc env override va tra `True`.
3. Runtime phat hien `product_id == L9ECAV7KIM`, nen khong cho candidate model tu bịa summary sai nua ma inject truc tiep inaccurate fixture.
4. Inaccurate fixture van di qua `post_process_output(...)` de dam bao luong dung voi output that se tra cho user.
5. `call_summary_judge(...)` goi `amazon.nova-micro-v1:0` voi:
   - candidate summary sai
   - raw reviews that
6. Judge phat hien nhieu unsupported claims.
7. Runtime log `Summary rejected by evaluator ...` va khong tra summary sai cho client.
8. Runtime tra fallback an toan:
   - `Hien tai khong the xac minh noi dung tom tat, vui long thu lai sau.`

### 8.6 Client response captured

```text
Hien tai khong the xac minh noi dung tom tat, vui long thu lai sau.
```

### 8.7 Runtime log excerpt captured

```text
Receive AskProductAIAssistant for product id:L9ECAV7KIM, question: Can you summarize the product reviews?
Using env override for feature flag llmInaccurateResponse: True
llmInaccurateResponse feature flag: True
Returning an inaccurate response for product_id: L9ECAV7KIM
Using inaccurate summary fixture for product_id: L9ECAV7KIM
Summary rejected by evaluator for product_id:L9ECAV7KIM judge_provider=bedrock judge_model=amazon.nova-micro-v1:0 unsupported=4 contradicted=0 reason=The candidate summary contradicts the raw reviews which all praise the cleaning kit for its effectiveness, versatility, and value. None of the reviews mention ineffectiveness, sticky residue, harsh brushes, scratches, or damage to equipment.
```

### 8.8 Conclusion for inaccurate runtime trace

Guard reject/fallback da hoat dong dung:
- Summary sai khong den duoc client.
- Runtime chan no truoc khi response roi khoi service.

## 9. Runtime blockers encountered and how they were fixed

### 9.1 Blocker 1: review parsing failed in the Bedrock path

Symptom dau tien:

```text
Error filtering reviews for Bedrock path: could not convert string to float: 'r'
```

Root cause:
- `normalize_reviews_for_context(...)` dang gia dinh sai payload shape cua review.
- Dong thoi, `DB_CONNECTION_STRING` ban dau tro toi `demo` thay vi `otel`, lam `fetch_product_reviews(...)` tra ve JSON loi thay vi danh sach review that.

Fix ap dung:
- `normalize_reviews_for_context(...)` duoc sua de:
  - handle payload list/tuple thuc te
  - handle dict review rows
  - fail fast neu gap payload `{"error": ...}`
  - bo qua malformed row va invalid score
- local DB duoc doi sang `dbname=otel`

Trang thai:
- Resolved.

### 9.2 Blocker 2: host-run instances collided on port 8085

Symptom:

```text
RuntimeError: Failed to bind to address [::]:8085
WSA Error 10048
```

Root cause:
- Co hon 1 process `product_reviews_server.py` cung bind vao `8085`.

Operational note:
- Chi nen chay 1 host-run process tren `8085` tai 1 thoi diem.
- Neu can parallel trace, moi process phai dung mot port rieng.

### 9.3 Blocker 3: prompt-only inaccurate mode was not deterministic

Symptom:
- Bat `llmInaccurateResponse` nhung candidate van co luc tra summary gan dung.

Root cause:
- Yeu cau model "make the answer inaccurate" chi la prompt control, khong phai deterministic control.

Fix ap dung:
- Them inaccurate fixture co dinh cho `L9ECAV7KIM`.

Trang thai:
- Resolved cho local negative-control test.

### 9.4 Blocker 4: retry ton tai trong codebase nhung chua thuc su duoc dung

Trang thai ban dau:
- `guardrails/fallback.py` da co `MAX_RETRIES=3` va `with_fallback(...)`.
- Nhung neu runtime khong boc cac network call bang decorator nay thi retry thuc te khong chay.

Fix ap dung:
- Candidate calls va judge call duoc boc boi `@with_fallback`.

Ket qua:
- Retry 3 lan gio da la runtime behavior that, khong con chi nam trong file helper.

## 10. Offline evaluator trace: `repro/eval_fidelity.py`

### 10.1 Goal

Kiem tra xem offline evaluator co da dong bo voi kien truc runtime moi hay chua.

### 10.2 Historical blockers before the fixes

#### Block A: `DB_CONNECTION_STRING` parser mismatch

Lan run that bai dau tien dung:

```text
DB_CONNECTION_STRING=host=localhost user=otelu password=otelp dbname=otel port=50319
PRODUCT_REVIEWS_ADDR=localhost:8085
```

Observed error:

```text
could not translate host name "localhost user=otelu password=otelp dbname=otel port=50319" to address
```

Root cause:
- `eval_fidelity.py` ban dau chi hieu format:
  - `Host=...;Username=...;Password=...;Database=...;Port=...`
- trong khi local runtime/AIE1 doc guide moi lai dung format:
  - `host=... user=... password=... dbname=... port=...`

#### Block B: judge path only supported OpenAI-compatible client

Sau khi vuot qua blocker A, invalid-run tiep theo la:

```text
OPENAI_API_KEY is required for LLM judge evaluation.
```

Root cause:
- `judge_fidelity()` hard-code `OpenAI(...)`
- du `JUDGE_MODEL=amazon.nova-micro-v1:0`, code van assume OpenAI-compatible path
- khong co nhanh Bedrock direct qua `boto3`

#### Block C: invalid-run branch overwrote `format_passed`

Day la bug an:
- `aggregate_case_result(...)` set cung `format_passed=False` neu `invalid_run`
- du `rule_checks["format_passed"]` da tinh dung truoc do

#### Block D: artifact metadata looked like OpenAI even when Bedrock was used

Artifact trung gian van ghi:

```json
"judge_provider": "bedrock",
"judge_base_url": "https://api.openai.com/v1"
```

Van de nay khong lam sai ket qua, nhung gay hieu nham khi doc lai artifact.

#### Block E: top-level `boto3` import could crash OpenAI-only runs

Neu may nao chua cai `boto3`, script se crash ngay luc import du cho ho chi muon dung OpenAI judge.

### 10.3 Fixes applied to `eval_fidelity.py`

Sau khi sua, `eval_fidelity.py` co cac thay doi sau:

1. `parse_db_conn_string(...)` hieu ca 2 format:
   - `Host=...;Username=...;Password=...;Database=...;Port=...`
   - `host=... user=... password=... dbname=... port=...`
2. `open_db_connection()` map duoc ca:
   - `username` va `user`
   - `database` va `dbname`
3. Local defaults da dong bo:
   - default DB -> `otel`
   - default gRPC addr -> `localhost:8085`
4. `judge_fidelity(...)` ho tro:
   - `judge_provider=openai`
   - `judge_provider=bedrock`
5. Bedrock judge su dung `boto3.client("bedrock-runtime").converse(...)`
6. `aggregate_case_result(...)` giu dung `format_passed` ngay ca khi `invalid_run`
7. `judge_base_url` chi duoc ghi vao report khi provider la `openai`
8. `judge_region` chi duoc ghi vao report khi provider la `bedrock`
9. `boto3` import tro thanh optional import, chi raise neu that su chay `judge_provider=bedrock` ma thieu dependency

### 10.4 Successful offline run after the fixes

Cau hinh run thanh cong:

```text
DB_CONNECTION_STRING=Host=localhost;Username=otelu;Password=otelp;Database=otel;Port=50319
PRODUCT_REVIEWS_ADDR=localhost:8085
JUDGE_PROVIDER=bedrock
JUDGE_MODEL=amazon.nova-micro-v1:0
JUDGE_REGION=us-east-1
```

Artifact clean sau cung:
- `repro/artifacts/fidelity_eval_20260714T152508Z.json`

Metadata cua artifact sau cung:

```json
{
  "judge_provider": "bedrock",
  "judge_base_url": "",
  "judge_region": "us-east-1",
  "judge_model": "amazon.nova-micro-v1:0"
}
```

Aggregate result:

```json
{
  "total_cases": 1,
  "ok_cases": 1,
  "passed_cases": 1,
  "fidelity_passed_cases": 1,
  "format_passed_cases": 1,
  "invalid_run_cases": 0,
  "avg_fidelity_score": 4.0,
  "avg_claim_precision": 1.0,
  "aspect_coverage_avg": 0.8,
  "sentiment_alignment_rate": 1.0
}
```

### 10.5 What the successful offline run actually did

1. Doc review that cua `L9ECAV7KIM` tu Postgres.
2. Goi live gRPC `AskProductAIAssistant` tren `localhost:8085`.
3. Nhan candidate summary do runtime Bedrock sinh ra.
4. Build `fact_sheet`.
5. Chay deterministic `rule_checks`.
6. Goi `amazon.nova-micro-v1:0` lam Bedrock direct judge.
7. Ghi artifact JSON.

### 10.6 Why runtime evaluator and offline evaluator both still exist

Hai luong nay giai quyet hai bai toan khac nhau:
- Runtime evaluator: bao ve serving path, chan summary sai truoc khi user thay
- Offline evaluator: benchmark va audit toan he thong sau thay doi model/prompt/guardrail

Runtime evaluator KHONG thay the `eval_fidelity.py`.
No chi giai bai toan online serving.

## 11. Trace mapping for bug investigation

Neu can debug mot bug moi o fidelity evaluation, thu tu map hop ly la:

1. Runtime path:
   - `product_reviews_server.py:get_ai_assistant_response(...)`
   - `product_reviews_server.py:post_process_output(...)`
   - `product_reviews_server.py:call_summary_judge(...)`
   - `guardrails/evaluator.py:evaluate_summary_fidelity(...)`
2. Neu symptom nam o reviews input:
   - `product_reviews_server.py:normalize_reviews_for_context(...)`
   - `database.py:fetch_product_reviews_from_db(...)`
3. Neu symptom nam o retry/fallback:
   - `guardrails/fallback.py:with_fallback(...)`
   - `guardrails/fallback.py:handle_exception(...)`
4. Neu symptom nam o offline artifact:
   - `repro/eval_fidelity.py:evaluate_one_product(...)`
   - `repro/eval_fidelity.py:judge_fidelity(...)`
   - `repro/eval_fidelity.py:aggregate_case_result(...)`
   - `repro/eval_fidelity.py:summarize_suite(...)`

## 12. Overall conclusion

### 12.1 Runtime path

AIE1 runtime da chay duoc voi kien truc moi:
- candidate = Bedrock Nova Lite
- judge = Bedrock Nova Micro
- evaluator dat sau `output_filter`
- inaccurate summary bi reject va thay bang fallback an toan
- retry 3 lan da la behavior that nhờ `@with_fallback`

### 12.2 Offline evaluation path

Offline evaluator khong con bi block boi cac assumption cu:
- parser DB da khop local runtime moi
- judge path da ho tro Bedrock direct
- invalid-run aggregation khong con lam sai `format_passed`
- artifact metadata khong con lam hieu nham la OpenAI run

### 12.3 Remaining notes

1. Runtime va offline evaluator hien da nhat quan ve provider path Bedrock direct.
2. Inaccurate fixture cho `L9ECAV7KIM` nen duoc giu lai de lam negative-control test on-demand.
3. Neu can chay nhieu host-run instance, phai tach cong gRPC.
4. `docs/guides/TEST_SERVICES_GUIDE.md` da duoc sua de dung local DB `otel` thay vi `demo`.
