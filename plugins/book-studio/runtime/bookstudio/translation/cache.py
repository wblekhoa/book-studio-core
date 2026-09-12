"""Atomic canonical translation-cache persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Collection, Mapping

from ..config import ProjectConfig, atomic_write_json, validate_project_node_shapes
from ..errors import BookStudioError
from ..safety.xhtml import validate_inline_xhtml
from .context import current_translation_context_sha256


CACHE_FILENAME = "translations.json"
_CACHE_KEYS = frozenset({"schema_version", "source_sha256", "files"})
_INTERNAL_ROW_KEYS = frozenset({"packet_id", "context_sha256"})
_REQUIRED_ROW_KEYS = frozenset(
    {"block_index", "source_role", "source_sha256", "translation"}
) | _INTERNAL_ROW_KEYS
_OPTIONAL_ROW_KEYS = frozenset(
    {
        "translation_xhtml",
        "explanation",
        "image_annotations",
        "image_companions",
        "market_contexts",
    }
)
_ROW_KEYS = _REQUIRED_ROW_KEYS | _OPTIONAL_ROW_KEYS | _INTERNAL_ROW_KEYS
_IMAGE_ANNOTATION_KEYS = frozenset({"source_path", "annotation"})
_IMAGE_COMPANION_KEYS = frozenset({"source_path", "companion"})
_IMAGE_COMPANION_WITH_ANNOTATION_KEYS = _IMAGE_COMPANION_KEYS | {"annotation"}


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def read_json(path: Path, *, missing_code: str, invalid_code: str) -> Any:
    if not path.is_file():
        raise BookStudioError(
            code=missing_code,
            message=f"Required JSON artifact is missing: {path.name}",
            next_action="Run the preceding Book Studio workflow command first.",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BookStudioError(
            code=invalid_code,
            message=f"Invalid JSON artifact: {path.name}",
            next_action="Repair or regenerate the JSON artifact.",
        ) from exc


def empty_cache(config: ProjectConfig) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_sha256": "",
        "files": {},
    }


def cache_path(config: ProjectConfig) -> Path:
    return config.paths.cache / CACHE_FILENAME


def load_cache(config: ProjectConfig) -> dict[str, Any]:
    validate_project_node_shapes(config.paths)
    path = cache_path(config)
    if not path.exists():
        return empty_cache(config)
    payload = read_json(
        path,
        missing_code="CACHE_MISSING",
        invalid_code="CACHE_JSON_INVALID",
    )
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
    ):
        raise BookStudioError(
            code="CACHE_SCHEMA_INVALID",
            message="Canonical cache must use schema_version 1.",
            next_action="Restore or regenerate cache/translations.json.",
        )
    if not isinstance(payload.get("files"), dict):
        raise BookStudioError(
            code="CACHE_SCHEMA_INVALID",
            message="Canonical cache files must be a JSON object.",
            next_action="Restore or regenerate cache/translations.json.",
        )
    return payload


def _image_schema_invalid(message: str) -> BookStudioError:
    return _fail(
        "IMAGE_MANIFEST_SCHEMA_INVALID",
        message,
        "Return image annotations and companions using the documented exact record schema.",
    )


def validate_optional_cache_fields(
    config: ProjectConfig, row: Mapping[str, Any]
) -> None:
    """Validate optional response/cache fields through one exact policy gate."""
    if "translation_xhtml" in row:
        xhtml = row["translation_xhtml"]
        if type(xhtml) is not str or not xhtml.strip():
            raise _fail(
                "XHTML_INVALID",
                "translation_xhtml must be nonempty text when present.",
                "Remove translation_xhtml or return valid inline XHTML.",
            )
        validate_inline_xhtml(xhtml)
    if "explanation" in row and (
        type(row["explanation"]) is not str or not row["explanation"].strip()
    ):
        raise _fail(
            "CACHE_ROW_INVALID",
            "Cache explanation must be nonempty text when present.",
            "Remove the explanation or return nonempty text.",
        )
    if "market_contexts" in row:
        contexts = row["market_contexts"]
        if type(contexts) is not list:
            raise _fail(
                "CACHE_ROW_INVALID",
                "market_contexts must be a JSON array.",
                "Return market contexts using the documented schema.",
            )
        for value in contexts:
            if type(value) is str and value.strip():
                continue
            if (
                type(value) is dict
                and set(value) == {"text"}
                and type(value.get("text")) is str
                and value["text"].strip()
            ):
                continue
            raise _fail(
                "CACHE_ROW_INVALID",
                "Every market context must be nonempty text or an exact text object.",
                "Return market contexts using the documented schema.",
            )

    from ..images.manifest import validate_image_record

    annotations = row.get("image_annotations", [])
    if type(annotations) is not list:
        raise _image_schema_invalid("image_annotations must be a JSON array.")
    for record in annotations:
        if type(record) is not dict or set(record) != _IMAGE_ANNOTATION_KEYS:
            raise _image_schema_invalid(
                "Each image annotation must contain only source_path and annotation."
            )
        validate_image_record(config, {**record, "policy": "annotation"})

    companions = row.get("image_companions", [])
    if type(companions) is not list:
        raise _image_schema_invalid("image_companions must be a JSON array.")
    for record in companions:
        if type(record) is not dict or set(record) not in {
            _IMAGE_COMPANION_KEYS,
            _IMAGE_COMPANION_WITH_ANNOTATION_KEYS,
        }:
            raise _image_schema_invalid(
                "Each image companion must contain only source_path, companion, and optional annotation."
            )
        annotation = record.get("annotation")
        if "annotation" in record and (
            type(annotation) is not str or not annotation.strip()
        ):
            raise _image_schema_invalid(
                "An optional companion annotation must be nonempty text."
            )
        validate_image_record(
            config, {**record, "policy": "original_plus_companion"}
        )


def validate_cache_payload(
    payload: Any,
    *,
    config: ProjectConfig,
    targets: Mapping[tuple[str, int], Mapping[str, Any]],
    source_sha256: str,
    allowed_targets: Collection[tuple[str, int]] | None = None,
    allow_stale_context: bool = False,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Validate one cache against exact prepared targets without changing it."""
    if type(payload) is not dict or set(payload) != _CACHE_KEYS:
        raise _fail(
            "CACHE_SCHEMA_INVALID",
            "Canonical cache must contain only the schema, source hash, and files map.",
            "Restore or regenerate cache/translations.json with Book Studio apply.",
        )
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or type(payload.get("source_sha256")) is not str
    ):
        raise _fail(
            "CACHE_SCHEMA_INVALID",
            "Canonical cache must use schema_version 1 and a text source hash.",
            "Restore or regenerate cache/translations.json with Book Studio apply.",
        )
    files = payload.get("files")
    if type(files) is not dict:
        raise _fail(
            "CACHE_SCHEMA_INVALID",
            "Canonical cache files must be a JSON object of row arrays.",
            "Restore or regenerate cache/translations.json with Book Studio apply.",
        )

    allowed = set(allowed_targets) if allowed_targets is not None else None
    known_paths = {path for path, _ in targets}
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    row_count = 0
    current_context_sha256: str | None = None
    for source_path, rows in files.items():
        if type(source_path) is not str or not source_path or type(rows) is not list:
            raise _fail(
                "CACHE_SCHEMA_INVALID",
                "Each cache source path must map to a JSON row array.",
                "Restore or regenerate cache/translations.json with Book Studio apply.",
            )
        if source_path not in known_paths:
            raise _fail(
                "CACHE_TARGET_UNKNOWN",
                f"Cache names a source document outside global translation coverage: {source_path}",
                "Remove the unknown cache document and request a fresh packet.",
            )
        for row in rows:
            row_count += 1
            if (
                type(row) is not dict
                or not _REQUIRED_ROW_KEYS.issubset(row)
                or not set(row).issubset(_ROW_KEYS)
                or type(row.get("block_index")) is not int
                or type(row.get("source_role")) is not str
                or not row["source_role"].strip()
                or type(row.get("source_sha256")) is not str
                or type(row.get("translation")) is not str
                or not row["translation"].strip()
            ):
                raise _fail(
                    "CACHE_ROW_INVALID",
                    f"Cache row schema is invalid in {source_path}.",
                    "Restore the row from a validated Book Studio apply response.",
                )
            internal_values = {key: row.get(key) for key in _INTERNAL_ROW_KEYS}
            valid_internal = all(
                type(value) is str
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value.lower())
                for value in internal_values.values()
            )
            if not valid_internal:
                raise _fail(
                    "CACHE_ROW_INVALID",
                    f"Cache context identity is invalid in {source_path}.",
                    "Restore the row from a validated Book Studio apply response.",
                )
            if not allow_stale_context:
                if current_context_sha256 is None:
                    current_context_sha256 = current_translation_context_sha256(config)
                if row["context_sha256"] != current_context_sha256:
                    raise _fail(
                        "CACHE_CONTEXT_STALE",
                        f"Cache row was translated under stale context: {source_path}#{row['block_index']}.",
                        "Request a fresh packet and use pilot revise, or start a new expert project.",
                    )
            validate_optional_cache_fields(config, row)
            key = (source_path, row["block_index"])
            if key in indexed:
                raise _fail(
                    "CACHE_DUPLICATE",
                    f"Cache repeats canonical target {source_path}#{row['block_index']}.",
                    "Keep exactly one accepted row for each canonical target.",
                )
            target = targets.get(key)
            if target is None:
                raise _fail(
                    "CACHE_TARGET_UNKNOWN",
                    f"Cache names a block outside global translation coverage: {source_path}#{row['block_index']}.",
                    "Remove the unknown row and request a fresh packet.",
                )
            if row["source_sha256"] != target.get("text_sha256"):
                raise _fail(
                    "CACHE_TARGET_STALE",
                    f"Cache source hash is stale for {source_path}#{row['block_index']}.",
                    "Remove the stale row and request a fresh packet.",
                )
            if row["source_role"] != target.get("role"):
                raise _fail(
                    "CACHE_ROW_INVALID",
                    f"Cache source role is stale for {source_path}#{row['block_index']}.",
                    "Remove the stale row and request a fresh packet.",
                )
            if allowed is not None and key not in allowed:
                raise _fail(
                    "CACHE_SCOPE_INVALID",
                    f"Cache row is outside the currently authorized pilot scope: {source_path}#{row['block_index']}.",
                    "Remove out-of-scope rows before continuing the pilot.",
                )
            indexed[key] = dict(row)

    cache_source = payload["source_sha256"]
    if cache_source != source_sha256 and not (cache_source == "" and row_count == 0):
        raise _fail(
            "CACHE_SOURCE_STALE",
            "Canonical cache does not match the prepared source EPUB.",
            "Restore or regenerate cache/translations.json for the current source.",
        )
    return indexed


def validated_cache_index(
    config: ProjectConfig,
    *,
    targets: Mapping[tuple[str, int], Mapping[str, Any]],
    source_sha256: str,
    allowed_targets: Collection[tuple[str, int]] | None = None,
    allow_stale_context: bool = False,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Load the cache and return only rows proven against exact global targets."""
    return validate_cache_payload(
        load_cache(config),
        config=config,
        targets=targets,
        source_sha256=source_sha256,
        allowed_targets=allowed_targets,
        allow_stale_context=allow_stale_context,
    )


def save_cache(config: ProjectConfig, payload: dict[str, Any]) -> None:
    validate_project_node_shapes(config.paths)
    atomic_write_json(cache_path(config), payload)
