"""Deterministic pilot selection and fail-closed lifecycle state."""

from __future__ import annotations

import json
import math
import posixpath
import re
from typing import Any, Mapping

from .config import (
    ProjectConfig,
    atomic_write_json,
    resolved_profile,
    validate_project_node_shapes,
)
from .epub.extract import extract_block_map
from .epub.inspect import inspect_epub
from .errors import BookStudioError
from .intake import (
    intake_facts,
    missing_questions,
    profile_from_answers,
    validate_answers,
)
from .translation.cache import read_json, validated_cache_index
from .translation.context import (
    current_translation_context_identity,
    current_translation_context_sha256,
)
from .translation.coverage import (
    target_index as coverage_target_index,
    validate_prepared_block_map,
)


_EXCLUSION_WORDS = frozenset(
    {
        "contents",
        "copyright",
        "cover",
        "dedication",
        "frontmatter",
        "index",
        "legal",
        "license",
        "nav",
        "navigation",
        "title",
        "toc",
    }
)
_EXCLUSION_COMPOUNDS = frozenset(
    {
        "coverpage",
        "copyrightpage",
        "frontmatter",
        "legalnotice",
        "legalpage",
        "navigationpage",
        "tableofcontents",
        "titlepage",
    }
)
_EXCLUSION_STEMS = ("acknowledg",)
_SELECTION_FACT_KEYS = frozenset(
    {
        "selected_title",
        "selected_spine_index",
        "selected_block_count",
        "selected_image_count",
        "nonempty_candidate_count",
        "non_excluded_candidate_count",
        "non_trivial_candidate_count",
        "ranked_candidate_count",
        "median_block_count",
        "all_nonempty_excluded",
    }
)
_SELECTION_INTEGER_FACT_KEYS = (
    "selected_spine_index",
    "selected_block_count",
    "selected_image_count",
    "nonempty_candidate_count",
    "non_excluded_candidate_count",
    "non_trivial_candidate_count",
    "ranked_candidate_count",
)
_STATUSES = frozenset(
    {
        "pilot_proposed",
        "pilot_active",
        "full_active",
        "pilot_approved",
        "pilot_accepted",
    }
)
_STATUS_NORMALIZATION = {
    "pilot_approved": "pilot_active",
    "pilot_accepted": "full_active",
}
_PILOT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "source_sha256",
        "source_document",
        "targets",
        "eligible_blocks",
        "translated_blocks",
        "reason_codes",
        "selection_facts",
    }
)
_POLICY_IDENTITY_KEYS = frozenset(
    {
        "schema_version",
        "policy_sha256",
        "glossary_sha256",
        "reference_notes_sha256",
        "image_manifest_sha256",
        "sha256",
    }
)
_ARTIFACT_NOT_SUPPLIED = object()


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def current_policy_identity(config: ProjectConfig) -> dict[str, Any]:
    """Return a content-free canonical identity for the current accepted policy."""
    return current_translation_context_identity(config)


def _validate_policy_identity(config: ProjectConfig, value: Any) -> None:
    valid_shape = (
        type(value) is dict
        and set(value) == _POLICY_IDENTITY_KEYS
        and type(value.get("schema_version")) is int
        and value.get("schema_version") == 1
        and _sha256(value.get("policy_sha256"))
        and (
            value.get("glossary_sha256") == "absent"
            or _sha256(value.get("glossary_sha256"))
        )
        and (
            value.get("reference_notes_sha256") == "absent"
            or _sha256(value.get("reference_notes_sha256"))
        )
        and (
            value.get("image_manifest_sha256") == "absent"
            or _sha256(value.get("image_manifest_sha256"))
        )
        and _sha256(value.get("sha256"))
    )
    if not valid_shape or value != current_policy_identity(config):
        raise _fail(
            "PILOT_POLICY_STALE",
            "Accepted pilot policy identity is malformed, tampered, or no longer current.",
            "Restore the accepted policy inputs or run a new guided pilot before full-book work.",
        )


