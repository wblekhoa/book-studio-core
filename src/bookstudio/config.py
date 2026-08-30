"""Validated, immutable Book Studio project configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import BookStudioError


CONFIG_FILENAME = "bookstudio.toml"
ALLOWED_OUTPUT_MODES = frozenset({"target_only", "vi_only", "bilingual"})
MANAGED_PROJECT_DIRECTORIES = (
    "state",
    "source-blocks",
    "packets",
    "cache",
    "assets",
    "assets/localized",
    "output",
    "reports",
)
MANAGED_PROJECT_SINGLETONS = (
    ".bookstudio-project",
    ".bookstudio-guided",
    CONFIG_FILENAME,
    "glossary.md",
    "state/intake.json",
    "state/inspection.json",
    "state/pilot.json",
    "source-blocks/full-block-map.json",
    "source-blocks/coverage.json",
    "cache/translations.json",
    "assets/image-manifest.json",
    "reference-notes.json",
)
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
DEFAULT_PROFILE = {
    "domain": "general",
    "audience": "general-readers",
    "tone": "clear, conversational, domain-aware",
    "terminology_policy": "keep-established-industry-terms",
    "localization_boundary": "editorial-blocks-only",
    "image_policy": "original-plus-companion",
}


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config: Path
    marker: Path
    guided_marker: Path
    glossary: Path
    inspection: Path
    intake: Path
    pilot: Path
    source_blocks: Path
    packets: Path
    cache: Path
    localized_assets: Path
    output: Path
    reports: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        return cls(
            root=root,
            config=root / CONFIG_FILENAME,
            marker=root / ".bookstudio-project",
            guided_marker=root / ".bookstudio-guided",
            glossary=root / "glossary.md",
            inspection=root / "state/inspection.json",
            intake=root / "state/intake.json",
            pilot=root / "state/pilot.json",
            source_blocks=root / "source-blocks",
            packets=root / "packets",
            cache=root / "cache",
            localized_assets=root / "assets/localized",
            output=root / "output",
            reports=root / "reports",
        )


@dataclass(frozen=True)
class ProjectConfig:
    schema_version: int
    slug: str
    source: Path
    source_language: str
    target_language: str
    output_mode: str
    profile: Mapping[str, str]
    batch_scope: str
    max_blocks: int
    prompt_version: str
    require_complete: bool
    require_reproducible_build: bool
    paths: ProjectPaths

    @property
    def config_path(self) -> Path:
        return self.paths.config

    @property
    def project_root(self) -> Path:
        return self.paths.root


def _config_error(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _lexically_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def validate_project_node_shapes(paths: ProjectPaths) -> None:
    """Reject managed paths that could redirect reads or writes outside a project."""
    for relative in MANAGED_PROJECT_DIRECTORIES:
        path = paths.root / relative
        if _lexically_present(path) and (path.is_symlink() or not path.is_dir()):
            raise _config_error(
                "PROJECT_DIRECTORY_PATH_INVALID",
                f"Managed project directory must be a non-symlink directory: {relative}",
                "Restore this managed path as a real directory before continuing.",
            )
    for relative in MANAGED_PROJECT_SINGLETONS:
        path = paths.root / relative
        if _lexically_present(path) and (path.is_symlink() or not path.is_file()):
            raise _config_error(
                "PROJECT_ARTIFACT_PATH_INVALID",
                f"Project artifact must be a non-symlink regular file: {relative}",
                "Restore this artifact as a real file or remove the wrong-node path before continuing.",
            )


def validate_language(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _LANGUAGE_PATTERN.fullmatch(value):
        raise _config_error(
            "CONFIG_LANGUAGE_INVALID",
            f"{field} must be a BCP-47-like language code: {value!r}",
            "Use a code such as 'en', 'vi', 'en-US', or 'vi-VN'.",
        )
    return value


def validate_output_mode(value: str) -> str:
    if value not in ALLOWED_OUTPUT_MODES:
        raise _config_error(
            "CONFIG_OUTPUT_MODE_INVALID",
            f"Unsupported output mode: {value!r}",
            "Choose 'target_only', 'vi_only', or 'bilingual'.",
        )
    return value


def validate_source(source: Path) -> Path:
    resolved = source.expanduser().resolve()
    if not resolved.is_file():
        raise _config_error(
            "SOURCE_NOT_FOUND",
            f"Source EPUB does not exist: {source}",
            "Pass an existing read-only EPUB source path.",
        )
    return resolved


def _required(table: Mapping[str, Any], key: str, section: str) -> Any:
    try:
        return table[key]
    except KeyError as exc:
        raise _config_error(
            "CONFIG_FIELD_MISSING",
            f"Missing required field [{section}].{key}",
            f"Add '{key}' to the [{section}] section of {CONFIG_FILENAME}.",
        ) from exc


def _table(document: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = _required(document, name, "root")
    if not isinstance(value, dict):
        raise _config_error(
            "CONFIG_SECTION_INVALID",
            f"Configuration section [{name}] must be a TOML table.",
            f"Rewrite [{name}] as a TOML table.",
        )
    return value


def load_config(path: Path) -> ProjectConfig:
    requested_path = path.expanduser()
    if requested_path.is_symlink():
        raise _config_error(
            "PROJECT_ARTIFACT_PATH_INVALID",
            f"Project config must be a non-symlink regular file: {requested_path.name}",
            "Pass the real bookstudio.toml path or a project directory alias instead.",
        )
    config_path = requested_path.resolve()
    if not config_path.is_file():
        raise _config_error(
            "PROJECT_CONFIG_MISSING",
            f"Book Studio project config not found: {config_path}",
            "Run 'bookstudio init' or pass an existing project directory.",
        )
    try:
        with config_path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise _config_error(
            "CONFIG_TOML_INVALID",
            f"Invalid TOML in {CONFIG_FILENAME}: {exc}",
            "Correct the TOML syntax and run the command again.",
        ) from exc

    schema_version = _required(document, "schema_version", "root")
    if type(schema_version) is not int or schema_version != 1:
        raise _config_error(
            "CONFIG_SCHEMA_UNSUPPORTED",
            f"Unsupported schema_version: {schema_version!r}",
            "Use schema_version = 1.",
        )

    book = _table(document, "book")
    profile = _table(document, "profile")
    translation = _table(document, "translation")
    quality = _table(document, "quality")
    source_value = _required(book, "source", "book")
    if not isinstance(source_value, str):
        raise _config_error(
            "CONFIG_SOURCE_INVALID",
            "[book].source must be a path string.",
            "Set source to an existing EPUB path.",
        )
    source_path = Path(source_value).expanduser()
    if not source_path.is_absolute():
        source_path = config_path.parent / source_path

    max_blocks = _required(translation, "max_blocks", "translation")
    if not isinstance(max_blocks, int) or isinstance(max_blocks, bool) or max_blocks <= 0:
        raise _config_error(
            "CONFIG_MAX_BLOCKS_INVALID",
            f"max_blocks must be a positive integer: {max_blocks!r}",
            "Set [translation].max_blocks to a positive integer.",
        )

    profile_values: dict[str, str] = {}
    for key in (
        "domain",
        "audience",
        "tone",
        "terminology_policy",
        "localization_boundary",
        "image_policy",
    ):
        value = _required(profile, key, "profile")
        if not isinstance(value, str):
            raise _config_error(
                "CONFIG_PROFILE_INVALID",
                f"[profile].{key} must be a string.",
                f"Set [profile].{key} to a text value.",
            )
        profile_values[key] = value
    for key, value in profile.items():
        if key not in profile_values and isinstance(value, str):
            profile_values[key] = value

    result = ProjectConfig(
        schema_version=1,
        slug=str(_required(book, "slug", "book")),
        source=validate_source(source_path),
        source_language=validate_language(
            _required(book, "source_language", "book"), field="source_language"
        ),
        target_language=validate_language(
            _required(book, "target_language", "book"), field="target_language"
        ),
        output_mode=validate_output_mode(_required(book, "output_mode", "book")),
        profile=profile_values,
        batch_scope=str(_required(translation, "batch_scope", "translation")),
        max_blocks=max_blocks,
        prompt_version=str(_required(translation, "prompt_version", "translation")),
        require_complete=bool(_required(quality, "require_complete", "quality")),
        require_reproducible_build=bool(
            _required(quality, "require_reproducible_build", "quality")
        ),
        paths=ProjectPaths.from_root(config_path.parent),
    )
    validate_project_node_shapes(result.paths)
    return result


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def resolved_profile(profile: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the complete validated profile written by default configuration."""
    values = dict(DEFAULT_PROFILE)
    if profile is not None:
        for key, value in profile.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise _config_error(
                    "CONFIG_PROFILE_INVALID",
                    "Profile overrides must use text keys and values.",
                    "Pass validated text profile overrides.",
                )
            values[key] = value
    return values


