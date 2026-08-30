"""Deterministic source assessment for guided project intake."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .config import validate_language, validate_output_mode
from .errors import BookStudioError
from .epub.inspect import inspect_epub


ANSWER_ORDER = (
    "source_language",
    "target_language",
    "output_mode",
    "audience",
    "translation_approach",
    "image_text_policy",
    "image_annotation_policy",
    "market_context_policy",
    "layout_policy",
)
OPTIONAL_ANSWERS = frozenset(
    {
        "domain",
        "tone",
        "terminology_policy",
        "market_context_label",
        "image_annotation_label",
    }
)
_KNOWN_ANSWERS = frozenset(ANSWER_ORDER) | OPTIONAL_ANSWERS
_QUESTION_PROMPTS = {
    "source_language": "What language is the source book written in?",
    "target_language": "What language should the translated book use?",
    "output_mode": "Should the output replace source text or show both languages?",
    "audience": "Who is the intended reader?",
    "translation_approach": "What translation approach should guide editorial choices?",
    "image_text_policy": "How should text contained in images be handled?",
    "image_annotation_policy": "Should images receive translated annotations?",
    "market_context_policy": "How should market-specific context be handled?",
    "layout_policy": "What layout changes are permitted?",
}
_ENUM_VALUES = {
    "translation_approach": ("faithful", "adaptive"),
    "image_text_policy": ("none", "selective", "all"),
    "image_annotation_policy": ("none", "selective", "all"),
    "market_context_policy": ("none", "labeled_selective"),
    "layout_policy": ("preserve", "adaptive"),
}
_QUESTION_ACCEPTED_VALUES: dict[str, tuple[str, ...] | None] = {
    "source_language": None,
    "target_language": None,
    "output_mode": ("target_only", "bilingual", "vi_only"),
    "audience": None,
    **_ENUM_VALUES,
}
_QUESTION_RECOMMENDATIONS: dict[str, str | None] = {
    "source_language": None,
    "target_language": None,
    "output_mode": "target_only",
    "audience": None,
    "translation_approach": "faithful",
    "image_text_policy": "selective",
    "image_annotation_policy": "selective",
    "market_context_policy": "labeled_selective",
    "layout_policy": "preserve",
}


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def load_intake_answers(path: Path | None) -> dict[str, Any]:
    """Load an optional JSON answers object without deriving source facts."""
    if path is None:
        return {}
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise _fail(
            "INTAKE_ANSWERS_MISSING",
            f"Intake answers file does not exist: {path}",
            "Pass an existing JSON object file or omit the answers file.",
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _fail(
            "INTAKE_ANSWERS_INVALID",
            f"Intake answers are not valid JSON: {path}",
            "Provide a JSON object whose values are text answers.",
        ) from exc
    if not isinstance(payload, dict):
        raise _fail(
            "INTAKE_ANSWERS_INVALID",
            "Intake answers must be a JSON object.",
            "Provide named text answers in one JSON object.",
        )
    return payload


def _inferred_source_language(inspection: Mapping[str, Any]) -> str | None:
    languages = inspection.get("metadata", {}).get("language", [])
    if not isinstance(languages, list) or len(languages) != 1:
        return None
    value = languages[0]
    try:
        return validate_language(value, field="source_language")
    except BookStudioError:
        return None


def validate_answers(
    inspection: Mapping[str, Any], answers: Mapping[str, Any]
) -> dict[str, str]:
    if not isinstance(answers, Mapping):
        raise _fail(
            "INTAKE_ANSWERS_INVALID",
            "Intake answers must be a mapping.",
            "Provide named text answers in a JSON object.",
        )
    unknown = sorted(set(answers) - _KNOWN_ANSWERS)
    if unknown:
        raise _fail(
            "INTAKE_ANSWER_UNKNOWN",
            f"Unsupported intake answer: {unknown[0]!r}",
            "Use only the question ids returned by the assessment.",
        )

    normalized_values: dict[str, str] = {}
    for key, value in answers.items():
        if not isinstance(value, str):
            raise _fail(
                "INTAKE_ANSWER_INVALID",
                f"Intake answer {key!r} must be text.",
                "Provide text values for supplied answers.",
            )
        normalized = value.strip()
        if normalized:
            normalized_values[key] = normalized
    if "source_language" in normalized_values:
        normalized_values["source_language"] = validate_language(
            normalized_values["source_language"], field="source_language"
        )
    elif (inferred := _inferred_source_language(inspection)) is not None:
        normalized_values["source_language"] = inferred
    if "target_language" in normalized_values:
        normalized_values["target_language"] = validate_language(
            normalized_values["target_language"], field="target_language"
        )
    if "output_mode" in normalized_values:
        normalized_values["output_mode"] = validate_output_mode(
            normalized_values["output_mode"]
        )
    for key, accepted in _ENUM_VALUES.items():
        value = normalized_values.get(key)
        if value is not None and value not in accepted:
            raise _fail(
                "INTAKE_ANSWER_INVALID",
                f"Unsupported {key}: {value!r}.",
                f"Use one of: {', '.join(accepted)}.",
            )

    ordered: dict[str, str] = {}
    for key in ANSWER_ORDER:
        if key in normalized_values:
            ordered[key] = normalized_values[key]
    for key in sorted(OPTIONAL_ANSWERS):
        if key in normalized_values:
            ordered[key] = normalized_values[key]
    return ordered


def intake_facts(inspection: Mapping[str, Any]) -> dict[str, Any]:
    files = inspection["text"]["files"]
    inline_images = sum(file["images"] for file in files)
    return {
        "title": inspection["metadata"]["title"][:1],
        "languages": inspection["metadata"]["language"],
        "spine_items": inspection["spine_items"],
        "approx_words": inspection["text"]["approx_words"],
        "translation_blocks": inspection["text"]["translation_blocks"],
        "images": max(inline_images, inspection.get("image_resources", 0)),
        "documents": [
            {
                "spine_index": file["spine_index"],
                "logical_path": file["source_path"],
                "title": file["title"],
                "size_bytes": file["size_bytes"],
                "block_count": file["blocks"],
                "image_count": file["images"],
            }
            for file in files
        ],
    }


def missing_questions(
    inspection: Mapping[str, Any], answers: Mapping[str, str]
) -> list[dict[str, Any]]:
    has_images = inspection.get("image_resources", 0) > 0 or any(
        file["images"] for file in inspection["text"]["files"]
    )
    return [
        {
            "id": key,
            "prompt": _QUESTION_PROMPTS[key],
            "required": True,
            "accepted_values": (
                list(_QUESTION_ACCEPTED_VALUES[key])
                if _QUESTION_ACCEPTED_VALUES[key] is not None
                else None
            ),
            "recommendation": _QUESTION_RECOMMENDATIONS[key],
        }
        for key in ANSWER_ORDER
        if key not in answers
        and (has_images or key not in {"image_text_policy", "image_annotation_policy"})
    ]


def profile_from_answers(answers: Mapping[str, Any]) -> dict[str, str]:
    profile: dict[str, str] = {}
    direct_keys = (
        "domain",
        "audience",
        "tone",
        "terminology_policy",
        "translation_approach",
        "image_text_policy",
        "image_annotation_policy",
        "market_context_policy",
        "layout_policy",
        "market_context_label",
        "image_annotation_label",
    )
    for key in direct_keys:
        value = answers.get(key)
        if isinstance(value, str):
            profile[key] = value
    if "image_text_policy" in profile:
        profile["image_policy"] = profile["image_text_policy"]
    if "market_context_policy" in profile:
        profile["localization_boundary"] = profile["market_context_policy"]
    return profile


def assess_intake(source: Path, answers: Mapping[str, Any]) -> dict[str, Any]:
    inspection = inspect_epub(source)
    normalized = validate_answers(inspection, answers)
    questions = missing_questions(inspection, normalized)
    return {
        "status": "needs_input" if questions else "ready",
        "schema_version": 1,
        "source": inspection["source"],
        "book_facts": intake_facts(inspection),
        "answers": normalized,
        "questions": questions,
    }
