"""Fail-closed PDF source gateway for the EPUB translation workflow.

The adapter never edits a PDF in place. It inspects the text layer first and
only prepares a semantic EPUB when the source is sufficiently extractable.
Prepared EPUBs remain review-gated because PDF reading order and layout cannot
be proven from extraction alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from xml.etree import ElementTree as ET

from ..config import validate_language
from ..errors import BookStudioError


XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_PDF_BYTES = 1_073_741_824
MAX_XML_BYTES = 268_435_456
MAX_IMAGE_BYTES = 268_435_456
MAX_TOTAL_IMAGE_BYTES = 1_073_741_824
INSPECTION_TIMEOUT_SECONDS = 120
CONVERSION_TIMEOUT_SECONDS = 900
TEXT_THRESHOLD = 20
SUBSTANTIAL_TEXT_THRESHOLD = 80

ToolRunner = Callable[[list[str], int], Any]

ET.register_namespace("", XHTML_NS)
ET.register_namespace("epub", EPUB_NS)
ET.register_namespace("dc", DC_NS)


def _fail(
    code: str,
    message: str,
    next_action: str,
    *,
    exit_code: int = 1,
    evidence: Sequence[str] = (),
) -> BookStudioError:
    return BookStudioError(
        code=code,
        message=message,
        next_action=next_action,
        exit_code=exit_code,
        evidence=tuple(evidence),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_pdf_source(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise _fail(
            "PDF_INVALID",
            "PDF source must be a regular file, not a symbolic link.",
            "Pass the regular PDF file directly.",
        )
    source = expanded.resolve()
    if not source.is_file():
        raise _fail(
            "SOURCE_NOT_FOUND",
            f"PDF source does not exist: {path}",
            "Pass an existing PDF source path.",
        )
    size = source.stat().st_size
    if size <= 0 or size > MAX_PDF_BYTES:
        raise _fail(
            "PDF_INVALID",
            f"PDF size is outside the supported 1 GiB boundary: {size} bytes.",
            "Use a non-empty PDF smaller than 1 GiB.",
        )
    with source.open("rb") as handle:
        header = handle.read(1024)
    if b"%PDF-" not in header:
        raise _fail(
            "PDF_INVALID",
            "Source does not contain a valid PDF header.",
            "Pass a readable PDF file.",
        )
    return source


def pdf_tool_status() -> dict[str, bool]:
    """Return optional local PDF tool availability without mutating the host."""
    return {
        name: shutil.which(name) is not None
        for name in ("pdfinfo", "pdftotext", "pdftohtml", "pdftoppm", "tesseract")
    }


def _tool(name: str, runner: ToolRunner | None) -> str:
    if runner is not None:
        return name
    resolved = shutil.which(name)
    if resolved is None:
        raise _fail(
            "PDF_TOOL_MISSING",
            f"Required PDF tool is not available: {name}.",
            "Install Poppler with your system package manager, then rerun the command.",
            evidence=(name,),
        )
    return resolved


def _default_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _run_checked(
    command: list[str],
    *,
    runner: ToolRunner | None,
    timeout: int,
    code: str,
    action: str,
) -> Any:
    execute = runner or _default_runner
    try:
        result = execute(command, timeout)
    except FileNotFoundError as exc:
        raise _fail(
            "PDF_TOOL_MISSING",
            f"Required PDF tool is not available: {Path(command[0]).name}.",
            "Install Poppler with your system package manager, then rerun the command.",
            evidence=(Path(command[0]).name,),
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise _fail(
            code,
            f"PDF tool timed out after {timeout} seconds.",
            action,
        ) from exc
    if int(getattr(result, "returncode", 1)) != 0:
        stderr = " ".join(str(getattr(result, "stderr", "")).split())[:500]
        evidence = (stderr,) if stderr else ()
        raise _fail(
            code,
            f"PDF tool failed: {Path(command[0]).name}.",
            action,
            evidence=evidence,
        )
    return result


def _parse_pdfinfo(value: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, raw = line.partition(":")
        if separator:
            fields[key.strip().casefold()] = raw.strip()
    return fields


def _metadata_value(fields: Mapping[str, str], key: str) -> list[str]:
    value = " ".join(fields.get(key, "").split())
    return [value] if value else []


def _page_texts(text: str, pages: int) -> list[str]:
    values = text.replace("\r\n", "\n").replace("\r", "\n").split("\f")
    while len(values) > pages and not values[-1].strip():
        values.pop()
    if len(values) < pages:
        values.extend([""] * (pages - len(values)))
    if len(values) > pages:
        head = values[: pages - 1]
        head.append("\n".join(values[pages - 1 :]))
        values = head
    return values


def _visible_char_count(value: str) -> int:
    return sum(1 for character in value if not character.isspace())


def inspect_pdf(path: Path, *, runner: ToolRunner | None = None) -> dict[str, Any]:
    """Inspect a PDF without including extracted prose or absolute paths in its receipt."""
    source = _validate_pdf_source(path)
    source_hash = _sha256(source)
    info = _run_checked(
        [_tool("pdfinfo", runner), "-enc", "UTF-8", str(source)],
        runner=runner,
        timeout=INSPECTION_TIMEOUT_SECONDS,
        code="PDF_INVALID",
        action="Repair the PDF or provide a readable, unencrypted source.",
    )
    fields = _parse_pdfinfo(str(getattr(info, "stdout", "")))
    if fields.get("encrypted", "").casefold().startswith("yes"):
        raise _fail(
            "PDF_ENCRYPTED",
            "Encrypted or permission-restricted PDFs are not processed.",
            "Provide an authorized, unencrypted PDF source.",
        )
    try:
        pages = int(fields.get("pages", ""))
    except ValueError as exc:
        raise _fail(
            "PDF_INVALID",
            "PDF page count could not be determined.",
            "Repair the PDF or provide a readable source.",
        ) from exc
    if pages <= 0 or pages > 100_000:
        raise _fail(
            "PDF_INVALID",
            f"PDF page count is outside the supported boundary: {pages}.",
            "Provide a PDF with between 1 and 100000 pages.",
        )

    extracted = _run_checked(
        [
            _tool("pdftotext", runner),
            "-enc",
            "UTF-8",
            "-eol",
            "unix",
            str(source),
            "-",
        ],
        runner=runner,
        timeout=INSPECTION_TIMEOUT_SECONDS,
        code="PDF_TEXT_EXTRACTION_FAILED",
        action="Repair the PDF text layer or route it through reviewed OCR.",
    )
    page_counts = [
        _visible_char_count(value)
        for value in _page_texts(str(getattr(extracted, "stdout", "")), pages)
    ]
    pages_with_text = sum(value >= TEXT_THRESHOLD for value in page_counts)
    pages_with_substantial_text = sum(
        value >= SUBSTANTIAL_TEXT_THRESHOLD for value in page_counts
    )
    total_chars = sum(page_counts)
    coverage_ratio = pages_with_substantial_text / pages
    if pages_with_text == 0 or total_chars < TEXT_THRESHOLD:
        classification = "image_only"
        source_readiness = "ocr_required"
        warnings = ["PDF_TEXT_LAYER_ABSENT"]
    elif coverage_ratio < 0.6 or total_chars < pages * SUBSTANTIAL_TEXT_THRESHOLD:
        classification = "mixed_or_sparse"
        source_readiness = "mixed_source_review_required"
        warnings = ["PDF_TEXT_LAYER_SPARSE"]
    else:
        classification = "text_layer_sufficient"
        source_readiness = "review_required"
        warnings = []

    median_chars = sorted(page_counts)[len(page_counts) // 2]
    if _sha256(source) != source_hash:
        raise _fail(
            "PDF_SOURCE_CHANGED",
            "PDF source changed during inspection.",
            "Stop concurrent edits, then reinspect the stable PDF source.",
        )
    return {
        "status": "pass",
        "schema_version": 1,
        "source": {
            "name": source.name,
            "sha256": source_hash,
            "size_bytes": source.stat().st_size,
            "format": "pdf",
        },
        "metadata": {
            "title": _metadata_value(fields, "title"),
            "creator": _metadata_value(fields, "author"),
            "subject": _metadata_value(fields, "subject"),
        },
        "pages": pages,
        "tagged": fields.get("tagged", "").casefold().startswith("yes"),
        "pdf_version": fields.get("pdf version") or None,
        "page_size": fields.get("page size") or None,
        "text": {
            "classification": classification,
            "pages_with_text": pages_with_text,
            "pages_with_substantial_text": pages_with_substantial_text,
            "total_chars": total_chars,
            "median_chars_per_page": median_chars,
            "coverage_ratio": round(coverage_ratio, 6),
        },
        "source_readiness": source_readiness,
        "warnings": warnings,
    }


def _clean_text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or "")
    except ValueError:
        return default


def _read_xml(path: Path) -> ET.Element:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "PDF conversion XML must be a regular file, not a symbolic link.",
            "Rerun PDF preparation in a trusted temporary workspace.",
        )
    source = expanded.resolve()
    if not source.is_file():
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "PDF conversion did not produce a regular XML document.",
            "Rerun PDF preparation and inspect the Poppler conversion output.",
        )
    raw = source.read_bytes()
    if not raw or len(raw) > MAX_XML_BYTES or re.search(br"<!ENTITY\b", raw, re.I):
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "PDF conversion XML is empty, oversized, or contains unsupported entities.",
            "Inspect the PDF and conversion output before retrying.",
        )
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            f"PDF conversion XML is invalid: {exc}.",
            "Rerun PDF preparation and inspect the Poppler conversion output.",
        ) from exc


def _edge_artifacts(pages: list[dict[str, Any]]) -> set[tuple[int, int]]:
    occurrences: Counter[str] = Counter()
    keyed: dict[tuple[int, int], str] = {}
    for page_index, page in enumerate(pages):
        page_keys: set[str] = set()
        height = float(page["height"])
        for item_index, item in enumerate(page["items"]):
            if item["kind"] != "text":
                continue
            top = float(item["top"])
            bottom = top + float(item["height"])
            if top > height * 0.13 and bottom < height * 0.88:
                continue
            key = " ".join(str(item["text"]).casefold().split())
            if key:
                keyed[(page_index, item_index)] = key
                page_keys.add(key)
        occurrences.update(page_keys)

    threshold = max(2, math.ceil(len(pages) * 0.4))
    artifacts: set[tuple[int, int]] = set()
    page_number = re.compile(r"^(?:page\s*)?(?:\d+|[ivxlcdm]+)$", re.I)
    for location, key in keyed.items():
        if occurrences[key] >= threshold or page_number.fullmatch(key):
            artifacts.add(location)
    return artifacts


def _image_media_type(path: Path) -> tuple[str, str]:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    raise _fail(
        "PDF_IMAGE_EXTRACTION_FAILED",
        f"Unsupported extracted image format: {path.name}.",
        "Review or replace the unsupported image before preparing the source.",
    )


def _safe_image(xml_path: Path, value: str) -> Path:
    root = xml_path.expanduser().resolve().parent
    unresolved = root / value
    if unresolved.is_symlink():
        raise _fail(
            "PDF_IMAGE_EXTRACTION_FAILED",
            "PDF conversion referenced a symbolic-link image.",
            "Rerun PDF preparation in a trusted temporary workspace.",
        )
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _fail(
            "PDF_IMAGE_EXTRACTION_FAILED",
            "PDF conversion referenced an image outside its temporary workspace.",
            "Inspect the source and retry with a trusted PDF.",
        ) from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise _fail(
            "PDF_IMAGE_EXTRACTION_FAILED",
            f"Extracted image is missing or unsafe: {Path(value).name}.",
            "Rerun PDF preparation and inspect the conversion output.",
        )
    if candidate.stat().st_size > MAX_IMAGE_BYTES:
        raise _fail(
            "PDF_IMAGE_EXTRACTION_FAILED",
            f"Extracted image exceeds the 256 MiB limit: {candidate.name}.",
            "Optimize the source image before retrying.",
        )
    return candidate


def _parse_pages(root: ET.Element, xml_path: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    image_total = 0
    for page_element in root.findall(".//page"):
        try:
            page_number = int(page_element.attrib["number"])
        except (KeyError, ValueError) as exc:
            raise _fail(
                "PDF_SOURCE_INCOMPLETE",
                "PDF conversion contains a page without a valid number.",
                "Inspect the conversion output and repair the source PDF.",
            ) from exc
        fonts = {
            node.attrib.get("id", ""): _float(node.attrib.get("size"))
            for node in page_element.findall("fontspec")
        }
        items: list[dict[str, Any]] = []
        for node in page_element:
            if node.tag == "text":
                text = _clean_text(node)
                if not text:
                    continue
                items.append(
                    {
                        "kind": "text",
                        "text": text,
                        "top": _float(node.attrib.get("top")),
                        "left": _float(node.attrib.get("left")),
                        "width": _float(node.attrib.get("width")),
                        "height": _float(node.attrib.get("height")),
                        "font_size": fonts.get(node.attrib.get("font", ""), 0.0),
                    }
                )
            elif node.tag == "image" and node.attrib.get("src"):
                image = _safe_image(xml_path, node.attrib["src"])
                image_total += image.stat().st_size
                if image_total > MAX_TOTAL_IMAGE_BYTES:
                    raise _fail(
                        "PDF_IMAGE_EXTRACTION_FAILED",
                        "Extracted images exceed the 1 GiB total limit.",
                        "Optimize the source images before retrying.",
                    )
                media_type, extension = _image_media_type(image)
                items.append(
                    {
                        "kind": "image",
                        "source": image,
                        "media_type": media_type,
                        "extension": extension,
                        "top": _float(node.attrib.get("top")),
                        "left": _float(node.attrib.get("left")),
                        "width": _float(node.attrib.get("width")),
                        "height": _float(node.attrib.get("height")),
                    }
                )
        pages.append(
            {
                "number": page_number,
                "width": _float(page_element.attrib.get("width"), 612.0),
                "height": _float(page_element.attrib.get("height"), 792.0),
                "items": items,
            }
        )
    if not pages:
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "PDF conversion produced no pages.",
            "Inspect the PDF and Poppler conversion output before retrying.",
        )
    page_numbers = [int(page["number"]) for page in pages]
    if len(set(page_numbers)) != len(page_numbers):
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "PDF conversion contains duplicate page numbers.",
            "Repair the source PDF before retrying.",
        )
    return pages


def _outline_entries(root: ET.Element, pages: list[dict[str, Any]]) -> list[tuple[int, str]]:
    page_numbers = {int(page["number"]) for page in pages}
    entries: list[tuple[int, str]] = []
    seen_pages: set[int] = set()
    for outline in root.findall(".//outline"):
        for item in outline.iter("item"):
            try:
                page = int(item.attrib.get("page", ""))
            except ValueError:
                continue
            label = _clean_text(item)
            if page not in page_numbers or page in seen_pages or not label:
                continue
            seen_pages.add(page)
            entries.append((page, label[:300]))
    return sorted(entries, key=lambda entry: entry[0])


def _body_font_size(pages: list[dict[str, Any]], artifacts: set[tuple[int, int]]) -> float:
    weights: Counter[float] = Counter()
    for page_index, page in enumerate(pages):
        for item_index, item in enumerate(page["items"]):
            if item["kind"] != "text" or (page_index, item_index) in artifacts:
                continue
            size = round(float(item["font_size"]), 1)
            if size > 0:
                weights[size] += min(len(str(item["text"])), 300)
    return max(weights, key=lambda value: (weights[value], -value)) if weights else 12.0


def _complex_layout_pages(
    pages: list[dict[str, Any]], artifacts: set[tuple[int, int]]
) -> list[int]:
    result: list[int] = []
    for page_index, page in enumerate(pages):
        width = float(page["width"])
        narrow = [
            item
            for item_index, item in enumerate(page["items"])
            if item["kind"] == "text"
            and (page_index, item_index) not in artifacts
            and float(item["width"]) < width * 0.48
        ]
        left = sum(float(item["left"]) < width * 0.45 for item in narrow)
        right = sum(float(item["left"]) > width * 0.45 for item in narrow)
        if left >= 3 and right >= 3:
            result.append(int(page["number"]))
    return result


def _append_text(parent: ET.Element, tag: str, text: str) -> None:
    node = ET.SubElement(parent, f"{{{XHTML_NS}}}{tag}")
    node.text = text


def _join_lines(lines: list[str], value: str) -> None:
    if lines and lines[-1].endswith("-") and value[:1].islower():
        lines[-1] = lines[-1][:-1] + value
    else:
        lines.append(value)


def _xhtml_bytes(title: str, language: str, section: ET.Element) -> bytes:
    root = ET.Element(
        f"{{{XHTML_NS}}}html",
        {
            "lang": language,
            f"{{{XML_NS}}}lang": language,
        },
    )
    head = ET.SubElement(root, f"{{{XHTML_NS}}}head")
    ET.SubElement(head, f"{{{XHTML_NS}}}meta", {"charset": "utf-8"})
    title_node = ET.SubElement(head, f"{{{XHTML_NS}}}title")
    title_node.text = title
    ET.SubElement(
        head,
        f"{{{XHTML_NS}}}link",
        {"rel": "stylesheet", "type": "text/css", "href": "../styles/book.css"},
    )
    body = ET.SubElement(root, f"{{{XHTML_NS}}}body")
    body.append(section)
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )


def _title_from(
    title: str | None, inspection: Mapping[str, Any], pages: list[dict[str, Any]], source: Path
) -> str:
    if title and title.strip():
        return title.strip()
    metadata = inspection.get("metadata", {})
    if isinstance(metadata, Mapping):
        titles = metadata.get("title", [])
        if isinstance(titles, list) and titles and isinstance(titles[0], str):
            if titles[0].strip():
                return titles[0].strip()
    for page in pages:
        text = next(
            (
                str(item["text"])
                for item in page["items"]
                if item["kind"] == "text" and str(item["text"]).strip()
            ),
            "",
        )
        if text:
            return text[:200]
    return source.stem


def _creator_from(inspection: Mapping[str, Any]) -> str | None:
    metadata = inspection.get("metadata", {})
    if not isinstance(metadata, Mapping):
        return None
    creators = metadata.get("creator", [])
    if isinstance(creators, list) and creators and isinstance(creators[0], str):
        return creators[0].strip() or None
    return None


def _render_documents(
    pages: list[dict[str, Any]],
    *,
    artifacts: set[tuple[int, int]],
    outline_entries: list[tuple[int, str]],
    language: str,
    book_title: str,
) -> tuple[list[tuple[str, str, bytes]], list[dict[str, Any]], dict[str, int]]:
    body_size = _body_font_size(pages, artifacts)
    heading_threshold = max(body_size * 1.28, body_size + 3.0)
    image_paths: dict[Path, dict[str, Any]] = {}
    documents: list[tuple[str, str, bytes]] = []
    source_text_nodes = 0
    preserved_text_nodes = 0
    pages_with_text: set[int] = set()

    page_indexes = {int(page["number"]): index for index, page in enumerate(pages)}
    if outline_entries:
        labels_by_start = {
            page_indexes[page]: label
            for page, label in outline_entries
            if page in page_indexes
        }
        starts = sorted({0, *labels_by_start})
    else:
        labels_by_start = {}
        starts = list(range(0, len(pages), 12))
    boundaries = starts + [len(pages)]

    for chunk_index, start in enumerate(starts, start=1):
        chunk = pages[start : boundaries[chunk_index]]
        section = ET.Element(f"{{{XHTML_NS}}}section")
        section.attrib["id"] = f"pdf-section-{chunk_index}"
        chapter_title = labels_by_start.get(start, "")
        if chapter_title:
            _append_text(section, "h1", chapter_title)
        for local_page_index, page in enumerate(chunk):
            page_index = start + local_page_index
            anchor = ET.SubElement(
                section,
                f"{{{XHTML_NS}}}span",
                {
                    "id": f"page-{page['number']}",
                    f"{{{EPUB_NS}}}type": "pagebreak",
                    "title": str(page["number"]),
                },
            )
            anchor.tail = "\n"
            pending: list[str] = []
            previous: dict[str, Any] | None = None

            def flush() -> None:
                nonlocal pending, previous
                if pending:
                    _append_text(section, "p", " ".join(pending))
                    pending = []
                previous = None

            ordered = sorted(
                enumerate(page["items"]),
                key=lambda value: (
                    float(value[1]["top"]),
                    float(value[1]["left"]),
                    0 if value[1]["kind"] == "text" else 1,
                ),
            )
            emitted_on_page = False
            for item_index, item in ordered:
                if item["kind"] == "text":
                    source_text_nodes += 1
                    if (page_index, item_index) in artifacts:
                        continue
                    preserved_text_nodes += 1
                    pages_with_text.add(int(page["number"]))
                    text = str(item["text"])
                    is_heading = (
                        float(item["font_size"]) >= heading_threshold
                        and len(text) <= 240
                    )
                    if is_heading:
                        flush()
                        if " ".join(text.casefold().split()) != " ".join(
                            chapter_title.casefold().split()
                        ):
                            _append_text(section, "h1" if not chapter_title else "h2", text)
                            if not chapter_title:
                                chapter_title = text
                        emitted_on_page = True
                        continue
                    if previous is not None:
                        vertical_gap = float(item["top"]) - (
                            float(previous["top"]) + float(previous["height"])
                        )
                        left_gap = abs(float(item["left"]) - float(previous["left"]))
                        same_paragraph = (
                            -2.0 <= vertical_gap <= max(float(previous["height"]) * 1.2, 24.0)
                            and left_gap <= max(float(page["width"]) * 0.09, 36.0)
                        )
                        if not same_paragraph:
                            flush()
                    _join_lines(pending, text)
                    previous = item
                    emitted_on_page = True
                else:
                    flush()
                    image_source = Path(item["source"])
                    image = image_paths.get(image_source)
                    if image is None:
                        index = len(image_paths) + 1
                        is_cover = (
                            int(page["number"]) == int(pages[0]["number"])
                            and float(item["width"]) * float(item["height"])
                            >= float(page["width"]) * float(page["height"]) * 0.5
                        )
                        image = {
                            "id": f"pdf-image-{index}",
                            "name": f"image-{index:04d}{item['extension']}",
                            "source": image_source,
                            "media_type": item["media_type"],
                            "cover": is_cover,
                        }
                        image_paths[image_source] = image
                    figure = ET.SubElement(section, f"{{{XHTML_NS}}}figure")
                    ET.SubElement(
                        figure,
                        f"{{{XHTML_NS}}}img",
                        {
                            "src": f"../images/{image['name']}",
                            "alt": f"Illustration from PDF page {page['number']}",
                        },
                    )
                    emitted_on_page = True
            flush()
            if any(
                item["kind"] == "text"
                and (page_index, item_index) not in artifacts
                for item_index, item in enumerate(page["items"])
            ) and not emitted_on_page:
                raise _fail(
                    "PDF_SOURCE_INCOMPLETE",
                    f"Text-bearing PDF page {page['number']} produced no semantic content.",
                    "Inspect the page and conversion reading order before retrying.",
                )
        if not chapter_title:
            chapter_title = f"{book_title}, pages {chunk[0]['number']}-{chunk[-1]['number']}"
        name = f"chapter-{chunk_index:03d}.xhtml"
        documents.append((name, chapter_title, _xhtml_bytes(chapter_title, language, section)))

    images = list(image_paths.values())
    metrics = {
        "source_text_nodes": source_text_nodes,
        "preserved_text_nodes": preserved_text_nodes,
        "removed_artifact_nodes": source_text_nodes - preserved_text_nodes,
        "pages_with_text": len(pages_with_text),
    }
    return documents, images, metrics


def _navigation_bytes(
    title: str, language: str, documents: list[tuple[str, str, bytes]]
) -> bytes:
    root = ET.Element(
        f"{{{XHTML_NS}}}html",
        {"lang": language, f"{{{XML_NS}}}lang": language},
    )
    head = ET.SubElement(root, f"{{{XHTML_NS}}}head")
    title_node = ET.SubElement(head, f"{{{XHTML_NS}}}title")
    title_node.text = "Contents"
    body = ET.SubElement(root, f"{{{XHTML_NS}}}body")
    nav = ET.SubElement(body, f"{{{XHTML_NS}}}nav", {f"{{{EPUB_NS}}}type": "toc"})
    heading = ET.SubElement(nav, f"{{{XHTML_NS}}}h1")
    heading.text = title
    ordered = ET.SubElement(nav, f"{{{XHTML_NS}}}ol")
    for name, label, _raw in documents:
        item = ET.SubElement(ordered, f"{{{XHTML_NS}}}li")
        link = ET.SubElement(item, f"{{{XHTML_NS}}}a", {"href": f"text/{name}"})
        link.text = label
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )


def _package_bytes(
    *,
    source_hash: str,
    title: str,
    creator: str | None,
    language: str,
    documents: list[tuple[str, str, bytes]],
    images: list[dict[str, Any]],
) -> bytes:
    package = ET.Element(
        f"{{{OPF_NS}}}package",
        {"version": "3.0", "unique-identifier": "book-id"},
    )
    metadata = ET.SubElement(package, f"{{{OPF_NS}}}metadata")
    identifier = ET.SubElement(metadata, f"{{{DC_NS}}}identifier", {"id": "book-id"})
    identifier.text = f"urn:sha256:{source_hash}"
    title_node = ET.SubElement(metadata, f"{{{DC_NS}}}title")
    title_node.text = title
    language_node = ET.SubElement(metadata, f"{{{DC_NS}}}language")
    language_node.text = language
    if creator:
        creator_node = ET.SubElement(metadata, f"{{{DC_NS}}}creator")
        creator_node.text = creator
    cover = next((image for image in images if image.get("cover") is True), None)
    if cover is not None:
        ET.SubElement(
            metadata,
            f"{{{OPF_NS}}}meta",
            {"name": "cover", "content": str(cover["id"])},
        )
    modified = ET.SubElement(
        metadata,
        f"{{{OPF_NS}}}meta",
        {"property": "dcterms:modified"},
    )
    modified.text = "2000-01-01T00:00:00Z"
    manifest = ET.SubElement(package, f"{{{OPF_NS}}}manifest")
    ET.SubElement(
        manifest,
        f"{{{OPF_NS}}}item",
        {
            "id": "nav",
            "href": "nav.xhtml",
            "media-type": "application/xhtml+xml",
            "properties": "nav",
        },
    )
    ET.SubElement(
        manifest,
        f"{{{OPF_NS}}}item",
        {"id": "styles", "href": "styles/book.css", "media-type": "text/css"},
    )
    for index, (name, _label, _raw) in enumerate(documents, start=1):
        ET.SubElement(
            manifest,
            f"{{{OPF_NS}}}item",
            {
                "id": f"chapter-{index}",
                "href": f"text/{name}",
                "media-type": "application/xhtml+xml",
            },
        )
    for image in images:
        attributes = {
            "id": str(image["id"]),
            "href": f"images/{image['name']}",
            "media-type": str(image["media_type"]),
        }
        if image.get("cover") is True:
            attributes["properties"] = "cover-image"
        ET.SubElement(
            manifest,
            f"{{{OPF_NS}}}item",
            attributes,
        )
    spine = ET.SubElement(package, f"{{{OPF_NS}}}spine")
    for index in range(1, len(documents) + 1):
        ET.SubElement(spine, f"{{{OPF_NS}}}itemref", {"idref": f"chapter-{index}"})
    ET.indent(package, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        package, encoding="utf-8"
    )


def _zip_member(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _write_epub(
    output: Path,
    *,
    title: str,
    creator: str | None,
    language: str,
    source: Path,
    inspection: Mapping[str, Any],
    pages: list[dict[str, Any]],
    documents: list[tuple[str, str, bytes]],
    images: list[dict[str, Any]],
    metrics: Mapping[str, int],
    complex_pages: list[int],
) -> None:
    source_hash = str(inspection["source"]["sha256"])
    provenance = {
        "schema_version": 1,
        "source": {
            "name": source.name,
            "sha256": source_hash,
            "size_bytes": source.stat().st_size,
            "format": "pdf",
        },
        "pdf": {
            "pages": len(pages),
            "tagged": bool(inspection.get("tagged", False)),
            "text_classification": inspection.get("text", {}).get("classification"),
        },
        "conversion": {
            "adapter": "bookstudio.pdf",
            "page_anchors": len(pages),
            **dict(metrics),
            "images_preserved": len(images),
            "cover_preserved": any(image.get("cover") is True for image in images),
            "complex_layout_pages": complex_pages,
        },
    }
    container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''
    css = b"""html { color: inherit; background: transparent; }
