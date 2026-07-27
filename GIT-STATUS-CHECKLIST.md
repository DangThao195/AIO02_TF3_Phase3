# Checklist Git — repo DangThao195/AIO02_TF3_Phase3 đã làm tới đâu

> Rà soát trạng thái repo nhóm (clone tại `D:\AWS\AIO23\AIO02_TF3_Phase3`, `main` đồng bộ
> `origin/main` @ `d239b60`, 2026-07-20). Mục đích: biết nhóm đã đẩy gì lên git, phần AIOps
> tới đâu, và bản code trên repo có phải bản mới nhất không.

## 1. Nhánh & tiến độ (commit mới nhất mỗi nhánh)

| Nhánh | Cập nhật | Nội dung mới nhất |
|---|---|---|
| `main` | 2026-07-20 | docs mandate 7a + 7b |
| `feature/copilot` | 2026-07-20 | eval baseline 100% guardrail (AIE agent) |
| `feat/-Bao` | 2026-07-19 | signed ADR |
| `feature/product-review` | 2026-07-19 | ADR từ feat/-Bao (AIE review) |
| `hao2k5` | 2026-07-17 | datametric training data (AIOps) |
| `kiedev` | 2026-07-16 | Mandate 7a detection + ADR |
| `feature/copilot-*`, `feature/lang-graph-copilot` | — | các biến thể copilot agent |

Repo có **9 nhánh** — nhóm chia việc theo feature (copilot/agent, product-review, aiops).

## 2. Cấu trúc repo (main)

```
AIO02_TF3_Phase3/
├── AIE1/                      # AI feature 1 (tóm tắt review)
├── AIE2/                      # AI feature 2 (copilot agent)
├── AIOps/                     # ← phần AIOps
│   ├── aiops-engine/          # engine flat-structure (anomaly_detector, rca_engine, main.tf...)
│   ├── chaos-engine/          # ← chaos + ai-engine (code Claude đã viết)
│   │   └── ai-engine/         # src/ai_engine (aiops/aie/agent), scripts/chaos_validate.py
│   ├── contracts/             # C1-C6
│   └── docs/                  # mandate, ADR, backlog, screenshot
├── CLAUDE.md, README.md, docs-*.md
```

## 3. AIOps đã làm tới đâu (trên main)

### ✅ Đã có trên git
- **Detection** (chaos-engine/ai-engine): burnrate, latency, anomaly, iforest, logtemplate.
- **RCA**: rca_assistant, rca_guardrail, kb_retriever, correlator, local_matcher.
- **Remediation**: remediation, action_policy, approval, verify_loop (có G4 `blind`), audit_log.
- **Chaos harness**: `chaos_validate.py` (12 experiment) + `chaos_scoreboard.md`.
- **7 ADR ký tên**: ADR-001..008 (thiếu 007) + CONSOLIDATED_ADR.
- **Mandate**: 7a (detection analysis) + 7b submission + Mandate-15.
- **Bằng chứng vận hành**: screenshot (Pod status, Slack), datametric training data.
- **2 engine song song**: `aiops-engine/` (flat, có main.tf + train_anomaly_model_eks) và
  `chaos-engine/ai-engine/` (structured — code Claude).

### ⚠️ Bản trên repo là bản TRUNG GIAN (chưa đồng bộ code mới nhất local)
So bản `chaos-engine/ai-engine` trên repo với bản local mới nhất
(`D:\AWS\AIO23\phase3\TF3\submit-final`):

| Nội dung | Trên repo DangThao | Bản local mới nhất |
|---|---|---|
| G4 verify blind | ✅ có | ✅ |
| G1 `assess_risk` (Risk 3 mức) | ❌ CHƯA | ✅ |
| G2 `auto_execute` | ❌ CHƯA | ✅ |
| BUG#2 `MAX_HISTORY_WINDOWS` | ❌ CHƯA | ✅ |
| `forecast.py` (dự báo capacity/cost) | ❌ CHƯA | ✅ |
| `detector_drift.py` (PSI) | ❌ CHƯA | ✅ |
| test count | ~157 | 180 |

→ **Repo đang thiếu**: G1/G2 (Risk Assessment + auto-execute), forecast, drift, bug#2 fix,
20 test mới. Nếu muốn repo có bản đầy đủ nhất, cần đẩy `submit-final` lên.

## 4. Việc còn thiếu trên git (theo checklist AIOps)

- ⚠️ **Đồng bộ code mới nhất**: đẩy G1/G2 + forecast + drift + bug fixes lên repo (repo đang cũ hơn local).
- ⚠️ **ADR-007** (multi-signal detection) — local đã có, repo có ADR-008 baseline nhưng thiếu 007.
- ❌ Các mục AIOps còn treo giống local: bằng chứng chạy liên tục cluster thật (MTTD/MTTR đo thật).

## 5. Kết luận

- **Local repo đã đồng bộ với remote** (`main` = `origin/main`, không có commit local chờ push).
- **Nhóm đã làm rất nhiều trên git**: đủ detection/RCA/remediation, 7 ADR, mandate 7a/7b, chaos
  scoreboard, screenshot vận hành, 2 engine.
- **Điểm cần lưu ý**: bản `chaos-engine/ai-engine` trên repo **cũ hơn** bản local mới nhất
  (thiếu Risk Assessment + auto-execute + forecast + drift). Đây không phải lỗi — chỉ là công
  việc mới nhất chưa được đẩy lên. Quyết định đẩy hay không là của bạn.

---
*Đọc read-only qua gh API + git local, không thay đổi gì trên repo.*