def _canonical_blocks(file: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks = file.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [
        block
        for block in blocks
        if isinstance(block, dict)
        and isinstance(block.get("block_index"), int)
        and not isinstance(block.get("block_index"), bool)
        and block.get("canonical") is True
        and block.get("watermark") is not True
        and _sha256(block.get("text_sha256"))
    ]


def _classification_parts(
    value: str, *, logical_path: bool = False
) -> tuple[set[str], set[str]]:
    normalized = posixpath.normpath(value.replace("\\", "/")) if logical_path else value
    segments = normalized.split("/") if logical_path else [normalized]
    words: set[str] = set()
    compounds: set[str] = set()
    for segment in segments:
        stem = posixpath.splitext(segment)[0] if logical_path else segment
        segment_words = re.findall(r"[a-z0-9]+", stem.casefold())
        words.update(segment_words)
        if segment_words:
            compounds.add("".join(segment_words))
    return words, compounds


def _is_excluded(source_path: str, title: str) -> bool:
    path_words, path_compounds = _classification_parts(source_path, logical_path=True)
    title_words, title_compounds = _classification_parts(title)
    words = path_words | title_words
    compounds = path_compounds | title_compounds
    return (
        bool(words & _EXCLUSION_WORDS)
        or bool(compounds & _EXCLUSION_COMPOUNDS)
        or any(
            word.startswith(stem) or compound.startswith(stem)
            for stem in _EXCLUSION_STEMS
            for word in words
            for compound in compounds
        )
    )


def _inspection_documents(inspection: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    files = inspection.get("text", {}).get("files", [])
    if not isinstance(files, list):
        return {}
    facts: dict[str, dict[str, Any]] = {}
    for row in files:
        if not isinstance(row, Mapping) or not isinstance(row.get("source_path"), str):
            continue
        image_count = row.get("images")
        if not isinstance(image_count, int) or isinstance(image_count, bool) or image_count < 0:
            image_count = 0
        title = row.get("title") if isinstance(row.get("title"), str) else ""
        facts[row["source_path"]] = {"title": title, "image_count": image_count}
    return facts


def _pilot_candidates(
    inspection: Mapping[str, Any], block_map: Mapping[str, Any]
) -> list[dict[str, Any]]:
    inspected_documents = _inspection_documents(inspection)
    candidates: list[dict[str, Any]] = []
    files = block_map.get("files")
    if not isinstance(files, list):
        return candidates
    for file in files:
        if not isinstance(file, Mapping):
            continue
        source_path = file.get("source_path")
        spine_index = file.get("spine_index")
        blocks = _canonical_blocks(file)
        if (
            not isinstance(source_path, str)
            or not isinstance(spine_index, int)
            or isinstance(spine_index, bool)
            or not blocks
        ):
            continue
        document_facts = inspected_documents.get(source_path, {})
        title = document_facts.get("title", "")
        image_count = document_facts.get("image_count", 0)
        candidates.append(
            {
                "source_path": source_path,
                "spine_index": spine_index,
                "blocks": sorted(blocks, key=lambda block: block["block_index"]),
                "title": title,
                "image_count": image_count,
                "excluded": _is_excluded(source_path, title),
            }
        )
    return candidates


def _selection_context(
    candidates: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int | float | None,
    bool,
]:
    eligible = [candidate for candidate in candidates if not candidate["excluded"]]
    non_trivial = [candidate for candidate in eligible if len(candidate["blocks"]) >= 2]
    if not eligible:
        selected = min(candidates, key=lambda candidate: candidate["spine_index"])
        return eligible, non_trivial, [selected], None, True
    ranked = non_trivial if non_trivial else eligible
    counts = sorted(len(candidate["blocks"]) for candidate in ranked)
    middle = len(counts) // 2
    median_sum = counts[middle] if len(counts) % 2 else counts[middle - 1] + counts[middle]
    median_scale = 1 if len(counts) % 2 else 2
    median: int | float = (
        median_sum // median_scale
        if median_sum % median_scale == 0
        else median_sum / median_scale
    )
    return eligible, non_trivial, ranked, median, False


def _selection_facts(
    selected: Mapping[str, Any],
    *,
    candidates: list[dict[str, Any]],
    context: tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        int | float | None,
        bool,
    ],
) -> dict[str, Any]:
    eligible, non_trivial, ranked, median_block_count, all_nonempty_excluded = context
    return {
        "selected_title": selected["title"],
        "selected_spine_index": selected["spine_index"],
        "selected_block_count": len(selected["blocks"]),
        "selected_image_count": selected["image_count"],
        "nonempty_candidate_count": len(candidates),
        "non_excluded_candidate_count": len(eligible),
        "non_trivial_candidate_count": len(non_trivial),
        "ranked_candidate_count": len(ranked),
        "median_block_count": median_block_count,
        "all_nonempty_excluded": all_nonempty_excluded,
    }


def _selection_facts_match(value: Any, expected: Mapping[str, Any]) -> bool:
    if not isinstance(value, dict) or set(value) != _SELECTION_FACT_KEYS:
        return False
    if (
        not isinstance(value.get("selected_title"), str)
        or any(type(value.get(key)) is not int for key in _SELECTION_INTEGER_FACT_KEYS)
        or type(value.get("all_nonempty_excluded")) is not bool
    ):
        return False
    median = value.get("median_block_count")
    if median is not None and (
        not isinstance(median, (int, float))
        or isinstance(median, bool)
        or not math.isfinite(median)
    ):
        return False
    return value == expected


def _expected_selection_facts(
    inspection: Mapping[str, Any],
    block_map: Mapping[str, Any],
    source_document: str,
) -> dict[str, Any] | None:
    candidates = _pilot_candidates(inspection, block_map)
    if not candidates:
        return None
    selected = next(
        (
            candidate
            for candidate in candidates
            if candidate["source_path"] == source_document
        ),
        None,
    )
    if selected is None:
        return None
    context = _selection_context(candidates)
    _, _, ranked, median, all_nonempty_excluded = context
    if all_nonempty_excluded:
        if selected != ranked[0]:
            return None
    else:
        closest_distance = min(
            abs(len(candidate["blocks"]) - median) for candidate in ranked
        )
        if selected not in ranked or abs(len(selected["blocks"]) - median) != closest_distance:
            return None
    return _selection_facts(selected, candidates=candidates, context=context)


def select_pilot(
    inspection: Mapping[str, Any], block_map: Mapping[str, Any], answers: Mapping[str, Any]
) -> dict[str, Any]:
    """Choose one reproducible document and all of its canonical blocks."""
    source = block_map.get("source") if isinstance(block_map, Mapping) else None
    source_hash = source.get("sha256") if isinstance(source, Mapping) else None
    inspection_source = inspection.get("source") if isinstance(inspection, Mapping) else None
    if (
        type(block_map.get("schema_version")) is not int
        or block_map.get("schema_version") != 1
        or not _sha256(source_hash)
        or not isinstance(inspection_source, Mapping)
        or inspection_source.get("sha256") != source_hash
    ):
        raise _fail(
            "PILOT_INPUT_INVALID",
            "Pilot selection requires matching schema-versioned inspection and block-map source hashes.",
            "Run inspection and prepare again before selecting a pilot.",
        )
    files = block_map.get("files")
    if not isinstance(files, list):
        raise _fail(
            "PILOT_INPUT_INVALID",
            "Pilot selection requires a block-map files list.",
            "Run prepare again before selecting a pilot.",
        )

    candidates = _pilot_candidates(inspection, block_map)
    if not candidates:
        raise _fail(
            "PILOT_SELECTION_EMPTY",
            "No canonical translation blocks are available for a pilot.",
            "Prepare a source with at least one canonical text block.",
        )

    context = _selection_context(candidates)
    eligible, non_trivial, ranked, median_block_count, all_nonempty_excluded = context
    if all_nonempty_excluded:
        selected = ranked[0]
        reason_codes = ["front_matter_fallback", "first_nonempty_spine"]
        targets = [
            {
                "block_index": block["block_index"],
                "source_sha256": block["text_sha256"],
            }
            for block in selected["blocks"]
        ]
        return {
            "schema_version": 1,
            "status": "pilot_proposed",
            "source_sha256": source_hash,
            "source_document": selected["source_path"],
            "targets": targets,
            "eligible_blocks": len(targets),
            "translated_blocks": 0,
            "reason_codes": reason_codes,
            "selection_facts": _selection_facts(
                selected,
                candidates=candidates,
                context=context,
            ),
        }

    reason_codes = ["representative_block_count"]
    if len(eligible) != len(candidates):
        reason_codes.insert(0, "front_matter_excluded")
    if non_trivial:
        reason_codes.append("non_trivial_document_preferred")

    closest_distance = min(
        abs(len(candidate["blocks"]) - median_block_count)
        for candidate in ranked
    )
    finalists = [
        candidate
        for candidate in ranked
        if abs(len(candidate["blocks"]) - median_block_count) == closest_distance
    ]

    image_enabled = isinstance(answers, Mapping) and any(
        answers.get(policy) in {"selective", "all"}
        for policy in ("image_text_policy", "image_annotation_policy")
    )
    image_finalists = [candidate for candidate in finalists if candidate["image_count"] > 0]
    if image_enabled and image_finalists:
        finalists = image_finalists
        reason_codes.append("image_document_preferred")
    if len(finalists) > 1:
        reason_codes.append("spine_tie_break")
    selected = min(finalists, key=lambda candidate: candidate["spine_index"])
    targets = [
        {
            "block_index": block["block_index"],
            "source_sha256": block["text_sha256"],
        }
        for block in selected["blocks"]
    ]
    return {
        "schema_version": 1,
        "status": "pilot_proposed",
        "source_sha256": source_hash,
        "source_document": selected["source_path"],
        "targets": targets,
        "eligible_blocks": len(targets),
        "translated_blocks": 0,
        "reason_codes": reason_codes,
        "selection_facts": _selection_facts(
            selected,
            candidates=candidates,
            context=context,
        ),
    }


def _prepared_block_map(config: ProjectConfig) -> dict[str, Any]:
    payload = read_json(
        config.paths.source_blocks / "full-block-map.json",
        missing_code="PILOT_BLOCK_MAP_MISSING",
        invalid_code="PILOT_BLOCK_MAP_INVALID",
    )
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
    ):
        raise _fail(
            "PILOT_BLOCK_MAP_INVALID",
            "Pilot lifecycle requires a schema-versioned prepared block map.",
            "Run prepare again before continuing the pilot.",
        )
    return payload


