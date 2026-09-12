"""Content-free identity for every input that can shape an AI response."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import ProjectConfig, load_config
from ..errors import BookStudioError


MAX_PRODUCTION_BRIEF_BYTES = 32_768


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _artifact_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"


def read_production_brief(config: ProjectConfig) -> str | None:
    """Read the bounded private editorial contract used to shape every packet."""
    path = config.paths.production_brief
    if not path.is_file():
        return None
    payload = path.read_bytes()
    if len(payload) > MAX_PRODUCTION_BRIEF_BYTES:
        raise BookStudioError(
            code="PRODUCTION_BRIEF_TOO_LARGE",
            message=(
                "production-brief.md exceeds the bounded editorial-context limit "
                f"of {MAX_PRODUCTION_BRIEF_BYTES} bytes."
            ),
            next_action=(
                "Condense the brief to decisions and short voice guidance, "
                "then request a fresh packet."
            ),
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BookStudioError(
            code="PRODUCTION_BRIEF_INVALID",
            message="production-brief.md must be valid UTF-8 text.",
            next_action=(
                "Rewrite the private brief as UTF-8 Markdown, then request a fresh packet."
            ),
        ) from exc
    if not text.strip():
        raise BookStudioError(
            code="PRODUCTION_BRIEF_INVALID",
            message="production-brief.md cannot be empty when present.",
            next_action="Record the approved editorial decisions or remove the empty optional brief.",
        )
    return text


def current_translation_context_snapshot(
    config: ProjectConfig,
) -> tuple[dict[str, Any], str | None]:
    """Read one bounded editorial snapshot and its content-free identity."""
    current = load_config(config.paths.config)
    if current != config:
        raise BookStudioError(
            code="CONFIG_STALE",
            message="The loaded project config no longer matches bookstudio.toml.",
            next_action="Reload the project config and request a fresh packet before continuing.",
        )
    policy = {
        "slug": current.slug,
        "source_language": current.source_language,
        "target_language": current.target_language,
        "output_mode": current.output_mode,
        "profile": dict(sorted(current.profile.items())),
        "batch_scope": current.batch_scope,
        "max_blocks": current.max_blocks,
        "prompt_version": current.prompt_version,
        "require_complete": current.require_complete,
        "require_reproducible_build": current.require_reproducible_build,
    }
    production_brief = read_production_brief(current)
    identity: dict[str, Any] = {
        "schema_version": 1,
        "policy_sha256": _canonical_sha256(policy),
        "glossary_sha256": _artifact_sha256(current.paths.glossary),
        "reference_notes_sha256": _artifact_sha256(
            current.paths.root / "reference-notes.json"
        ),
        "image_manifest_sha256": _artifact_sha256(
            current.paths.root / "assets/image-manifest.json"
        ),
    }
    if production_brief is not None:
        identity["production_brief_sha256"] = hashlib.sha256(
            production_brief.encode("utf-8")
        ).hexdigest()
    identity["sha256"] = _canonical_sha256(identity)
    return identity, production_brief


def current_translation_context_identity(config: ProjectConfig) -> dict[str, Any]:
    """Hash policy and local editorial inputs without persisting their content."""
    return current_translation_context_snapshot(config)[0]


def current_translation_context_sha256(config: ProjectConfig) -> str:
    return str(current_translation_context_identity(config)["sha256"])
