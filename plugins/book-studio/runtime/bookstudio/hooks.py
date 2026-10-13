"""Agent-host hooks: a guard for gate-owned files and a session-start status note.

Both read one JSON object on stdin (Claude Code hook input) and never raise: a hook
that crashes would block or confuse the host, so malformed input means "no opinion".
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, TextIO

from .config import load_config
from .errors import BookStudioError

MARKER = ".bookstudio-project"
# Files only the CLI gates may write: the certified book, its receipt, and the canonical cache.
PROTECTED = (("output", "final.epub"), ("reports", "release.json"), ("cache", "translations.json"))
PROTECTED_NAMES = tuple(name for _, name in PROTECTED)
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_COPY_COMMANDS = {"cp", "mv", "rsync", "install", "ln"}
_ANYWHERE_COMMANDS = {"rm", "zip", "tee", "truncate", "dd", "shred", "unlink"}
_INLINE_WRITE = re.compile(
    r"ZipFile\([^)]*['\"][wax]['\"]|open\([^)]*['\"][wax]b?\+?['\"]|write_bytes|write_text|shutil\.(copy|move)"
)


def _project_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if (candidate / MARKER).is_file():
            return candidate
    return None


def _protected_reason(path: Path) -> str | None:
    root = _project_root(path.parent)
    if root is None:
        return None
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if tuple(relative.parts) in PROTECTED:
        return f"{relative.as_posix()} is written only by Book Studio gates"
    return None


def _command_targets(command: str) -> list[tuple[str, str]]:
    """(path-like word, reason) pairs for shell writes that may hit a gate-owned file."""
    if not any(name in command for name in PROTECTED_NAMES):
        return []
    names = "|".join(map(re.escape, PROTECTED_NAMES))
    targets: list[tuple[str, str]] = []
    for match in re.finditer(r">>?\s*['\"]?([^\s;&|'\"]*(?:" + names + "))", command):
        targets.append((match.group(1), "shell redirection into a gate-owned file"))
    if re.search(r"sed\s+(-[a-zA-Z]*i|--in-place)", command) or _INLINE_WRITE.search(command):
        for match in re.finditer(r"([^\s'\"=]*(?:" + names + "))", command):
            targets.append((match.group(1), "in-place or scripted write to a gate-owned file"))
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        words = command.split()
    segments: list[list[str]] = [[]]
    for word in words:
        if word in {"&&", "||", ";", "|"}:
            segments.append([])
        else:
            segments[-1].append(word)
    for segment in segments:
        if not segment:
            continue
        program = Path(segment[0]).name
        arguments = [word for word in segment[1:] if not word.startswith("-")]
        if program in _ANYWHERE_COMMANDS:
            targets.extend((a.split("=", 1)[-1], f"`{program}` on a gate-owned file") for a in arguments if any(n in a for n in PROTECTED_NAMES))
        if program in _COPY_COMMANDS and arguments and any(n in arguments[-1] for n in PROTECTED_NAMES):
            targets.append((arguments[-1], f"`{program}` into a gate-owned file"))
    return targets


def guard_decision(event: dict[str, Any]) -> dict[str, Any] | None:
    tool = event.get("tool_name")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    reason = None
    if tool in WRITE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        if isinstance(raw, str) and raw:
            path = Path(raw).expanduser()
            reason = _protected_reason((path if path.is_absolute() else cwd / path).resolve())
    elif tool == "Bash" and isinstance(tool_input.get("command"), str):
        for word, why in _command_targets(tool_input["command"]):
            path = Path(word).expanduser()
            if _protected_reason((path if path.is_absolute() else cwd / path).resolve()):
                reason = why
                break
    if not reason:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Book Studio: {reason}. Declare corrections in PROJECT/edits.json and run "
                "`bookstudio finish`; apply translations with `bookstudio apply` or `apply-drafts`."
            ),
        }
    }


def _projects_near(cwd: Path, extra: list[Path], limit: int = 8) -> list[Path]:
    found: list[Path] = []
    candidates = [cwd, *extra]
    for base in candidates:
        if not base.is_dir():
            continue
        if (base / MARKER).is_file():
            found.append(base)
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / MARKER).is_file():
                found.append(child)
        projects = base / "projects"
        if projects.is_dir():
            found.extend(c for c in sorted(projects.iterdir()) if c.is_dir() and (c / MARKER).is_file())
    unique: list[Path] = []
    for path in found:
        if path.resolve() not in {p.resolve() for p in unique}:
            unique.append(path)
    return unique[:limit]


def session_note(event: dict[str, Any], environ: dict[str, str] | None = None) -> str:
    from .review import project_status

    environ = os.environ if environ is None else environ
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    extra = [Path(environ["CLAUDE_PLUGIN_OPTION_PROJECTS_DIR"]).expanduser()] if environ.get("CLAUDE_PLUGIN_OPTION_PROJECTS_DIR") else []
    lines = []
    for root in _projects_near(cwd, extra):
        try:
            status = project_status(load_config(root / "bookstudio.toml"))
            progress = f"{status['translated']}/{status['eligible']} blocks" if status["eligible"] else "not prepared"
            lines.append(f"- {root.name}: {status['workflow_status']} ({progress}); next: `{status['next_command']}`")
        except (BookStudioError, OSError, ValueError) as error:
            lines.append(f"- {root.name}: unreadable ({getattr(error, 'code', type(error).__name__)})")
    if not lines:
        return ""
    return "Book Studio projects nearby (read-only status):\n" + "\n".join(lines) + "\n"


def run_hook(name: str, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        event = json.loads(stdin.read() or "{}")
        if not isinstance(event, dict):
            return 0
        if name == "guard":
            decision = guard_decision(event)
            if decision:
                stdout.write(json.dumps(decision) + "\n")
        elif name == "session-start":
            stdout.write(session_note(event))
    except Exception:  # noqa: BLE001 - a hook must never break the host session
        return 0
    return 0
