# Chaos Engine — Tài liệu vận hành & vấn đáp (TF3 AIOps)

> Tài liệu này giải thích **chaos validation harness** của TF3: nó test cái gì, chạy như thế nào,
> pipeline gọi file nào, và cơ chế remediation/auto-action đằng sau. Dùng để nắm vững cơ chế +
> chuẩn bị trình bày với mentor.
>
> Liên quan: [AIOPS-EXPERIENCE-PLAYBOOK.md](AIOPS-EXPERIENCE-PLAYBOOK.md) §1.8 (lý thuyết chaos) ·
> [SELF-HEALING-CHECKLIST.md](SELF-HEALING-CHECKLIST.md) (vòng closed-loop) ·
> [AIOPS-PROBLEM-STATEMENT.md](AIOPS-PROBLEM-STATEMENT.md).

---

## 0. TL;DR — chaos này là gì, KHÔNG phải gì

- **Là:** một harness **offline, deterministic** đo chất lượng của *chính pipeline AIOps*
  (detect → correlate → RCA). Nó "bơm" tín hiệu lỗi mô phỏng rồi kiểm tra pipeline có
  **phát hiện đúng** (recall), **chỉ đúng thủ phạm** (RCA accuracy), và **không báo nhầm**
  (false alarm) hay không.
- **KHÔNG phải:** chaos injection thật vào cluster (không `kubectl delete pod`, không `tc netem`).
  Triết lý W3-D2: *"system alive" không phải thước đo — thước đo là confusion matrix của pipeline*.
  Vì thế ta test pipeline bằng tín hiệu tổng hợp, chạy được trong CI, không cần EKS.
- **Vì sao quan trọng:** đây là **bằng chứng định lượng** để bảo vệ trước mentor/panel —
  "pipeline của tôi bắt được 100% 10 loại sự cố, chỉ đúng thủ phạm, 0 báo nhầm" thay vì
  "tôi tin là nó chạy".

---

## 1. Luồng hoạt động của engine chaos (pipeline run)

### 1.1 File gọi file nào

```
scripts/chaos_validate.py                    ← ENTRY POINT (chạy tay hoặc CI)
  │
  ├─ import ai_engine.aiops.correlator.Correlator        (thật, không mock)
  ├─ import ai_engine.aiops.rca_assistant.RCAAssistant   (thật, không mock)
  ├─ import ai_engine.aiops.detector_burnrate.BurnSignal (dataclass tín hiệu)
  ├─ import ai_engine.aiops.detector_anomaly.AnomalySignal
  └─ import ai_engine.common.schemas.{Severity, SourceLayer}
  │
  ├─ experiments()        → dựng 12 kịch bản (10 fault + 2 control)
  │
  ├─ run_experiment(exp)  → VÒNG LẶP MÔ PHỎNG mỗi experiment:
  │     for tick in tbuilt-in ticks:
  │        Correlator.correlate(burns, anomalies)  → list[Incident]
  │        (đo detect + MTTD)
  │     RCAAssistant.build(first_critical_incident) → EvidencePack
  │        │  (RCA build gọi tiếp, TẤT CẢ với telemetry stub trả rỗng:)
  │        ├─ _gather_traces()  → _StubJaeger.find_error_traces() → []
  │        ├─ _gather_logs()    → _StubOS.search()               → {}
  │        ├─ _rank_hypotheses() → score_candidates() (graph+timestamp)
  │        └─ match_incident_locally() (local_matcher, offline fallback)
  │        (đo RCA top-3 có chứa đúng culprit không)
  │
  ├─ scoreboard(results)  → tính recall / RCA-acc / false-alarm → markdown
  │
  └─ main() → in console + ghi chaos/scoreboard.md → exit 0 (PASS) / 1 (FAIL)
```

**Điểm mấu chốt:** `Correlator` và `RCAAssistant` là **code production thật** — chaos chỉ thay
*nguồn tín hiệu* (bơm `BurnSignal`/`AnomalySignal` dựng sẵn) và *nguồn telemetry* (stub trả rỗng).
Nghĩa là nếu logic correlate/RCA sai, chaos sẽ bắt được — đúng mục đích "test pipeline".

