from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bookstudio.errors import BookStudioError
from bookstudio.install import HOSTS, MARKER, SKILL, bundle_root, engine_home, install, uninstall

T1 = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 24, 9, 5, tzinfo=timezone.utc)
OTHER = {"command": "npx", "args": ["-y", "other-mcp"]}


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.home = Path(self._directory.name)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _install(self, host: str, **kwargs):
        return install(host, home=self.home, env={}, platform="darwin", python="/opt/py/bin/python3", now=T1, **kwargs)

    def _config(self, host: str) -> Path:
        return self.home.joinpath(*HOSTS[host].config)

    def _seed(self, host: str) -> dict:
        key = "mcp" if HOSTS[host].style == "opencode" else "mcpServers"
        original = {"$schema": "keep-me", key: {"other": OTHER}}
        path = self._config(host)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(original), encoding="utf-8")
        return original

    # BSC-HOST-001
    def test_each_host_gets_engine_skill_and_one_mcp_entry_and_keeps_the_rest(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                original = self._seed(host)
                result = self._install(host)
                engine = self.home / ".book-studio" / "engine"
                self.assertEqual("pass", result["status"])
                config = json.loads(self._config(host).read_text(encoding="utf-8"))
                key = "mcp" if HOSTS[host].style == "opencode" else "mcpServers"
                self.assertEqual(OTHER, config[key]["other"])
                self.assertEqual("keep-me", config["$schema"])
                entry = config[key]["book-studio"]
                runner = str(Path(result["engine"]["path"]) / "scripts" / "bookstudio.py")
                if host == "opencode":
                    self.assertEqual({"type": "local", "command": ["/opt/py/bin/python3", runner, "mcp"], "enabled": True,
                                      "environment": {"PLUGIN_ROOT": result["engine"]["path"]}}, entry)
                else:
                    self.assertEqual("/opt/py/bin/python3", entry["command"])
                    self.assertEqual([runner, "mcp"], entry["args"])
                    self.assertEqual({"PLUGIN_ROOT": result["engine"]["path"]}, entry["env"])
                self.assertTrue(Path(runner).is_file())
                self.assertTrue(str(Path(runner)).startswith(str(engine)))
                backup = Path(result["mcp"]["backup"])
                self.assertEqual(original, json.loads(backup.read_text(encoding="utf-8")))

                skill = self.home.joinpath(*HOSTS[host].skills) / SKILL
                text = (skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("# Book Translation and Design", text)
                self.assertIn("## Establish the boundary", text)
                self.assertIn(f'"/opt/py/bin/python3" "{runner}"', text)
                for stale in ("<plugin-root>", 'python3 "', "${CLAUDE_PLUGIN_ROOT}"):
                    self.assertNotIn(stale, text)
                self.assertTrue((skill / MARKER).is_file())
                self.assertTrue((skill / "references" / "chat-workflow.md").is_file())

    # BSC-HOST-002
    def test_rerun_changes_nothing_and_makes_no_backup(self) -> None:
        self._seed("cursor")
        self._install("cursor")
        before = _tree(self.home)
        again = install("cursor", home=self.home, env={}, platform="darwin", python="/opt/py/bin/python3", now=T2)
        self.assertEqual(("unchanged",) * 3,
                         (again["engine"]["action"], again["skill"]["action"], again["mcp"]["action"]))
        self.assertIsNone(again["mcp"]["backup"])
        self.assertEqual(before, _tree(self.home))

    # BSC-HOST-002
    def test_new_python_or_version_replaces_our_own_entry(self) -> None:
        self._install("kimi")
        moved = install("kimi", home=self.home, env={}, platform="darwin", python="/usr/bin/python3.12", now=T2)
        self.assertEqual("replace", moved["mcp"]["action"])
        entry = json.loads(self._config("kimi").read_text(encoding="utf-8"))["mcpServers"]["book-studio"]
        self.assertEqual("/usr/bin/python3.12", entry["command"])

    # BSC-HOST-003
    def test_uninstall_restores_the_config_and_removes_only_our_skill(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                original = self._seed(host)
                self._install(host)
                result = uninstall(host, home=self.home, now=T2)
                self.assertEqual("removed", result["mcp"]["action"])
                self.assertEqual(original, json.loads(self._config(host).read_text(encoding="utf-8")))
                self.assertTrue(Path(result["mcp"]["backup"]).is_file())
                self.assertFalse((self.home.joinpath(*HOSTS[host].skills) / SKILL).exists())
        self.assertTrue((self.home / ".book-studio" / "engine").is_dir())

    # BSC-HOST-004
    def test_unsafe_configs_and_folders_are_refused_untouched(self) -> None:
        cases = {
            "malformed": ("cursor", lambda: self._config("cursor").write_text("{ nope", encoding="utf-8")),
            "not an object": ("kimi", lambda: self._config("kimi").write_text("[]", encoding="utf-8")),
            "servers not an object": ("antigravity", lambda: self._config("antigravity").write_text('{"mcpServers": 3}', encoding="utf-8")),
            "foreign skill": ("cursor", lambda: (self.home / ".cursor" / "skills" / SKILL).mkdir(parents=True)),
            "foreign entry": ("cursor", lambda: self._config("cursor").write_text(
                json.dumps({"mcpServers": {"book-studio": OTHER}}), encoding="utf-8")),
            "jsonc": ("opencode", lambda: self.home.joinpath(".config", "opencode", "opencode.jsonc").write_text("{}", encoding="utf-8")),
        }
        expected = {"malformed": "INSTALL_CONFIG_MALFORMED", "not an object": "INSTALL_CONFIG_MALFORMED",
                    "servers not an object": "INSTALL_CONFIG_MALFORMED", "foreign skill": "INSTALL_SKILL_CONFLICT",
                    "foreign entry": "INSTALL_ENTRY_CONFLICT", "jsonc": "INSTALL_CONFIG_UNSUPPORTED"}
        for label, (host, arrange) in cases.items():
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as directory:
                    self.home = Path(directory)
                    self._config(host).parent.mkdir(parents=True, exist_ok=True)
                    arrange()
                    before = _tree(self.home)
                    with self.assertRaises(BookStudioError) as caught:
                        self._install(host)
                    self.assertEqual(expected[label], caught.exception.code)
                    self.assertEqual(before, _tree(self.home))

    # BSC-HOST-004
    def test_bom_and_empty_configs_are_read_and_symlinks_survive(self) -> None:
        self._config("cursor").parent.mkdir(parents=True)
        self._config("cursor").write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": {"other": OTHER}}).encode())
        self._install("cursor")
        self.assertIn("other", json.loads(self._config("cursor").read_text(encoding="utf-8"))["mcpServers"])

        self._config("kimi").parent.mkdir(parents=True)
        self._config("kimi").write_text("  \n", encoding="utf-8")
        self._install("kimi")
        self.assertIn("book-studio", json.loads(self._config("kimi").read_text(encoding="utf-8"))["mcpServers"])

        real = self.home / ".gemini" / "config" / "mcp_config.json"
        real.parent.mkdir(parents=True)
        real.write_text(json.dumps({"mcpServers": {"other": OTHER}}), encoding="utf-8")
        link = self._config("antigravity")
        link.parent.mkdir(parents=True)
        link.symlink_to(real)
        self._install("antigravity")
        self.assertTrue(link.is_symlink())
        self.assertIn("book-studio", json.loads(real.read_text(encoding="utf-8"))["mcpServers"])

    # BSC-HOST-005
    def test_dry_run_writes_nothing(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._seed(host)
                before = _tree(self.home)
                result = self._install(host, dry_run=True)
                self.assertEqual("dry_run", result["status"])
                self.assertEqual("add", result["mcp"]["action"])
                self.assertEqual(before, _tree(self.home))
                self.assertFalse((self.home / ".book-studio").exists())

    # BSC-WIN-002
    def test_windows_engine_lives_in_local_app_data(self) -> None:
        local = self.home / "Local"
        self.assertEqual(local / "BookStudio" / "engine",
                         engine_home(self.home, {"LOCALAPPDATA": str(local)}, "win32").parent)
        self.assertEqual(self.home / "AppData" / "Local" / "BookStudio" / "engine",
                         engine_home(self.home, {}, "win32").parent)

    # BSC-HOST-006
    def test_the_installed_entry_starts_a_working_server_that_guards_its_folder(self) -> None:
        result = install("cursor", home=self.home, env={}, platform=sys.platform if sys.platform != "win32" else "darwin",
                         python=sys.executable, now=T1)
        entry = result["mcp"]["entry"]
        engine = Path(result["engine"]["path"])
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "doctor", "arguments": {}}},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "status", "arguments": {"project": "my-book"}}}]
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "BOOKSTUDIO_PROJECTS_DIR", "CLAUDE_PROJECT_DIR"}}
        env.update(entry["env"], PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([entry["command"], *entry["args"]], input="\n".join(map(json.dumps, lines)) + "\n",
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=engine)
        self.assertEqual(0, done.returncode, done.stderr)
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertIn("doctor", {tool["name"] for tool in replies[0]["result"]["tools"]})
        self.assertFalse(replies[1]["result"]["isError"], replies[1])
        self.assertEqual("MCP_PRIVATE_PATH_REQUIRED", replies[2]["result"]["structuredContent"]["code"])
        self.assertFalse(any(p.name == "__pycache__" for p in engine.rglob("*")))

    def test_bundle_root_is_found_from_the_checkout(self) -> None:
        self.assertTrue((bundle_root() / "bundle.json").is_file())


if __name__ == "__main__":
    unittest.main()
