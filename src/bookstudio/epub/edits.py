"""Declared, hash-pinned editorial edits applied inside the deterministic build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from ..config import ProjectConfig, atomic_write_json
from ..errors import BookStudioError


EDITS_FILENAME = "edits.json"
_OPERATION_KEYS = {
    "replace_text": ({"op", "member", "find", "replace", "count"}, {"note"}),
    "replace_member": ({"op", "member", "base_sha256", "from", "sha256"}, {"note"}),
    "add_member": ({"op", "member", "from", "sha256"}, {"note"}),
}
_MARKUP_SUFFIXES = (".xhtml", ".html", ".htm", ".xml", ".opf", ".ncx", ".svg")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))})


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _schema(message: str) -> BookStudioError:
    return _fail(
        "EDITS_SCHEMA_INVALID",
        message,
        "Fix edits.json: schema_version 1 and only replace_text, replace_member or add_member operations.",
    )


def _safe_member(name: Any) -> str:
    posix = PurePosixPath(name) if isinstance(name, str) else None
    if (
        posix is None
        or not name
        or "\\" in name
        or name.startswith("/")
        or ".." in posix.parts
        or name == "mimetype"
        or name.endswith("/")
        or ":" in name
        or any(part != part.rstrip(". ") or part.split(".")[0].upper() in _WINDOWS_RESERVED for part in posix.parts)
    ):
        raise _schema(f"Unsafe or invalid EPUB member name in edits.json: {name!r}")
    return name


def load_edits(config: ProjectConfig) -> tuple[list[dict[str, Any]], str | None]:
    """Return validated operations and the edits file hash, or ([], None) without a file."""
    path = config.project_root / EDITS_FILENAME
    if not path.exists() and not path.is_symlink():
        return [], None
    if path.is_symlink() or not path.is_file():
        raise _schema("edits.json must be a regular file inside the project.")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise _schema(f"edits.json is not valid UTF-8 JSON: {type(error).__name__}") from error
    if (
        type(payload) is not dict
        or set(payload) != {"schema_version", "operations"}
        or payload.get("schema_version") != 1
        or type(payload.get("operations")) is not list
    ):
        raise _schema("edits.json must contain exactly schema_version 1 and an operations list.")
    operations = []
    for index, operation in enumerate(payload["operations"]):
        kind = operation.get("op") if type(operation) is dict else None
        if kind not in _OPERATION_KEYS:
            raise _schema(f"Operation {index} has an unsupported op: {kind!r}.")
        required, optional = _OPERATION_KEYS[kind]
        keys = set(operation)
        if not required <= keys or keys - required - optional:
            raise _schema(f"Operation {index} ({kind}) must use exactly the keys {sorted(required)} plus optional note.")
        _safe_member(operation["member"])
        if "note" in operation and type(operation["note"]) is not str:
            raise _schema(f"Operation {index} note must be text.")
        if kind == "replace_text":
            if (
                type(operation["find"]) is not str
                or not operation["find"]
                or type(operation["replace"]) is not str
                or type(operation["count"]) is not int
                or operation["count"] < 1
            ):
                raise _schema(f"Operation {index} needs non-empty find text, replace text and a count of at least 1.")
        else:
            hashes = [operation["sha256"]] + ([operation["base_sha256"]] if kind == "replace_member" else [])
            if any(type(value) is not str or not _SHA256.fullmatch(value) for value in hashes):
                raise _schema(f"Operation {index} hashes must be lowercase SHA-256 hex.")
            if type(operation["from"]) is not str or not operation["from"]:
                raise _schema(f"Operation {index} needs a project-relative 'from' path.")
        operations.append(operation)
    return operations, hashlib.sha256(raw).hexdigest()


def _asset_bytes(config: ProjectConfig, operation: dict[str, Any]) -> bytes:
    invalid = _fail(
        "EDITS_ASSET_INVALID",
        f"Edit asset is missing, outside the project, a symlink, or has a different SHA-256: {operation['from']}",
        "Keep edit assets as regular files inside the project and pin their current SHA-256 in edits.json.",
    )
    relative = PurePosixPath(operation["from"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in operation["from"] or ":" in operation["from"]:
        raise invalid
    path = config.project_root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise invalid
    if not path.is_file():
        raise invalid
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != operation["sha256"]:
        raise invalid
    return data


_ACTIVE_ELEMENTS = frozenset(
    {
        "script", "iframe", "frame", "frameset", "object", "embed", "applet", "form", "base",
        "animate", "set", "animatemotion", "animatetransform", "foreignobject",
        "button", "input", "textarea", "select", "portal",
    }
)
_LINK_ATTRIBUTES = frozenset({"href"})
_RESOURCE_ATTRIBUTES = frozenset(
    {"src", "data", "action", "formaction", "poster", "background", "srcset", "codebase", "usemap", "longdesc", "cite"}
)
_MARKUP_MEDIA_TYPES = ("application/xhtml+xml", "text/html", "image/svg+xml", "application/xml", "text/xml")


def _unsafe(member: str, reason: str) -> BookStudioError:
    return _fail(
        "EDITS_UNSAFE_MARKUP",
        f"Edited markup in {member} is unsafe: {reason}",
        "Use plain XHTML: relative links, http(s)/mailto anchors, and local images only.",
    )


def _scheme(value: str) -> str:
    # urlsplit drops tab/newline; also drop other control characters a reader would ignore.
    cleaned = "".join(char for char in value if ord(char) > 0x20 or char == " ").strip()
    return urlsplit(cleaned).scheme.lower()


def _check_markup(member: str, data: bytes) -> None:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise _unsafe(member, "not well-formed XML") from error
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in _ACTIVE_ELEMENTS:
            raise _unsafe(member, f"<{tag}> is not allowed")
        if tag == "meta" and any(key.rsplit("}", 1)[-1].lower() == "http-equiv" for key in node.attrib):
            raise _unsafe(member, "<meta http-equiv> is not allowed")
        if tag == "style" and re.search(r"@import|url\s*\(\s*['\"]?\s*[a-z][a-z0-9+.-]*:", node.text or "", re.I):
            raise _unsafe(member, "external resources in <style>")
        for name, value in node.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on") or local == "srcdoc":
                raise _unsafe(member, f"attribute {local}")
            if local == "style" and re.search(r"url\s*\(|expression\s*\(|javascript:", value, re.I):
                raise _unsafe(member, "active style attribute")
            if local in _LINK_ATTRIBUTES and _scheme(value) not in {"", "http", "https", "mailto"}:
                raise _unsafe(member, f"{local} scheme {_scheme(value)!r}")
            if local in _RESOURCE_ATTRIBUTES and _scheme(value):
                raise _unsafe(member, f"{local} must reference a file inside the book")


def _markup_members(members: list[tuple[zipfile.ZipInfo, bytes]]) -> set[str]:
    """Members a reader would parse as markup, by suffix or by manifest media-type."""
    data = {info.filename: content for info, content in members}
    names = {name for name in data if name.lower().endswith(_MARKUP_SUFFIXES)}
    try:
        container = ET.fromstring(data.get("META-INF/container.xml", b""))
        rootfile = next(node for node in container.iter() if str(node.tag).endswith("rootfile"))
        opf_path = rootfile.attrib["full-path"]
        package = ET.fromstring(data[opf_path])
    except (ET.ParseError, StopIteration, KeyError):
        return names
    base = PurePosixPath(opf_path).parent
    for node in package.iter():
        if str(node.tag).endswith("item") and node.attrib.get("media-type", "").startswith(_MARKUP_MEDIA_TYPES):
            href = unquote(node.attrib.get("href", "").split("#", 1)[0])
            parts: list[str] = []
            for part in (base / href).parts:
                if part == "..":
                    if parts:
                        parts.pop()
                elif part not in {"", "."}:
                    parts.append(part)
            names.add("/".join(parts))
    return names


def apply_edits(
    config: ProjectConfig,
    members: list[tuple[zipfile.ZipInfo, bytes]],
    operations: list[dict[str, Any]],
) -> list[tuple[zipfile.ZipInfo, bytes]]:
    """Apply operations in order to (info, bytes) members; additions are appended in declared order."""
    index = {info.filename: position for position, (info, _) in enumerate(members)}
    result = list(members)
    touched: set[str] = set()
    for number, operation in enumerate(operations):
        member = operation["member"]
        kind = operation["op"]
        if kind == "add_member":
            if member in index:
                raise _fail(
                    "EDITS_MEMBER_EXISTS",
                    f"Operation {number} adds a member that already exists: {member}",
                    "Use replace_member for existing members.",
                )
            template = result[0][0]
            info = zipfile.ZipInfo(member, date_time=template.date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = template.create_system
            info.external_attr = 0o100644 << 16
            index[member] = len(result)
            result.append((info, _asset_bytes(config, operation)))
            touched.add(member)
            continue
        if member not in index:
            raise _fail(
                "EDITS_MEMBER_MISSING",
                f"Operation {number} targets a member the build did not produce: {member}",
                "Check the member path against the built EPUB.",
            )
        info, data = result[index[member]]
        if kind == "replace_member":
            if hashlib.sha256(data).hexdigest() != operation["base_sha256"]:
                raise _fail(
                    "EDITS_BASE_STALE",
                    f"Operation {number}: the built {member} no longer matches base_sha256.",
                    "Review the new build output, refresh the replacement file, then update both hashes.",
                )
            data = _asset_bytes(config, operation)
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise _schema(f"Operation {number} replace_text targets a non-UTF-8 member: {member}") from error
            found = text.count(operation["find"])
            if found != operation["count"]:
                raise _fail(
                    "EDITS_TEXT_COUNT_MISMATCH",
                    f"Operation {number}: expected {operation['count']} match(es) in {member}, found {found}.",
                    "Review the build output and update find text or count in edits.json.",
                )
            data = text.replace(operation["find"], operation["replace"]).encode("utf-8")
        result[index[member]] = (info, data)
        touched.add(member)
    markup = _markup_members(result)
    for member in sorted(touched & markup):
        _check_markup(member, result[index[member]][1])
    return result


def _write_asset(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _capture_invalid(reason: str) -> BookStudioError:
    return _fail(
        "EDITS_ASSET_INVALID",
        f"Cannot capture edits safely: {reason}.",
        "Remove symlinks under assets/, and make member names unique, case-insensitively and without file/folder clashes.",
    )


def _check_capture_destinations(config: ProjectConfig, destinations: list[Path]) -> None:
    root = config.project_root
    seen: dict[str, Path] = {}
    files = {destination.relative_to(root).as_posix().casefold() for destination in destinations}
    for destination in destinations:
        relative = destination.relative_to(root)
        key = unicodedata.normalize("NFC", relative.as_posix()).casefold()
        if key in seen:
            raise _capture_invalid(f"{relative.as_posix()} collides with {seen[key].relative_to(root).as_posix()}")
        seen[key] = destination
        parents = [parent.casefold() for parent in relative.as_posix().split("/")[:-1]]
        for depth in range(1, len(parents) + 1):
            if "/".join(parents[:depth]) in files:
                raise _capture_invalid(f"{relative.as_posix()} needs a folder where another captured file goes")
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise _capture_invalid(f"{current.relative_to(root).as_posix()} is a symlink")
        if destination.exists() and not destination.is_file():
            raise _capture_invalid(f"{relative.as_posix()} exists and is not a file")


def capture_edits(config: ProjectConfig, edited: Path) -> dict[str, Any]:
    """Express an EPUB edited elsewhere as edits.json against the plain core build."""
    from .archive import preflight_archive
    from .build import build_epub

    if (config.project_root / EDITS_FILENAME).exists():
        raise _fail(
            "EDITS_ALREADY_DECLARED",
            "This project already declares edits.json; capture never overwrites it.",
            "Move the existing edits.json aside after review, then capture again.",
        )
    preflight_archive(edited)
    with tempfile.TemporaryDirectory(dir=config.project_root, prefix=".capture-") as directory:
        base_path = Path(directory) / "base.epub"
        build_epub(config, base_path, apply_declared_edits=False)
        with zipfile.ZipFile(base_path) as archive:
            base = {name: archive.read(name) for name in archive.namelist()}
    with zipfile.ZipFile(edited) as archive:
        target = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    removed = sorted(name for name in base if name not in target and not name.endswith("/"))
    if removed:
        raise _fail(
            "EDITS_CAPTURE_DELETION",
            f"The edited EPUB removes {len(removed)} member(s), which edits.json cannot express: {removed[0]}",
            "Keep every built member in the edited EPUB, then capture again.",
        )
    operations = []
    pending: list[tuple[Path, bytes]] = []
    for name in sorted(target):
        data = target[name]
        if base.get(name) == data:
            continue
        _safe_member(name)
        relative = PurePosixPath("assets/edits") / name
        destination = config.project_root / relative
        if destination.is_file() and not destination.is_symlink() and destination.read_bytes() != data:
            raise _fail(
                "EDITS_ASSET_CONFLICT",
                f"A different file already exists at {relative.as_posix()}.",
                "Move the existing assets/edits folder aside after review, then capture again.",
            )
        pending.append((destination, data))
        operation: dict[str, Any] = {"op": "replace_member", "member": name, "base_sha256": hashlib.sha256(base[name]).hexdigest()} if name in base else {"op": "add_member", "member": name}
        operation.update({"from": relative.as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "note": "captured from an edited EPUB"})
        operations.append(operation)
    if not operations:
        return {
            "status": "no_changes",
            "schema_version": 1,
            "operations": 0,
            "message": "The edited EPUB matches the plain core build; nothing to declare.",
        }
    _check_capture_destinations(config, [destination for destination, _ in pending])
    try:
        for destination, data in pending:
            _write_asset(destination, data)
    except OSError as error:
        raise _capture_invalid(f"could not write {destination.name}: {type(error).__name__}") from error
    atomic_write_json(config.project_root / EDITS_FILENAME, {"schema_version": 1, "operations": operations})
    load_edits(config)
    return {
        "status": "pass",
        "schema_version": 1,
        "operations": len(operations),
        "written": EDITS_FILENAME,
        "assets": "assets/edits/",
        "next_action": "Review edits.json, then run 'bookstudio finish PROJECT'.",
        "message": f"Captured {len(operations)} edit operation(s) into edits.json.",
    }
