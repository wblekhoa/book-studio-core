"""Install the Book Studio skill and MCP server into other AI hosts.

One command per host (Cursor, Antigravity, Kimi Code, OpenCode): copy the engine to a stable per-user folder,
copy the skill into the host's skills folder with absolute run commands, and merge one ``book-studio`` MCP entry
into the host's config. Configs are backed up before any change; other entries are never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .config import atomic_write_text
from .errors import BookStudioError

SERVER = "book-studio"
SKILL = "book-translation"
MARKER = ".book-studio-install.json"
RUNTIME_HEADING = "## Plugin runtime"


@dataclass(frozen=True)
class Host:
    name: str
    label: str
    skills: tuple[str, ...]
    config: tuple[str, ...]
    style: str  # "mcpServers" or "opencode"
    refuse_if: tuple[str, ...] = ()


HOSTS: dict[str, Host] = {
    "cursor": Host("cursor", "Cursor", (".cursor", "skills"), (".cursor", "mcp.json"), "mcpServers"),
    "antigravity": Host("antigravity", "Antigravity", (".gemini", "antigravity", "skills"),
                        (".gemini", "antigravity", "mcp_config.json"), "mcpServers"),
    "kimi": Host("kimi", "Kimi Code", (".kimi-code", "skills"), (".kimi-code", "mcp.json"), "mcpServers"),
    "opencode": Host("opencode", "OpenCode", (".config", "opencode", "skills"),
                     (".config", "opencode", "opencode.json"), "opencode",
                     refuse_if=(".config", "opencode", "opencode.jsonc")),
}


def _error(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


# ---------------------------------------------------------------- locations

def bundle_root() -> Path:
    """The plugin bundle this engine came from: its own runtime layout, or the source checkout's bundle."""
    package = Path(__file__).resolve().parent
    if package.parent.name == "runtime" and (package.parents[1] / "bundle.json").is_file():
        return package.parents[1]
    checkout = package.parents[1] / "plugins" / "book-studio"
    if (checkout / "bundle.json").is_file():
        return checkout
    raise _error("INSTALL_BUNDLE_MISSING", "This copy of Book Studio has no plugin bundle to install from.",
                 "Download the release zip, unpack it, then run: py plugins\\book-studio\\scripts\\bookstudio.py "
                 "install --host <name> (python3 instead of py on macOS/Linux).")


def engine_home(home: Path, env: Mapping[str, str], platform: str) -> Path:
    if platform == "win32":
        base = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else home / "AppData" / "Local"
        return base / "BookStudio" / "engine" / __version__
    return home / ".book-studio" / "engine" / __version__


def _manifest(root: Path) -> dict[str, str]:
    data = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    return dict(data["sha256"])


# ---------------------------------------------------------------- config files

def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _error("INSTALL_CONFIG_MALFORMED", f"{path} is not valid JSON (line {exc.lineno}); it was left untouched.",
                     "Fix or move that file, then run install again.") from exc
    if not isinstance(data, dict):
        raise _error("INSTALL_CONFIG_MALFORMED", f"{path} does not hold a JSON object; it was left untouched.",
                     "Fix or move that file, then run install again.")
    return data


def wanted_entry(style: str, python: str, runner: Path, engine: Path) -> dict[str, Any]:
    if style == "opencode":
        return {"type": "local", "command": [python, str(runner), "mcp"], "enabled": True,
                "environment": {"PLUGIN_ROOT": str(engine)}}
    return {"command": python, "args": [str(runner), "mcp"], "env": {"PLUGIN_ROOT": str(engine)}}


def _servers(config: dict[str, Any], style: str, path: Path) -> dict[str, Any]:
    key = "mcp" if style == "opencode" else "mcpServers"
    servers = config.setdefault(key, {})
    if not isinstance(servers, dict):
        raise _error("INSTALL_CONFIG_MALFORMED", f'"{key}" in {path} is not an object; the file was left untouched.',
                     "Fix that field, then run install again.")
    return servers


