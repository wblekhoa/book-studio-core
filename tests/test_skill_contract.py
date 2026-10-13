from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from bookstudio.cli import BEGINNER_COMMANDS


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/book-translation"


def _skill_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
    )


class SkillContractTests(unittest.TestCase):
    # BSC-SKILL-011
    def test_skill_documents_every_beginner_command(self) -> None:
        text = _skill_text()
        missing = [name for name in BEGINNER_COMMANDS if f"bookstudio {name}" not in text]
        self.assertEqual([], missing)
        for contract in ("edits.json", "apply-drafts", "reports/review.html"):
            self.assertIn(contract, text)

    # BSC-SKILL-012
    def test_skill_never_recommends_editing_after_the_gate(self) -> None:
        text = _skill_text()
        for phrase in ("deterministic finalizer", "deterministic postprocessor", "project-owned script"):
            self.assertNotIn(phrase, text)
        self.assertIn("never\nwrite a per-book finalizer", text)

    # BSC-SKILL-013
    def test_plugin_and_engine_share_one_release_version(self) -> None:
        from bookstudio import __version__

        manifest = json.loads((ROOT / "plugins/book-studio/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(__version__, manifest["version"])


if __name__ == "__main__":
    unittest.main()
