#!/usr/bin/env python3
"""Validate candidate-bound contextual editorial review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


MAX_RECEIPT_BYTES = 2 * 1024 * 1024
RESULTS = frozenset({"pass", "fail", "unknown"})
REVIEWER_KINDS = frozenset({"self", "user", "independent"})
STATUSES = frozenset({"pass", "fail", "incomplete"})
CONTENT_MODES = frozenset(
    {
        "argument",
        "explanation",
        "instruction",
        "research",
        "narrative",
        "dialogue",
        "quotation",
        "case_study",
        "reference",
        "reflection",
        "other",
    }
)
CHECK_KEYS = frozenset(
    {
        "meaning_fidelity",
        "logic_and_qualifiers",
        "target_language_naturalness",
        "voice_and_register",
        "terminology",
        "cross_block_continuity",
    }
)
WHOLE_BOOK_KEYS = frozenset(
    {
        "source_term_introductions",
        "author_vs_added_context",
        "register_consistency",
    }
)
COVERAGE_KEYS = frozenset(
    {
        "front_matter_inventory",
        "front_matter_prose",
        "front_matter_image_text",
        "opening_voice",
        "difficult_passage",
        "material_content_modes",
        "cross_packet_boundary",
        "terminology_heavy_passage",
        "ending_voice",
    }
)
TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "candidate",
        "candidate_sha256",
        "production_brief_sha256",
        "reviewed_at",
        "reviewer_kind",
        "samples",
        "whole_book_checks",
        "coverage_checks",
        "findings",
        "status",
    }
)
SAMPLE_KEYS = frozenset(
    {"source_document", "location", "content_mode", "checks", "note"}
)
FINDING_KEYS = frozenset(
    {"severity", "location", "criterion", "result", "note"}
)


class ReceiptError(Exception):
    """Raised when review evidence is malformed, stale, or contradictory."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nonempty_text(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def _validate_reviewed_at(value: Any) -> None:
    if not _nonempty_text(value):
        raise ReceiptError("The editorial receipt field reviewed_at must be nonempty text.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReceiptError("The editorial receipt reviewed_at must be ISO-8601.") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ReceiptError("The editorial receipt reviewed_at must include a timezone.")


def _validate_candidate_label(
    label: Any, *, candidate_path: Path, receipt_path: Path
) -> None:
    if not _nonempty_text(label):
        raise ReceiptError("The editorial receipt field candidate must be nonempty text.")
    if "\\" in label:
        raise ReceiptError("The editorial receipt candidate must use a safe POSIX path.")
    relative = PurePosixPath(label)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ReceiptError("The editorial receipt candidate must be a safe relative path.")
    project_root = (
        receipt_path.parent.parent
        if receipt_path.parent.name == "reports"
        else receipt_path.parent
    )
    declared = project_root.joinpath(*relative.parts).resolve()
    if declared != candidate_path.resolve():
        raise ReceiptError("The editorial receipt candidate path does not match the reviewed file.")


def _load_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ReceiptError("The editorial receipt must be a real local file.")
    if path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ReceiptError("The editorial receipt exceeds the bounded size limit.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReceiptError("The editorial receipt must be valid UTF-8 JSON.") from exc
    if type(payload) is not dict or set(payload) != TOP_LEVEL_KEYS:
        raise ReceiptError("The editorial receipt has an invalid top-level schema.")
    return payload


def _validate_results(value: Any, expected_keys: frozenset[str], label: str) -> list[str]:
    if type(value) is not dict or set(value) != expected_keys:
        raise ReceiptError(f"The {label} result set has an invalid schema.")
    results = list(value.values())
    if any(type(result) is not str or result not in RESULTS for result in results):
        raise ReceiptError(f"The {label} results must be pass, fail, or unknown.")
    return results


def _expected_status(results: list[str], findings: list[dict[str, Any]]) -> str:
    hard_results = results + [
        finding["result"]
        for finding in findings
        if finding["severity"] == "hard"
    ]
    if "fail" in hard_results:
        return "fail"
    if "unknown" in hard_results:
        return "incomplete"
    return "pass"


def audit(
    candidate_path: Path, production_brief_path: Path, receipt_path: Path
) -> dict[str, Any]:
    candidate = candidate_path.expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise ReceiptError("The reviewed candidate must be a real local file.")
    production_brief = production_brief_path.expanduser()
    if production_brief.is_symlink() or not production_brief.is_file():
        raise ReceiptError("The reviewed production brief must be a real local file.")
    resolved_receipt_path = receipt_path.expanduser()
    receipt = _load_receipt(resolved_receipt_path)
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
        raise ReceiptError("The editorial receipt must use schema_version 1.")
    for key in ("candidate_sha256", "production_brief_sha256", "reviewer_kind"):
        if not _nonempty_text(receipt.get(key)):
            raise ReceiptError(f"The editorial receipt field {key} must be nonempty text.")
    _validate_candidate_label(
        receipt.get("candidate"),
        candidate_path=candidate,
        receipt_path=resolved_receipt_path,
    )
    _validate_reviewed_at(receipt.get("reviewed_at"))
    if receipt["reviewer_kind"] not in REVIEWER_KINDS:
        raise ReceiptError("The editorial reviewer_kind is unsupported.")
    if type(receipt.get("status")) is not str or receipt["status"] not in STATUSES:
        raise ReceiptError("The editorial receipt status is unsupported.")

    candidate_sha256 = _sha256(candidate)
    if receipt["candidate_sha256"].lower() != candidate_sha256:
        raise ReceiptError("The editorial receipt does not match the candidate bytes.")
    production_brief_sha256 = _sha256(production_brief)
    if receipt["production_brief_sha256"].lower() != production_brief_sha256:
        raise ReceiptError("The editorial receipt does not match the production brief.")

    samples = receipt.get("samples")
    if type(samples) is not list or not samples:
        raise ReceiptError("The editorial receipt must contain at least one sample.")
    results: list[str] = []
    content_modes: set[str] = set()
    for sample in samples:
        if type(sample) is not dict or set(sample) != SAMPLE_KEYS:
            raise ReceiptError("An editorial sample has an invalid schema.")
        for key in ("source_document", "location", "content_mode", "note"):
            if not _nonempty_text(sample.get(key)):
                raise ReceiptError(f"Every editorial sample needs nonempty {key} text.")
        if sample["content_mode"] not in CONTENT_MODES:
            raise ReceiptError("An editorial sample uses an unsupported content_mode.")
        content_modes.add(sample["content_mode"])
        results.extend(_validate_results(sample.get("checks"), CHECK_KEYS, "sample"))

    results.extend(
        _validate_results(
            receipt.get("whole_book_checks"), WHOLE_BOOK_KEYS, "whole-book"
        )
    )
    results.extend(
        _validate_results(
            receipt.get("coverage_checks"), COVERAGE_KEYS, "review-coverage"
        )
    )
    findings = receipt.get("findings")
    if type(findings) is not list:
        raise ReceiptError("Editorial findings must be a JSON array.")
    for finding in findings:
        if type(finding) is not dict or set(finding) != FINDING_KEYS:
            raise ReceiptError("An editorial finding has an invalid schema.")
        if finding.get("severity") not in {"hard", "advisory"}:
            raise ReceiptError("Editorial finding severity must be hard or advisory.")
        if finding.get("result") not in RESULTS:
            raise ReceiptError("Editorial finding result must be pass, fail, or unknown.")
        for key in ("location", "criterion", "note"):
            if not _nonempty_text(finding.get(key)):
                raise ReceiptError(f"Every editorial finding needs nonempty {key} text.")

    expected = _expected_status(results, findings)
    if receipt["status"] != expected:
        raise ReceiptError(
            "The editorial receipt status contradicts its independent criterion results."
        )
    return {
        "schema_version": 1,
        "status": expected,
        "passed": expected == "pass",
        "candidate_sha256": candidate_sha256,
        "production_brief_sha256": production_brief_sha256,
        "reviewer_kind": receipt["reviewer_kind"],
        "samples_reviewed": len(samples),
        "content_modes_reviewed": sorted(content_modes),
        "hard_checks": len(results),
        "findings": len(findings),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate contextual editorial evidence for one final candidate."
    )
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--production-brief", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="Emit a JSON receipt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = audit(args.candidate, args.production_brief, args.receipt)
    except (OSError, ReceiptError) as exc:
        result = {
            "schema_version": 1,
            "status": "error",
            "passed": False,
            "code": "EDITORIAL_RECEIPT_INVALID",
            "message": str(exc),
        }
        exit_code = 1
    else:
        exit_code = 0 if result["passed"] else 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"{result['status']}: {result.get('samples_reviewed', 0)} sample(s), "
            f"{result.get('hard_checks', 0)} hard check(s)"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
