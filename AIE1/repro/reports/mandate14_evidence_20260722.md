# Mandate #14 Evidence Snapshot — 2026-07-22

## Scope

This snapshot records the current AIE1 evidence for the eval runner, PII-in-review dataset coverage, LLM-as-a-judge agreement, and reproducibility targets.

## Completed evidence

| Area | Artifact / command | Result |
|---|---|---|
| Unit regression | `python -m pytest AIE1\repro\test_eval_fidelity.py -q` | `33 passed` |
| PII-in-review local sanitizer | `AIE1/repro/artifacts/toxic_pii_local_20260722T143414.json` | `16/16 passed`, quality gate passed |
| Judge-human agreement | `AIE1/repro/artifacts/judge_human_agreement_bedrock_20260722T143444.json` | `10/10 agreed`, agreement rate `1.0`, quality gate passed |
| Runtime core guardrail | `AIE1/repro/artifacts/dataset_runtime_core_mandate14_20260722T143855.json` | `190/197 passed`, no runtime errors, quality gate passed |
| Runtime hallucination probe | `AIE1/repro/artifacts/hallucination_runtime_probe_bedrock_20260722T144333.json` | `3/3 passed`, quality gate passed |
| Fidelity live run | `AIE1/repro/artifacts/fidelity_eval_mandate14_20260722T143945.json` | `36/43 passed`, quality gate passed |

## Dataset contract

`AIE1/repro/datasets/dataset.jsonl` currently contains:

| Type | Count |
|---|---:|
| `normal` | 43 |
| `unanswerable` | 11 |
| `off_topic` | 9 |
| `injection_query` | 118 |
| `toxic_review` | 16 |
| `hallucination_probe` | 3 |

Additional coverage:

- 200/200 rows include a `surface` field.
- PII-in-review Loại B cases: `147`, `152`, `153`.
- Hallucination runtime probes: `181`, `182`, `183`.
- Approved dataset SHA-256: `5fe93cd58dadddfdd17a1490e3463ee92507835e810bb1fd6092a1ad0db286fe`.

## Repro entrypoints

Primary entrypoints:

- `AIE1/repro/eval_fidelity.py`
- `AIE1/repro/run_eval_guardrail.py`

Support/audit modules:

- `AIE1/repro/eval_support/case_selection.py`
- `AIE1/repro/eval_support/judge_agreement.py`

One-command Makefile target:

```bash
cd AIE1
make eval-mandate14
```

## Re-run commands

```powershell
cd AIE1
make eval-mandate14
```

If `make` is unavailable on Windows, run the equivalent Python commands from the `Makefile` targets.