def _current_target_index(
    config: ProjectConfig, block_map: Mapping[str, Any]
) -> tuple[str, dict[str, dict[int, str]], dict[str, Any]]:
    prepared_source = block_map.get("source")
    prepared_hash = prepared_source.get("sha256") if isinstance(prepared_source, Mapping) else None
    current_map = extract_block_map(config.source)
    current_source = current_map.get("source")
    current_hash = current_source.get("sha256") if isinstance(current_source, Mapping) else None
    if not _sha256(prepared_hash) or prepared_hash != current_hash:
        raise _fail(
            "PILOT_SOURCE_STALE",
            "Prepared pilot state does not match the current source EPUB.",
            "Run prepare again and create a new pilot proposal for the current source.",
        )
    validate_prepared_block_map(config, block_map, current_map=current_map)
    index: dict[str, dict[int, str]] = {}
    current_files = {
        file.get("source_path"): file
        for file in current_map.get("files", [])
        if isinstance(file, Mapping) and isinstance(file.get("source_path"), str)
    }
    for file in block_map.get("files", []):
        if not isinstance(file, Mapping) or not isinstance(file.get("source_path"), str):
            continue
        source_path = file["source_path"]
        current_file = current_files.get(source_path)
        if not isinstance(current_file, Mapping):
            continue
        current_blocks = {
            block["block_index"]: block.get("text_sha256")
            for block in _canonical_blocks(current_file)
        }
        prepared_blocks = _canonical_blocks(file)
        if any(
            current_blocks.get(block["block_index"]) != block.get("text_sha256")
            for block in prepared_blocks
        ):
            raise _fail(
                "PILOT_BLOCK_MAP_STALE",
                "Prepared canonical blocks do not match the current source EPUB.",
                "Run prepare again and create a new pilot proposal.",
            )
        index[source_path] = {
            block["block_index"]: block["text_sha256"] for block in prepared_blocks
        }
    return prepared_hash, index, current_map