### 1.2 Trình tự thời gian trong mỗi experiment (mô phỏng đúng đời thật)

| Tick | Thời điểm | Sự kiện bơm vào | Ý nghĩa |
|---|---|---|---|
| 1 | +30s | Layer-2 **anomaly** (WARNING) trên service *thủ phạm* | Tín hiệu cảnh báo sớm đi TRƯỚC (z-score/iforest/log) |
| 2 | +60s | **Burn-rate** CRITICAL trên service *bị ảnh hưởng* + anomaly tiếp | SLO vỡ — pipeline phải correlate về 1 incident, chỉ đúng thủ phạm |

Trình tự "warning trước, breach sau" là có chủ đích: nó cho `score_candidates` dữ liệu
`first_seen` để phân biệt **thủ phạm động trước** vs **nạn nhân động sau** (chống retry-storm).

### 1.3 MTTD được tính thế nào

`mttd_s = (tick_phát_hiện − fault_start_tick + 1) × TICK_S(30s)`. Đây là **con số mô phỏng**
(tick cố định 30s như nhịp `AIOpsEngine.run()` thật). Trên cluster thật phải đo lại — scoreboard
ghi rõ điều này để không nhầm số mô phỏng thành số production.

---

## 2. Cách chạy chaos trên máy (checklist môi trường)

### 2.1 Yêu cầu

| Mục | Giá trị | Ghi chú |
|---|---|---|
| Python | 3.11+ (máy đang dùng **3.13.14**) | `pyproject.toml` yêu cầu `>=3.11` |
| Virtualenv | `TF3/ai-engine/.venv` | đã tồn tại |
| Dependency lõi | pydantic, httpx, prometheus-client, PyYAML, openai | `pip install -e .` |
| Dependency `[ml]` (cho iforest) | scikit-learn, numpy | **đã cài** — chỉ cần nếu chạy test iforest, chaos harness KHÔNG cần |
| Cluster / AWS / Slack | **KHÔNG cần** | chaos chạy offline hoàn toàn |

### 2.2 Các bước chạy (đúng trên máy này)

```powershell
cd D:\AWS\AIO23\phase3\TF3\ai-engine
.venv\Scripts\python scripts\chaos_validate.py
```

Kết quả mong đợi: in bảng scoreboard ra console + ghi `chaos\scoreboard.md`, exit code 0.

### 2.3 Nếu chạy trên máy MỚI (chưa có venv) — các mục phải bổ sung/cập nhật

```powershell
cd D:\AWS\AIO23\phase3\TF3\ai-engine
py -3.11 -m venv .venv                       # hoặc python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e .           # dependency lõi
.venv\Scripts\python -m pip install -e ".[ml,dev]" # thêm sklearn (iforest) + pytest
.venv\Scripts\python scripts\chaos_validate.py
```

**Các điểm dễ vấp (phải sửa nếu gặp):**

1. **`ModuleNotFoundError: ai_engine`** → chaos_validate.py đã tự chèn `src/` vào `sys.path`
   (dòng 25). Nếu vẫn lỗi, chạy từ **đúng thư mục `ai-engine/`** (không phải từ TF3/).
2. **`sklearn not found`** khi chạy *test* iforest → cài `[ml]` extra. Chaos harness không import
   sklearn nên không bị ảnh hưởng.
3. **Encoding console Windows** → scoreboard có emoji ✅/❌; nếu terminal lỗi unicode, mở
   `chaos\scoreboard.md` (ghi UTF-8) thay vì đọc console.
4. **Muốn chạy trong CI** → thêm step: `python scripts/chaos_validate.py`; exit code 1 khi trượt
   ngưỡng sẽ làm CI fail — dùng như một acceptance gate.

### 2.4 Muốn mở rộng bộ test (thêm sự cố mới)

