"""Deterministic, source-aligned EPUB construction and finalization."""

from __future__ import annotations

import copy
import hashlib
import mimetypes
import os
import posixpath
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from ..config import ProjectConfig, atomic_write_json
from ..errors import BookStudioError
from ..images.manifest import (
    companion_epub_path,
    companion_file,
    load_image_manifest,
)
from ..pilot import require_full_scope
from ..safety.xhtml import EPUB_NAMESPACE, validate_inline_xhtml
from ..translation.cache import validated_cache_index
from ..translation.coverage import coverage_receipt, target_index
from .edits import apply_edits, load_edits
from .archive import preflight_archive
from .extract import BLOCK_TAGS
from .inspect import DC_NS, OPF_NS, clean_text, local_name, package_context


XHTML_NS = "http://www.w3.org/1999/xhtml"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
BOOKSTUDIO_STYLESHEET = b"""/* Book Studio generated editorial styles */
.bs-localized-image-block {
  box-sizing: border-box;
  break-inside: avoid;
  page-break-inside: avoid;
  margin: 0.65em 0 1em;
  padding: 0.75em 0.9em;
  background-color: rgba(127, 127, 127, 0.08);
  border-radius: 0.35em;
}
.bs-localized-image {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0 auto;
}
.bs-image-annotation {
  margin: 0;
  font-size: 0.82em;
  line-height: 1.45;
  font-style: italic;
  opacity: 0.78;
}
"""
ET.register_namespace("", XHTML_NS)
ET.register_namespace("epub", EPUB_NAMESPACE)


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _classed(element: ET.Element, name: str) -> None:
    classes = element.attrib.get("class", "").split()
    if name not in classes:
        classes.append(name)
    element.attrib["class"] = " ".join(classes)


def _remove_ids(element: ET.Element) -> None:
    for node in element.iter():
        node.attrib.pop("id", None)


def _replace_content(element: ET.Element, entry: dict[str, Any]) -> None:
    for child in list(element):
        element.remove(child)
    element.text = None
    xhtml = entry.get("translation_xhtml")
    if xhtml:
        validate_inline_xhtml(xhtml)
        fragment = ET.fromstring(
            f'<root xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NAMESPACE}">{xhtml}</root>'
        )
        element.text = fragment.text
        for child in list(fragment):
            fragment.remove(child)
            element.append(child)
    else:
        element.text = entry["translation"]


def _source_anchor_artifacts(
    element: ET.Element,
) -> list[tuple[str, ET.Element, set[str]]]:
    artifacts: list[tuple[str, ET.Element, set[str]]] = []

    def structural_copy(source: ET.Element) -> ET.Element:
        artifact = copy.deepcopy(source)
        for descendant in artifact.iter():
            descendant.text = None
            descendant.tail = None
        return artifact

    def walk(parent: ET.Element) -> None:
        for child in list(parent):
            if local_name(child.tag) == "a" and child.attrib.get("id"):
                artifact = structural_copy(child)
                artifacts.append(("prefix", artifact, {child.attrib["id"]}))
                continue
            if local_name(child.tag) == "sup":
                ids = {
                    descendant.attrib["id"]
                    for descendant in child.iter()
                    if local_name(descendant.tag) == "a" and descendant.attrib.get("id")
                }
                if ids:
                    artifact = copy.deepcopy(child)
                    artifact.tail = None
                    artifacts.append(("suffix", artifact, ids))
                    continue
            epub_type = child.attrib.get(f"{{{EPUB_NAMESPACE}}}type", "").split()
            if child.attrib.get("id") or "pagebreak" in epub_type:
                artifact = structural_copy(child)
                ids = {
                    descendant.attrib["id"]
                    for descendant in artifact.iter()
                    if descendant.attrib.get("id")
                }
                artifacts.append(("prefix", artifact, ids))
                continue
            walk(child)

    walk(element)
    return artifacts


