#!/usr/bin/env python3
"""Build a bilingual or Vietnamese-only EPUB from translated block JSON files.

The script is intentionally conservative:
- never modifies the source EPUB in place
- applies only translations present in JSON cache files
- preserves original source blocks and inserts Vietnamese sibling blocks
- can replace source blocks for a Vietnamese-only edition
- repacks EPUB with mimetype first and uncompressed
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import posixpath
import re
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XML_NS = "http://www.w3.org/XML/1998/namespace"
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote"}
EPUB_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)

ET.register_namespace("", XHTML_NS)
ET.register_namespace("epub", EPUB_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("opf", OPF_NS)


def write_epub_entry(
    archive: zipfile.ZipFile,
    name: str,
    data: bytes,
    *,
    compress_type: int,
) -> None:
    info = zipfile.ZipInfo(name, date_time=EPUB_ZIP_DATETIME)
    info.compress_type = compress_type
    info.create_system = 0
    info.external_attr = 0
    archive.writestr(info, data)


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def clean_text(value: str) -> str:
    return " ".join(value.split())


def class_with(existing: str | None, class_name: str) -> str:
    classes = (existing or "").split()
    if class_name not in classes:
        classes.append(class_name)
    return " ".join(classes)


def class_without(existing: str | None, class_name: str) -> str:
    return " ".join(cls for cls in (existing or "").split() if cls != class_name)


TranslationEntry = dict[str, str | None]
ImageCompanion = dict[str, str]
MarketContext = dict[str, Any]


def load_translations(translated_dir: Path) -> dict[str, dict[int, TranslationEntry]]:
    translations: dict[str, dict[int, TranslationEntry]] = {}
    for path in sorted(translated_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_path = data.get("source_path")
        blocks = data.get("blocks")
        if not source_path or not isinstance(blocks, list):
            continue
        values: dict[int, TranslationEntry] = {}
        for fallback_index, block in enumerate(blocks):
            translation = block.get("translation") if isinstance(block, dict) else None
            if not isinstance(translation, str) or not translation.strip():
                raise ValueError(f"Missing translation in {path}")
            block_index = block.get("block_index") if isinstance(block, dict) else None
            if block_index is None:
                block_index = fallback_index
            if not isinstance(block_index, int) or block_index < 0:
                raise ValueError(f"Invalid block_index in {path}: {block_index}")
            if block_index in values:
                raise ValueError(f"Duplicate block_index in {path}: {block_index}")
            explanation = block.get("explanation") if isinstance(block, dict) else None
            if explanation is not None and (not isinstance(explanation, str) or not explanation.strip()):
                raise ValueError(f"Invalid explanation in {path}")
            translation_xhtml = block.get("translation_xhtml") if isinstance(block, dict) else None
            if translation_xhtml is not None and (
                not isinstance(translation_xhtml, str) or not translation_xhtml.strip()
            ):
                raise ValueError(f"Invalid translation_xhtml in {path}")
            values[block_index] = {
                "translation": translation.strip(),
                "explanation": explanation.strip() if isinstance(explanation, str) else None,
                "translation_xhtml": translation_xhtml.strip() if isinstance(translation_xhtml, str) else None,
            }
        if source_path not in translations:
            translations[source_path] = {}
        duplicate_indices = sorted(set(translations[source_path]) & set(values))
        if duplicate_indices:
            raise ValueError(
                f"Duplicate translation indices for {source_path} in {path}: {duplicate_indices[:10]}"
            )
        translations[source_path].update(values)
    return translations


def load_image_annotations(translated_dir: Path) -> dict[str, dict[str, str]]:
    annotations: dict[str, dict[str, str]] = {}
    for path in sorted(translated_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_path = data.get("source_path")
        values = data.get("image_annotations", [])
        if not source_path or not values:
            continue
        if not isinstance(values, list):
            raise ValueError(f"Invalid image_annotations in {path}")
        by_src = annotations.setdefault(source_path, {})
        for item in values:
            image_src = item.get("image_src") if isinstance(item, dict) else None
            text = item.get("text") if isinstance(item, dict) else None
            if not isinstance(image_src, str) or not image_src.strip():
                raise ValueError(f"Invalid image_src in {path}")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Invalid image annotation text in {path}: {image_src}")
            image_src = image_src.strip()
            if image_src in by_src:
                raise ValueError(f"Duplicate image annotation in {path}: {image_src}")
            by_src[image_src] = text.strip()
    return annotations


def load_image_companions(
    translated_dir: Path,
) -> tuple[dict[str, dict[str, ImageCompanion]], dict[str, Path]]:
    companions: dict[str, dict[str, ImageCompanion]] = {}
    assets: dict[str, Path] = {}
    for path in sorted(translated_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_path = data.get("source_path")
        values = data.get("image_companions", [])
        if not source_path or not values:
            continue
        if not isinstance(values, list):
            raise ValueError(f"Invalid image_companions in {path}")
        by_src = companions.setdefault(source_path, {})
        for item in values:
            if not isinstance(item, dict):
                raise ValueError(f"Invalid image companion in {path}")
            original_src = item.get("image_src")
            asset_value = item.get("asset_path")
            epub_href = item.get("epub_href")
            alt = item.get("alt")
            if not all(isinstance(value, str) and value.strip() for value in (original_src, asset_value, epub_href, alt)):
                raise ValueError(f"Incomplete image companion in {path}: {item}")
            original_src = original_src.strip()
            epub_href = posixpath.normpath(epub_href.strip())
            if epub_href.startswith("../") or epub_href.startswith("/"):
                raise ValueError(f"Image companion epub_href must be OPF-relative: {epub_href}")
            if original_src in by_src:
                raise ValueError(f"Duplicate image companion in {path}: {original_src}")
            asset_path = Path(asset_value.strip())
            if not asset_path.is_absolute():
                asset_path = (path.parent / asset_path).resolve()
            if not asset_path.is_file():
                raise ValueError(f"Image companion asset missing: {asset_path}")
            prior_asset = assets.get(epub_href)
            if prior_asset is not None and prior_asset != asset_path:
                raise ValueError(f"Conflicting image companion assets for {epub_href}")
            assets[epub_href] = asset_path
            rendered_src = posixpath.relpath(epub_href, posixpath.dirname(source_path))
            by_src[original_src] = {
                "image_src": rendered_src,
                "epub_href": epub_href,
                "alt": alt.strip(),
            }
    return companions, assets


def image_dimensions(data: bytes) -> tuple[int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        offset = 2
        start_of_frame_markers = {
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
            segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
            if segment_length < 2 or offset + segment_length > len(data):
                break
            if marker in start_of_frame_markers and segment_length >= 7:
                height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
                return width, height
            offset += segment_length
    raise ValueError("Unsupported image data for dimension validation")


def validate_companion_dimensions(
    archive: zipfile.ZipFile,
    companions: dict[str, dict[str, ImageCompanion]],
    assets: dict[str, Path],
) -> int:
    matches = 0
    archive_names = set(archive.namelist())
    for source_path, by_src in companions.items():
        for original_src, companion in by_src.items():
            source_image_path = posixpath.normpath(
                posixpath.join(posixpath.dirname(source_path), original_src)
            )
            if source_image_path not in archive_names:
                raise ValueError(f"Image companion source asset missing: {source_image_path}")
            epub_href = companion["epub_href"]
            source_size = image_dimensions(archive.read(source_image_path))
            companion_size = image_dimensions(assets[epub_href].read_bytes())
            if source_size != companion_size:
                raise ValueError(
                    "Image companion dimensions do not match source: "
                    f"{source_image_path} {source_size[0]}x{source_size[1]} vs "
                    f"{epub_href} {companion_size[0]}x{companion_size[1]}"
                )
            matches += 1
    return matches


def load_market_contexts(
    translated_dir: Path,
) -> dict[str, dict[int, list[MarketContext]]]:
    contexts: dict[str, dict[int, list[MarketContext]]] = {}
    for path in sorted(translated_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_path = data.get("source_path")
        values = data.get("market_contexts", [])
        if not source_path or not values:
            continue
        if not isinstance(values, list):
            raise ValueError(f"Invalid market_contexts in {path}")
        by_anchor = contexts.setdefault(source_path, {})
        for item in values:
            if not isinstance(item, dict):
                raise ValueError(f"Invalid market context in {path}")
            anchor = item.get("after_block_index")
            title = item.get("title") or "Góc nhìn Việt Nam"
            paragraphs = item.get("paragraphs")
            if not isinstance(anchor, int) or anchor < 0:
                raise ValueError(f"Invalid market context anchor in {path}: {anchor}")
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"Invalid market context title in {path}: {anchor}")
            if not isinstance(paragraphs, list) or not paragraphs:
                raise ValueError(f"Invalid market context paragraphs in {path}: {anchor}")
            if not all(isinstance(paragraph, str) and paragraph.strip() for paragraph in paragraphs):
                raise ValueError(f"Invalid market context paragraph in {path}: {anchor}")
            by_anchor.setdefault(anchor, []).append(
                {
                    "title": title.strip(),
                    "paragraphs": [paragraph.strip() for paragraph in paragraphs],
                }
            )
    return contexts


def media_type_for_image(path: str) -> str:
    suffix = Path(path).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    if suffix not in media_types:
        raise ValueError(f"Unsupported companion image type: {path}")
    return media_types[suffix]


def rootfile_path(container_xml: bytes) -> str:
    root = ET.fromstring(container_xml)
    for elem in root.iter():
        if local_name(elem.tag) == "rootfile" and elem.get("full-path"):
            return elem.get("full-path") or ""
    raise ValueError("EPUB container.xml has no rootfile")


def add_companion_manifest_items(opf_raw: bytes, epub_hrefs: list[str]) -> bytes:
    root = ET.fromstring(opf_raw)
    manifest = next((elem for elem in root.iter() if local_name(elem.tag) == "manifest"), None)
    if manifest is None:
        raise ValueError("OPF has no manifest")
    existing_hrefs = {elem.get("href") for elem in manifest if local_name(elem.tag) == "item"}
    existing_ids = {elem.get("id") for elem in manifest if local_name(elem.tag) == "item"}
    for href in sorted(epub_hrefs):
        if href in existing_hrefs:
            continue
        base_id = "bs-localized-" + re.sub(r"[^a-zA-Z0-9]+", "-", href).strip("-")
        item_id = base_id
        suffix = 2
        while item_id in existing_ids:
            item_id = f"{base_id}-{suffix}"
            suffix += 1
        item = ET.SubElement(manifest, f"{{{OPF_NS}}}item")
        item.set("id", item_id)
        item.set("href", href)
        item.set("media-type", media_type_for_image(href))
        existing_ids.add(item_id)
        existing_hrefs.add(href)
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def localize_package_metadata(opf_raw: bytes, metadata: dict[str, Any]) -> bytes:
    root = ET.fromstring(opf_raw)
    metadata_elem = next((elem for elem in root.iter() if local_name(elem.tag) == "metadata"), None)
    if metadata_elem is None:
        raise ValueError("OPF has no metadata")

    for elem in list(metadata_elem):
        tag = local_name(elem.tag)
        scheme = next(
            (value for key, value in elem.attrib.items() if local_name(key) == "scheme"),
            "",
        )
        name = elem.get("name", "")
        stale = (
            name.startswith("calibre:")
            or (tag == "contributor" and "calibre" in (elem.text or "").lower())
            or (tag == "identifier" and scheme.lower() in {"calibre", "mobi-asin"})
        )
        if stale:
            metadata_elem.remove(elem)

    def set_single(tag: str, value: str) -> None:
        matches = [elem for elem in metadata_elem if local_name(elem.tag) == tag]
        target = matches[0] if matches else ET.SubElement(metadata_elem, f"{{{DC_NS}}}{tag}")
        target.text = value
        for extra in matches[1:]:
            metadata_elem.remove(extra)

    set_single("title", metadata["title"])
    set_single("language", metadata.get("language", "vi"))
    if metadata.get("description"):
        set_single("description", metadata["description"])
    if "subjects" in metadata:
        for elem in list(metadata_elem):
            if local_name(elem.tag) == "subject":
                metadata_elem.remove(elem)
        for subject in metadata["subjects"]:
            subject_elem = ET.SubElement(metadata_elem, f"{{{DC_NS}}}subject")
            subject_elem.text = subject
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def text_without_superscripts(elem: ET.Element) -> str:
    values: list[str] = []

    def walk(node: ET.Element) -> None:
        if local_name(node.tag) == "sup":
            return
        if node.text:
            values.append(node.text)
        for child in list(node):
            walk(child)
            if child.tail:
                values.append(child.tail)

    walk(elem)
    return clean_text("".join(values))


def navigation_label_for_ref(
    content_ref: str,
    documents: dict[str, bytes],
    overrides: dict[str, str],
) -> str | None:
    if content_ref in overrides:
        return overrides[content_ref]
    split = content_ref.split("#", 1)
    document = split[0]
    fragment = split[1] if len(split) == 2 else None
    raw = documents.get(document)
    if raw is None:
        return None
    root = ET.fromstring(raw)
    parent_by_child = {child: parent for parent in root.iter() for child in list(parent)}
    target: ET.Element | None = None
    if fragment:
        target = next((elem for elem in root.iter() if elem.get("id") == fragment), None)
        while target is not None and local_name(target.tag) not in BLOCK_TAGS:
            target = parent_by_child.get(target)
    else:
        target = next(
            (
                elem
                for elem in root.iter()
                if local_name(elem.tag) in {"h1", "h2", "h3", "h4"}
                and text_without_superscripts(elem)
            ),
            None,
        )
        if target is None:
            target = next(
                (
                    elem
                    for elem in root.iter()
                    if local_name(elem.tag) in BLOCK_TAGS and text_without_superscripts(elem)
                ),
                None,
            )
    return text_without_superscripts(target) if target is not None else None


def localize_xhtml_document_metadata(raw: bytes, title: str) -> bytes:
    root = ET.fromstring(raw)
    root.set("lang", "vi")
    root.set(f"{{{XML_NS}}}lang", "vi")
    head = next((elem for elem in root.iter() if local_name(elem.tag) == "head"), None)
    if head is not None:
        title_elem = next((elem for elem in head if local_name(elem.tag) == "title"), None)
        if title_elem is None:
            title_elem = ET.SubElement(head, f"{{{XHTML_NS}}}title")
        title_elem.text = title
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def localize_ncx(
    raw: bytes,
    documents: dict[str, bytes],
    metadata: dict[str, Any],
) -> tuple[bytes, int]:
    root = ET.fromstring(raw)
    root.set(f"{{{XML_NS}}}lang", metadata.get("language", "vi"))
    doc_title = next((elem for elem in root.iter() if local_name(elem.tag) == "docTitle"), None)
    if doc_title is not None:
        title_text = next((elem for elem in doc_title.iter() if local_name(elem.tag) == "text"), None)
        if title_text is not None:
            title_text.text = metadata["title"]
    overrides = metadata.get("navigation_overrides", {})
    localized = 0
    for nav_point in (elem for elem in root.iter() if local_name(elem.tag) == "navPoint"):
        content = next((elem for elem in nav_point if local_name(elem.tag) == "content"), None)
        nav_label = next((elem for elem in nav_point if local_name(elem.tag) == "navLabel"), None)
        label_text = (
            next((elem for elem in nav_label.iter() if local_name(elem.tag) == "text"), None)
            if nav_label is not None
            else None
        )
        if content is None or label_text is None or not content.get("src"):
            continue
        label = navigation_label_for_ref(content.get("src", ""), documents, overrides)
        if label:
            label_text.text = label
            localized += 1
    return ET.tostring(root, encoding="utf-8", xml_declaration=False), localized


def find_blocks(root: ET.Element) -> list[ET.Element]:
    blocks: list[ET.Element] = []
    for elem in root.iter():
        tag = local_name(elem.tag)
        if tag not in BLOCK_TAGS:
            continue
        text = clean_text("".join(elem.itertext()))
        if text:
            blocks.append(elem)
    return blocks


def make_translation_element(source: ET.Element, translation: str) -> ET.Element:
    elem = ET.Element(source.tag)
    # Preserve non-unique styling attributes only. Do not duplicate ids/epub:type.
    for key, value in source.attrib.items():
        if local_name(key) in {"id", "type"}:
            continue
        if local_name(key) == "class":
            value = class_without(value, "bs-source")
        elem.set(key, value)
    elem.set("class", class_with(elem.attrib.get("class"), "bs-translation"))
    elem.set("lang", "vi")
    elem.set("{http://www.w3.org/XML/1998/namespace}lang", "vi")
    elem.text = translation
    return elem


def make_explanation_element(explanation: str) -> ET.Element:
    elem = ET.Element(f"{{{XHTML_NS}}}p")
    elem.set("class", "bs-explanation")
    elem.set("lang", "vi")
    elem.set("{http://www.w3.org/XML/1998/namespace}lang", "vi")
    elem.text = f"Nói dễ hiểu: {explanation}"
    return elem


def make_image_annotation_element(annotation: str) -> ET.Element:
    elem = ET.Element(f"{{{XHTML_NS}}}p")
    elem.set("class", "bs-image-annotation")
    elem.set("lang", "vi")
    elem.set("{http://www.w3.org/XML/1998/namespace}lang", "vi")
    elem.text = annotation
    return elem


def make_image_companion_element(companion: ImageCompanion) -> ET.Element:
    container = ET.Element(f"{{{XHTML_NS}}}div")
    container.set("class", "image bs-image-companion")
    image = ET.SubElement(container, f"{{{XHTML_NS}}}img")
    image.set("src", companion["image_src"])
    image.set("alt", companion["alt"])
    image.set("class", "calibre3")
    return container


def make_localized_image_block(
    companion: ImageCompanion,
    annotation: str | None,
) -> ET.Element:
    container = ET.Element(f"{{{XHTML_NS}}}div")
    container.set("class", "bs-image-localized-block")
    container.set("lang", "vi")
    container.set("{http://www.w3.org/XML/1998/namespace}lang", "vi")

    companion_elem = make_image_companion_element(companion)
    companion_elem.tail = "\n"
    container.append(companion_elem)

    if annotation:
        annotation_elem = make_image_annotation_element(annotation)
        annotation_elem.tail = "\n"
        container.append(annotation_elem)

    return container


def make_market_context_element(context: MarketContext) -> ET.Element:
    container = ET.Element(f"{{{XHTML_NS}}}div")
    container.set("class", "bs-market-context")
    container.set("lang", "vi")
    container.set("{http://www.w3.org/XML/1998/namespace}lang", "vi")

    title = ET.SubElement(container, f"{{{XHTML_NS}}}p")
    title.set("class", "bs-market-context-title")
    title.text = str(context["title"])
    title.tail = "\n"

    for paragraph in context["paragraphs"]:
        body = ET.SubElement(container, f"{{{XHTML_NS}}}p")
        body.set("class", "bs-market-context-body")
        body.text = str(paragraph)
        body.tail = "\n"

    return container


def annotation_image_src(elem: ET.Element) -> str | None:
    if local_name(elem.tag) != "div" or "image" not in (elem.get("class") or "").split():
        return None
    for descendant in elem.iter():
        if local_name(descendant.tag) == "img" and descendant.get("src"):
            return descendant.get("src")
    return None


def replace_inner_xhtml(elem: ET.Element, fragment: str) -> None:
    wrapper = ET.fromstring(f'<wrapper xmlns="{XHTML_NS}">{fragment}</wrapper>')
    elem.text = wrapper.text
    elem[:] = [copy.deepcopy(child) for child in list(wrapper)]


def source_anchor_artifacts(elem: ET.Element) -> list[tuple[str, ET.Element, set[str]]]:
    """Capture link targets that must survive replacing a translated block.

    Page anchors and footnote backlinks belong at the start of their block. A
    footnote reference nested in ``sup`` belongs at the end. Textual cross-links
    are deliberately left to ``translation_xhtml`` so English link text is not
    reintroduced into the Vietnamese-only edition.
    """

    artifacts: list[tuple[str, ET.Element, set[str]]] = []

    def walk(parent: ET.Element) -> None:
        for child in list(parent):
            if local_name(child.tag) == "a" and child.get("id"):
                artifact = copy.deepcopy(child)
                artifact.tail = None
                artifacts.append(("prefix", artifact, {child.get("id") or ""}))
                continue
            if local_name(child.tag) == "sup":
                ids = {
                    descendant.get("id") or ""
                    for descendant in child.iter()
                    if local_name(descendant.tag) == "a" and descendant.get("id")
                }
                if ids:
                    artifact = copy.deepcopy(child)
                    artifact.tail = None
                    artifacts.append(("suffix", artifact, ids))
                    continue
            walk(child)

    walk(elem)
    return artifacts


def restore_source_anchor_artifacts(
    elem: ET.Element,
    artifacts: list[tuple[str, ET.Element, set[str]]],
) -> None:
    existing_ids = {
        descendant.get("id") or ""
        for descendant in elem.iter()
        if descendant.get("id")
    }
    prefixes: list[ET.Element] = []
    suffixes: list[ET.Element] = []
    for placement, artifact, ids in artifacts:
        if ids <= existing_ids:
            continue
        if placement == "prefix":
            prefixes.append(copy.deepcopy(artifact))
        else:
            suffixes.append(copy.deepcopy(artifact))
        existing_ids.update(ids)

    if prefixes:
        leading_text = elem.text
        elem.text = None
        for artifact in prefixes:
            artifact.tail = None
        separator = " " if leading_text and clean_text("".join(prefixes[-1].itertext())) else ""
        prefixes[-1].tail = separator + (leading_text or "")
        elem[:] = prefixes + list(elem)
    for artifact in suffixes:
        artifact.tail = None
        elem.append(artifact)


def without_duplicate_footnote_markers(
    translation: str,
    artifacts: list[tuple[str, ET.Element, set[str]]],
) -> str:
    superscript_digits = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    result = translation
    for placement, artifact, _ in artifacts:
        marker = clean_text("".join(artifact.itertext()))
        if not marker.isdigit():
            continue
        variants = sorted({marker, marker.translate(superscript_digits)}, key=len, reverse=True)
        pattern = "(?:" + "|".join(re.escape(value) for value in variants) + ")"
        if placement == "prefix":
            result = re.sub(rf"^\s*{pattern}\s*", "", result, count=1)
        else:
            result = re.sub(rf"\s*{pattern}\s*$", "", result, count=1)
    return result


def replace_with_plain_translation(elem: ET.Element, translation: str) -> None:
    prefix: list[ET.Element] = []
    suffix: list[ET.Element] = []
    for child in list(elem):
        tag = local_name(child.tag)
        text = clean_text("".join(child.itertext()))
        if tag == "a" and (child.get("id") or child.get("href")) and not text:
            prefix.append(copy.deepcopy(child))
        elif tag == "a" and child.get("href") and local_name(elem.tag) == "p" and "footnote" in elem.get("class", ""):
            prefix.append(copy.deepcopy(child))
        elif not text and any(local_name(desc.tag) == "img" for desc in child.iter()):
            prefix.append(copy.deepcopy(child))
        elif tag == "sup" and any(local_name(desc.tag) == "a" for desc in child.iter()):
            suffix.append(copy.deepcopy(child))

    elem.text = None if prefix else translation
    elem[:] = []
    for child in prefix:
        child.tail = ""
        elem.append(child)
    if prefix:
        separator = " " if clean_text("".join(prefix[-1].itertext())) else ""
        prefix[-1].tail = separator + translation
    for child in suffix:
        child.tail = None
        elem.append(child)


def replace_with_vietnamese(elem: ET.Element, entry: TranslationEntry) -> None:
    translation = entry.get("translation") or ""
    translation_xhtml = entry.get("translation_xhtml")
    anchor_artifacts = source_anchor_artifacts(elem)
    if translation_xhtml:
        replace_inner_xhtml(elem, translation_xhtml)
    else:
        replace_with_plain_translation(
            elem,
            without_duplicate_footnote_markers(translation, anchor_artifacts),
        )
    restore_source_anchor_artifacts(elem, anchor_artifacts)
    elem.set("lang", "vi")
    elem.set("{http://www.w3.org/XML/1998/namespace}lang", "vi")
    elem.set("class", class_without(elem.attrib.get("class"), "bs-source"))


def apply_translations(
    raw: bytes,
    translations: dict[int, TranslationEntry],
    *,
    allow_partial: bool,
    mode: str = "bilingual",
    image_annotations: dict[str, str] | None = None,
    image_companions: dict[str, ImageCompanion] | None = None,
    market_contexts: dict[int, list[MarketContext]] | None = None,
) -> tuple[bytes, int, int]:
    if mode not in {"bilingual", "vi_only"}:
        raise ValueError(f"Unsupported output mode: {mode}")
    root = ET.fromstring(raw)
    blocks = find_blocks(root)
    invalid_indices = sorted(index for index in translations if index >= len(blocks))
    if invalid_indices:
        raise ValueError(f"Translation indices outside XHTML block range: {invalid_indices[:10]}")
    if not allow_partial:
        missing_indices = sorted(set(range(len(blocks))) - set(translations))
        if missing_indices:
            raise ValueError(
                f"Block count mismatch: XHTML has {len(blocks)}, translations have {len(translations)}; "
                f"missing indices start with {missing_indices[:10]}"
            )

    block_to_translation = {id(block): translations[index] for index, block in enumerate(blocks) if index in translations}
    block_index_by_id = {id(block): index for index, block in enumerate(blocks)}
    applied = 0
    explanations_applied = 0
    image_annotations = image_annotations or {}
    image_companions = image_companions or {}
    market_contexts = market_contexts or {}
    invalid_market_anchors = sorted(anchor for anchor in market_contexts if anchor >= len(blocks))
    if invalid_market_anchors:
        raise ValueError(f"Market context anchors outside XHTML block range: {invalid_market_anchors[:10]}")
    applied_image_annotations: set[str] = set()
    applied_image_companions: set[str] = set()

    def rewrite_children(parent: ET.Element) -> None:
        nonlocal applied, explanations_applied
        new_children: list[ET.Element] = []
        for child in list(parent):
            rewrite_children(child)
            image_src = annotation_image_src(child)
            companion = image_companions.get(image_src or "")
            new_children.append(child)
            if companion is not None:
                child.tail = "\n"
                localized_block = make_localized_image_block(
                    companion,
                    image_annotations.get(image_src or ""),
                )
                localized_block.tail = "\n"
                new_children.append(localized_block)
                applied_image_companions.add(image_src or "")
                if image_src in image_annotations:
                    applied_image_annotations.add(image_src)
            elif image_src in image_annotations:
                annotation_elem = make_image_annotation_element(image_annotations[image_src])
                annotation_elem.tail = child.tail
                child.tail = "\n"
                new_children.append(annotation_elem)
                applied_image_annotations.add(image_src)
            entry = block_to_translation.get(id(child))
            if entry is not None:
                if mode == "bilingual":
                    child.set("class", class_with(child.attrib.get("class"), "bs-source"))
                    child.set("lang", "en")
                    child.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
                    translation_elem = make_translation_element(child, entry["translation"] or "")
                    translation_elem.tail = child.tail
                    child.tail = "\n"
                    new_children.append(translation_elem)
                else:
                    replace_with_vietnamese(child, entry)
                explanation = entry.get("explanation")
                if explanation:
                    explanation_elem = make_explanation_element(explanation)
                    explanation_elem.tail = child.tail
                    child.tail = "\n"
                    new_children.append(explanation_elem)
                    explanations_applied += 1
                applied += 1
            block_index = block_index_by_id.get(id(child))
            if block_index in market_contexts:
                tail_owner = new_children[-1]
                for context in market_contexts[block_index]:
                    context_elem = make_market_context_element(context)
                    context_elem.tail = tail_owner.tail
                    tail_owner.tail = "\n"
                    new_children.append(context_elem)
                    tail_owner = context_elem
        parent[:] = new_children

    rewrite_children(root)
    missing_image_annotations = sorted(set(image_annotations) - applied_image_annotations)
    if missing_image_annotations:
        raise ValueError(f"Image annotations did not match source images: {missing_image_annotations[:10]}")
    missing_image_companions = sorted(set(image_companions) - applied_image_companions)
    if missing_image_companions:
        raise ValueError(f"Image companions did not match source images: {missing_image_companions[:10]}")
    return ET.tostring(root, encoding="utf-8", xml_declaration=False), applied, explanations_applied


BILINGUAL_CSS = """

