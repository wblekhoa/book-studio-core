#!/usr/bin/env python3
"""Validate source-aligned Book Studio translation cache coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(
    block_map_path: Path,
    translated_dir: Path,
    coverage_path: Path,
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    block_map = load_json(block_map_path)
    coverage = load_json(coverage_path)
    excluded = set(coverage.get("excluded_files", []))

    source_blocks: dict[str, dict[int, dict[str, Any]]] = {}
    for file_entry in block_map.get("files", []):
        source_path = file_entry.get("source_path")
        if not source_path or source_path in excluded:
            continue
        canonical_blocks = {
            block["block_index"]: block
            for block in file_entry.get("blocks", [])
            if block.get("canonical", True)
        }
        if canonical_blocks:
            source_blocks[source_path] = canonical_blocks

    declared_files = {
        entry["source_path"]: entry
        for entry in coverage.get("files", [])
        if isinstance(entry, dict) and entry.get("source_path")
    }
    expected_total = sum(len(blocks) for blocks in source_blocks.values())
    contract_errors: list[str] = []
    if coverage.get("canonical_total") != expected_total:
        contract_errors.append(
            f"coverage canonical_total={coverage.get('canonical_total')} but source map yields {expected_total}"
        )
    for source_path, blocks in source_blocks.items():
        declared = declared_files.get(source_path)
        if declared is None:
            contract_errors.append(f"coverage file missing: {source_path}")
        elif declared.get("target_blocks") != len(blocks):
            contract_errors.append(
                f"coverage target mismatch for {source_path}: {declared.get('target_blocks')} != {len(blocks)}"
            )

    seen: dict[str, dict[int, str]] = {}
    duplicate_blocks: list[str] = []
    extra_blocks: list[str] = []
    source_hash_mismatches: list[str] = []
    empty_translations: list[str] = []
    cache_files = 0

    for cache_path in sorted(translated_dir.glob("*.json")):
        data = load_json(cache_path)
        source_path = data.get("source_path")
        blocks = data.get("blocks")
        if not source_path or not isinstance(blocks, list):
            continue
        cache_files += 1
        file_seen = seen.setdefault(source_path, {})
        expected = source_blocks.get(source_path)
        for fallback_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                empty_translations.append(f"{cache_path.name}:{fallback_index}")
                continue
            block_index = block.get("block_index", fallback_index)
            key = f"{source_path}:{block_index}"
            if block_index in file_seen:
                duplicate_blocks.append(key)
                continue
            file_seen[block_index] = cache_path.name
            translation = block.get("translation")
            if not isinstance(translation, str) or not translation.strip():
                empty_translations.append(key)
            if expected is None or block_index not in expected:
                extra_blocks.append(key)
                continue
            expected_hash = expected[block_index].get("text_sha256")
            actual_hash = block.get("source_sha256")
            if actual_hash != expected_hash:
                source_hash_mismatches.append(
                    f"{key}:{actual_hash or 'missing'}!={expected_hash}"
                )

    missing_blocks: list[str] = []
    translated_total = 0
    for source_path, expected in source_blocks.items():
        actual_indices = set(seen.get(source_path, {}))
        expected_indices = set(expected)
        translated_total += len(actual_indices & expected_indices)
        missing_blocks.extend(f"{source_path}:{index}" for index in sorted(expected_indices - actual_indices))

    hard_errors = (
        contract_errors
        + duplicate_blocks
        + extra_blocks
        + source_hash_mismatches
        + empty_translations
    )
    if require_complete:
        hard_errors += missing_blocks

    return {
        "canonical_total": expected_total,
        "translated_total": translated_total,
        "remaining_total": len(missing_blocks),
        "cache_files": cache_files,
        "files_with_translation": len([values for values in seen.values() if values]),
        "complete": not missing_blocks,
        "contract_errors": contract_errors,
        "duplicate_blocks": duplicate_blocks,
        "extra_blocks": extra_blocks,
        "source_hash_mismatches": source_hash_mismatches,
        "empty_translations": empty_translations,
        "missing_blocks_sample": missing_blocks[:20],
        "hard_error_count": len(hard_errors),
        "passed": not hard_errors,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block-map", required=True, type=Path)
    parser.add_argument("--translated-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    result = validate(
        args.block_map,
        args.translated_dir,
        args.coverage,
        require_complete=args.require_complete,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
