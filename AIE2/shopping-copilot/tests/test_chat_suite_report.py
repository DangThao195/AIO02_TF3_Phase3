from pathlib import Path

from tests.chat_test_suite import run_chat_suite


def test_chat_suite_report_is_generated(tmp_path):
    output_markdown = tmp_path / "chat_test_suite_report.md"
    output_log = tmp_path / "chat_test_suite.log"

    results = run_chat_suite(output_markdown_path=output_markdown, log_path=output_log)

    assert output_markdown.exists(), "Markdown report should be created"
    assert output_log.exists(), "Log file should be created"
    assert len(results) >= 10, "At least 10 chat cases should be executed"
    report_text = output_markdown.read_text(encoding="utf-8")
    assert "# Shopping Copilot Chat Test Suite" in report_text
    assert "Guardrail" in report_text or "Fallback" in report_text