def _owned(entry: Any, engine_root: Path) -> bool:
    """True when an existing entry points at a Book Studio engine installed by this command."""
    text = json.dumps(entry)
    return "bookstudio.py" in text and str(engine_root) in text


def merge_decision(existing: Any, wanted: dict[str, Any], owned: bool) -> str:
    """Return "add", "unchanged" or "replace" for the book-studio entry, or raise to refuse."""
    if existing is None:
        return "add"
    if existing == wanted:
        return "unchanged"
    if owned:
        return "replace"  # An older Book Studio install (another version or Python): upgrade it.
    # Someone else's "book-studio" entry (hand-made or another tool's): never overwrite it silently.
    raise _error("INSTALL_ENTRY_CONFLICT",
                 f'The host config already has a "{SERVER}" MCP entry that Book Studio did not write; it was left untouched.',
                 f'Rename or remove that "{SERVER}" entry, then run install again (--dry-run shows the entry to be added).')


def _backup(path: Path, now: datetime) -> Path:
    target = path.with_name(f"{path.name}.bookstudio-backup-{now.strftime('%Y%m%dT%H%M%SZ')}")
    shutil.copy2(path, target)
    return target


def _dump(config: dict[str, Any]) -> str:
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- skill text

def rewrite_runtime(skill_text: str, python: str, runner: Path, engine: Path) -> str:
    lines = skill_text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip() == RUNTIME_HEADING]
    if len(starts) != 1:
        raise _error("INSTALL_SKILL_INVALID", "The bundled skill does not have exactly one runtime section.",
                     "Rebuild the plugin bundle (scripts/build_plugin.py), then install again.")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    command = f'"{python}" "{runner}"'
    section = f"""{RUNTIME_HEADING}

`bookstudio install` placed this skill's matching Python engine in `{engine}`.
For every `bookstudio ...` command in this skill and its references, run
`{command} ...` instead (in PowerShell, put `& ` before it). Do not use a
separately installed global CLI or pip-install another engine. Run
`{command} doctor --json` first. Keep all private project files outside
the engine folder. When the `{SERVER}` MCP tools are available, you may call them
instead of shell commands; they run the same engine and gates (accept a pilot
only with `user_confirmed: true` after the user explicitly approved the reviewed
sample).

"""
    return "".join(lines[:start]) + section + "".join(lines[end:])


# ---------------------------------------------------------------- install / uninstall

