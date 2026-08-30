"""Safe, marker-owned Book Studio project initialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .config import (
    MANAGED_PROJECT_DIRECTORIES,
    ProjectPaths,
    atomic_write_json,
    atomic_write_text,
    load_config,
    resolved_profile,
    validate_language,
    validate_output_mode,
    validate_project_node_shapes,
    validate_source,
    write_default_config,
)
from .epub.extract import extract_block_map
from .epub.inspect import inspect_epub
from .errors import BookStudioError
from .images.manifest import MANIFEST_RELATIVE_PATH, load_image_manifest
from .intake import assess_intake, profile_from_answers
from .pilot import load_pilot, pilot_receipt, select_pilot
from .translation.cache import CACHE_FILENAME, read_json, validated_cache_index


PROJECT_MARKER = ".bookstudio-project"
GUIDED_MARKER = ".bookstudio-guided"
_PROJECT_MARKER_TEXT = "bookstudio-project-v1\n"
_GUIDED_MARKER_TEXT = "bookstudio-guided-v1\n"


def _glossary_template() -> str:
    template = Path(__file__).with_name("templates") / "glossary.md"
    return template.read_text(encoding="utf-8")


def _marker_matches(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


def _recoverable_guided_partial(root: Path) -> bool:
    if not root.is_dir():
        return False
    entries = list(root.iterdir())
    return (
        len(entries) == 1
        and entries[0].name == GUIDED_MARKER
        and _marker_matches(entries[0], _GUIDED_MARKER_TEXT)
    )


def init_project(
    target: Path,
    *,
    slug: str,
    source: Path,
    target_language: str,
    output_mode: str,
    source_language: str = "en",
    max_blocks: int = 40,
    profile: Mapping[str, str] | None = None,
    guided: bool = False,
) -> Path:
    resolved_source = validate_source(source)
    validate_language(source_language, field="source_language")
    validate_language(target_language, field="target_language")
    validate_output_mode(output_mode)
    if not isinstance(max_blocks, int) or isinstance(max_blocks, bool) or max_blocks <= 0:
        raise BookStudioError(
            code="CONFIG_MAX_BLOCKS_INVALID",
            message=f"max_blocks must be a positive integer: {max_blocks!r}",
            next_action="Pass a positive --max-blocks value.",
        )

    root = target.expanduser().resolve()
    marker = root / PROJECT_MARKER
    if root.exists() and not root.is_dir():
        raise BookStudioError(
            code="PROJECT_PATH_INVALID",
            message=f"Project target is not a directory: {root}",
            next_action="Choose a directory path for the Book Studio project.",
        )
    if (
        root.is_dir()
        and any(root.iterdir())
        and not marker.is_file()
        and not (guided and _recoverable_guided_partial(root))
    ):
        raise BookStudioError(
            code="PROJECT_NOT_OWNED",
            message=f"Refusing to write into a nonempty unowned directory: {root}",
            next_action="Choose an empty directory or an existing Book Studio project.",
        )

    created = not marker.is_file()
    root.mkdir(parents=True, exist_ok=True)
    guided_marker = root / GUIDED_MARKER
    if guided and not _marker_matches(guided_marker, _GUIDED_MARKER_TEXT):
        if guided_marker.exists():
            raise BookStudioError(
                code="PROJECT_NOT_OWNED",
                message=f"Guided ownership marker is invalid: {root}",
                next_action="Choose an empty directory or restore the exact guided marker.",
            )
        atomic_write_text(guided_marker, _GUIDED_MARKER_TEXT)
    if created:
        atomic_write_text(marker, _PROJECT_MARKER_TEXT)
    for relative in MANAGED_PROJECT_DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)

    paths = ProjectPaths.from_root(root)
    if not paths.config.exists():
        write_default_config(
            paths.config,
            slug=slug,
            source=resolved_source,
            source_language=source_language,
            target_language=target_language,
            output_mode=output_mode,
            max_blocks=max_blocks,
            profile=profile,
        )
    if not paths.glossary.exists():
        atomic_write_text(paths.glossary, _glossary_template())

    load_config(paths.config)
    return paths.config


def full_coverage(block_map: Mapping[str, Any]) -> dict[str, Any]:
    """Return the default complete-source coverage contract for a block map."""
    return {
        "schema_version": 1,
        "source_sha256": block_map["source"]["sha256"],
        "included_files": [file["source_path"] for file in block_map["files"]],
        "excluded_files": [],
    }


def locked_intake(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """Persist only the validated, source-relative intake contract."""
    return {
        "status": "locked",
        "schema_version": assessment["schema_version"],
        "source": assessment["source"],
        "book_facts": assessment["book_facts"],
        "answers": assessment["answers"],
        "questions": [],
    }


def _read_locked_intake(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BookStudioError(
            code="PROJECT_INTAKE_INVALID",
            message="Existing project intake receipt is not valid JSON.",
            next_action="Restore state/intake.json from a matching project receipt.",
        ) from exc
    if not isinstance(payload, dict):
        raise BookStudioError(
            code="PROJECT_INTAKE_INVALID",
            message="Existing project intake receipt must be a JSON object.",
            next_action="Restore state/intake.json from a matching project receipt.",
        )
    source = payload.get("source")
    answers = payload.get("answers")
    source_is_valid = (
        isinstance(source, Mapping)
        and isinstance(source.get("name"), str)
        and isinstance(source.get("sha256"), str)
        and isinstance(source.get("size_bytes"), int)
        and not isinstance(source.get("size_bytes"), bool)
    )
    answers_are_valid = isinstance(answers, Mapping) and all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in answers.items()
    )
    if (
        payload.get("status") != "locked"
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or not source_is_valid
        or not answers_are_valid
    ):
        raise BookStudioError(
            code="PROJECT_INTAKE_INVALID",
            message="Existing project intake receipt does not match the locked schema.",
            next_action="Restore state/intake.json from a matching project receipt.",
        )
    return payload


def _same_source(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("sha256") == right.get("sha256") and left.get("size_bytes") == right.get("size_bytes")


def _canonical_json_identity(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _project_error(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _preflight_guided_owner(root: Path) -> ProjectPaths:
    paths = ProjectPaths.from_root(root)
    if root.exists() and not root.is_dir():
        raise _project_error(
            "PROJECT_PATH_INVALID",
            f"Project target is not a directory: {root}",
            "Choose a directory path for the Book Studio project.",
        )
    validate_project_node_shapes(paths)
    if (
        root.is_dir()
        and any(root.iterdir())
        and not paths.marker.is_file()
        and not _recoverable_guided_partial(root)
    ):
        raise _project_error(
            "PROJECT_NOT_OWNED",
            f"Refusing to write into a nonempty unowned directory: {root}",
            "Choose an empty directory or an existing Book Studio project.",
        )
    if paths.marker.exists() and not _marker_matches(
        paths.marker, _PROJECT_MARKER_TEXT
    ):
        raise _project_error(
            "PROJECT_NOT_OWNED",
            f"Project ownership marker is invalid: {root}",
            "Restore the exact project marker or choose a new project directory.",
        )
    if paths.guided_marker.exists() and not _marker_matches(
        paths.guided_marker, _GUIDED_MARKER_TEXT
    ):
        raise _project_error(
            "PROJECT_NOT_OWNED",
            f"Guided ownership marker is invalid: {root}",
            "Restore the exact guided marker or choose a new project directory.",
        )
    if (
        paths.marker.is_file()
        and not _marker_matches(paths.guided_marker, _GUIDED_MARKER_TEXT)
        and not paths.intake.is_file()
    ):
        raise _project_error(
            "PROJECT_GUIDED_OWNERSHIP_REQUIRED",
            "Refusing to convert a direct-init project into a guided project implicitly.",
            "Choose a new project directory or continue this project through the expert init flow.",
        )
    return paths


def _assert_matching_source(existing: Mapping[str, Any], assessment: Mapping[str, Any]) -> None:
    if not _same_source(existing, assessment["source"]):
        raise _project_error(
            "PROJECT_SOURCE_DRIFT",
            "Existing project is locked to a different source EPUB fingerprint.",
            "Choose the original source EPUB or start a new project directory.",
        )


def _assert_config_contract(
    config: Any,
    assessment: Mapping[str, Any],
    *,
    require_profile_match: bool,
) -> None:
    answers = assessment["answers"]
    if (
        config.source_language != answers["source_language"]
        or config.target_language != answers["target_language"]
        or config.output_mode != answers["output_mode"]
    ):
        raise _project_error(
            "PROJECT_CONFIG_DRIFT",
            "Existing project language or output policy does not match this guided restart.",
            "Use the locked guided answers or start a new project directory.",
        )
    configured_source = inspect_epub(config.source)["source"]
    _assert_matching_source(configured_source, assessment)
    if require_profile_match:
        expected_profile = resolved_profile(profile_from_answers(answers))
        if dict(config.profile) != expected_profile:
            raise _project_error(
                "PROJECT_CONFIG_DRIFT",
                "Interrupted guided project profile does not match the supplied answers.",
                "Use the answers that created the project or start a new project directory.",
            )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _project_error(
            "PROJECT_ARTIFACT_INVALID",
            f"Existing guided artifact is invalid JSON: {path.name}",
            "Restore the artifact from the matching project state.",
        ) from exc
    if not isinstance(value, dict):
        raise _project_error(
            "PROJECT_ARTIFACT_INVALID",
            f"Existing guided artifact must be a JSON object: {path.name}",
            "Restore the artifact from the matching project state.",
        )
    return value


def _validate_coverage(
    path: Path, block_map: Mapping[str, Any]
) -> dict[str, Any]:
    from .translation.coverage import validate_coverage_contract

    coverage = _read_object(path)
    try:
        return validate_coverage_contract(block_map, coverage)
    except BookStudioError as exc:
        raise _project_error(
            "PROJECT_ARTIFACT_INVALID",
            "Existing coverage contract does not match the current prepared source.",
            "Restore the reviewed coverage contract or start a new guided project.",
        ) from exc


def _coverage_targets(
    block_map: Mapping[str, Any], coverage: Mapping[str, Any]
) -> dict[tuple[str, int], Mapping[str, Any]]:
    excluded = set(coverage["excluded_files"])
    return {
        (file["source_path"], block["block_index"]): block
        for file in block_map["files"]
        if file["source_path"] not in excluded
        for block in file["blocks"]
        if block.get("canonical") is True and block.get("watermark") is not True
    }


def _validate_exact_present_json(
    path: Path,
    expected: Mapping[str, Any],
) -> None:
    if not path.exists():
        return
    existing = _read_object(path)
    if _canonical_json_identity(existing) != _canonical_json_identity(expected):
        raise _project_error(
            "PROJECT_ARTIFACT_INVALID",
            f"Existing guided artifact does not match the current source: {path.name}",
            "Restore the matching artifact or start a new guided project.",
        )


def _write_missing_json(path: Path, payload: Mapping[str, Any]) -> None:
    if not path.exists():
        atomic_write_json(path, payload)


def start_project(
    target: Path, source: Path, answers: Mapping[str, Any]
) -> dict[str, Any]:
    """Initialize a project only after a complete validated intake assessment."""
    assessment = assess_intake(source, answers)
    if assessment["questions"]:
        return {**assessment, "_exit_code": 2}

    root = target.expanduser().resolve()
    paths = _preflight_guided_owner(root)
    existing_intake = _read_locked_intake(paths.intake)
    if existing_intake is not None:
        _assert_matching_source(existing_intake["source"], assessment)
        if existing_intake.get("answers") != assessment["answers"]:
            raise _project_error(
                "PROJECT_INTAKE_DRIFT",
                "Existing project intake answers do not match this restart.",
                "Use the locked answers or start a new project directory.",
            )
        if _canonical_json_identity(existing_intake) != _canonical_json_identity(
            locked_intake(assessment)
        ):
            raise _project_error(
                "PROJECT_INTAKE_DRIFT",
                "Existing project intake receipt does not exactly match this guided restart.",
                "Restore the complete locked intake receipt or start a new project directory.",
            )

    existing_config = load_config(paths.config) if paths.config.is_file() else None
    if existing_config is not None:
        _assert_config_contract(
            existing_config,
            assessment,
            require_profile_match=existing_intake is None,
        )

    inspection = inspect_epub(source)
    block_map = extract_block_map(source)
    expected_intake = locked_intake(assessment)
    expected_pilot = select_pilot(inspection, block_map, assessment["answers"])
    block_map_path = paths.source_blocks / "full-block-map.json"
    coverage_path = paths.source_blocks / "coverage.json"

    # Validation is a read-only phase. No missing artifact is reconstructed until
    # every canonical artifact already present has passed its complete contract.
    _validate_exact_present_json(paths.inspection, inspection)
    _validate_exact_present_json(block_map_path, block_map)
    coverage = (
        _validate_coverage(coverage_path, block_map)
        if coverage_path.exists()
        else full_coverage(block_map)
    )
    reference_notes_path = paths.root / "reference-notes.json"
    if reference_notes_path.exists():
        read_json(
            reference_notes_path,
            missing_code="REFERENCE_NOTES_MISSING",
            invalid_code="REFERENCE_NOTES_JSON_INVALID",
        )
    image_manifest_path = paths.root / MANIFEST_RELATIVE_PATH
    if image_manifest_path.exists():
        if existing_config is None:
            raise _project_error(
                "PROJECT_ARTIFACT_INVALID",
                "Existing image manifest cannot be validated without its project config.",
                "Restore bookstudio.toml from the matching guided project.",
            )
        load_image_manifest(existing_config)
    validated_pilot = expected_pilot
    if paths.pilot.exists():
        if existing_config is None:
            raise _project_error(
                "PROJECT_ARTIFACT_INVALID",
                "Existing pilot state cannot be validated without its project config.",
                "Restore bookstudio.toml from the matching guided project.",
            )
        validated_pilot = load_pilot(
            existing_config,
            prepared_block_map=block_map,
            fresh_inspection=inspection,
            locked_intake_payload=expected_intake,
        )
        assert validated_pilot is not None
    cache_file = paths.cache / CACHE_FILENAME
    if cache_file.exists():
        if existing_config is None:
            raise _project_error(
                "PROJECT_ARTIFACT_INVALID",
                "Existing translation cache cannot be validated without its project config.",
                "Restore bookstudio.toml from the matching guided project.",
            )
        targets = _coverage_targets(block_map, coverage)
        allowed_targets = (
            None
            if validated_pilot["status"] == "full_active"
            else frozenset(
                (validated_pilot["source_document"], target["block_index"])
                for target in validated_pilot["targets"]
            )
        )
        validated_cache_index(
            existing_config,
            targets=targets,
            source_sha256=block_map["source"]["sha256"],
            allowed_targets=allowed_targets,
        )

    needs_scaffold = existing_config is None or not paths.glossary.is_file()
    if needs_scaffold or not paths.marker.is_file():
        config_path = init_project(
            root,
            slug=root.name,
            source=source,
            source_language=assessment["answers"]["source_language"],
            target_language=assessment["answers"]["target_language"],
            output_mode=assessment["answers"]["output_mode"],
            profile=profile_from_answers(assessment["answers"]),
            guided=True,
        )
    else:
        config_path = paths.config
    config = load_config(config_path)
    _assert_config_contract(
        config,
        assessment,
        require_profile_match=existing_intake is None,
    )

    _write_missing_json(paths.intake, expected_intake)
    _write_missing_json(config.paths.inspection, inspection)
    _write_missing_json(block_map_path, block_map)
    _write_missing_json(coverage_path, full_coverage(block_map))
    _write_missing_json(config.paths.pilot, expected_pilot)
    return {**assessment, "workflow_status": pilot_receipt(config)["status"]}