body { margin: 0 5%; line-height: 1.55; }
h1, h2 { break-after: avoid; page-break-after: avoid; }
p { margin: 0.55em 0; }
figure { break-inside: avoid; page-break-inside: avoid; margin: 1em auto; }
img { display: block; max-width: 100%; height: auto; margin: 0 auto; }
[epub\\:type~="pagebreak"] { display: block; height: 0; }
"""
    entries: list[tuple[str, bytes, bool]] = [
        ("mimetype", b"application/epub+zip", True),
        ("META-INF/container.xml", container, False),
        (
            "META-INF/bookstudio-source.json",
            (json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
            False,
        ),
        (
            "OEBPS/content.opf",
            _package_bytes(
                source_hash=source_hash,
                title=title,
                creator=creator,
                language=language,
                documents=documents,
                images=images,
            ),
            False,
        ),
        ("OEBPS/nav.xhtml", _navigation_bytes(title, language, documents), False),
        ("OEBPS/styles/book.css", css, False),
    ]
    entries.extend(
        (f"OEBPS/text/{name}", raw, False) for name, _label, raw in documents
    )
    entries.extend(
        (f"OEBPS/images/{image['name']}", Path(image["source"]).read_bytes(), False)
        for image in images
    )
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw, stored in entries:
            archive.writestr(_zip_member(name, stored=stored), raw)


def build_semantic_epub_from_xml(
    source: Path,
    xml_path: Path,
    destination: Path,
    inspection: Mapping[str, Any],
    *,
    source_language: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, review-gated EPUB from Poppler XML output."""
    pdf = _validate_pdf_source(source)
    expected_hash = str(inspection.get("source", {}).get("sha256", ""))
    actual_hash = _sha256(pdf)
    if not expected_hash or expected_hash != actual_hash:
        raise _fail(
            "PDF_SOURCE_CHANGED",
            "PDF source no longer matches its inspection receipt.",
            "Reinspect the PDF and rerun preparation.",
        )
    classification = inspection.get("text", {}).get("classification")
    if classification != "text_layer_sufficient":
        code = "PDF_OCR_REQUIRED" if classification == "image_only" else "PDF_MIXED_SOURCE_REVIEW_REQUIRED"
        raise _fail(
            code,
            "PDF text extraction is not sufficient for automatic semantic preparation.",
            "Route the source through reviewed OCR/layout repair, then reinspect it.",
            exit_code=2,
        )
    language = validate_language(source_language, field="source_language") if source_language else "und"
    output = destination.expanduser().resolve()
    if output == pdf or output.suffix.casefold() != ".epub":
        raise _fail(
            "PDF_OUTPUT_INVALID",
            "Prepared output must be a separate .epub file.",
            "Choose a new EPUB output path outside the source PDF.",
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    xml_input = xml_path.expanduser()
    root = _read_xml(xml_input)
    xml = xml_input.resolve()
    pages = _parse_pages(root, xml)
    declared_pages = inspection.get("pages")
    if not isinstance(declared_pages, int) or declared_pages != len(pages):
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "Converted page count does not match the inspected PDF.",
            "Rerun inspection and conversion from the same PDF source.",
        )
    artifacts = _edge_artifacts(pages)
    outline_entries = _outline_entries(root, pages)
    book_title = _title_from(title, inspection, pages, pdf)
    creator = _creator_from(inspection)
    documents, images, metrics = _render_documents(
        pages,
        artifacts=artifacts,
        outline_entries=outline_entries,
        language=language,
        book_title=book_title,
    )
    if int(metrics["preserved_text_nodes"]) <= 0:
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "PDF conversion contains no semantic text after edge-artifact removal.",
            "Review the source pages, repair the text layer, or use authorized OCR.",
        )
    if int(metrics["source_text_nodes"]) != (
        int(metrics["preserved_text_nodes"]) + int(metrics["removed_artifact_nodes"])
    ):
        raise _fail(
            "PDF_SOURCE_INCOMPLETE",
            "Extracted text nodes were not fully accounted for.",
            "Inspect the conversion receipt and repair the source before retrying.",
        )
    complex_pages = _complex_layout_pages(pages, artifacts)
    source_before = _sha256(pdf)
    if source_before != expected_hash:
        raise _fail(
            "PDF_SOURCE_CHANGED",
            "PDF source changed after semantic extraction.",
            "Discard the conversion workspace, reinspect the stable PDF, and retry.",
        )
    temporary: Path | None = None
    published = False
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        _write_epub(
            temporary,
            title=book_title,
            creator=creator,
            language=language,
            source=pdf,
            inspection=inspection,
            pages=pages,
            documents=documents,
            images=images,
            metrics=metrics,
            complex_pages=complex_pages,
        )
        if output.exists():
            if not output.is_file() or _sha256(output) != _sha256(temporary):
                raise _fail(
                    "PDF_OUTPUT_EXISTS",
                    f"Prepared EPUB already exists with different content: {output.name}.",
                    "Choose a new output path or explicitly remove the obsolete candidate.",
                )
            written = False
        else:
            if _sha256(pdf) != expected_hash:
                raise _fail(
                    "PDF_SOURCE_CHANGED",
                    "PDF source changed before prepared output publication.",
                    "Discard the candidate, reinspect the stable PDF, and retry.",
                )
            os.replace(temporary, output)
            temporary = None
            written = True
            published = True
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    if source_before != _sha256(pdf):
        if published and output.is_file():
            output.unlink()
        raise _fail(
            "PDF_SOURCE_CHANGED",
            "PDF source changed during preparation.",
            "Discard the prepared candidate, restore the source, and rerun inspection.",
        )
    return {
        "status": "source_review_required",
        "schema_version": 1,
        "source": {
            "name": pdf.name,
            "sha256": actual_hash,
            "format": "pdf",
        },
        "output": output.name,
        "written": written,
        "source_readiness": "review_required",
        "pages": len(pages),
        "page_anchors": len(pages),
        "outline_entries": len(outline_entries),
        "source_text_nodes": metrics["source_text_nodes"],
        "preserved_text_nodes": metrics["preserved_text_nodes"],
        "removed_artifact_nodes": metrics["removed_artifact_nodes"],
        "text_nodes_accounted": True,
        "images_preserved": len(images),
        "cover_preserved": any(image.get("cover") is True for image in images),
        "complex_layout_pages": complex_pages,
        "next_action": (
            "Render representative prepared EPUB sections and compare reading order, "
            "images, and complex-layout pages with the PDF before running bookstudio start."
        ),
    }