def _locked_pilot_answers(
    config: ProjectConfig,
    fresh_inspection: Mapping[str, Any],
    *,
    intake_payload: Any = _ARTIFACT_NOT_SUPPLIED,
) -> dict[str, str]:
    try:
        payload = (
            read_json(
                config.paths.intake,
                missing_code="PILOT_INTAKE_INVALID",
                invalid_code="PILOT_INTAKE_INVALID",
            )
            if intake_payload is _ARTIFACT_NOT_SUPPLIED
            else intake_payload
        )
        answers = payload.get("answers") if isinstance(payload, Mapping) else None
        normalized_answers = validate_answers(fresh_inspection, answers)
        questions = missing_questions(fresh_inspection, normalized_answers)
        assessment = {
            "schema_version": 1,
            "source": fresh_inspection["source"],
            "book_facts": intake_facts(fresh_inspection),
            "answers": normalized_answers,
            "questions": questions,
        }
    except (BookStudioError, TypeError) as exc:
        raise _fail(
            "PILOT_INTAKE_INVALID",
            "Persisted pilot requires a complete source-bound locked intake receipt.",
            "Restore state/intake.json from the guided start that selected this pilot.",
        ) from exc
    expected = {
        "status": "locked",
        "schema_version": assessment["schema_version"],
        "source": assessment["source"],
        "book_facts": assessment["book_facts"],
        "answers": assessment["answers"],
        "questions": [],
    }
    if (
        type(payload) is not dict
        or type(payload.get("schema_version")) is not int
        or assessment["questions"]
        or assessment["source"] != fresh_inspection.get("source")
        or _canonical_json(payload) != _canonical_json(expected)
    ):
        raise _fail(
            "PILOT_INTAKE_INVALID",
            "Persisted pilot requires a complete source-bound locked intake receipt.",
            "Restore state/intake.json from the guided start that selected this pilot.",
        )
    return assessment["answers"]


