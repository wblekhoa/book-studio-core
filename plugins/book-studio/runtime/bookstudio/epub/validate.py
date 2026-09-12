"""Independent EPUB integrity and related-impact validation."""

from __future__ import annotations

import hashlib
import posixpath
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from ..config import ProjectConfig
from ..images.manifest import companion_epub_path, load_image_manifest
from ..translation.coverage import coverage_receipt
from .archive import preflight_archive
from .build import ZIP_TIME
from .inspect import DC_NS, local_name, package_context


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _violation(category: str, path: str, detail: str) -> dict[str, str]:
    return {"category": category, "path": path, "detail": detail}


def _resolved_reference(document: str, value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    raw_path = unquote(parsed.path)
    target = (
        document
        if not raw_path
        else posixpath.normpath(posixpath.join(posixpath.dirname(document), raw_path))
    )
    return target, parsed.fragment


def validate_epub(config: ProjectConfig, output_path: Path) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    output = output_path.expanduser().resolve()
    try:
        preflight = preflight_archive(output)
        coverage = coverage_receipt(config, require_complete=True)
        if not coverage["passed"]:
            violations.append(_violation("coverage", "cache/translations.json", coverage["status"]))
        image_manifest = load_image_manifest(config)
        source_preflight = preflight_archive(config.source)
        with zipfile.ZipFile(config.source, "r") as source_archive, zipfile.ZipFile(
            output, "r"
        ) as archive:
            infos = archive.infolist()
            names = set(archive.namelist())
            if not infos or infos[0].filename != "mimetype":
                violations.append(_violation("mimetype_order", "mimetype", "not first"))
            elif infos[0].compress_type != zipfile.ZIP_STORED:
                violations.append(_violation("mimetype_compression", "mimetype", "not stored"))
            elif archive.read("mimetype") != b"application/epub+zip":
                violations.append(_violation("mimetype_value", "mimetype", "invalid value"))
            for info in infos:
                if info.date_time != ZIP_TIME:
                    violations.append(
                        _violation("timestamp", info.filename, str(info.date_time))
                    )

            source_context = package_context(source_archive)
            context = package_context(archive)
            if len(context["spine"]) != len(source_context["spine"]):
                violations.append(
                    _violation("spine_count", context["opf_path"], "differs from source")
                )
            for item in context["manifest"].values():
                if item["path"] not in names:
                    violations.append(
                        _violation("manifest_resource_missing", item["path"], item["id"])
                    )

            languages = [
                " ".join((node.text or "").split())
                for node in context["package"].findall(f".//{{{DC_NS}}}language")
            ]
            if config.target_language not in languages:
                violations.append(
                    _violation("metadata_language", context["opf_path"], str(languages))
                )

            source_nav = sum(
                "nav" in item.get("properties", "").split()
                for item in source_context["manifest"].values()
            )
            output_nav = sum(
                "nav" in item.get("properties", "").split()
                for item in context["manifest"].values()
            )
            if source_nav != output_nav:
                violations.append(
                    _violation("navigation", context["opf_path"], "nav item count changed")
                )

            source_images = [
                item
                for item in source_context["manifest"].values()
                if item.get("media_type", "").startswith("image/")
            ]
            for item in source_images:
                if item["path"] not in names:
                    violations.append(
                        _violation("source_image_missing", item["path"], "missing from output")
                    )
                elif _hash_bytes(source_archive.read(item["path"])) != _hash_bytes(
                    archive.read(item["path"])
                ):
                    violations.append(
                        _violation("source_image_changed", item["path"], "content hash differs")
                    )

            ids_by_document: dict[str, set[str]] = {}
            roots: dict[str, ET.Element] = {}
            referenced_resources: set[str] = set()
            for item in context["manifest"].values():
                if item.get("media_type") not in {"application/xhtml+xml", "text/html"}:
                    continue
                try:
                    root = ET.fromstring(archive.read(item["path"]))
                except (ET.ParseError, KeyError) as exc:
                    violations.append(
                        _violation("xhtml_parse", item["path"], type(exc).__name__)
                    )
                    continue
                roots[item["path"]] = root
                ids = [node.attrib["id"] for node in root.iter() if node.attrib.get("id")]
                duplicates = [value for value, count in Counter(ids).items() if count > 1]
                for duplicate in duplicates:
                    violations.append(
                        _violation("duplicate_id", item["path"], duplicate)
                    )
                ids_by_document[item["path"]] = set(ids)

            for document, root in roots.items():
                for node in root.iter():
                    for attribute in ("href", "src"):
                        value = node.attrib.get(attribute)
                        if not value:
                            continue
                        parsed = urlsplit(value)
                        if parsed.scheme or parsed.netloc:
                            continue
                        target, fragment = _resolved_reference(document, value)
                        referenced_resources.add(target)
                        if target not in names:
                            violations.append(
                                _violation("missing_reference", document, value)
                            )
                            continue
                        if fragment and fragment not in ids_by_document.get(target, set()):
                            violations.append(
                                _violation("missing_fragment", document, value)
                            )

            for record in image_manifest["images"]:
                if record.get("policy") != "original_plus_companion":
                    continue
                companion_path = companion_epub_path(context["opf_path"], record)
                if companion_path not in names:
                    violations.append(
                        _violation("localized_asset_missing", companion_path, "not packaged")
                    )
                if companion_path not in referenced_resources:
                    violations.append(
                        _violation("localized_asset_unreferenced", companion_path, "not used by XHTML")
                    )

        return {
            "status": "pass" if not violations else "error",
            "passed": not violations,
            "schema_version": 1,
            "output_name": output.name,
            "output_sha256": preflight["source_sha256"],
            "source_sha256": source_preflight["source_sha256"],
            "spine_items": len(context["spine"]),
            "source_images": len(source_images),
            "violations": violations,
        }
    except Exception as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return {
            "status": "error",
            "passed": False,
            "schema_version": 1,
            "output_name": output.name,
            "violations": [
                _violation("validation_error", output.name, f"{type(exc).__name__}: {exc}")
            ],
        }