/* Book Studio bilingual EPUB styles */
.bs-source {
  color: #66717f;
  font-size: 0.92em;
  line-height: 1.5;
  margin-bottom: 0.25em;
}

.bs-translation {
  color: #172033;
  font-size: 1em;
  line-height: 1.65;
  margin-top: 0;
  margin-bottom: 1em;
}

.bs-explanation {
  background: #f5f0e6;
  border-left: 0.18em solid #b08b57;
  color: #273142;
  font-size: 0.95em;
  line-height: 1.6;
  margin-top: -0.35em;
  margin-bottom: 1.1em;
  padding: 0.7em 0.9em;
}

h1.bs-translation,
h2.bs-translation,
h3.bs-translation {
  margin-top: 0.25em;
}

.figcaption.bs-source,
.figcaption.bs-translation,
p.figcaption.bs-source,
p.figcaption.bs-translation {
  font-size: 0.9em;
}
"""

VI_ONLY_CSS = """

/* Book Studio Vietnamese-only EPUB styles */
img.calibre3 {
  height: auto;
  max-width: 100%;
}

.bs-image-annotation {
  font-size: 0.82em;
  font-style: italic;
  line-height: 1.45;
  margin: 0.3em 1em 1.1em;
  opacity: 0.78;
}

.bs-image-companion {
  margin-top: 0;
}