Sửa hàm `experiments()` trong `chaos_validate.py`: thêm một `Experiment(...)` với `ticks`
(tick→(burns, anomalies)) và `expected_culprit`. Không cần đụng tới correlator/RCA.

---

## 3. Công nghệ & các lỗi/case bơm vào

### 3.1 Công nghệ dùng

| Thành phần | Công nghệ | Vai trò trong chaos |
|---|---|---|
| Ngôn ngữ | Python 3.11+ (stdlib `asyncio`, `dataclass`) | harness thuần, không framework |
| Pipeline thật | `Correlator` (dependency-graph + dedup) · `RCAAssistant` (graph+temporal ranking) | đối tượng ĐƯỢC test |
| Tín hiệu | `BurnSignal` (SLO burn-rate) · `AnomalySignal` (z-score/iforest/log) | dữ liệu bơm vào |
| Telemetry | Stub trả rỗng (`_StubJaeger`, `_StubOS`) | ép RCA đi đường fail-graceful, chứng minh pack vẫn ship khi telemetry mù |
| Đo lường | Confusion matrix (TP/FN/FP), MTTD, RCA top-3 accuracy | scoreboard |

### 3.2 12 case bơm vào (map 1-1 với INCIDENT_HISTORY.md)

| Exp | Nguồn | Lỗi mô phỏng | Culprit kỳ vọng | Điểm test đặc biệt |
|---|---|---|---|---|
| exp01 | INC-1 | PostgreSQL pool exhaustion | product-catalog | correlate downstream |
| exp02 | INC-2 | Valkey cart state loss (SPOF) | valkey-cart | culprit ngoài DEPENDENCY_MAP |
| exp03 | INC-3 | gRPC EventStream timeout | kafka | |
| exp04 | INC-4 | Bedrock 429 rate limit | llm | |
| exp05 | INC-5 | Kafka consumer lag | kafka | |
| exp06 | INC-6 | Memory pressure + GC | recommendation | |
| exp07 | INC-7 | Circuit breaker kẹt OPEN | product-reviews | **không có downstream** — test nhánh flagd hypothesis |
| exp08 | INC-8 | Cold start currency (self-heal) | currency | |
| exp09 | RETRY-STORM | payment (nạn nhân) ồn hơn product-catalog (thủ phạm) | product-catalog | **chống retry-storm** — timestamp fusion |
| exp10 | MULTI-FAULT | 2 fault độc lập cùng lúc | checkout(+frontend) | phải ra **2 incident**, không gộp |
| ctrl01 | CONTROL | không có lỗi | (none) | **false-alarm = 0** |
| ctrl02 | CONTROL | dup storm cùng signal 3 tick | (none) | **dedup fold về 1 incident** |

exp09 và ctrl02 là 2 case "khó" nhất — chúng chứng minh pipeline không bị lừa bởi 2 failure-mode
kinh điển (retry storm rank nhầm nạn nhân, và alert flood).

---

## 4. Remediation — xác định thế nào, dựa trên cơ sở nào

> Lưu ý: chaos harness hiện **đo đến bước RCA** (detect→correlate→diagnose). Phần remediation
> dưới đây là *đường production thật* trong `server.py` mà chaos chưa replay end-to-end —
> mô tả ở đây để trả lời mentor "sau khi RCA xong thì hành động thế nào".

### 4.1 Action đưa ra dựa trên cơ sở nào?

`action_policy.propose_for(service)` — **bảng tra cứu theo service bị ảnh hưởng**, mỗi entry là
action *đúng* rút từ INCIDENT_HISTORY.md, KHÔNG phải LLM tự nghĩ:

| Service | Action | Cơ sở (bài học lịch sử) |
|---|---|---|
| checkout | SCALE 2→4 | INC-1: cạn DB pool khi tải → scale giãn tải |
| frontend | SCALE 2→4 | flood/latency p95 vỡ → hấp thụ tải |
| kafka | SCALE consumer 1→3 | INC-5: consumer lag → tiêu lag |
| **cart** | **None** | **INC-2: SPOF single-replica — restart mất giỏ, KHÔNG auto-mutate** |
| ad/recommendation/llm/email | None | xử ở tầng khác (degrade/guardrail) hoặc cần người |