def _restore_source_anchor_artifacts(
    element: ET.Element,
    artifacts: list[tuple[str, ET.Element, set[str]]],
) -> None:
    existing_ids = {
        descendant.attrib["id"]
        for descendant in element.iter()
        if descendant.attrib.get("id")
    }
    prefixes: list[ET.Element] = []
    suffixes: list[ET.Element] = []
    for placement, artifact, ids in artifacts:
        if ids and ids <= existing_ids:
            continue
        if placement == "prefix":
            prefixes.append(copy.deepcopy(artifact))
        else:
            suffixes.append(copy.deepcopy(artifact))
        existing_ids.update(ids)

    if prefixes:
        leading_text = element.text
        element.text = None
        prefixes[-1].tail = leading_text or ""
        element[:] = prefixes + list(element)
    for artifact in suffixes:
        element.append(artifact)


def _replace_content_preserving_anchors(
    element: ET.Element, entry: dict[str, Any]
) -> None:
    artifacts = _source_anchor_artifacts(element)
    _replace_content(element, entry)
    _restore_source_anchor_artifacts(element, artifacts)


def _block_nodes(root: ET.Element) -> list[tuple[ET.Element, ET.Element, int, bool]]:
    rows: list[tuple[ET.Element, ET.Element, int, bool]] = []
    block_index = 0

    def walk(parent: ET.Element, element: ET.Element, inside_block: bool) -> None:
        nonlocal block_index
        tag = local_name(element.tag)
        text = clean_text("".join(element.itertext()))
        is_block = tag in BLOCK_TAGS and bool(text)
        if is_block:
            rows.append((parent, element, block_index, not inside_block))
            block_index += 1
        for child in list(element):
            walk(element, child, inside_block or is_block)

    for child in list(root):
        walk(root, child, False)
    return rows


def _editorial_label(
    config: ProjectConfig,
    profile_key: str,
    *,
    vietnamese: str,
    fallback: str,
) -> str:
    override = config.profile.get(profile_key)
    if isinstance(override, str) and override.strip():
        return override.strip()
    if config.target_language.lower().split("-", 1)[0] == "vi":
        return vietnamese
    return fallback


def _market_context_nodes(
    entry: dict[str, Any], config: ProjectConfig
) -> list[ET.Element]:
    values = entry.get("market_contexts")
    if not isinstance(values, list):
        return []
    nodes: list[ET.Element] = []
    for value in values:
        text = value.get("text") if isinstance(value, dict) else value
        if not isinstance(text, str) or not text.strip():
            continue
        block = ET.Element(f"{{{XHTML_NS}}}aside", {"class": "bs-market-context"})
        label = ET.SubElement(block, f"{{{XHTML_NS}}}strong")
        label.text = _editorial_label(
            config,
            "market_context_label",
            vietnamese="Bối cảnh Việt Nam",
            fallback="Market context",
        )
        paragraph = ET.SubElement(block, f"{{{XHTML_NS}}}p")
        paragraph.text = text.strip()
        nodes.append(block)
    return nodes


def _translate_document(
    raw: bytes,
    *,
    source_path: str,
    config: ProjectConfig,
    cache_rows: list[dict[str, Any]],
) -> ET.Element:
    root = ET.fromstring(raw)
    root.attrib["lang"] = config.target_language
    root.attrib[f"{{{XML_NS}}}lang"] = config.target_language
    by_index = {row["block_index"]: row for row in cache_rows}
    nodes = _block_nodes(root)
    for parent, element, block_index, canonical in reversed(nodes):
        entry = by_index.get(block_index)
        if not canonical or entry is None:
            continue
        if config.output_mode == "bilingual":
            _classed(element, "bs-source")
            translated = copy.deepcopy(element)
            _remove_ids(translated)
            _replace_content(translated, entry)
            _classed(translated, "bs-translation")
            position = list(parent).index(element)
            parent.insert(position + 1, translated)
            insertion_anchor = translated
        else:
            _replace_content_preserving_anchors(element, entry)
            _classed(element, "bs-translation")
            insertion_anchor = element
        position = list(parent).index(insertion_anchor)
        for context_node in _market_context_nodes(entry, config):
            position += 1
            parent.insert(position, context_node)
    if config.output_mode != "bilingual":
        title = _document_heading_title(root)
        if title:
            for node in root.iter():
                if local_name(node.tag) == "title":
                    node.text = title
                    node[:] = []
                    break
    return root