def default_config_text(
    *,
    slug: str,
    source: Path,
    source_language: str = "en",
    target_language: str,
    output_mode: str = "target_only",
    max_blocks: int = 40,
    profile: Mapping[str, str] | None = None,
) -> str:
    validate_language(source_language, field="source_language")
    validate_language(target_language, field="target_language")
    validate_output_mode(output_mode)
    if max_blocks <= 0:
        raise _config_error(
            "CONFIG_MAX_BLOCKS_INVALID",
            f"max_blocks must be positive: {max_blocks!r}",
            "Pass a positive max_blocks value.",
        )
    resolved_source = validate_source(source)
    profile_values = resolved_profile(profile)
    profile_text = "\n".join(
        f"{key} = {_toml_string(value)}" for key, value in profile_values.items()
    )
    return f'''schema_version = 1

[book]
slug = {_toml_string(slug)}
source = {_toml_string(str(resolved_source))}
source_language = {_toml_string(source_language)}
target_language = {_toml_string(target_language)}
output_mode = {_toml_string(output_mode)}

[profile]
{profile_text}

[translation]
batch_scope = "chapter"
max_blocks = {max_blocks}
prompt_version = "1"

[quality]
require_complete = true
require_reproducible_build = true
'''


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_default_config(path: Path, **values: Any) -> None:
    atomic_write_text(path, default_config_text(**values))
