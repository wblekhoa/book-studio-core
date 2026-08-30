"""Stable source-aligned translation block extraction."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .archive import ArchiveLimits, DEFAULT_LIMITS, preflight_archive
from .inspect import TEXT_MEDIA_TYPES, clean_text, local_name, package_context


BLOCK_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "li", "blockquote"})


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


def extract_file_blocks(raw: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    blocks: list[dict[str, Any]] = []
    block_index = 0

    def walk(element: ET.Element, inside_block: bool) -> None:
        nonlocal block_index
        tag = local_name(element.tag)
        text = clean_text("".join(element.itertext()))
        is_block = tag in BLOCK_TAGS and bool(text)
        if is_block:
            blocks.append(
                {
                    "block_index": block_index,
                    "tag": tag,
                    "role": _role_for(element),
                    "class": element.attrib.get("class", ""),
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "word_count": _word_count(text),
                    "canonical": not inside_block,
                    "watermark": text == "OceanofPDF.com",
                }
            )
            block_index += 1
        for child in element:
            walk(child, inside_block or is_block)

    walk(root, False)
    return blocks


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
