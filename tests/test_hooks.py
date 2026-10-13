from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from bookstudio.hooks import guard_decision, run_hook, session_note
from tests.fixtures import build_synthetic_epub
from tests.test_e2e import run_cli


class HookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls._directory.name)
        source = cls.root / "book.epub"
        build_synthetic_epub(source)
        cls.project = cls.root / "workspace" / "projects" / "demo"
        cls.project.parent.mkdir(parents=True)
        assert run_cli("init", str(cls.project), "--source", str(source), "--target", "vi").returncode == 0
        assert run_cli("prepare", str(cls.project)).returncode == 0

    @classmethod
    def tearDownClass(cls) -> None:
        cls._directory.cleanup()

    def _denied(self, tool: str, tool_input: dict, cwd: Path | None = None) -> bool:
        decision = guard_decision({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or self.project)})
        if decision is None:
            return False
        self.assertEqual("deny", decision["hookSpecificOutput"]["permissionDecision"])
        self.assertIn("edits.json", decision["hookSpecificOutput"]["permissionDecisionReason"])
        return True

    # BSC-HOOK-001
    def test_guard_blocks_direct_writes_to_gate_owned_files_only_inside_projects(self) -> None:
        for relative in ("output/final.epub", "reports/release.json", "cache/translations.json"):
            for tool in ("Write", "Edit", "MultiEdit"):
                with self.subTest(relative=relative, tool=tool):
                    self.assertTrue(self._denied(tool, {"file_path": str(self.project / relative)}))
        self.assertTrue(self._denied("Write", {"file_path": "output/final.epub"}))
        for allowed in ("edits.json", "glossary.md", "production-brief.md", "output/notes.txt"):
            with self.subTest(allowed=allowed):
                self.assertFalse(self._denied("Write", {"file_path": str(self.project / allowed)}))
        self.assertFalse(self._denied("Write", {"file_path": str(self.root / "elsewhere/output/final.epub")}, cwd=self.root))

    # BSC-HOOK-002
    def test_guard_blocks_shell_writes_but_allows_reads_and_copies_out(self) -> None:
        final = self.project / "output/final.epub"
        blocked = [
            f"cp other.epub {final}",
            f"echo x > {self.project}/reports/release.json",
            f"rm {self.project}/cache/translations.json",
            f"python3 -c \"open('{final}','wb').write(b'')\"",
            f"sed -i '' s/a/b/ {self.project}/reports/release.json",
            "cp x.epub output/final.epub",
        ]
        for command in blocked:
            with self.subTest(command=command):
                self.assertTrue(self._denied("Bash", {"command": command}))
        allowed = [
            f"cp {final} ~/Books/demo.epub",
            f"unzip -l {final}",
            f"shasum -a 256 {final}",
            f"rm {self.root}/other/reports/release.json",
            "bookstudio finish demo --json",
        ]
        for command in allowed:
            with self.subTest(command=command):
                self.assertFalse(self._denied("Bash", {"command": command}))

    # BSC-HOOK-003
    def test_hooks_never_break_the_host_on_bad_input(self) -> None:
        for raw in ("", "not json", "[]", '{"tool_name": "Write", "tool_input": "x"}'):
            for name in ("guard", "session-start"):
                with self.subTest(raw=raw, name=name):
                    output = io.StringIO()
                    self.assertEqual(0, run_hook(name, io.StringIO(raw), output))
                    self.assertEqual("", output.getvalue())

    # BSC-HOOK-004
    def test_session_note_lists_nearby_projects_with_next_command(self) -> None:
        inside = session_note({"cwd": str(self.project)}, environ={})
        self.assertIn("demo: legacy", inside)
        self.assertIn("bookstudio next demo", inside)
        self.assertIn("demo:", session_note({"cwd": str(self.project.parents[1])}, environ={}))
        self.assertIn("demo:", session_note({"cwd": str(self.root)}, environ={"CLAUDE_PLUGIN_OPTION_PROJECTS_DIR": str(self.project.parent)}))
        self.assertEqual("", session_note({"cwd": str(self.root)}, environ={}))


if __name__ == "__main__":
    unittest.main()