def _validate_pre_acceptance_config(
    config: ProjectConfig,
    locked_answers: Mapping[str, str],
) -> None:
    expected_profile = resolved_profile(profile_from_answers(locked_answers))
    if (
        config.source_language != locked_answers["source_language"]
        or config.target_language != locked_answers["target_language"]
        or config.output_mode != locked_answers["output_mode"]
        or dict(config.profile) != expected_profile
    ):
        raise _fail(
            "PILOT_CONFIG_DRIFT",
            "Current project policy no longer matches the locked guided intake.",
            "Use the locked policy or start a new guided project with corrected answers.",
        )


def _validated_pilot(
    config: ProjectConfig,
    payload: Any,
    *,
    prepared_block_map: Mapping[str, Any] | None = None,
    fresh_inspection: Mapping[str, Any] | None = None,
    locked_intake_payload: Any = _ARTIFACT_NOT_SUPPLIED,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _fail(
            "PILOT_SCHEMA_INVALID",
            "Pilot state must be a JSON object.",
            "Restore or recreate state/pilot.json.",
        )
    raw_status = payload.get("status")
    if raw_status in {"full_active", "pilot_accepted"} and "policy_identity" not in payload:
        raise _fail(
            "PILOT_POLICY_STALE",
            "Accepted pilot state has no verifiable policy identity.",
            "Run a new guided pilot and accept it against the current policy.",
        )
    expected_keys = _PILOT_KEYS | (
        {"policy_identity"}
        if raw_status in {"full_active", "pilot_accepted"}
        else set()
    )
    if set(payload) != expected_keys:
        raise _fail(
            "PILOT_SCHEMA_INVALID",
            "Pilot state contains missing or status-incompatible fields.",
            "Restore or recreate state/pilot.json.",
        )
    block_map = (
        _prepared_block_map(config)
        if prepared_block_map is None
        else prepared_block_map
    )
    source_hash, target_index, current_map = _current_target_index(config, block_map)
    source_document = payload.get("source_document")
    targets = payload.get("targets")
    eligible = payload.get("eligible_blocks")
    translated = payload.get("translated_blocks")
    reasons = payload.get("reason_codes")
    selection_facts = payload.get("selection_facts")
    invalid = (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or raw_status not in _STATUSES
        or payload.get("source_sha256") != source_hash
        or not isinstance(source_document, str)
        or source_document not in target_index
        or not isinstance(targets, list)
        or not targets
        or not isinstance(eligible, int)
        or isinstance(eligible, bool)
        or not isinstance(translated, int)
        or isinstance(translated, bool)
        or eligible != len(targets)
        or translated < 0
        or translated > eligible
        or not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(reason, str) or not reason for reason in reasons)
    )
    if invalid:
        raise _fail(
            "PILOT_SCHEMA_INVALID",
            "Pilot state does not match the required lifecycle schema.",
            "Restore or recreate state/pilot.json from the current source.",
        )
    seen: set[int] = set()
    for target in targets:
        if (
            not isinstance(target, Mapping)
            or not isinstance(target.get("block_index"), int)
            or isinstance(target.get("block_index"), bool)
            or not _sha256(target.get("source_sha256"))
            or target["block_index"] in seen
            or target_index[source_document].get(target["block_index"])
            != target["source_sha256"]
        ):
            raise _fail(
                "PILOT_TARGET_STALE",
                "Pilot targets must exactly match canonical blocks in the current source.",
                "Create a new pilot proposal from the current prepared source.",
            )
        seen.add(target["block_index"])
    if seen != set(target_index[source_document]):
        raise _fail(
            "PILOT_TARGET_SET_INVALID",
            "Pilot targets must include the complete canonical target set for the source document.",
            "Create a new pilot proposal from the current prepared source.",
        )
    fresh_inspection = (
        inspect_epub(config.source)
        if fresh_inspection is None
        else fresh_inspection
    )
    expected_facts = _expected_selection_facts(
        fresh_inspection, current_map, source_document
    )
    if (
        expected_facts is None
        or expected_facts["selected_block_count"] != eligible
        or not _selection_facts_match(selection_facts, expected_facts)
    ):
        raise _fail(
            "PILOT_SCHEMA_INVALID",
            "Pilot selection facts do not exactly match the current source structure.",
            "Restore or recreate state/pilot.json from the current source.",
        )
    locked_answers = _locked_pilot_answers(
        config,
        fresh_inspection,
        intake_payload=locked_intake_payload,
    )
    normalized_status = _STATUS_NORMALIZATION.get(raw_status, raw_status)
    if normalized_status != "full_active":
        _validate_pre_acceptance_config(config, locked_answers)
    expected_selection = select_pilot(fresh_inspection, current_map, locked_answers)
    selection_keys = (
        "source_sha256",
        "source_document",
        "targets",
        "eligible_blocks",
        "reason_codes",
        "selection_facts",
    )
    if any(
        _canonical_json(payload.get(key)) != _canonical_json(expected_selection[key])
        for key in selection_keys
    ):
        raise _fail(
            "PILOT_SELECTION_STALE",
            "Persisted pilot is not the exact deterministic winner for the locked intake.",
            "Restore or recreate state/pilot.json from the locked guided intake.",
        )
    normalized = dict(payload)
    normalized["status"] = normalized_status
    if normalized["status"] == "full_active":
        if translated != eligible:
            raise _fail(
                "PILOT_SCHEMA_INVALID",
                "Accepted pilot state must record complete pilot coverage.",
                "Restore the accepted pilot receipt or run a new guided pilot.",
            )
        _validate_policy_identity(config, normalized.get("policy_identity"))
    elif "policy_identity" in normalized:
        raise _fail(
            "PILOT_SCHEMA_INVALID",
            "Only full_active pilot state may carry acceptance policy identity.",
            "Remove the premature identity or restore the accepted state.",
        )
    return normalized