def _document_heading_title(root: ET.Element) -> str | None:
    body = next((node for node in root.iter() if local_name(node.tag) == "body"), None)
    if body is None:
        return None
    canonical_blocks = [
        element
        for _, element, _, canonical in _block_nodes(body)
        if canonical
    ]
    if not canonical_blocks:
        return None
    first_tag = local_name(canonical_blocks[0].tag)
    if first_tag not in {"h1", "h2", "h3", "h4"}:
        return None
    parts: list[str] = []
    for element in canonical_blocks:
        if local_name(element.tag) != first_tag:
            break
        text = clean_text("".join(element.itertext()))
        if text:
            parts.append(text)
    return " ".join(parts) or None


def _ensure_stylesheet_link(
    root: ET.Element, *, document_path: str, stylesheet_path: str
) -> None:
    head = next((node for node in root.iter() if local_name(node.tag) == "head"), None)
    if head is None:
        return
    href = posixpath.relpath(stylesheet_path, posixpath.dirname(document_path))
    for node in list(head):
        if local_name(node.tag) == "link" and node.attrib.get("href") == href:
            return
    ET.SubElement(
        head,
        f"{{{XHTML_NS}}}link",
        {"href": href, "rel": "stylesheet", "type": "text/css"},
    )


def _navigation_label(config: ProjectConfig, current: str) -> str:
    return _editorial_label(
        config,
        "navigation_label",
        vietnamese="Mục lục",
        fallback=current or "Contents",
    )


def _localize_navigation_document(
    raw: bytes,
    *,
    config: ProjectConfig,
    document_path: str,
    translated_titles: dict[str, str],
) -> bytes:
    root = ET.fromstring(raw)
    root.attrib["lang"] = config.target_language
    root.attrib[f"{{{XML_NS}}}lang"] = config.target_language
    title_node = next(
        (node for node in root.iter() if local_name(node.tag) == "title"), None
    )
    current_title = clean_text("".join(title_node.itertext())) if title_node is not None else ""
    label = _navigation_label(config, current_title)
    if title_node is not None:
        title_node.text = label
        title_node[:] = []
    for node in root.iter():
        if local_name(node.tag) in {"h1", "h2"}:
            node.text = label
            node[:] = []
            break
    for node in root.iter():
        if local_name(node.tag) != "a":
            continue
        href = node.attrib.get("href")
        if not href:
            continue
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            continue
        raw_path = unquote(parsed.path)
        target = (
            document_path
            if not raw_path
            else posixpath.normpath(
                posixpath.join(posixpath.dirname(document_path), raw_path)
            )
        )
        translated = translated_titles.get(target)
        if translated:
            node.text = translated
            node[:] = []
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _localize_ncx_document(
    raw: bytes,
    *,
    config: ProjectConfig,
    document_path: str,
    translated_titles: dict[str, str],
) -> bytes:
    root = ET.fromstring(raw)
    root.attrib[f"{{{XML_NS}}}lang"] = config.target_language
    for nav_point in root.iter():
        if local_name(nav_point.tag) != "navPoint":
            continue
        content = next(
            (
                node
                for node in nav_point.iter()
                if local_name(node.tag) == "content" and node.attrib.get("src")
            ),
            None,
        )
        if content is None:
            continue
        parsed = urlsplit(content.attrib["src"])
        if parsed.scheme or parsed.netloc:
            continue
        raw_path = unquote(parsed.path)
        target = (
            document_path
            if not raw_path
            else posixpath.normpath(
                posixpath.join(posixpath.dirname(document_path), raw_path)
            )
        )
        translated = translated_titles.get(target)
        if not translated:
            continue
        label = next(
            (node for node in nav_point.iter() if local_name(node.tag) == "navLabel"),
            None,
        )
        if label is None:
            continue
        text_node = next(
            (node for node in label.iter() if local_name(node.tag) == "text"),
            None,
        )
        if text_node is not None:
            text_node.text = translated
            text_node[:] = []
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _insert_image_blocks(
    root: ET.Element,
    *,
    config: ProjectConfig,
    document_path: str,
    opf_path: str,
    image_records: list[dict[str, Any]],
) -> None:
    parent_of = {child: parent for parent in root.iter() for child in parent}
    for image in list(root.iter()):
        if local_name(image.tag) != "img":
            continue
        src = image.attrib.get("src")
        if not src:
            continue
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(document_path), src.split("#", 1)[0])
        )
        record = next(
            (row for row in image_records if row.get("source_path") == resolved), None
        )
        if record is None or record.get("policy") == "original_only":
            continue
        block = ET.Element(
            f"{{{XHTML_NS}}}div", {"class": "bs-localized-image-block"}
        )
        if record.get("policy") == "original_plus_companion":
            localized_path = companion_epub_path(opf_path, record)
            localized_src = posixpath.relpath(
                localized_path, posixpath.dirname(document_path)
            )
            companion = ET.SubElement(
                block,
                f"{{{XHTML_NS}}}img",
                {
                    "class": "bs-localized-image",
                    "src": localized_src,
                    "alt": image.attrib.get("alt", ""),
                },
            )
            companion.tail = "\n"
        annotation = record.get("annotation")
        if isinstance(annotation, str) and annotation.strip():
            paragraph = ET.SubElement(
                block,
                f"{{{XHTML_NS}}}p",
                {"class": "bs-image-annotation"},
            )
            label = _editorial_label(
                config,
                "image_annotation_label",
                vietnamese="Chú giải ảnh",
                fallback="Image annotation",
            )
            paragraph.text = f"{label}: {annotation.strip()}"

        anchor = image
        image_parent = parent_of.get(image)
        if image_parent is not None and local_name(image_parent.tag) == "figure":
            anchor = image_parent
        parent = parent_of.get(anchor)
        if parent is None:
            continue
        position = list(parent).index(anchor)
        parent.insert(position + 1, block)


