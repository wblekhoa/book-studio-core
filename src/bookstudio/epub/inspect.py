"""Generic, privacy-conscious EPUB structure inspection."""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..errors import BookStudioError
from .archive import ArchiveLimits, DEFAULT_LIMITS, preflight_archive


CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
TEXT_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _parse_xml(raw: bytes, *, logical_path: str) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise _fail(
            "EPUB_XML_INVALID",
            f"Invalid XML in EPUB member {logical_path}: {exc}",
            "Repair the EPUB XML before continuing.",
        ) from exc


def package_context(archive: zipfile.ZipFile) -> dict[str, Any]:
    names = set(archive.namelist())
    container_path = "META-INF/container.xml"
    if container_path not in names:
        raise _fail(
            "EPUB_CONTAINER_MISSING",
            "EPUB is missing META-INF/container.xml.",
            "Provide a valid EPUB with a container document.",
        )
    container = _parse_xml(archive.read(container_path), logical_path=container_path)
    rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
    opf_path = rootfile.attrib.get("full-path") if rootfile is not None else None
    if not opf_path:
        raise _fail(
            "EPUB_ROOTFILE_MISSING",
            "EPUB container does not declare an OPF rootfile.",
            "Repair META-INF/container.xml and declare one package rootfile.",
        )
    opf_path = posixpath.normpath(opf_path)
    if opf_path not in names:
        raise _fail(
            "EPUB_PACKAGE_MISSING",
            f"Declared OPF package is missing: {opf_path}",
            "Add the declared package document or repair container.xml.",
        )
    package = _parse_xml(archive.read(opf_path), logical_path=opf_path)
    opf_dir = posixpath.dirname(opf_path)

    manifest: dict[str, dict[str, str]] = {}
    for item in package.findall(f".//{{{OPF_NS}}}manifest/{{{OPF_NS}}}item"):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if not item_id or not href:
            continue
        logical_path = posixpath.normpath(posixpath.join(opf_dir, href))
        manifest[item_id] = {
            "id": item_id,
            "href": href,
            "path": logical_path,
            "media_type": item.attrib.get("media-type", ""),
            "properties": item.attrib.get("properties", ""),
        }

    spine: list[dict[str, Any]] = []
    for spine_index, itemref in enumerate(
        package.findall(f".//{{{OPF_NS}}}spine/{{{OPF_NS}}}itemref")
    ):
        idref = itemref.attrib.get("idref", "")
        item = manifest.get(idref)
        if item is None:
            raise _fail(
                "EPUB_SPINE_ITEM_MISSING",
                f"Spine references an unknown manifest id: {idref!r}",
                "Repair the OPF manifest/spine relationship.",
            )
        if item["path"] not in names:
            raise _fail(
                "EPUB_RESOURCE_MISSING",
                f"Manifest resource is missing: {item['path']}",
                "Add the missing EPUB resource or repair its manifest href.",
            )
        spine.append({"spine_index": spine_index, "idref": idref, **item})

    return {
        "opf_path": opf_path,
        "package": package,
        "manifest": manifest,
        "spine": spine,
    }


def _metadata(package: ET.Element) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key in ("title", "creator", "language", "publisher", "date", "identifier"):
        values = [
            clean_text(node.text)
            for node in package.findall(f".//{{{DC_NS}}}{key}")
            if clean_text(node.text)
        ]
        result[key] = values[:5] if key == "identifier" else values
    return result


def _visible_text(root: ET.Element) -> str:
    ignored = {"script", "style"}
    parts: list[str] = []
    for node in root.iter():
        if local_name(node.tag) in ignored:
            continue
        if clean_text(node.text):
            parts.append(clean_text(node.text))
        if clean_text(node.tail):
            parts.append(clean_text(node.tail))
    return " ".join(parts)


def _inline_image_count(root: ET.Element) -> int:
    nodes = list(root.iter())
    count = sum(1 for node in nodes if local_name(node.tag) in {"img", "image"})
    for node in nodes:
        if local_name(node.tag) != "svg":
            continue
        if not any(local_name(descendant.tag) == "image" for descendant in node.iter()):
            count += 1
    return count


def inspect_epub(
    path: Path, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    preflight = preflight_archive(path, limits)
    source = path.expanduser().resolve()
    with zipfile.ZipFile(source, "r") as archive:
        context = package_context(archive)
        tag_counts: Counter[str] = Counter()
        class_counts: Counter[str] = Counter()
        text_files: list[dict[str, Any]] = []
        total_words = 0
        total_chars = 0
        total_blocks = 0
        block_tags = {"p", "li", "h1", "h2", "h3", "h4", "blockquote"}

        for item in context["spine"]:
            if item["media_type"] not in TEXT_MEDIA_TYPES:
                continue
            raw = archive.read(item["path"])
            root = _parse_xml(raw, logical_path=item["path"])
            for node in root.iter():
                tag_counts[local_name(node.tag)] += 1
                class_counts.update(node.attrib.get("class", "").split())
            text = _visible_text(root)
            words = re.findall(r"[^\W_]+(?:[-'][^\W_]+)?", text, flags=re.UNICODE)
            blocks = sum(1 for node in root.iter() if local_name(node.tag) in block_tags)
            images = _inline_image_count(root)
            title_node = next(
                (node for node in root.iter() if local_name(node.tag) == "title"), None
            )
            total_words += len(words)
            total_chars += len(text)
            total_blocks += blocks
            text_files.append(
                {
                    "spine_index": item["spine_index"],
                    "idref": item["idref"],
                    "source_path": item["path"],
                    "title": clean_text(title_node.text if title_node is not None else ""),
                    "size_bytes": len(raw),
                    "chars": len(text),
                    "approx_words": len(words),
                    "blocks": blocks,
                    "images": images,
                }
            )

        media_types = Counter(
            item["media_type"] for item in context["manifest"].values()
        )
        image_resources = sum(
            count for media_type, count in media_types.items() if media_type.startswith("image/")
        )
        package: ET.Element = context["package"]
        return {
            "status": "pass",
            "schema_version": 1,
            "source": {
                "name": preflight["source_name"],
                "sha256": preflight["source_sha256"],
                "size_bytes": source.stat().st_size,
            },
            "zip_entries": preflight["entries"],
            "first_zip_entry": archive.namelist()[0] if archive.namelist() else None,
            "has_mimetype": "mimetype" in archive.namelist(),
            "has_encryption_xml": "META-INF/encryption.xml" in archive.namelist(),
            "opf_rootfile": context["opf_path"],
            "epub_version": package.attrib.get("version"),
            "metadata": _metadata(package),
            "manifest_items": len(context["manifest"]),
            "spine_items": len(context["spine"]),
            "media_types": dict(sorted(media_types.items())),
            "image_resources": image_resources,
            "text": {
                "files": text_files,
                "total_chars": total_chars,
                "approx_words": total_words,
                "translation_blocks": total_blocks,
            },
            "top_tags": tag_counts.most_common(20),
            "top_classes": class_counts.most_common(30),
        }