.bs-image-localized-block {
  background-color: #f1f1f1;
  -webkit-column-break-inside: avoid;
  break-inside: avoid;
  margin: 1.1em 0 1.25em;
  page-break-inside: avoid;
  padding: 0.65em 0 0.75em;
}

.bs-image-localized-block .bs-image-companion {
  margin: 0;
}

.bs-image-localized-block .bs-image-annotation {
  margin: 0.45em 0.35em 0.1em;
}

.bs-market-context {
  background-color: #eef5f3;
  border-left: 0.22em solid #3f7f75;
  margin: 1em 0 1.25em;
  padding: 0.72em 0.85em 0.78em;
}

.bs-market-context-title {
  color: #285f57;
  font-size: 0.86em;
  font-weight: bold;
  letter-spacing: 0.02em;
  margin: 0 0 0.45em;
}

.bs-market-context-body {
  font-size: 0.92em;
  line-height: 1.5;
  margin: 0.35em 0 0;
}
"""


def stylesheet_for_mode(stylesheet: str, *, mode: str) -> str:
    if mode == "bilingual" and "Book Studio bilingual EPUB styles" not in stylesheet:
        return stylesheet + BILINGUAL_CSS
    if mode == "vi_only" and "Book Studio Vietnamese-only EPUB styles" not in stylesheet:
        return stylesheet + VI_ONLY_CSS
    return stylesheet


def build_epub(
    source_epub: Path,
    translated_dir: Path,
    output_epub: Path,
    *,
    allow_partial: bool = False,
    mode: str = "bilingual",
    metadata_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"bilingual", "vi_only"}:
        raise ValueError(f"Unsupported output mode: {mode}")
    translations = load_translations(translated_dir)
    image_annotations = load_image_annotations(translated_dir)
    image_companions, companion_assets = load_image_companions(translated_dir)
    market_contexts = load_market_contexts(translated_dir)
    output_epub.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "source_epub": str(source_epub),
        "output_epub": str(output_epub),
        "translated_files": sorted(translations),
        "applied_blocks": 0,
        "explanation_blocks": 0,
        "image_annotation_blocks": sum(len(values) for values in image_annotations.values()),
        "image_companion_blocks": sum(len(values) for values in image_companions.values()),
        "market_context_blocks": sum(
            len(contexts)
            for anchors in market_contexts.values()
            for contexts in anchors.values()
        ),
        "companion_assets": sorted(companion_assets),
        "image_companion_dimension_matches": 0,
        "coverage_files": len(translations),
        "allow_partial": allow_partial,
        "mode": mode,
        "metadata_localized": bool(metadata_config),
        "navigation_labels_localized": 0,
    }

    with zipfile.ZipFile(source_epub, "r") as zin:
        names = zin.namelist()
        if "mimetype" not in names:
            raise ValueError("Source EPUB missing mimetype")
        if "META-INF/container.xml" not in names:
            raise ValueError("Source EPUB missing META-INF/container.xml")
        opf_path = rootfile_path(zin.read("META-INF/container.xml"))
        opf_dir = posixpath.dirname(opf_path)
        report["image_companion_dimension_matches"] = validate_companion_dimensions(
            zin,
            image_companions,
            companion_assets,
        )
        processed: dict[str, bytes] = {}
        for name in names:
            if name == "mimetype":
                continue
            data = zin.read(name)
            if name in translations:
                data, applied, explanations_applied = apply_translations(
                    data,
                    translations[name],
                    allow_partial=allow_partial,
                    mode=mode,
                    image_annotations=image_annotations.get(name),
                    image_companions=image_companions.get(name),
                    market_contexts=market_contexts.get(name),
                )
                report["applied_blocks"] += applied
                report["explanation_blocks"] += explanations_applied
            elif name == "OEBPS/styles/stylesheet.css" or name.endswith("/stylesheet.css") or name == "stylesheet.css":
                text = data.decode("utf-8")
                text = stylesheet_for_mode(text, mode=mode)
                data = text.encode("utf-8")
            processed[name] = data

        if companion_assets:
            processed[opf_path] = add_companion_manifest_items(
                processed[opf_path],
                list(companion_assets),
            )

        if metadata_config:
            if mode != "vi_only":
                raise ValueError("Localized metadata is supported only for vi_only mode")
            navigation_overrides = metadata_config.get("navigation_overrides", {})
            for document in sorted(translations):
                label = navigation_label_for_ref(document, processed, navigation_overrides)
                if label:
                    processed[document] = localize_xhtml_document_metadata(processed[document], label)
            for document, title in metadata_config.get("document_title_overrides", {}).items():
                if document in processed:
                    processed[document] = localize_xhtml_document_metadata(processed[document], title)
            ncx_path = next((name for name in names if name.lower().endswith(".ncx")), None)
            if ncx_path is None:
                raise ValueError("Source EPUB has no NCX navigation document")
            processed[ncx_path], localized_labels = localize_ncx(
                processed[ncx_path],
                processed,
                metadata_config,
            )
            report["navigation_labels_localized"] = localized_labels
            processed[opf_path] = localize_package_metadata(
                processed[opf_path],
                metadata_config,
            )

        with zipfile.ZipFile(output_epub, "w") as zout:
            write_epub_entry(
                zout,
                "mimetype",
                zin.read("mimetype"),
                compress_type=zipfile.ZIP_STORED,
            )
            for name in names:
                if name == "mimetype":
                    continue
                write_epub_entry(
                    zout,
                    name,
                    processed[name],
                    compress_type=zipfile.ZIP_DEFLATED,
                )
            for epub_href, asset_path in sorted(companion_assets.items()):
                zip_path = posixpath.normpath(posixpath.join(opf_dir, epub_href))
                if zip_path in names:
                    raise ValueError(f"Companion asset would overwrite source EPUB entry: {zip_path}")
                write_epub_entry(
                    zout,
                    zip_path,
                    asset_path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    report["output_sha256"] = hashlib.sha256(output_epub.read_bytes()).hexdigest()
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build a bilingual or Vietnamese-only EPUB from translated blocks.")
    parser.add_argument("--source", required=True, type=Path, help="Source EPUB path.")
    parser.add_argument("--translated-dir", required=True, type=Path, help="Directory containing translation JSON files.")
    parser.add_argument("--output", required=True, type=Path, help="Output EPUB path.")
    parser.add_argument("--report", type=Path, help="Optional JSON report path.")
    parser.add_argument("--metadata", type=Path, help="Optional Vietnamese package/navigation metadata JSON.")
    parser.add_argument(
        "--mode",
        choices=("bilingual", "vi_only"),
        default="bilingual",
        help="Keep English plus Vietnamese siblings, or replace source text with Vietnamese.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow sparse translation JSON for progress EPUBs; untranslated source blocks are left unchanged.",
    )
    args = parser.parse_args(argv)

    report = build_epub(
        args.source,
        args.translated_dir,
        args.output,
        allow_partial=args.allow_partial,
        mode=args.mode,
        metadata_config=(json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else None),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