def _media_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _modified_package(
    context: dict[str, Any],
    config: ProjectConfig,
    image_records: list[dict[str, Any]],
    stylesheet_path: str,
) -> bytes:
    package: ET.Element = context["package"]
    languages = package.findall(f".//{{{DC_NS}}}language")
    if languages:
        for language in languages:
            language.text = config.target_language
    else:
        metadata = package.find(f".//{{{OPF_NS}}}metadata")
        if metadata is not None:
            ET.SubElement(metadata, f"{{{DC_NS}}}language").text = config.target_language

    manifest = package.find(f".//{{{OPF_NS}}}manifest")
    if manifest is None:
        raise _fail(
            "EPUB_MANIFEST_MISSING",
            "OPF package has no manifest.",
            "Repair the source EPUB package document.",
        )
    existing_ids = {item.attrib.get("id") for item in list(manifest)}
    existing_hrefs = {item.attrib.get("href") for item in list(manifest)}
    opf_dir = posixpath.dirname(context["opf_path"])
    stylesheet_href = posixpath.relpath(stylesheet_path, opf_dir)
    if stylesheet_href not in existing_hrefs:
        stylesheet_id = "bookstudio-styles"
        suffix = 1
        while stylesheet_id in existing_ids:
            stylesheet_id = f"bookstudio-styles-{suffix}"
            suffix += 1
        ET.SubElement(
            manifest,
            f"{{{OPF_NS}}}item",
            {
                "id": stylesheet_id,
                "href": stylesheet_href,
                "media-type": "text/css",
            },
        )
        existing_ids.add(stylesheet_id)
        existing_hrefs.add(stylesheet_href)
    companion_index = 0
    for record in image_records:
        if record.get("policy") != "original_plus_companion":
            continue
        epub_path = companion_epub_path(context["opf_path"], record)
        href = posixpath.relpath(epub_path, opf_dir)
        if href in existing_hrefs:
            continue
        item_id = f"bookstudio-localized-{companion_index}"
        while item_id in existing_ids:
            companion_index += 1
            item_id = f"bookstudio-localized-{companion_index}"
        ET.SubElement(
            manifest,
            f"{{{OPF_NS}}}item",
            {"id": item_id, "href": href, "media-type": _media_type(epub_path)},
        )
        existing_ids.add(item_id)
        existing_hrefs.add(href)
        companion_index += 1
    return ET.tostring(package, encoding="utf-8", xml_declaration=True)


