#!/usr/bin/env python3
"""Audit final EPUB gaps that structural translation coverage can miss."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


MAX_XML_BYTES = 24 * 1024 * 1024
EPUB_NS = "http://www.idpf.org/2007/ops"
REVIEW_TAGS = frozenset({"figcaption", "caption", "th", "td", "text", "desc"})
REVIEW_ATTRIBUTES = frozenset({"alt", "title", "aria-label"})
OPENING_TEXT_TAGS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "dt", "dd"}
)
# ``bodymatter`` is too broad to identify the first real chapter. PDF-derived
# EPUBs commonly apply it to forewords, introductions, and other opening pages.
# Stop only at an explicit chapter/part signal.
BODY_START_TYPES = frozenset({"chapter", "part"})
OPENING_SPINE_LIMIT = 8
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


class AuditError(Exception):
    """Raised when an input cannot be audited safely."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in DEFAULT_IGNORABLE_RANGES)


def _has_visible_text(value: str) -> bool:
    return any(
        not character.isspace()
        and unicodedata.category(character)
        not in {"Cc", "Cf", "Cn", "Cs", "Zl", "Zp", "Zs"}
        and not unicodedata.category(character).startswith("M")
        and not _is_default_ignorable(character)
        for character in value
    )


def _has_letters(value: str) -> bool:
    return any(unicodedata.category(character).startswith("L") for character in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise AuditError("The EPUB contains an unsafe archive member name.")
    if ".." in name.split("/"):
        raise AuditError("The EPUB contains an unsafe archive member path.")
    normalized = posixpath.normpath(name)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise AuditError("The EPUB contains an unsafe archive member path.")
    return normalized


def _resolve_member(base_path: str, href: str) -> tuple[str, str] | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = unquote(parsed.path)
    target = base_path if not raw_path else posixpath.join(posixpath.dirname(base_path), raw_path)
    return _safe_member_name(posixpath.normpath(target)), unquote(parsed.fragment)


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise AuditError("The EPUB references a missing XML resource.") from exc
    if info.file_size > MAX_XML_BYTES:
        raise AuditError("An EPUB XML resource exceeds the audit size limit.")
    try:
        return ET.fromstring(archive.read(info))
    except ET.ParseError as exc:
        raise AuditError("The EPUB contains malformed XML.") from exc


class EpubSnapshot:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if not self.path.is_file():
            raise AuditError("An EPUB input does not exist or is not a file.")
        if not zipfile.is_zipfile(self.path):
            raise AuditError("An EPUB input is not a readable ZIP archive.")
        self.archive = zipfile.ZipFile(self.path)
        names = [_safe_member_name(info.filename) for info in self.archive.infolist()]
        if len(names) != len(set(names)):
            self.archive.close()
            raise AuditError("The EPUB contains duplicate archive member names.")
        self.names = frozenset(names)
        if "META-INF/container.xml" not in self.names:
            self.archive.close()
            raise AuditError("The EPUB has no META-INF/container.xml.")
        container = _read_xml(self.archive, "META-INF/container.xml")
        rootfile = next(
            (
                node.attrib.get("full-path")
                for node in container.iter()
                if _local_name(node.tag) == "rootfile" and node.attrib.get("full-path")
            ),
            None,
        )
        if rootfile is None:
            self.archive.close()
            raise AuditError("The EPUB container has no package rootfile.")
        self.opf_path = _safe_member_name(rootfile)
        self.package = _read_xml(self.archive, self.opf_path)
        self.manifest: dict[str, dict[str, str]] = {}
        for node in self.package.iter():
            if _local_name(node.tag) != "item" or not node.attrib.get("id"):
                continue
            resolved = _resolve_member(self.opf_path, node.attrib.get("href", ""))
            if resolved is None:
                continue
            path_value, _ = resolved
            self.manifest[node.attrib["id"]] = {
                "path": path_value,
                "media_type": node.attrib.get("media-type", ""),
                "properties": node.attrib.get("properties", ""),
            }
        self.spine_paths = tuple(
            self.manifest[idref]["path"]
            for node in self.package.iter()
            if _local_name(node.tag) == "itemref"
            and (idref := node.attrib.get("idref")) in self.manifest
        )
        self.xhtml_paths = frozenset(
            row["path"]
            for row in self.manifest.values()
            if row["media_type"] in {"application/xhtml+xml", "text/html"}
            and row["path"] in self.names
        )
        self.nav_paths = frozenset(
            row["path"]
            for row in self.manifest.values()
            if "nav" in row["properties"].split() and row["path"] in self.names
        )
        self.ncx_paths = frozenset(
            row["path"]
            for row in self.manifest.values()
            if row["media_type"] == "application/x-dtbncx+xml"
            and row["path"] in self.names
        )
        self._documents: dict[str, ET.Element] = {}

    def close(self) -> None:
        self.archive.close()

    def document(self, path: str) -> ET.Element:
        if path not in self._documents:
            self._documents[path] = _read_xml(self.archive, path)
        return self._documents[path]

    def metadata_values(self, names: Iterable[str]) -> dict[str, Counter[str]]:
        wanted = set(names)
        result: dict[str, Counter[str]] = {name: Counter() for name in wanted}
        for node in self.package.iter():
            name = _local_name(node.tag)
            if name in wanted:
                value = _clean_text("".join(node.itertext()))
                if value and _has_letters(value):
                    result[name][value] += 1
        return result

    def navigation_entries(self) -> dict[str, list[tuple[str, str]]]:
        entries: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for path in sorted(self.nav_paths):
            root = self.document(path)
            toc_nodes = [
                node
                for node in root.iter()
                if _local_name(node.tag) == "nav"
                and "toc"
                in node.attrib.get(f"{{{EPUB_NS}}}type", node.attrib.get("epub:type", "")).split()
            ]
            for toc in toc_nodes:
                for node in toc.iter():
                    if _local_name(node.tag) != "a" or not node.attrib.get("href"):
                        continue
                    resolved = _resolve_member(path, node.attrib["href"])
                    if resolved is None:
                        continue
                    target_path, fragment = resolved
                    label = _clean_text("".join(node.itertext()))
                    entries[path].append((f"{target_path}#{fragment}", label))
        for path in sorted(self.ncx_paths):
            root = _read_xml(self.archive, path)
            for nav_point in root.iter():
                if _local_name(nav_point.tag) != "navPoint":
                    continue
                content = next(
                    (
                        node
                        for node in nav_point.iter()
                        if _local_name(node.tag) == "content" and node.attrib.get("src")
                    ),
                    None,
                )
                if content is None:
                    continue
                resolved = _resolve_member(path, content.attrib["src"])
                if resolved is None:
                    continue
                target_path, fragment = resolved
                label_node = next(
                    (
                        node
                        for node in nav_point.iter()
                        if _local_name(node.tag) == "navLabel"
                    ),
                    None,
                )
                label = ""
                if label_node is not None:
                    label = _clean_text("".join(label_node.itertext()))
                entries[path].append((f"{target_path}#{fragment}", label))
        return dict(entries)

    def opening_paths(self) -> tuple[str, ...]:
        """Return a bounded leading scope, stopping before an explicit body chapter."""
        result: list[str] = []
        for path in self.spine_paths:
            if path not in self.xhtml_paths or path in self.nav_paths:
                continue
            root = self.document(path)
            if result and _looks_like_body_start(path, root):
                break
            result.append(path)
            if len(result) >= OPENING_SPINE_LIMIT:
                break
        return tuple(result)


def _looks_like_body_start(path: str, root: ET.Element) -> bool:
    semantic_types: set[str] = set()
    for node in root.iter():
        value = node.attrib.get(
            f"{{{EPUB_NS}}}type", node.attrib.get("epub:type", "")
        )
        semantic_types.update(value.casefold().split())
    if semantic_types & BODY_START_TYPES:
        return True

    basename = posixpath.basename(path).casefold()
    if "chapter" in basename or re.search(r"(?:^|[-_.])ch(?:apter)?[-_.]?\d", basename):
        return True
    label = next(
        (
            _clean_text("".join(node.itertext())).casefold()
            for node in root.iter()
            if _local_name(node.tag) in {"title", "h1", "h2"}
            and _clean_text("".join(node.itertext()))
        ),
        "",
    )
    return label.startswith("chapter ") or label.startswith("part ")


def _is_substantive_opening_text(value: str) -> bool:
    letters = sum(
        1 for character in value if unicodedata.category(character).startswith("L")
    )
    return letters >= 12


def _count_shared_opening_text(
    source: EpubSnapshot, output: EpubSnapshot
) -> dict[tuple[str, str, str], int]:
    findings: Counter[tuple[str, str, str]] = Counter()
    for path in source.opening_paths():
        if path not in output.xhtml_paths:
            continue
        source_root = source.document(path)
        output_root = output.document(path)
        for tag in OPENING_TEXT_TAGS:
            source_values = Counter(
                value
                for node in source_root.iter()
                if _local_name(node.tag) == tag
                and (value := _clean_text("".join(node.itertext())))
                and _is_substantive_opening_text(value)
            )
            output_values = Counter(
                value
                for node in output_root.iter()
                if _local_name(node.tag) == tag
                and (value := _clean_text("".join(node.itertext())))
                and _is_substantive_opening_text(value)
            )
            shared = sum((source_values & output_values).values())
            if shared:
                findings[("unchanged_opening_text", path, tag)] += shared
    return dict(findings)


def _count_shared_values(
    source: EpubSnapshot, output: EpubSnapshot
) -> dict[tuple[str, str, str], int]:
    findings: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(source.xhtml_paths & output.xhtml_paths):
        source_root = source.document(path)
        output_root = output.document(path)
        for tag in REVIEW_TAGS | {"title"}:
            source_values = Counter(
                value
                for node in source_root.iter()
                if _local_name(node.tag) == tag
                and (value := _clean_text("".join(node.itertext())))
                and _has_letters(value)
            )
            output_values = Counter(
                value
                for node in output_root.iter()
                if _local_name(node.tag) == tag
                and (value := _clean_text("".join(node.itertext())))
                and _has_letters(value)
            )
            shared = sum((source_values & output_values).values())
            if shared:
                findings[(f"unchanged_{tag}", path, tag)] += shared
        for attribute in REVIEW_ATTRIBUTES:
            source_values = Counter(
                value
                for node in source_root.iter()
                if (value := _clean_text(node.attrib.get(attribute, "")))
                and _has_letters(value)
            )
            output_values = Counter(
                value
                for node in output_root.iter()
                if (value := _clean_text(node.attrib.get(attribute, "")))
                and _has_letters(value)
            )
            shared = sum((source_values & output_values).values())
            if shared:
                findings[(f"unchanged_{attribute.replace('-', '_')}", path, attribute)] += shared
    source_metadata = source.metadata_values({"title", "description"})
    output_metadata = output.metadata_values({"title", "description"})
    for name in sorted(source_metadata):
        shared = sum((source_metadata[name] & output_metadata[name]).values())
        if shared:
            findings[(f"unchanged_metadata_{name}", source.opf_path, name)] += shared
    return dict(findings)


def _navigation_findings(
    source: EpubSnapshot, output: EpubSnapshot
) -> tuple[dict[tuple[str, str, str], int], dict[tuple[str, str, str], int]]:
    hard: Counter[tuple[str, str, str]] = Counter()
    review: Counter[tuple[str, str, str]] = Counter()
    source_resources = source.navigation_entries()
    output_resources = output.navigation_entries()
    for resource, source_rows in source_resources.items():
        output_rows = output_resources.get(resource, [])
        source_map = dict(source_rows)
        output_map = dict(output_rows)
        for target, label in source_map.items():
            if target not in output_map:
                hard[("navigation_entry_missing", resource, target.split("#", 1)[0])] += 1
            elif label and label == output_map[target] and _has_letters(label):
                review[("unchanged_navigation_label", resource, target.split("#", 1)[0])] += 1
        grouped: dict[str, list[str]] = defaultdict(list)
        for target, label in source_rows:
            base, fragment = target.split("#", 1)
            if fragment:
                grouped[base].append(target)
        for base, targets in grouped.items():
            distinct_targets = set(targets)
            source_labels = {source_map[target] for target in distinct_targets if source_map[target]}
            matching_output = [output_map[target] for target in distinct_targets if target in output_map]
            if (
                len(distinct_targets) >= 2
                and len(source_labels) >= 2
                and len(matching_output) == len(distinct_targets)
                and len(set(matching_output)) == 1
            ):
                hard[("navigation_label_collapse", resource, base)] += len(distinct_targets)
    for resource in sorted(set(output_resources) - set(source_resources)):
        review[("added_navigation_resource", resource, resource)] += len(output_resources[resource])
    return dict(hard), dict(review)


def _invisible_translations(output: EpubSnapshot) -> dict[tuple[str, str, str], int]:
    findings: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(output.xhtml_paths):
        root = output.document(path)
        for node in root.iter():
            if "bs-translation" not in node.attrib.get("class", "").split():
                continue
            has_visual = any(
                _local_name(descendant.tag) in {"img", "svg", "image", "object"}
                for descendant in node.iter()
            )
            if not has_visual and not _has_visible_text("".join(node.itertext())):
                findings[("invisible_translation", path, _local_name(node.tag))] += 1
    return dict(findings)


def _render_findings(rows: dict[tuple[str, str, str], int]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    totals: Counter[str] = Counter()
    for (code, path, role), count in sorted(rows.items()):
        totals[code] += count
        grouped[code].append({"path": path, "role": role, "count": count})
    return [
        {
            "code": code,
            "count": totals[code],
            "locations": grouped[code][:50],
            "omitted_locations": max(0, len(grouped[code]) - 50),
        }
        for code in sorted(grouped)
    ]


def audit(source_path: Path, output_path: Path) -> dict[str, object]:
    source = EpubSnapshot(source_path)
    output = EpubSnapshot(output_path)
    try:
        hard_rows = Counter(_invisible_translations(output))
        nav_hard, nav_review = _navigation_findings(source, output)
        hard_rows.update(nav_hard)
        review_rows = Counter(_count_shared_values(source, output))
        review_rows.update(_count_shared_opening_text(source, output))
        review_rows.update(nav_review)
        hard = _render_findings(dict(hard_rows))
        review = _render_findings(dict(review_rows))
        status = "error" if hard else "review_required" if review else "pass"
        return {
            "schema_version": 1,
            "status": status,
            "passed": status == "pass",
            "source_sha256": _sha256(source.path),
            "output_sha256": _sha256(output.path),
            "documents_compared": len(source.xhtml_paths & output.xhtml_paths),
            "opening_documents_compared": len(
                set(source.opening_paths()) & output.xhtml_paths
            ),
            "hard_failures": hard,
            "review_findings": review,
        }
    finally:
        source.close()
        output.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find final EPUB gaps that canonical translation coverage can miss."
    )
    parser.add_argument("--source", required=True, type=Path, help="Source semantic EPUB")
    parser.add_argument("--output", required=True, type=Path, help="Final candidate EPUB")
    parser.add_argument("--json", action="store_true", help="Emit a JSON receipt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = audit(args.source, args.output)
    except (AuditError, OSError, zipfile.BadZipFile) as exc:
        receipt = {
            "schema_version": 1,
            "status": "error",
            "passed": False,
            "code": "EPUB_AUDIT_INVALID",
            "message": str(exc),
            "hard_failures": [],
            "review_findings": [],
        }
        exit_code = 1
    else:
        exit_code = 1 if receipt["status"] == "error" else 2 if receipt["status"] == "review_required" else 0
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"{receipt['status']}: {len(receipt.get('hard_failures', []))} hard class(es), "
            f"{len(receipt.get('review_findings', []))} review class(es)"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
