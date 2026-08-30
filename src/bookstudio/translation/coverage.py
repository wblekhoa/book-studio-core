"""Independent strict translation coverage accounting."""

from __future__ import annotations

import json
from typing import Any

from ..config import ProjectConfig
from ..epub.extract import extract_block_map
from ..errors import BookStudioError
from .cache import read_json, validated_cache_index


_COVERAGE_KEYS = frozenset(
    {"schema_version", "source_sha256", "included_files", "excluded_files"}
)


def _coverage_schema_invalid(message: str) -> BookStudioError:
    return BookStudioError(
        code="COVERAGE_SCHEMA_INVALID",
        message=message,
        next_action="Restore the exact reviewed coverage contract for the prepared source.",
    )


def validate_coverage_contract(
    block_map: Any,
    contract: Any,
) -> dict[str, Any]:
    """Validate the exact source-bound coverage contract shared by every consumer."""
    source = block_map.get("source") if type(block_map) is dict else None
    files = block_map.get("files") if type(block_map) is dict else None
    current_source_hash = source.get("sha256") if type(source) is dict else None
    if (
        type(contract) is not dict
        or set(contract) != _COVERAGE_KEYS
        or type(contract.get("schema_version")) is not int
        or contract.get("schema_version") != 1
        or type(contract.get("source_sha256")) is not str
        or type(contract.get("included_files")) is not list
        or type(contract.get("excluded_files")) is not list
        or type(current_source_hash) is not str
        or type(files) is not list
    ):
        raise _coverage_schema_invalid(
            "Coverage must use the exact schema-versioned source scope contract."
        )

    included = contract["included_files"]
    excluded = contract["excluded_files"]
    source_paths = [
        file.get("source_path") if type(file) is dict else None for file in files
    ]
    if (
        any(type(value) is not str for value in source_paths)
        or any(type(value) is not str for value in included)
        or any(type(value) is not str for value in excluded)
        or len(set(included)) != len(included)
        or len(set(excluded)) != len(excluded)
        or included != source_paths
        or not set(excluded).issubset(set(included))
    ):
        raise _coverage_schema_invalid(
            "Coverage document lists must exactly match the prepared source order and exclusions."
        )
    if contract["source_sha256"] != current_source_hash:
        raise BookStudioError(
            code="COVERAGE_SOURCE_STALE",
            message="Coverage contract does not match the prepared source hash.",
            next_action="Run 'bookstudio prepare' and review exclusions again.",
        )
    return contract


def validate_prepared_block_map(
    config: ProjectConfig,
    block_map: Any,
    *,
    current_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the persisted map to be the exact deterministic source extraction."""
    fresh = extract_block_map(config.source) if current_map is None else current_map
    persisted_identity = json.dumps(
        block_map,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fresh_identity = json.dumps(
        fresh,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if type(block_map) is not dict or persisted_identity != fresh_identity:
        raise BookStudioError(
            code="BLOCK_MAP_STALE",
            message="Prepared full block map is incomplete, tampered, or stale.",
            next_action="Run 'bookstudio prepare' again before continuing.",
        )
    return fresh


def _inputs(config: ProjectConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    block_map = read_json(
        config.paths.source_blocks / "full-block-map.json",
        missing_code="BLOCK_MAP_MISSING",
        invalid_code="BLOCK_MAP_JSON_INVALID",
    )
    contract = read_json(
        config.paths.source_blocks / "coverage.json",
        missing_code="COVERAGE_CONTRACT_MISSING",
        invalid_code="COVERAGE_CONTRACT_JSON_INVALID",
    )
    if (
        type(block_map) is not dict
        or type(block_map.get("schema_version")) is not int
        or block_map.get("schema_version") != 1
    ):
        raise BookStudioError(
            code="COVERAGE_SCHEMA_INVALID",
            message="Block map must use schema_version 1.",
            next_action="Run 'bookstudio prepare' again.",
        )
    validate_prepared_block_map(config, block_map)
    return block_map, validate_coverage_contract(block_map, contract)


def target_index(
    config: ProjectConfig,
) -> tuple[dict[tuple[str, int], dict[str, Any]], int, dict[str, Any]]:
    block_map, contract = _inputs(config)
    excluded_files = set(contract.get("excluded_files", []))
    targets: dict[tuple[str, int], dict[str, Any]] = {}
    excluded = 0
    for file in block_map.get("files", []):
        source_path = file.get("source_path")
        for block in file.get("blocks", []):
            if not block.get("canonical") or block.get("watermark"):
                continue
            if source_path in excluded_files:
                excluded += 1
                continue
            targets[(source_path, block["block_index"])] = block
    return targets, excluded, block_map


def coverage_receipt(
    config: ProjectConfig, *, require_complete: bool
) -> dict[str, Any]:
    targets, excluded, block_map = target_index(config)
    source_hash = block_map.get("source", {}).get("sha256")
    translated_keys = set(
        validated_cache_index(
            config,
            targets=targets,
            source_sha256=source_hash,
        )
    )
    remaining = len(targets) - len(translated_keys)
    passed = remaining == 0 or not require_complete
    status = "pass" if passed else "incomplete"
    return {
        "status": status,
        "passed": passed,
        "schema_version": 1,
        "canonical": len(targets) + excluded,
        "eligible": len(targets),
        "translated": len(translated_keys),
        "remaining": remaining,
        "excluded": excluded,
        "extra": 0,
        "duplicate": 0,
        "empty": 0,
        "source_hash_mismatches": 0,
    }