def _stylesheet_path(opf_path: str, source_names: set[str]) -> str:
    directory = posixpath.join(posixpath.dirname(opf_path), "bookstudio")
    candidate = posixpath.join(directory, "bookstudio.css")
    suffix = 1
    while candidate in source_names:
        candidate = posixpath.join(directory, f"bookstudio-{suffix}.css")
        suffix += 1
    return candidate


def _zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o40755 if name.endswith("/") else 0o100644) << 16
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rewrite_with_edits(
    config: ProjectConfig, path: Path, operations: list[dict[str, Any]]
) -> None:
    with zipfile.ZipFile(path, "r") as built:
        members = [(info, built.read(info.filename)) for info in built.infolist()]
    edited = apply_edits(config, members, operations)
    rewritten = path.with_name(path.name + ".edits")
    try:
        with zipfile.ZipFile(rewritten, "w") as output:
            for info, data in edited:
                info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
                output.writestr(info, data, compresslevel=None if info.filename == "mimetype" else 9)
        rewritten.replace(path)
    except BaseException:
        rewritten.unlink(missing_ok=True)
        raise


def build_epub(config: ProjectConfig, output_path: Path) -> dict[str, Any]:
    require_full_scope(config)
    coverage = coverage_receipt(config, require_complete=True)
    if not coverage["passed"]:
        raise _fail(
            "COVERAGE_INCOMPLETE" if coverage["status"] == "incomplete" else "COVERAGE_INVALID",
            "Strict translation coverage must pass before build.",
            "Resolve all coverage findings and run the build again.",
        )
    targets, _, block_map = target_index(config)
    cache_index = validated_cache_index(
        config,
        targets=targets,
        source_sha256=block_map.get("source", {}).get("sha256"),
    )
    cache_files: dict[str, list[dict[str, Any]]] = {}
    for (source_path, _), row in cache_index.items():
        cache_files.setdefault(source_path, []).append(row)
    for rows in cache_files.values():
        rows.sort(key=lambda row: row["block_index"])
    preflight_archive(config.source)
    image_manifest = load_image_manifest(config)
    edit_operations, edits_sha256 = load_edits(config)
    destination = output_path.expanduser().resolve()
    if destination == config.source.resolve():
        raise _fail(
            "OUTPUT_OVERWRITES_SOURCE",
            "Build output may not replace the read-only source EPUB.",
            "Choose a separate output path.",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(config.source, "r") as source_archive:
        context = package_context(source_archive)
        image_records = image_manifest["images"]
        source_names = set(source_archive.namelist())
        stylesheet_path = _stylesheet_path(context["opf_path"], source_names)
        overrides: dict[str, bytes] = {
            context["opf_path"]: _modified_package(
                context,
                config,
                image_records,
                stylesheet_path,
            )
        }
        translated_titles: dict[str, str] = {}
        for item in context["spine"]:
            if "xhtml" not in item["media_type"] and "html" not in item["media_type"]:
                continue
            root = _translate_document(
                source_archive.read(item["path"]),
                source_path=item["path"],
                config=config,
                cache_rows=cache_files.get(item["path"], []),
            )
            _insert_image_blocks(
                root,
                config=config,
                document_path=item["path"],
                opf_path=context["opf_path"],
                image_records=image_records,
            )
            _ensure_stylesheet_link(
                root,
                document_path=item["path"],
                stylesheet_path=stylesheet_path,
            )
            if config.output_mode != "bilingual" and cache_files.get(item["path"]):
                title = _document_heading_title(root)
                if title:
                    translated_titles[item["path"]] = title
            overrides[item["path"]] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )

        if config.output_mode != "bilingual":
            for item in context["manifest"].values():
                raw = overrides.get(item["path"], source_archive.read(item["path"]))
                if "nav" in item.get("properties", "").split():
                    overrides[item["path"]] = _localize_navigation_document(
                        raw,
                        config=config,
                        document_path=item["path"],
                        translated_titles=translated_titles,
                    )
                elif item.get("media_type") == "application/x-dtbncx+xml":
                    overrides[item["path"]] = _localize_ncx_document(
                        raw,
                        config=config,
                        document_path=item["path"],
                        translated_titles=translated_titles,
                    )

        companions: dict[str, Path] = {}
        for record in image_records:
            if record.get("policy") == "original_plus_companion":
                companions[companion_epub_path(context["opf_path"], record)] = companion_file(
                    config, record
                )

        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            collisions = source_names.intersection(companions)
            if collisions:
                raise _fail(
                    "IMAGE_COMPANION_COLLISION",
                    f"Localized asset collides with source EPUB member: {sorted(collisions)[0]}",
                    "Rename the localized companion file.",
                )
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as output:
                output.writestr(
                    _zip_info("mimetype", stored=True),
                    source_archive.read("mimetype")
                    if "mimetype" in source_names
                    else b"application/epub+zip",
                )
                for name in sorted(source_names - {"mimetype"}):
                    info = _zip_info(name)
                    if name in overrides:
                        output.writestr(info, overrides[name])
                    elif name.endswith("/"):
                        output.writestr(info, b"")
                    else:
                        with source_archive.open(name, "r") as source_member:
                            with output.open(info, "w", force_zip64=True) as output_member:
                                shutil.copyfileobj(source_member, output_member, length=1024 * 1024)
                for name in sorted(companions):
                    with companions[name].open("rb") as source_member:
                        with output.open(_zip_info(name), "w", force_zip64=True) as output_member:
                            shutil.copyfileobj(source_member, output_member, length=1024 * 1024)
                output.writestr(_zip_info(stylesheet_path), BOOKSTUDIO_STYLESHEET)
            if edit_operations:
                _rewrite_with_edits(config, temporary, edit_operations)
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    return {
        "status": "pass",
        "message": "Deterministic EPUB build completed.",
        "output_name": destination.name,
        "output_sha256": _sha256(destination),
        "size_bytes": destination.stat().st_size,
        "source_sha256": preflight_archive(config.source)["source_sha256"],
        "output_mode": config.output_mode,
        "localized_companions": len(companions),
        "edits": {"applied": len(edit_operations), "sha256": edits_sha256},
    }