Trả `None` = "chỉ alert + RCA, không đề xuất mutate" — mặc định AN TOÀN.

### 4.2 Remediation xác định như thế nào (defense-in-depth)

Mọi action đi qua `RemediationEngine` (`remediation.py`) với các lớp:

1. **Safety gate** (`_safety_gate`): action phải trong whitelist; **hard-block** target chạm
   flagd/BTC flag (RULES §8 — tắt flag = bị loại); từ chối restart service single-replica (INC-2);
   bắt buộc có `rollback_plan`.
2. **Risk Assessment** (`action_policy.assess_risk`) → Low/Medium/High (xem §4.3).
3. **Dry-run** trước: `kubectl --dry-run=server` — nếu fail → risk HIGH → reject.
4. **Approval/Execute** theo risk.
5. **Verify 5 phút** (`verify_loop`): poll SLI mỗi 30s trong 300s; telemetry mù = coi như
   CHƯA hồi phục (fail-safe).
6. **Rollback/Escalate**: verify fail hoặc apply fail → tự rollback; rollback cũng fail → page người.
7. **Audit append-only**: ghi mọi trạng thái (proposed→executed→verified/rolled-back).

### 4.3 Auto-action khi nào? (nhánh Low của sơ đồ closed-loop)

`assess_risk()` gộp **dry-run + blast radius + service tier + loại action + confidence** → 3 mức:

| Điều kiện | Mức | Quyết định |
|---|---|---|
| dry-run FAIL | HIGH | **Reject** — chỉ alert |
| blast ≥ 5 service | HIGH | **Reject** |
| action không idempotent (restart/breaker/toggle) | MEDIUM | **Human Approval** (Slack) |
| service tier-1 (checkout/payment/cart/frontend) | MEDIUM | **Human Approval** |
| blast ≥ 2 service | MEDIUM | **Human Approval** |
| confidence < 0.85 | MEDIUM | **Human Approval** |
| **còn lại** (nhẹ + idempotent + hẹp + ngoài tier-1 + chắc) | **LOW** | **Auto-execute** |

**Auto-action (`remediation.auto_execute`) chỉ chạy ở mức LOW.** Ví dụ điển hình: `SCALE`/`CACHE_FLUSH`
cho `recommendation`/`ad` (service phụ trợ, idempotent, blast hẹp, confidence cao). Ngay cả khi
tự chạy, nó **vẫn** qua dry-run → verify 5 phút → rollback nếu không hồi phục — chỉ bỏ đúng
một bước "chờ người bấm". Approver ghi là `AUTO_APPROVER` (không giả danh người) để audit minh bạch.

---

## 5. Giới hạn & việc còn treo (nói thẳng với mentor)

- **Chaos chưa replay tới remediation end-to-end** — hiện đo tới RCA. Muốn đo cả vòng
  (detect→...→verify→rollback) cần mở rộng harness bơm cả kết quả verify.
- **MTTD là số mô phỏng** (tick 30s), không phải đo trên cluster thật.
- **G4 (SELF-HEALING-CHECKLIST):** `verify` giả định recording-rule `sli:{svc}_error:ratio_rate5m`
  tồn tại; nếu CDO chưa tạo, verify sẽ "mù → rollback" nhầm. Cần guard: rule thiếu → escalate.
- **Telemetry stub trả rỗng** — chaos test đúng đường fail-graceful, nhưng không test đường
  "telemetry trả data thật" (đó là việc của test tích hợp trên cluster).

---

## 6. Vấn đáp chuẩn bị trình bày với mentor

