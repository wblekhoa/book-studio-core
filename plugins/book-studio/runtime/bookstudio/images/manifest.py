"""Project-owned image policy and canvas-preservation checks."""

from __future__ import annotations

import posixpath
import struct
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from ..config import ProjectConfig
from ..epub.archive import preflight_archive
from ..errors import BookStudioError
from ..translation.cache import read_json


MANIFEST_RELATIVE_PATH = Path("assets/image-manifest.json")
ALLOWED_POLICIES = frozenset({"original_only", "annotation", "original_plus_companion"})


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def image_dimensions(data: bytes) -> tuple[int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        offset = 2
        frame_markers = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while offset < len(data):
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in {0x01, 0xD8, 0xD9}:
                continue
            if offset + 2 > len(data):
                break
            length = struct.unpack(">H", data[offset : offset + 2])[0]
            if length < 2 or offset + length > len(data):
                break
            if marker in frame_markers and length >= 7:
                height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
                return width, height
            offset += length
    raise _fail(
        "IMAGE_FORMAT_UNSUPPORTED",
        "Image dimensions can only be verified for PNG or JPEG data.",
        "Use a PNG or JPEG companion and source image.",
    )


def _source_path(record: dict[str, Any]) -> str:
    value = record.get("source_path")
    if not isinstance(value, str):
        raise _fail(
            "IMAGE_SOURCE_INVALID",
            "Image record requires a logical source_path.",
            "Use the exact relative image member path from the source EPUB.",
        )
    pure = PurePosixPath(value)
    if value.startswith("/") or "\\" in value or pure.is_absolute() or ".." in pure.parts:
        raise _fail(
            "IMAGE_SOURCE_INVALID",
            f"Unsafe image source path: {value!r}",
            "Use the exact relative image member path from the source EPUB.",
        )
    return posixpath.normpath(value)


def _owned_companion(config: ProjectConfig, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise _fail(
            "IMAGE_COMPANION_MISSING",
            "Companion policy requires a companion path.",
            "Place the localized image under assets/localized and register its relative path.",
        )
    relative = Path(value)
    if relative.is_absolute():
        raise _fail(
            "IMAGE_COMPANION_OUTSIDE_PROJECT",
            f"Companion path must be project-relative: {value}",
            "Place the localized image under assets/localized.",
        )
    candidate = (config.paths.root / relative).resolve()
    localized_root = config.paths.localized_assets.resolve()
    try:
        candidate.relative_to(localized_root)
    except ValueError as exc:
        raise _fail(
            "IMAGE_COMPANION_OUTSIDE_PROJECT",
            f"Companion escapes assets/localized: {value}",
            "Place the localized image under assets/localized.",
        ) from exc
    if not candidate.is_file():
        raise _fail(
            "IMAGE_COMPANION_MISSING",
            f"Companion file does not exist: {value}",
            "Create the localized companion before registering it.",
        )
    return candidate


def companion_epub_path(opf_path: str, record: dict[str, Any]) -> str:
    companion = Path(str(record["companion"]))
    opf_dir = posixpath.dirname(opf_path)
    return posixpath.normpath(
        posixpath.join(opf_dir, "bookstudio-localized", companion.name)
    )


def companion_file(config: ProjectConfig, record: dict[str, Any]) -> Path:
    return _owned_companion(config, record.get("companion"))


def validate_companion_dimensions(
    config: ProjectConfig, record: dict[str, Any]
) -> dict[str, Any]:
    source_path = _source_path(record)
    companion = _owned_companion(config, record.get("companion"))
    preflight_archive(config.source)
    with zipfile.ZipFile(config.source, "r") as archive:
        if source_path not in archive.namelist():
            raise _fail(
                "IMAGE_SOURCE_MISSING",
                f"Source image is absent from the EPUB: {source_path}",
                "Use an image path present in the inspected source EPUB.",
            )
        source_size = image_dimensions(archive.read(source_path))
    companion_size = image_dimensions(companion.read_bytes())
    if source_size != companion_size:
        raise _fail(
            "IMAGE_CANVAS_MISMATCH",
            f"Companion canvas {companion_size} differs from source canvas {source_size}.",
            "Recreate the localized image at the exact source pixel dimensions.",
        )
    return {"passed": True, "source_path": source_path, "canvas": list(source_size)}


def validate_image_record(
    config: ProjectConfig, record: dict[str, Any], *, archive_names: set[str] | None = None
) -> bool:
    source_path = _source_path(record)
    policy = record.get("policy")
    if policy not in ALLOWED_POLICIES:
        raise _fail(
            "IMAGE_POLICY_INVALID",
            f"Unsupported image policy: {policy!r}",
            "Choose original_only, annotation, or original_plus_companion.",
        )
    if archive_names is None:
        preflight_archive(config.source)
        with zipfile.ZipFile(config.source, "r") as archive:
            archive_names = set(archive.namelist())
    if source_path not in archive_names:
        raise _fail(
            "IMAGE_SOURCE_MISSING",
            f"Source image is absent from the EPUB: {source_path}",
            "Use an image path present in the inspected source EPUB.",
        )
    if policy == "annotation":
        annotation = record.get("annotation")
        if not isinstance(annotation, str) or not annotation.strip():
            raise _fail(
                "IMAGE_ANNOTATION_MISSING",
                "Annotation policy requires nonempty target-language annotation text.",
                "Add the secondary image annotation text.",
            )
    if policy == "original_plus_companion":
        validate_companion_dimensions(config, record)
        return True
    return False


def load_image_manifest(
    config: ProjectConfig, path: Path | None = None
) -> dict[str, Any]:
    manifest_path = path or (config.paths.root / MANIFEST_RELATIVE_PATH)
    if not manifest_path.is_file():
        return {
            "status": "pass",
            "passed": True,
            "schema_version": 1,
            "images": [],
            "companion_matches": 0,
        }
    payload = read_json(
        manifest_path,
        missing_code="IMAGE_MANIFEST_MISSING",
        invalid_code="IMAGE_MANIFEST_JSON_INVALID",
    )
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("images"), list)
    ):
        raise _fail(
            "IMAGE_MANIFEST_SCHEMA_INVALID",
            "Image manifest must use schema_version 1 and an images array.",
            "Regenerate assets/image-manifest.json using the documented schema.",
        )
    preflight_archive(config.source)
    with zipfile.ZipFile(config.source, "r") as archive:
        archive_names = set(archive.namelist())
    seen: set[str] = set()
    companion_matches = 0
    for record in payload["images"]:
        if not isinstance(record, dict):
            raise _fail(
                "IMAGE_MANIFEST_SCHEMA_INVALID",
                "Every image manifest entry must be an object.",
                "Regenerate the image manifest using the documented schema.",
            )
        source_path = _source_path(record)
        if source_path in seen:
            raise _fail(
                "IMAGE_RECORD_DUPLICATE",
                f"Image manifest repeats source path: {source_path}",
                "Keep one policy record per source image.",
            )
        seen.add(source_path)
        companion_matches += int(
            validate_image_record(config, record, archive_names=archive_names)
        )
    return {
        **payload,
        "status": "pass",
        "passed": True,
        "companion_matches": companion_matches,
    }