def load_pilot(
    config: ProjectConfig,
    *,
    prepared_block_map: Mapping[str, Any] | None = None,
    fresh_inspection: Mapping[str, Any] | None = None,
    locked_intake_payload: Any = _ARTIFACT_NOT_SUPPLIED,
) -> dict[str, Any] | None:
    """Load pilot state; only projects with no guided evidence may omit it."""
    validate_project_node_shapes(config.paths)
    if not config.paths.pilot.exists():
        if config.paths.guided_marker.is_file() or config.paths.intake.is_file():
            raise _fail(
                "PILOT_STATE_MISSING",
                "Guided project pilot state is missing, so translation scope cannot be inferred safely.",
                "Restore state/pilot.json from this guided project or rerun 'bookstudio start' with its locked answers.",
            )
        return None
    try:
        payload = json.loads(config.paths.pilot.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _fail(
            "PILOT_JSON_INVALID",
            "Pilot state is not valid JSON.",
            "Restore or recreate state/pilot.json.",
        ) from exc
    return _validated_pilot(
        config,
        payload,
        prepared_block_map=prepared_block_map,
        fresh_inspection=fresh_inspection,
        locked_intake_payload=locked_intake_payload,
    )


def _translated_target_count(config: ProjectConfig, pilot: Mapping[str, Any]) -> int:
    targets, _, block_map = coverage_target_index(config)
    source_hash = block_map.get("source", {}).get("sha256")
    pilot_targets = frozenset(
        (pilot["source_document"], target["block_index"])
        for target in pilot["targets"]
    )
    allowed = None if pilot["status"] == "full_active" else pilot_targets
    cache_index = validated_cache_index(
        config,
        targets=targets,
        source_sha256=source_hash,
        allowed_targets=allowed,
        allow_stale_context=True,
    )
    context_sha256 = current_translation_context_sha256(config)
    return sum(
        1
        for key in pilot_targets.intersection(cache_index)
        if cache_index[key].get("context_sha256") == context_sha256
    )


def pilot_scope_identity(receipt: Mapping[str, Any]) -> str:
    """Return the canonical packet-scope identity shared by CLI and revision."""
    return json.dumps(
        {
            "workflow_status": receipt["status"],
            "source_document": receipt["source_document"],
            "targets": [
                [
                    receipt["source_document"],
                    target["block_index"],
                    target["source_sha256"],
                ]
                for target in receipt["targets"]
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def pilot_receipt(config: ProjectConfig) -> dict[str, Any]:
    """Report derived pilot review state without mutating lifecycle files."""
    pilot = load_pilot(config)
    if pilot is None:
        return {"schema_version": 1, "status": "legacy"}
    translated = _translated_target_count(config, pilot)
    status = pilot["status"]
    review_required = status == "pilot_active" and translated == pilot["eligible_blocks"]
    return {
        **pilot,
        "status": "pilot_review_required" if review_required else status,
        "translated_blocks": translated,
    }


def approve_pilot(config: ProjectConfig) -> dict[str, Any]:
    pilot = load_pilot(config)
    if pilot is None or pilot["status"] != "pilot_proposed":
        raise _fail(
            "PILOT_TRANSITION_INVALID",
            "Only a proposed pilot can be approved.",
            "Create a pilot proposal before approving it.",
        )
    receipt = pilot_receipt(config)
    approved = {**pilot, "status": "pilot_active", "translated_blocks": receipt["translated_blocks"]}
    atomic_write_json(config.paths.pilot, approved)
    return approved


def accept_pilot(config: ProjectConfig, *, confirmed: bool) -> dict[str, Any]:
    pilot = load_pilot(config)
    if pilot is None:
        raise _fail(
            "PILOT_TRANSITION_INVALID",
            "A pilot proposal is required before acceptance.",
            "Create and approve a pilot proposal first.",
        )
    if not confirmed:
        raise _fail(
            "PILOT_CONFIRMATION_REQUIRED",
            "Pilot acceptance requires explicit confirmation.",
            "Review the completed pilot and retry with confirmed=True.",
        )
    receipt = pilot_receipt(config)
    if receipt["translated_blocks"] != pilot["eligible_blocks"]:
        raise _fail(
            "PILOT_INCOMPLETE",
            "Every pilot target needs a matching canonical translation before acceptance.",
            "Translate all pilot targets and review the derived pilot receipt.",
        )
    if pilot["status"] != "pilot_active":
        raise _fail(
            "PILOT_TRANSITION_INVALID",
            "Only an approved pilot can be accepted.",
            "Approve the completed pilot before accepting it.",
        )
    accepted = {
        **pilot,
        "status": "full_active",
        "translated_blocks": receipt["translated_blocks"],
        "policy_identity": current_policy_identity(config),
    }
    atomic_write_json(config.paths.pilot, accepted)
    return accepted


def require_translation_scope(config: ProjectConfig) -> frozenset[tuple[str, int]] | None:
    pilot = load_pilot(config)
    if pilot is None or pilot["status"] == "full_active":
        return None
    receipt = pilot_receipt(config)
    if receipt["status"] == "pilot_review_required":
        raise _fail(
            "PILOT_REVIEW_REQUIRED",
            "The completed pilot must be accepted before full translation can continue.",
            "Review the pilot and accept it with explicit confirmation.",
        )
    if pilot["status"] != "pilot_active":
        raise _fail(
            "PILOT_APPROVAL_REQUIRED",
            "The pilot proposal must be approved before pilot translation begins.",
            "Review and approve the pilot proposal.",
        )
    return frozenset(
        (pilot["source_document"], target["block_index"]) for target in pilot["targets"]
    )


def require_full_scope(config: ProjectConfig) -> None:
    pilot = load_pilot(config)
    if pilot is None or pilot["status"] == "full_active":
        return None
    raise _fail(
        "PILOT_FULL_SCOPE_BLOCKED",
        "Full-book processing is blocked until the pilot is accepted.",
        "Complete, review, and explicitly accept the pilot first.",
    )