def prepare_pdf(
    source: Path,
    destination: Path,
    *,
    source_language: str | None = None,
    title: str | None = None,
    runner: ToolRunner | None = None,
) -> dict[str, Any]:
    """Inspect and convert a text-layer PDF to a semantic, review-gated EPUB."""
    inspection = inspect_pdf(source, runner=runner)
    classification = inspection["text"]["classification"]
    if classification == "image_only":
        raise _fail(
            "PDF_OCR_REQUIRED",
            "PDF has no usable text layer.",
            "Run authorized OCR with the correct language pack, review it, then reinspect.",
            exit_code=2,
        )
    if classification != "text_layer_sufficient":
        raise _fail(
            "PDF_MIXED_SOURCE_REVIEW_REQUIRED",
            "PDF contains sparse or mixed text extraction.",
            "Review text coverage and repair or OCR affected pages before preparation.",
            exit_code=2,
        )
    pdf = _validate_pdf_source(source)
    with tempfile.TemporaryDirectory(prefix="bookstudio-pdf-") as directory:
        workspace = Path(directory)
        prefix = workspace / "source"
        _run_checked(
            [
                _tool("pdftohtml", runner),
                "-xml",
                "-hidden",
                "-q",
                str(pdf),
                str(prefix),
            ],
            runner=runner,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            code="PDF_TEXT_EXTRACTION_FAILED",
            action="Inspect the PDF layout and Poppler output before retrying.",
        )
        xml = prefix.with_suffix(".xml")
        return build_semantic_epub_from_xml(
            pdf,
            xml,
            destination,
            inspection,
            source_language=source_language,
            title=title,
        )
