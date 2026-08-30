"""Content-free identity for every input that can shape an AI response."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import ProjectConfig, load_config
from ..errors import BookStudioError


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


def current_translation_context_identity(config: ProjectConfig) -> dict[str, Any]:
    """Hash policy and local editorial inputs without persisting their content."""
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
    identity["sha256"] = _canonical_sha256(identity)
    return identity


def current_translation_context_sha256(config: ProjectConfig) -> str:
    return str(current_translation_context_identity(config)["sha256"])
