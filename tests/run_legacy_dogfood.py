#!/usr/bin/env python3
"""Rebuild an explicit private legacy project and prove accepted-output parity."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from bookstudio.compat.legacy_builder import build_epub
from bookstudio.compat.legacy_coverage import validate as validate_coverage


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_receipt(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = 0
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        size = path.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
        files += 1
        total_bytes += size
    return {"sha256": digest.hexdigest(), "files": files, "bytes": total_bytes}


def input_receipt(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "source_sha256": sha256_file(args.source),
        "block_map_sha256": sha256_file(args.block_map),
        "coverage_sha256": sha256_file(args.coverage),
        "metadata_sha256": sha256_file(args.metadata),
        "accepted_sha256": sha256_file(args.accepted),
        "private_project_tree": tree_receipt(args.translations.parent),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    for path in (
        args.source,
        args.block_map,
        args.coverage,
        args.metadata,
        args.accepted,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not args.translations.is_dir():
        raise NotADirectoryError(args.translations)

    before = input_receipt(args)
    coverage = validate_coverage(
        args.block_map,
        args.translations,
        args.coverage,
        require_complete=True,
    )
    if not coverage["passed"]:
        return {
            "status": "error",
            "passed": False,
            "code": "LEGACY_COVERAGE_FAILED",
            "coverage": coverage,
            "inputs_unchanged": True,
        }

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="bookstudio-dogfood-") as directory:
        temporary = Path(directory)
        candidate = temporary / "candidate.epub"
        report_path = temporary / "build-report.json"
        build = build_epub(
            args.source,
            args.translations,
            candidate,
            mode="vi_only",
            metadata_config=metadata,
        )
        report_path.write_text(
            json.dumps(build, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        candidate_sha256 = sha256_file(candidate)
        byte_identical = filecmp.cmp(candidate, args.accepted, shallow=False)
        after = input_receipt(args)
        inputs_unchanged = before == after
        passed = byte_identical and inputs_unchanged
        return {
            "status": "pass" if passed else "error",
            "passed": passed,
            "code": "DOGFOOD_PARITY_PASS" if passed else "DOGFOOD_PARITY_FAILED",
            "candidate_sha256": candidate_sha256,
            "accepted_sha256": before["accepted_sha256"],
            "byte_identical": byte_identical,
            "inputs_unchanged": inputs_unchanged,
            "coverage": {
                "passed": coverage["passed"],
                "canonical_total": coverage["canonical_total"],
                "translated_total": coverage["translated_total"],
                "remaining_total": coverage["remaining_total"],
            },
            "private_project_tree": before["private_project_tree"],
            "build": {
                "applied_blocks": build["applied_blocks"],
                "image_annotation_blocks": build["image_annotation_blocks"],
                "image_companion_blocks": build["image_companion_blocks"],
                "market_context_blocks": build["market_context_blocks"],
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--block-map", required=True, type=Path)
    parser.add_argument("--translations", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--accepted", required=True, type=Path)
    args = parser.parse_args()
    try:
        receipt = run(args)
    except Exception as exc:
        receipt = {
            "status": "error",
            "passed": False,
            "code": "DOGFOOD_EXECUTION_FAILED",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