def finish_project(config: ProjectConfig) -> dict[str, Any]:
    from .validate import validate_epub

    require_full_scope(config)
    first = config.paths.output / ".finish-candidate-1.epub"
    second = config.paths.output / ".finish-candidate-2.epub"
    final = config.paths.output / "final.epub"
    try:
        first_receipt = build_epub(config, first)
        integrity = validate_epub(config, first)
        if not integrity["passed"]:
            raise _fail(
                "INTEGRITY_FAILED",
                "Candidate EPUB failed independent integrity validation.",
                "Review reports and correct the cache or source before finishing.",
            )
        second_receipt = build_epub(config, second)
        if first_receipt["output_sha256"] != second_receipt["output_sha256"]:
            raise _fail(
                "REPRODUCIBILITY_FAILED",
                "Two builds from the same inputs were not byte-identical.",
                "Inspect nondeterministic metadata or archive ordering before release.",
            )
        first.replace(final)
        release = {
            "status": "pass",
            "schema_version": 1,
            "output": "output/final.epub",
            "output_sha256": first_receipt["output_sha256"],
            "reproducible": True,
            "integrity": integrity,
            "edits": first_receipt["edits"],
        }
        atomic_write_json(config.paths.reports / "release.json", release)
        return {
            **release,
            "message": "Final EPUB passed coverage, integrity, and reproducibility gates.",
        }
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
