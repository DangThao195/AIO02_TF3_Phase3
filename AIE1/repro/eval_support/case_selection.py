"""Shared JSONL test-case loading and label-based selection helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


EXPECTED_BEHAVIORS = {
    "normal": {"answer"},
    "unanswerable": {"no_info"},
    "off_topic": {"out_of_scope"},
    "injection_query": {"block"},
    "hallucination_probe": {"reject_unsupported"},
    "toxic_review": {"redact", "pass_clean"},
}

LEGACY_EXPECTED_BEHAVIOR_ALIASES = {
    ("unanswerable", "fallback"): "no_info",
}


def parse_csv_labels(value: str) -> List[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def load_jsonl_cases(path: Path) -> Tuple[List[Dict[str, Any]], bytes]:
    raw_bytes = path.read_bytes()
    cases: List[Dict[str, Any]] = []
    for line_number, line in enumerate(raw_bytes.decode("utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Dataset line {line_number} must be a JSON object.")
        cases.append(row)
    return cases, raw_bytes


def normalize_expected_behavior(case: Dict[str, Any]) -> None:
    case_type = case.get("type")
    expected_behavior = case.get("expected_behavior")
    alias = LEGACY_EXPECTED_BEHAVIOR_ALIASES.get((case_type, expected_behavior))
    if alias is not None:
        case["expected_behavior"] = alias


def validate_case_labels(cases: Sequence[Dict[str, Any]]) -> None:
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset contains duplicate case ids.")
    for case in cases:
        case_type = case.get("type")
        if case_type not in EXPECTED_BEHAVIORS:
            raise ValueError(f"Unsupported dataset case type: {case_type!r}")
        normalize_expected_behavior(case)
        if case.get("expected_behavior") not in EXPECTED_BEHAVIORS[case_type]:
            raise ValueError(
                f"Case {case.get('id')} has invalid expected_behavior "
                f"{case.get('expected_behavior')!r} for type {case_type!r}."
            )


def _validate_requested_labels(
    case_types: Iterable[str],
    expected_behaviors: Iterable[str],
) -> None:
    unknown_types = sorted(set(case_types) - set(EXPECTED_BEHAVIORS))
    if unknown_types:
        raise ValueError(f"Unsupported --case-types labels: {', '.join(unknown_types)}")
    valid_behaviors = {label for labels in EXPECTED_BEHAVIORS.values() for label in labels}
    unknown_behaviors = sorted(set(expected_behaviors) - valid_behaviors)
    if unknown_behaviors:
        raise ValueError(f"Unsupported --expected-behaviors labels: {', '.join(unknown_behaviors)}")


def select_cases_by_labels(
    cases: Sequence[Dict[str, Any]],
    case_types: Iterable[str] | None = None,
    expected_behaviors: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    selected_types = set(case_types or [])
    selected_behaviors = set(expected_behaviors or [])
    _validate_requested_labels(selected_types, selected_behaviors)

    if not selected_types and not selected_behaviors:
        return list(cases)

    selected = []
    for case in cases:
        if selected_types and case.get("type") not in selected_types:
            continue
        if selected_behaviors and case.get("expected_behavior") not in selected_behaviors:
            continue
        selected.append(case)
    return selected


def selection_rule(case_types: Iterable[str] | None = None, expected_behaviors: Iterable[str] | None = None) -> str:
    parts: List[str] = []
    selected_types = sorted(set(case_types or []))
    selected_behaviors = sorted(set(expected_behaviors or []))
    if selected_types:
        parts.append(f"type={selected_types[0]}" if len(selected_types) == 1 else "type IN (" + ", ".join(selected_types) + ")")
    if selected_behaviors:
        parts.append(
            f"expected_behavior={selected_behaviors[0]}"
            if len(selected_behaviors) == 1
            else "expected_behavior IN (" + ", ".join(selected_behaviors) + ")"
        )
    return " AND ".join(parts) if parts else "all_cases"


def build_selection_metadata(
    path: Path,
    raw_bytes: bytes,
    source_cases: Sequence[Dict[str, Any]],
    selected_cases: Sequence[Dict[str, Any]],
    case_types: Iterable[str] | None = None,
    expected_behaviors: Iterable[str] | None = None,
) -> Dict[str, Any]:
    source_counts = Counter(str(case.get("type", "missing_type")) for case in source_cases)
    selected_counts = Counter(str(case.get("type", "missing_type")) for case in selected_cases)
    excluded_counts = source_counts - selected_counts
    return {
        "case_file": str(path),
        "dataset_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "source_case_count": len(source_cases),
        "selected_case_count": len(selected_cases),
        "excluded_case_count": len(source_cases) - len(selected_cases),
        "source_by_type": dict(sorted(source_counts.items())),
        "selected_by_type": dict(sorted(selected_counts.items())),
        "excluded_by_type": dict(sorted(excluded_counts.items())),
        "case_types": sorted(set(case_types or [])),
        "expected_behaviors": sorted(set(expected_behaviors or [])),
        "selection_rule": selection_rule(case_types, expected_behaviors),
    }