**Q1. Tại sao chaos của em không phá cluster thật (kill pod, netem) mà chỉ bơm tín hiệu?**
> Vì mục tiêu là đo *pipeline AIOps*, không đo *app*. W3-D2 nói rõ: "system alive" không phải
> thước đo — thước đo là pipeline có detect/correlate/RCA đúng không. Bơm tín hiệu cho phép em
> chạy deterministic trong CI (recall/RCA-acc/false-alarm ổn định), không tốn cluster. Chaos
> injection thật là bước tiếp theo trên staging, dùng Chaos Mesh/Pumba — em có kế hoạch nhưng
> harness này là lớp nền chạy mỗi commit.

**Q2. Correlator và RCA trong chaos là code thật hay mock?**
> Code thật. Em chỉ thay *nguồn tín hiệu* (bơm BurnSignal/AnomalySignal) và *telemetry*
> (stub rỗng). Nếu logic correlate hay ranking sai, chaos bắt được ngay — đó là điểm khác
> với unit test dùng input nhỏ.

**Q3. Recall 100% có phải quá đẹp / overfit không?**
> Là fair question. 100% trên **10 case em tự thiết kế** — nó chứng minh pipeline xử đúng
> những sự cố *đã biết* từ INCIDENT_HISTORY. Nó KHÔNG chứng minh với sự cố chưa từng thấy.
> Giá trị thật nằm ở 2 case khó: retry-storm (exp09) và dedup (ctrl02) — chúng test được
> 2 failure-mode mà pipeline naive sẽ trượt. Em sẽ thêm case đối kháng để hạ recall xuống
> rồi vá, đúng vòng "chaos liên tục" chứ không phải chạy 1 lần.

**Q4. Làm sao phân biệt thủ phạm với nạn nhân khi retry storm?**
> Fusion `0.6×structural + 0.4×temporal`. Structural: service là downstream bất thường.
> Temporal: `first_seen` — thủ phạm động TRƯỚC, nạn nhân động SAU. Trong exp09, payment bắn
> gấp đôi alert so với product-catalog, nhưng product-catalog động trước nên vẫn rank top-1.
> Naive "rank theo số alert" sẽ chọn nhầm payment.

**Q5. Auto-action có nguy hiểm không? Lỡ nó tự scale sai thì sao?**
> Auto chỉ chạy ở mức risk LOW (idempotent + hẹp + ngoài tier-1 + confidence cao), và VẪN
> qua dry-run + verify 5 phút + rollback. Nếu scale sai, verify thấy SLI không hồi phục →
> tự rollback. Nếu rollback cũng fail → page người. checkout/payment (tier-1) không bao giờ
> auto — luôn cần người duyệt. Và tuyệt đối không đụng flagd (hard-block, RULES §8).

**Q6. Tại sao telemetry mù thì coi là "chưa hồi phục" (rollback) chứ không phải "cứ để nguyên"?**
> Fail-safe. Nếu em không nhìn thấy SLI, em không được phép *khẳng định* action đã cứu hệ thống.
> Giả định xấu (rollback) an toàn hơn giả định tốt (để nguyên một action có thể đang làm hại).
> Đây là nguyên tắc W3-D2 về monitoring dependency — không tin vào cái mình không đo được.

**Q7. Nếu chạy trên máy mentor mà lỗi thì fix gì đầu tiên?**
> Ba thứ: (1) đúng thư mục `ai-engine/`, (2) venv đã `pip install -e .`, (3) đọc
> `chaos/scoreboard.md` nếu console lỗi unicode. Chaos không cần cluster/AWS/Slack nên
> không có biến môi trường nào phải set — đó là chủ đích để nó chạy được ở mọi máy.

**Q8. Con số nào là bằng chứng em đưa ra hội đồng?**
> `chaos/scoreboard.md`: Recall 100% (10/10), RCA top-3 100%, false alarm 0, multi-fault
> tách incident đúng. Kèm 157/157 unit test pass. Đó là "evidence-driven", không phải "em tin".

---

*Chuẩn bị bởi: TF3 AIO. Cập nhật khi thêm case chaos hoặc mở rộng harness tới remediation.*