def install(host_name: str, *, home: Path | None = None, env: Mapping[str, str] | None = None,
            platform: str | None = None, python: str | None = None, dry_run: bool = False,
            now: datetime | None = None, source: Path | None = None) -> dict[str, Any]:
    host = HOSTS[host_name]
    home = home or Path.home()
    env = os.environ if env is None else env
    platform = platform or sys.platform
    python = python or sys.executable
    now = now or datetime.now(timezone.utc)
    source = source or bundle_root()
    engine = engine_home(home, env, platform)
    runner = engine / "scripts" / "bookstudio.py"
    config_path = home.joinpath(*host.config)
    skill_dir = home.joinpath(*host.skills) / SKILL

    if host.refuse_if and home.joinpath(*host.refuse_if).exists():
        raise _error("INSTALL_CONFIG_UNSUPPORTED", f"{home.joinpath(*host.refuse_if)} exists; Book Studio only edits "
                     f"{config_path.name}.", f'Add the "{SERVER}" entry shown by --dry-run --json to that file by hand.')
    if skill_dir.exists() and not (skill_dir / MARKER).is_file():
        raise _error("INSTALL_SKILL_CONFLICT", f"{skill_dir} exists and was not installed by Book Studio; it was left untouched.",
                     "Move or rename that folder, then run install again.")

    # Engine: copy every manifest file whose bytes differ, after checking the source hashes.
    manifest = _manifest(source)
    to_copy = []
    for name, digest in sorted(manifest.items()):
        data = (source / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise _error("INSTALL_BUNDLE_DRIFT", f"{name} in the bundle does not match bundle.json.",
                         "Rebuild the plugin bundle (scripts/build_plugin.py --check), then install again.")
        target = engine / name
        if not target.is_file() or target.read_bytes() != data:
            to_copy.append((target, data))
    same_place = source.resolve() == engine.resolve() if engine.exists() else False
    engine_action = "unchanged" if same_place or not to_copy else ("updated" if engine.exists() else "installed")

    # Skill: the bundled text with absolute run commands, plus an ownership marker.
    skill_files: dict[Path, bytes] = {}
    prefix = f"skills/{SKILL}/"
    for name in manifest:
        if not name.startswith(prefix):
            continue
        data = (source / name).read_bytes()
        if name == prefix + "SKILL.md":
            data = rewrite_runtime(data.decode("utf-8"), python, runner, engine).encode("utf-8")
        skill_files[skill_dir / name[len(prefix):]] = data
    skill_files[skill_dir / MARKER] = (_dump({"installed_by": "bookstudio", "version": __version__,
                                              "engine": str(engine)})).encode("utf-8")
    skill_action = ("unchanged" if all(p.is_file() and p.read_bytes() == d for p, d in skill_files.items())
                    else "updated" if skill_dir.exists() else "installed")

    # MCP entry.
    real_config = config_path.resolve() if config_path.is_symlink() else config_path
    config = read_config(real_config)
    servers = _servers(config, host.style, real_config)
    wanted = wanted_entry(host.style, python, runner, engine)
    decision = merge_decision(servers.get(SERVER), wanted, _owned(servers.get(SERVER), engine.parent))

    backup = None
    if not dry_run:
        for target, data in to_copy:
            if not same_place:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        if skill_action != "unchanged":
            for target, data in skill_files.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        if decision != "unchanged":
            if real_config.exists():
                backup = _backup(real_config, now)
            servers[SERVER] = wanted
            atomic_write_text(real_config, _dump(config))
    return {
        "status": "dry_run" if dry_run else "pass",
        "message": (f"{'Would install' if dry_run else 'Installed'} Book Studio for {host.label}. "
                    f"Restart {host.label}, then ask it to translate a book."),
        "host": host.name,
        "python": python,
        "engine": {"path": str(engine), "action": engine_action},
        "skill": {"path": str(skill_dir), "action": skill_action},
        "mcp": {"path": str(real_config), "action": decision, "backup": str(backup) if backup else None,
                "entry": wanted},
    }


def uninstall(host_name: str, *, home: Path | None = None, dry_run: bool = False,
              now: datetime | None = None) -> dict[str, Any]:
    host = HOSTS[host_name]
    home = home or Path.home()
    now = now or datetime.now(timezone.utc)
    config_path = home.joinpath(*host.config)
    real_config = config_path.resolve() if config_path.is_symlink() else config_path
    skill_dir = home.joinpath(*host.skills) / SKILL

    config = read_config(real_config)
    key = "mcp" if host.style == "opencode" else "mcpServers"
    servers = config.get(key)
    has_entry = isinstance(servers, dict) and SERVER in servers
    owned_skill = (skill_dir / MARKER).is_file()
    backup = None
    if not dry_run:
        if has_entry:
            backup = _backup(real_config, now)
            del servers[SERVER]
            atomic_write_text(real_config, _dump(config))
        if owned_skill:
            shutil.rmtree(skill_dir)
    return {
        "status": "dry_run" if dry_run else "pass",
        "message": f"{'Would remove' if dry_run else 'Removed'} Book Studio from {host.label}. The engine folder is kept.",
        "host": host.name,
        "skill": {"path": str(skill_dir), "action": "removed" if owned_skill else "absent"},
        "mcp": {"path": str(real_config), "action": "removed" if has_entry else "absent",
                "backup": str(backup) if backup else None},
    }
