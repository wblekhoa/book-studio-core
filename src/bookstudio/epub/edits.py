"""Declared, hash-pinned editorial edits applied inside the deterministic build."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from ..config import ProjectConfig
from ..errors import BookStudioError


EDITS_FILENAME = "edits.json"
_OPERATION_KEYS = {
    "replace_text": ({"op", "member", "find", "replace", "count"}, {"note"}),
    "replace_member": ({"op", "member", "base_sha256", "from", "sha256"}, {"note"}),
    "add_member": ({"op", "member", "from", "sha256"}, {"note"}),
}
_MARKUP_SUFFIXES = (".xhtml", ".html", ".htm", ".xml", ".opf", ".ncx", ".svg")
_SHA256 = re.compile(r"[0-9a-f]{64}")


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
    if relative.is_absolute() or ".." in relative.parts or "\\" in operation["from"]:
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


def _check_markup(member: str, data: bytes) -> None:
    if not member.lower().endswith(_MARKUP_SUFFIXES):
        return
    unsafe = _fail(
        "EDITS_UNSAFE_MARKUP",
        f"Edited markup is not well-formed or contains script, event handlers or javascript: links: {member}",
        "Remove scripts, on* attributes and javascript: URLs from the edit.",
    )
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise unsafe from error
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag.rsplit("}", 1)[-1].lower() == "script":
            raise unsafe
        for name, value in node.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on") or (
                local in {"href", "src"} and value.strip().lower().startswith("javascript:")
            ):
                raise unsafe


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
    for member in sorted(touched):
        _check_markup(member, result[index[member]][1])
    return result
