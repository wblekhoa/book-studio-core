"""Allowlist-first scanner for the shareable Book Studio source tree."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterator


ALLOWED_TOP_LEVEL = frozenset(
    {
        ".gitignore",
        ".github",
        "AGENTS.md",
        "LICENSE",
        "pyproject.toml",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "src",
        "tests",
        "docs",
        "skills",
    }
)
ALLOWED_TEXT_SUFFIXES = frozenset({".py", ".md", ".toml", ".json", ".txt", ".yml", ".yaml"})
ALLOWED_EXTENSIONLESS_FILES = frozenset({"LICENSE"})
BOOK_SUFFIXES = frozenset({".epub", ".pdf", ".mobi", ".azw3"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
PRIVATE_DIRECTORIES = frozenset(
    {"projects", "outputs", "manifests", "reports", "ai-memory", "inputs", "cache", "working"}
)
_PERSONAL_PATH = re.compile(
    re.escape("/" + "Users" + "/")
    + "|"
    + re.escape("/" + "home" + "/")
    + "|"
    + r"[A-Za-z]:[\\/]+Users[\\/]",
    flags=re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SECRETS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
)


def _walk(root: Path) -> Iterator[Path]:
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir(), key=lambda item: item.name, reverse=True):
            if path.is_symlink():
                yield path
                continue
            if path == root / ".git" and path.is_dir():
                continue
            yield path
            if path.is_dir():
                pending.append(path)


def _row(category: str, relative: str, line: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"category": category, "path": relative}
    if line is not None:
        result["line"] = line
    return result


def audit_public_tree(root: Path) -> dict[str, Any]:
    base = root.expanduser().resolve()
    violations: list[dict[str, Any]] = []
    files_scanned = 0
    ignored_artifacts = 0
    if not base.is_dir():
        return {
            "status": "error",
            "passed": False,
            "files_scanned": 0,
            "ignored_artifacts": 0,
            "category_counts": {"root_missing": 1},
            "violations": [_row("root_missing", ".")],
        }

    for path in _walk(base):
        relative_path = path.relative_to(base)
        relative = relative_path.as_posix()
        top = relative_path.parts[0]
        if top not in ALLOWED_TOP_LEVEL:
            violations.append(_row("top_level_not_allowlisted", relative))
        if any(part in PRIVATE_DIRECTORIES for part in relative_path.parts):
            violations.append(_row("private_data_directory", relative))
        if path.is_symlink():
            violations.append(_row("symlink", relative))
            continue
        if path.is_dir():
            continue

        suffix = path.suffix.casefold()
        files_scanned += 1
        if suffix == ".pyc":
            violations.append(_row("compiled_artifact", relative))
            continue
        if suffix in BOOK_SUFFIXES:
            violations.append(_row("book_binary", relative))
            continue
        if suffix in IMAGE_SUFFIXES:
            violations.append(_row("binary_asset", relative))
            continue
        if (
            path.name != ".gitignore"
            and path.name not in ALLOWED_EXTENSIONLESS_FILES
            and suffix not in ALLOWED_TEXT_SUFFIXES
        ):
            violations.append(_row("file_type_not_allowlisted", relative))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            violations.append(_row("non_text_or_unreadable", relative))
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _PERSONAL_PATH.search(line):
                violations.append(_row("personal_path", relative, line_number))
            if _EMAIL.search(line):
                violations.append(_row("email", relative, line_number))
            if any(pattern.search(line) for pattern in _SECRETS):
                violations.append(_row("secret", relative, line_number))

    violations.sort(key=lambda row: (row["path"], row.get("line", 0), row["category"]))
    counts = Counter(row["category"] for row in violations)
    return {
        "status": "pass" if not violations else "error",
        "passed": not violations,
        "files_scanned": files_scanned,
        "ignored_artifacts": ignored_artifacts,
        "category_counts": dict(sorted(counts.items())),
        "violations": violations,
    }
