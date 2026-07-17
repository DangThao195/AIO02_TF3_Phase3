from pathlib import Path

from src.evaluation import BenchmarkCase, ShoppingBenchmarkEvaluator


CASES_PATH = Path(__file__).with_name("shopping_benchmark_cases.json")


def test_benchmark_cases_cover_core_capabilities():
    evaluator = ShoppingBenchmarkEvaluator()
    cases = evaluator.load_cases_from_file(CASES_PATH)

    assert len(cases) >= 16

    categories = {case.category for case in cases}
    assert {"search", "review", "cart", "compare", "cross_sell", "currency", "shipping", "multi_turn", "guardrail"}.issubset(categories)

    difficulty_order = {"easy": 0, "medium": 1, "hard": 2}
    levels = [difficulty_order[case.difficulty] for case in cases]
    assert levels == sorted(levels)

    multi_turn = [case for case in cases if case.session_tag]
    assert len(multi_turn) >= 4
    assert [case.turn for case in multi_turn] == sorted(case.turn for case in multi_turn)


def test_benchmark_scoring_checks_status_tools_and_token():
    evaluator = ShoppingBenchmarkEvaluator()
    case = BenchmarkCase(
        id="dummy-pending",
        category="cart",
        difficulty="hard",
        turn=1,
        user_query="thêm 2 cái Vintage Typewriter vào giỏ hàng",
        expected_status="pending",
        expected_tools=["add_to_cart_tool"],
        expected_contains=["xác nhận"],
    )

    response = {
        "status": "pending",
        "reply": "Vui lòng xác nhận thêm 2 sản phẩm vào giỏ hàng.",
        "token": "token-123",
        "steps": [{"action": "Công cụ: add_to_cart_tool"}],
    }

    result = evaluator.score_case(case, response)

    assert result.passed is True
    assert result.checks["status_ok"] is True
    assert result.checks["tools_ok"] is True
    assert result.checks["token_ok"] is True


def test_benchmark_export_report_writes_json_and_markdown(tmp_path):
    evaluator = ShoppingBenchmarkEvaluator()
    case = BenchmarkCase(
        id="case-1",
        category="search",
        difficulty="easy",
        turn=1,
        user_query="tìm kính thiên văn dưới 100 đô",
    )
    result = evaluator.score_case(
        case,
        {
            "status": "ok",
            "reply": "Tìm thấy 3 sản phẩm.",
            "steps": [{"action": "Công cụ: search_products_v2"}],
        },
    )
    report = evaluator.build_report([case], [result])

    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"

    evaluator.export_report(report, json_path)
    evaluator.export_report(report, md_path)

    assert json_path.exists()
    assert md_path.exists()
    assert '"case_id": "case-1"' in json_path.read_text(encoding="utf-8")
    assert "# Shopping Copilot Benchmark Report" in md_path.read_text(encoding="utf-8")
