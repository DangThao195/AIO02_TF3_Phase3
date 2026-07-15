# Hướng dẫn chạy Evaluation cho Shopping Copilot

## 1. Chạy unit test
Để kiểm tra các rule trust & safety cơ bản:

```bash
cd AIE2/shopping-copilot
pytest -q tests/test_evaluation/test_trust_safety.py tests/test_evaluation/test_eval_suite.py
```

## 2. Chạy evaluation suite từ file JSON
Để chạy hàng loạt case mẫu và xuất report:

```bash
cd AIE2/shopping-copilot
python scripts/run_eval_suite.py --input docs/sample_eval_cases.json --output-json reports/trust_safety_report.json --output-md reports/trust_safety_report.md
```

## 3. Xem kết quả
- JSON report: reports/trust_safety_report.json
- Markdown report: reports/trust_safety_report.md

## 4. Tham khảo spec
- Spec evaluation: docs/evaluation_rule.md
- ADR: docs/ADR/ADR1.md
