"""Stable source-aligned translation block extraction."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..safety.xhtml import is_safe_href
from .archive import ArchiveLimits, DEFAULT_LIMITS, preflight_archive
from .inspect import TEXT_MEDIA_TYPES, clean_text, local_name, package_context


BLOCK_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "li", "blockquote"})
# Inline elements a translator must carry into ``translation_xhtml``; packets
# otherwise expose only flattened block text.
INLINE_HINT_TAGS = frozenset({"em", "strong", "i", "b", "a", "sup", "sub", "code"})
# Hints name the tag a safe ``translation_xhtml`` may use.
INLINE_HINT_NAMES = {"i": "em", "b": "strong"}


def _word_count(value: str) -> int:
    return len(value.split())


def _role_for(element: ET.Element) -> str:
    tag = local_name(element.tag)
    classes = set(element.attrib.get("class", "").split())
    if classes.intersection({"chapter-number", "chapter-numbers"}):
        return "chapter_number"
    if classes.intersection({"chapter-title", "chapter-title1"}):
        return "chapter_title"
    if "footnote" in classes:
        return "citation"
    if tag == "li":
        return "bullet"
    if tag == "blockquote":
        return "quote"
    if tag.startswith("h"):
        return "section_title"
    return "paragraph"


def _block_elements(root: ET.Element) -> list[tuple[ET.Element, str, bool]]:
    """Return block elements in block-index order with their text and nesting."""
    found: list[tuple[ET.Element, str, bool]] = []

    def walk(element: ET.Element, inside_block: bool) -> None:
        tag = local_name(element.tag)
        text = clean_text("".join(element.itertext()))
        is_block = tag in BLOCK_TAGS and bool(text)
        if is_block:
            found.append((element, text, inside_block))
        for child in element:
            walk(child, inside_block or is_block)

    walk(root, False)
    return found


def extract_file_blocks(raw: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    return [
        {
            "block_index": block_index,
            "tag": local_name(element.tag),
            "role": _role_for(element),
            "class": element.attrib.get("class", ""),
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "word_count": _word_count(text),
            "canonical": not inside_block,
            "watermark": text == "OceanofPDF.com",
        }
        for block_index, (element, text, inside_block) in enumerate(_block_elements(root))
    ]


def _inline_markup(block: ET.Element) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            tag = local_name(child.tag)
            if tag in INLINE_HINT_TAGS:
                # The builder restores id-bearing source elements (noterefs,
                # anchors) itself; hinting them would duplicate them.
                if any(node.attrib.get("id") for node in child.iter()):
                    continue
                text = clean_text("".join(child.itertext()))
                if text:
                    row = {"tag": INLINE_HINT_NAMES.get(tag, tag), "text": text}
                    href = child.attrib.get("href")
                    if tag == "a" and href and is_safe_href(href):
                        row["href"] = href
                    rows.append(row)
            visit(child)

    visit(block)
    return rows


def inline_markup_by_block(
    path: Path, source_path: str, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[int, list[dict[str, str]]]:
    """Map each block index of one spine document to its source inline markup."""
    preflight_archive(path, limits)
    with zipfile.ZipFile(path.expanduser().resolve(), "r") as archive:
        root = ET.fromstring(archive.read(source_path))
    hints: dict[int, list[dict[str, str]]] = {}
    for block_index, (element, _, _) in enumerate(_block_elements(root)):
        rows = _inline_markup(element)
        if rows:
            hints[block_index] = rows
    return hints


def extract_block_map(
    path: Path, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    preflight = preflight_archive(path, limits)
    source = path.expanduser().resolve()
    files: list[dict[str, Any]] = []
    with zipfile.ZipFile(source, "r") as archive:
        context = package_context(archive)
        for item in context["spine"]:
            if item["media_type"] not in TEXT_MEDIA_TYPES:
                continue
            blocks = extract_file_blocks(archive.read(item["path"]))
            files.append(
                {
                    "spine_index": item["spine_index"],
                    "source_path": item["path"],
                    "block_count": len(blocks),
                    "canonical_count": sum(
                        1
                        for block in blocks
                        if block["canonical"] and not block["watermark"]
                    ),
                    "watermark_count": sum(1 for block in blocks if block["watermark"]),
                    "blocks": blocks,
                }
            )

    all_blocks = [block for file in files for block in file["blocks"]]
    return {
        "schema_version": 1,
        "source": {"name": preflight["source_name"], "sha256": preflight["source_sha256"]},
        "opf_rootfile": context["opf_path"],
        "spine_files": len(files),
        "all_blocks": len(all_blocks),
        "canonical_targets": sum(
            1 for block in all_blocks if block["canonical"] and not block["watermark"]
        ),
        "watermark_blocks": sum(1 for block in all_blocks if block["watermark"]),
        "files": files,
    }
