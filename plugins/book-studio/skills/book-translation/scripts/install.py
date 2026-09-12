#!/usr/bin/env python3
"""Validate and atomically install the bundled Book Translation skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit


SKILL_NAME = "book-translation"
REQUIRED_FILES = ("SKILL.md", "agents/openai.yaml")
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
GENERATED_NAMES = frozenset({"__pycache__", ".DS_Store"})
EXIT_OK = 0
EXIT_OPERATIONAL_ERROR = 1
EXIT_CHECK_MISMATCH = 2
EXIT_SOURCE_INVALID = 3


class SourceInvalidError(ValueError):
    """The bundled source skill is not safe or structurally valid."""


class InstallError(RuntimeError):
    """The destination could not be installed or inspected safely."""


def _default_destination_root() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    codex_home = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return codex_home / "skills"


def _nodes(root: Path) -> Iterator[Path]:
    if root.is_symlink() or not root.is_dir():
        raise SourceInvalidError(f"Skill root must be a non-symlink directory: {root}")
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in directories:
            path = current_path / name
            if name in GENERATED_NAMES:
                raise SourceInvalidError(
                    f"Skill package contains generated state: {path.relative_to(root)}"
                )
            if path.is_symlink():
                raise SourceInvalidError(
                    f"Skill package contains a symlink: {path.relative_to(root)}"
                )
            if not path.is_dir():
                raise SourceInvalidError(
                    f"Skill package contains a non-directory node: {path.relative_to(root)}"
                )
            yield path
        for name in files:
            path = current_path / name
            if name in GENERATED_NAMES or path.suffix.casefold() == ".pyc":
                raise SourceInvalidError(
                    f"Skill package contains generated state: {path.relative_to(root)}"
                )
            if path.is_symlink():
                raise SourceInvalidError(
                    f"Skill package contains a symlink: {path.relative_to(root)}"
                )
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode):
                raise SourceInvalidError(
                    f"Skill package contains a non-regular file: {path.relative_to(root)}"
                )
            yield path


def _frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SourceInvalidError("SKILL.md must start with YAML frontmatter.")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise SourceInvalidError("SKILL.md frontmatter is not closed.") from exc

    values: dict[str, str] = {}
    for line in lines[1:closing]:
        match = re.match(r"^(name|description):\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("'\"")
    if not values.get("name") or not values.get("description"):
        raise SourceInvalidError(
            "SKILL.md frontmatter must contain nonempty name and description fields."
        )
    if values["name"] != SKILL_NAME:
        raise SourceInvalidError(
            f"SKILL.md name must be {SKILL_NAME!r}, not {values['name']!r}."
        )
    return values


def _reference_target(markdown: Path, raw_target: str, root: Path) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith("#"):
        return None
    path_text = unquote(parsed.path)
    if not path_text:
        return None
    relative = Path(path_text)
    if relative.is_absolute():
        raise SourceInvalidError(
            f"Markdown link must stay inside the skill: {markdown.relative_to(root)}"
        )
    candidate = (markdown.parent / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise SourceInvalidError(
            f"Markdown link escapes the skill: {markdown.relative_to(root)}"
        ) from exc
    return candidate


def validate_skill(root: Path) -> None:
    root = root.expanduser()
    if root.is_symlink():
        raise SourceInvalidError(f"Skill root must not be a symlink: {root}")
    root = root.resolve()
    all_nodes = list(_nodes(root))
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise SourceInvalidError(f"Required skill file is missing: {relative}")
    _frontmatter(root / "SKILL.md")

    for markdown in sorted(
        (path for path in all_nodes if path.is_file() and path.suffix.casefold() == ".md"),
        key=lambda path: path.relative_to(root).as_posix(),
    ):
        text = markdown.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = _reference_target(markdown, raw_target, root)
            if target is not None and (not target.is_file() or target.is_symlink()):
                raise SourceInvalidError(
                    "Markdown link does not resolve to a regular skill resource: "
                    f"{markdown.relative_to(root)} -> {raw_target}"
                )


def tree_hash(root: Path) -> str:
    root = root.expanduser()
    if root.is_symlink():
        raise SourceInvalidError(f"Skill root must not be a symlink: {root}")
    root = root.resolve()
    files = sorted(
        (path for path in _nodes(root) if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    digest = hashlib.sha256(b"book-translation-skill-tree-v1\0")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _destination_hash(destination: Path) -> str | None:
    if not destination.exists() and not destination.is_symlink():
        return None
    if destination.is_symlink() or not destination.is_dir():
        raise InstallError(
            f"Destination must be a non-symlink directory when present: {destination}"
        )
    try:
        return tree_hash(destination)
    except SourceInvalidError as exc:
        raise InstallError(f"Destination is unsafe: {exc}") from exc


def _backup_path(destination_root: Path, destination_hash: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = destination_root / (
        f".{SKILL_NAME}.backup-{timestamp}-{destination_hash[:8]}"
    )
    candidate = base
    suffix = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = Path(f"{base}-{suffix}")
        suffix += 1
    return candidate


def _receipt(
    *,
    status: str,
    source: Path,
    destination: Path,
    source_hash: str | None,
    destination_hash: str | None,
    changed: bool,
    backup: Path | None = None,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "changed": changed,
        "source": str(source),
        "destination": str(destination),
        "source_sha256": source_hash,
        "destination_sha256": destination_hash,
        "backup": str(backup) if backup is not None else None,
        "message": message,
    }


def install_skill(
    source: Path,
    destination_root: Path,
    *,
    check: bool = False,
    dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    source = source.expanduser()
    if source.is_symlink():
        raise SourceInvalidError(f"Skill root must not be a symlink: {source}")
    source = source.resolve()
    destination_root = destination_root.expanduser().resolve()
    destination = destination_root / SKILL_NAME
    validate_skill(source)
    source_hash = tree_hash(source)

    if destination == source or source in destination.parents:
        raise InstallError("Destination cannot be the source skill or live inside it.")

    destination_hash = _destination_hash(destination)
    current = destination_hash == source_hash
    if check:
        if current:
            return (
                _receipt(
                    status="current",
                    source=source,
                    destination=destination,
                    source_hash=source_hash,
                    destination_hash=destination_hash,
                    changed=False,
                    message="Installed skill exactly matches the source package.",
                ),
                EXIT_OK,
            )
        status = "missing" if destination_hash is None else "stale"
        return (
            _receipt(
                status=status,
                source=source,
                destination=destination,
                source_hash=source_hash,
                destination_hash=destination_hash,
                changed=False,
                message="Install or update the skill to match the source package.",
            ),
            EXIT_CHECK_MISMATCH,
        )

    if current:
        return (
            _receipt(
                status="current",
                source=source,
                destination=destination,
                source_hash=source_hash,
                destination_hash=destination_hash,
                changed=False,
                message="Installed skill is already current; no files changed.",
            ),
            EXIT_OK,
        )

    if dry_run:
        status = "would_install" if destination_hash is None else "would_update"
        return (
            _receipt(
                status=status,
                source=source,
                destination=destination,
                source_hash=source_hash,
                destination_hash=destination_hash,
                changed=False,
                message="Dry run completed; no files changed.",
            ),
            EXIT_OK,
        )

    destination_root.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{SKILL_NAME}.install-", dir=destination_root)
    )
    backup: Path | None = None
    moved_existing = False
    promoted = False
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True, copy_function=shutil.copy2)
        validate_skill(stage)
        if tree_hash(stage) != source_hash:
            raise InstallError("Staged skill does not exactly match the source package.")

        if destination_hash is not None:
            backup = _backup_path(destination_root, destination_hash)
            os.replace(destination, backup)
            moved_existing = True
        try:
            os.replace(stage, destination)
            promoted = True
        except BaseException:
            if moved_existing and backup is not None and not destination.exists():
                os.replace(backup, destination)
                moved_existing = False
                backup = None
            raise

        installed_hash = tree_hash(destination)
        if installed_hash != source_hash:
            raise InstallError("Installed skill hash differs from the validated source.")
        status = "updated" if backup is not None else "installed"
        return (
            _receipt(
                status=status,
                source=source,
                destination=destination,
                source_hash=source_hash,
                destination_hash=installed_hash,
                changed=True,
                backup=backup,
                message=(
                    "Skill updated atomically; the previous installation is recoverable."
                    if backup is not None
                    else "Skill installed atomically."
                ),
            ),
            EXIT_OK,
        )
    except BaseException as exc:
        if promoted and destination.exists():
            try:
                os.replace(destination, stage)
                promoted = False
            except OSError as demote_error:
                raise InstallError(
                    "Install failed and the promoted package could not be moved aside for "
                    f"recovery: {demote_error}"
                ) from exc
        if moved_existing and backup is not None and not destination.exists():
            try:
                os.replace(backup, destination)
                moved_existing = False
                backup = None
            except OSError as restore_error:
                raise InstallError(
                    f"Install failed and automatic restore also failed: {restore_error}"
                ) from exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit, SourceInvalidError, InstallError)):
            raise
        raise InstallError(str(exc)) from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and atomically install the bundled Book Translation skill.",
        epilog=(
            "Exit codes: 0 success/current/dry-run; 1 operational failure; "
            "2 --check found a missing or stale install; 3 source package invalid."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Compare the installed skill with the source without changing files.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Describe the install or update without changing files.",
    )
    parser.add_argument(
        "--dest-root",
        type=Path,
        default=None,
        help=(
            "Skills directory. Defaults to "
            "${CODEX_HOME:-~/.codex}/skills; book-translation is appended."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a stable JSON receipt.",
    )
    return parser


def _emit(receipt: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"{receipt['status']}: {receipt['message']}")
    print(f"source: {receipt['source']}")
    print(f"destination: {receipt['destination']}")
    if receipt.get("backup"):
        print(f"backup: {receipt['backup']}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    source = Path(__file__).resolve().parents[1]
    destination_root = arguments.dest_root or _default_destination_root()
    try:
        receipt, exit_code = install_skill(
            source,
            destination_root,
            check=arguments.check,
            dry_run=arguments.dry_run,
        )
    except SourceInvalidError as exc:
        receipt = {
            "status": "error",
            "changed": False,
            "code": "SOURCE_SKILL_INVALID",
            "message": str(exc),
            "source": str(source),
            "destination": str(destination_root.expanduser() / SKILL_NAME),
        }
        exit_code = EXIT_SOURCE_INVALID
    except (InstallError, OSError) as exc:
        receipt = {
            "status": "error",
            "changed": False,
            "code": "SKILL_INSTALL_FAILED",
            "message": str(exc),
            "source": str(source),
            "destination": str(destination_root.expanduser() / SKILL_NAME),
        }
        exit_code = EXIT_OPERATIONAL_ERROR
    _emit(receipt, as_json=arguments.json)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
