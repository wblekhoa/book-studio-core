"""Bounded AI packet emission and fail-closed response application."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Collection

from ..config import ProjectConfig
from ..errors import BookStudioError
from .cache import (
    load_cache,
    read_json,
    save_cache,
    validate_cache_payload,
    validate_optional_cache_fields,
    validated_cache_index,
)
from .coverage import target_index
from .context import (
    current_translation_context_sha256,
    current_translation_context_snapshot,
)


OPTIONAL_RESPONSE_KEYS = (
    "translation_xhtml",
    "explanation",
    "image_annotations",
    "image_companions",
    "market_contexts",
)
RESPONSE_REQUIRED_KEYS = (
    "schema_version",
    "packet_id",
    "source_document",
    "translations",
)
TRANSLATION_REQUIRED_KEYS = (
    "block_index",
    "source_sha256",
    "translation",
)
_RESPONSE_KEYS = frozenset(RESPONSE_REQUIRED_KEYS)
_TRANSLATION_REQUIRED_KEYS = frozenset(TRANSLATION_REQUIRED_KEYS)
_TRANSLATION_KEYS = _TRANSLATION_REQUIRED_KEYS | frozenset(OPTIONAL_RESPONSE_KEYS)


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _glossary(config: ProjectConfig, haystack: str) -> list[dict[str, str]]:
    if not config.paths.glossary.is_file():
        return []
    rows: list[dict[str, str]] = []
    for line in config.paths.glossary.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if len(columns) < 2 or columns[0].lower() == "source term" or set(columns[0]) <= {"-", ":"}:
            continue
        if columns[0].casefold() in haystack.casefold():
            rows.append(
                {
                    "source_term": columns[0],
                    "preferred_rendering": columns[1],
                    "usage_note": columns[2] if len(columns) > 2 else "",
                }
            )
    return rows


def _reference_notes(config: ProjectConfig, source_path: str) -> list[dict[str, str]]:
    path = config.paths.root / "reference-notes.json"
    if not path.is_file():
        return []
    payload = read_json(
        path,
        missing_code="REFERENCE_NOTES_MISSING",
        invalid_code="REFERENCE_NOTES_JSON_INVALID",
    )
    notes: list[dict[str, str]] = []
    for row in payload.get("notes", []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict) or row.get("source_path") != source_path:
            continue
        notes.append(
            {
                "source_path": source_path,
                "provenance": str(row.get("provenance", ""))[:500],
                "text": str(row.get("text", ""))[:2_000],
            }
        )
        if len(notes) == 8:
            break
    return notes


def _packet_id(
    config: ProjectConfig,
    source_document: str,
    blocks: list[dict[str, Any]],
    *,
    source_name: str,
    source_sha256: str,
    context_blocks: list[dict[str, Any]],
    context_sha256: str,
    scope_identity: str | None = None,
) -> str:
    identity = {
        "project": config.slug,
        "prompt_version": config.prompt_version,
        "source": {"name": source_name, "sha256": source_sha256},
        "context_sha256": context_sha256,
        "source_document": source_document,
        "blocks": [
            [block["block_index"], block["text_sha256"]] for block in blocks
        ],
        "neighboring_context": [
            [block["block_index"], block["role"], block["source_sha256"]]
            for block in context_blocks
        ],
    }
    if scope_identity is not None:
        identity["scope_identity"] = scope_identity
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def next_packet(
    config: ProjectConfig,
    *,
    allowed_targets: Collection[tuple[str, int]] | None = None,
    scope_identity: str | None = None,
) -> dict[str, Any] | None:
    targets, _, block_map = target_index(config)
    source_sha256 = block_map.get("source", {}).get("sha256")
    context_identity, production_brief = current_translation_context_snapshot(
        config
    )
    context_sha256 = str(context_identity["sha256"])
    cache_index = validated_cache_index(
        config,
        targets=targets,
        source_sha256=source_sha256,
        allowed_targets=allowed_targets,
        allow_stale_context=True,
    )
    translated = {
        key
        for key, row in cache_index.items()
        if row.get("context_sha256") == context_sha256
    }
    selected_file: dict[str, Any] | None = None
    selected: list[dict[str, Any]] = []
    for file in block_map.get("files", []):
        source_path = file.get("source_path")
        remaining = [
            block
            for block in file.get("blocks", [])
            if (source_path, block.get("block_index")) in targets
            and (
                allowed_targets is None
                or (source_path, block.get("block_index")) in allowed_targets
            )
            and (source_path, block.get("block_index")) not in translated
        ]
        if remaining:
            selected_file = file
            selected = remaining[: config.max_blocks]
            break
    if selected_file is None:
        return None

    source_document = selected_file["source_path"]
    selected_indexes = {block["block_index"] for block in selected}
    all_blocks = selected_file.get("blocks", [])
    first_position = next(
        index for index, block in enumerate(all_blocks) if block["block_index"] == selected[0]["block_index"]
    )
    last_position = max(
        index for index, block in enumerate(all_blocks) if block["block_index"] in selected_indexes
    )
    context_blocks = []
    for position in (first_position - 1, last_position + 1):
        if 0 <= position < len(all_blocks):
            block = all_blocks[position]
            if block["block_index"] not in selected_indexes:
                context_blocks.append(
                    {
                        "source_path": source_document,
                        "block_index": block["block_index"],
                        "role": block["role"],
                        "text": block["text"],
                        "source_sha256": block["text_sha256"],
                        "translate": False,
                    }
                )

    packet_blocks = [
        {
            "source_path": source_document,
            "block_index": block["block_index"],
            "tag": block["tag"],
            "role": block["role"],
            "text": block["text"],
            "source_sha256": block["text_sha256"],
            "translate": True,
        }
        for block in selected
    ]
    haystack = " ".join(block["text"] for block in selected + [
        all_blocks[position]
        for position in (first_position - 1, last_position + 1)
        if 0 <= position < len(all_blocks) and all_blocks[position]["block_index"] not in selected_indexes
    ])
    packet_id = _packet_id(
        config,
        source_document,
        selected,
        source_name=block_map["source"]["name"],
        source_sha256=source_sha256,
        context_blocks=context_blocks,
        context_sha256=context_sha256,
        scope_identity=scope_identity,
    )
    return {
        "status": "pass",
        "schema_version": 1,
        "prompt_version": config.prompt_version,
        "packet_id": packet_id,
        "project": {
            "slug": config.slug,
            "source_name": block_map["source"]["name"],
            "source_sha256": block_map["source"]["sha256"],
            "source_language": config.source_language,
            "target_language": config.target_language,
            "output_mode": config.output_mode,
        },
        "book_profile": dict(config.profile),
        **(
            {"production_brief": production_brief}
            if production_brief is not None
            else {}
        ),
        "source_document": source_document,
        "glossary": _glossary(config, haystack),
        "reference_notes": _reference_notes(config, source_document),
        "context": context_blocks,
        "blocks": packet_blocks,
        "response_schema": {
            "schema_version": 1,
            "required": list(RESPONSE_REQUIRED_KEYS),
            "allowed": list(RESPONSE_REQUIRED_KEYS),
            "translation_required": list(TRANSLATION_REQUIRED_KEYS),
            "translation_optional": list(OPTIONAL_RESPONSE_KEYS),
        },
    }


def _require_current_packet(
    config: ProjectConfig,
    *,
    response: dict[str, Any],
    source_document: str,
    entries: list[dict[str, Any]],
    allowed_targets: Collection[tuple[str, int]] | None,
    scope_identity: str | None,
) -> None:
    current_packet = next_packet(
        config,
        allowed_targets=allowed_targets,
        scope_identity=scope_identity,
    )
    current_indexes = {
        block["block_index"] for block in (current_packet or {}).get("blocks", [])
    }
    if (
        current_packet is None
        or response.get("packet_id") != current_packet["packet_id"]
        or source_document != current_packet["source_document"]
        or not {entry["block_index"] for entry in entries}.issubset(current_indexes)
    ):
        raise _fail(
            "RESPONSE_PACKET_STALE",
            "Response no longer matches the current bounded packet.",
            "Run 'bookstudio next' again and apply a response to that packet.",
        )


def _validated_response_shape(
    response: Any,
) -> tuple[str, list[dict[str, Any]]]:
    if (
        type(response) is not dict
        or set(response) != _RESPONSE_KEYS
        or type(response.get("schema_version")) is not int
        or response.get("schema_version") != 1
        or type(response.get("packet_id")) is not str
        or not response["packet_id"].strip()
        or type(response.get("source_document")) is not str
        or not response["source_document"].strip()
        or type(response.get("translations")) is not list
        or not response["translations"]
    ):
        raise _fail(
            "RESPONSE_SCHEMA_MISMATCH",
            "AI response must use the exact schema-versioned top-level contract.",
            "Return only the exact keys and types requested in the packet.",
        )

    translations = response["translations"]
    for row in translations:
        if (
            type(row) is not dict
            or not _TRANSLATION_REQUIRED_KEYS.issubset(row)
            or not set(row).issubset(_TRANSLATION_KEYS)
            or type(row.get("block_index")) is not int
            or type(row.get("source_sha256")) is not str
            or type(row.get("translation")) is not str
        ):
            raise _fail(
                "RESPONSE_SCHEMA_MISMATCH",
                "Every translation must use the exact documented keys and types.",
                "Return only the required translation fields and documented optional fields.",
            )
        if not row["translation"].strip():
            raise _fail(
                "RESPONSE_TRANSLATION_EMPTY",
                f"Translation is empty for block {row['block_index']}.",
                "Provide a nonempty translation for every returned block.",
            )
    return response["source_document"], translations


def apply_response(
    config: ProjectConfig,
    response_path: Path,
    *,
    allowed_targets: Collection[tuple[str, int]] | None = None,
    scope_identity: str | None = None,
    _replace_existing: bool = False,
) -> dict[str, Any]:
    response = read_json(
        response_path,
        missing_code="RESPONSE_MISSING",
        invalid_code="RESPONSE_JSON_INVALID",
    )
    source_document, translations = _validated_response_shape(response)
    context_sha256 = current_translation_context_sha256(config)

    targets, _, block_map = target_index(config)
    document_targets = {
        index: block
        for (path, index), block in targets.items()
        if path == source_document
        and (
            allowed_targets is None
            or (path, index) in allowed_targets
        )
    }
    seen: set[int] = set()
    validated: list[dict[str, Any]] = []
    for row in translations:
        block_index = row["block_index"]
        if block_index in seen:
            raise _fail(
                "RESPONSE_BLOCK_DUPLICATE",
                f"Response repeats block index {block_index}.",
                "Return each requested block exactly once.",
            )
        seen.add(block_index)
        target = document_targets.get(block_index)
        if target is None:
            raise _fail(
                "RESPONSE_BLOCK_UNKNOWN",
                f"Response names an unknown or excluded block: {source_document}#{block_index}",
                "Apply only blocks present in the emitted packet.",
            )
        translation = row["translation"]
        if row.get("source_sha256") != target.get("text_sha256"):
            raise _fail(
                "RESPONSE_SOURCE_STALE",
                f"Source hash is stale for block {block_index}.",
                "Request a fresh packet and translate that source version.",
            )
        entry = {
            "block_index": block_index,
            "source_role": target["role"],
            "source_sha256": target["text_sha256"],
            "translation": translation.strip(),
            "packet_id": response["packet_id"],
            "context_sha256": context_sha256,
        }
        for key in OPTIONAL_RESPONSE_KEYS:
            if key in row:
                entry[key] = row[key]
        validate_optional_cache_fields(config, entry)
        validated.append(entry)

    if scope_identity is not None and not _replace_existing:
        _require_current_packet(
            config,
            response=response,
            source_document=source_document,
            entries=validated,
            allowed_targets=allowed_targets,
            scope_identity=scope_identity,
        )

    cache = load_cache(config)
    source_sha256 = block_map.get("source", {}).get("sha256")
    cache_index = validate_cache_payload(
        cache,
        config=config,
        targets=targets,
        source_sha256=source_sha256,
        allowed_targets=allowed_targets,
        allow_stale_context=True,
    )
    existing = {
        index: row
        for (path, index), row in cache_index.items()
        if path == source_document
    }
    new_entries: list[dict[str, Any]] = []
    replacement_entries: dict[int, dict[str, Any]] = {}
    if _replace_existing:
        current_packet = next_packet(
            config,
            allowed_targets=allowed_targets,
            scope_identity=scope_identity,
        )
        current_indexes = {
            block["block_index"] for block in (current_packet or {}).get("blocks", [])
        }
        fresh_packet_matches = (
            current_packet is not None
            and response.get("packet_id") == current_packet["packet_id"]
            and source_document == current_packet["source_document"]
            and {entry["block_index"] for entry in validated}.issubset(current_indexes)
        )
        stored_packet_matches = all(
            (current := existing.get(entry["block_index"])) is not None
            and current.get("context_sha256") == context_sha256
            and current.get("packet_id") == response.get("packet_id")
            for entry in validated
        )
        if not fresh_packet_matches and not stored_packet_matches:
            raise _fail(
                "RESPONSE_PACKET_STALE",
                "Pilot revision no longer matches current response-shaping context.",
                "Run 'bookstudio next' again and revise only the fresh packet rows.",
            )
    for entry in validated:
        current = existing.get(entry["block_index"])
        if _replace_existing:
            if current is None:
                raise _fail(
                    "CACHE_REPLACEMENT_MISSING",
                    f"Pilot revision names an untranslated block {entry['block_index']}.",
                    "Translate the block through the normal next/apply flow before revising it.",
                )
            if current != entry:
                replacement_entries[entry["block_index"]] = entry
            continue
        if current is not None and current != entry:
            raise _fail(
                "CACHE_COLLISION",
                f"Accepted cache entry already differs for block {entry['block_index']}.",
                "Review the existing decision instead of overwriting it implicitly.",
            )
        if current is None:
            new_entries.append(entry)

    if new_entries and scope_identity is None:
        _require_current_packet(
            config,
            response=response,
            source_document=source_document,
            entries=new_entries,
            allowed_targets=allowed_targets,
            scope_identity=scope_identity,
        )

    if new_entries or replacement_entries:
        files = {key: list(value) for key, value in cache.get("files", {}).items()}
        merged = [
            replacement_entries.get(row["block_index"], row)
            for row in files.get(source_document, [])
        ] + new_entries
        merged.sort(key=lambda row: row["block_index"])
        files[source_document] = merged
        updated = {
            "schema_version": 1,
            "source_sha256": block_map["source"]["sha256"],
            "files": files,
        }
        validate_cache_payload(
            updated,
            config=config,
            targets=targets,
            source_sha256=source_sha256,
            allowed_targets=allowed_targets,
            allow_stale_context=_replace_existing,
        )
        save_cache(config, updated)

    if _replace_existing:
        return {
            "status": "pass",
            "message": "Validated pilot translations were revised atomically.",
            "revised": len(replacement_entries),
            "source_document": source_document,
        }
    return {
        "status": "pass",
        "message": "Validated translations were applied atomically.",
        "applied": len(new_entries),
        "source_document": source_document,
    }


def revise_pilot_response(
    config: ProjectConfig,
    response_path: Path,
) -> dict[str, Any]:
    """Replace existing pilot rows before acceptance, never full-scope rows."""
    from ..pilot import pilot_receipt, pilot_scope_identity

    receipt = pilot_receipt(config)
    if receipt.get("status") not in {"pilot_active", "pilot_review_required"}:
        raise _fail(
            "PILOT_REVISION_LOCKED",
            "Pilot translations can be revised only after approval and before acceptance.",
            "Approve the pilot first, or keep accepted full-scope decisions immutable.",
        )
    source_document = receipt["source_document"]
    allowed_targets = frozenset(
        (source_document, target["block_index"])
        for target in receipt["targets"]
    )
    return apply_response(
        config,
        response_path,
        allowed_targets=allowed_targets,
        scope_identity=pilot_scope_identity(receipt),
        _replace_existing=True,
    )
