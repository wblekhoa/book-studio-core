from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


class DistributionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]

    def test_pyproject_exposes_dependency_free_console_application(self) -> None:
        pyproject = tomllib.loads(
            (self.root / "pyproject.toml").read_text(encoding="utf-8")
        )

        project = pyproject["project"]
        self.assertEqual("bookstudio", project["name"])
        self.assertEqual("0.1.0", project["version"])
        self.assertEqual(">=3.11", project["requires-python"])
        self.assertEqual([], project["dependencies"])
        self.assertEqual("bookstudio.cli:main", project["scripts"]["bookstudio"])
        self.assertEqual(
            "https://github.com/wblekhoa/book-studio-core",
            project["urls"]["Repository"],
        )

        setuptools = pyproject["tool"]["setuptools"]
        self.assertEqual({"": "src"}, setuptools["package-dir"])
        self.assertEqual(
            ["templates/*.md"],
            setuptools["package-data"]["bookstudio"],
        )

    def test_version_and_license_match_public_release_contract(self) -> None:
        package_init = (self.root / "src/bookstudio/__init__.py").read_text(
            encoding="utf-8"
        )
        license_text = (self.root / "LICENSE").read_text(encoding="utf-8")

        self.assertIn('__version__ = "0.1.0"', package_init)
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 khoa 'jak' le", license_text)

    def test_public_defaults_and_guidance_are_target_language_neutral(self) -> None:
        glossary = (self.root / "src/bookstudio/templates/glossary.md").read_text(
            encoding="utf-8"
        )
        image_runtime = (self.root / "src/bookstudio/images/manifest.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("Vietnamese", glossary)
        self.assertNotIn("Vietnamese annotation", image_runtime)
        self.assertIn("target-language", glossary)
        self.assertIn("target-language annotation", image_runtime)

    def test_public_skill_has_valid_minimal_structure_and_resolvable_references(self) -> None:
        skill_root = self.root / "skills/book-translation"
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        openai_yaml = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")

        self.assertTrue(skill_text.startswith("---\n"))
        self.assertIn("\nname: book-translation\n", skill_text)
        self.assertRegex(skill_text, r"\ndescription: .+\n")
        self.assertIn("$book-translation", openai_yaml)

        references = re.findall(r"\]\((references/[^)]+)\)", skill_text)
        self.assertGreaterEqual(len(references), 3)
        for relative in references:
            with self.subTest(reference=relative):
                self.assertTrue((skill_root / relative).is_file())

    def test_ci_runs_install_tests_compile_and_public_boundary_gate(self) -> None:
        workflow = (self.root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("uses: actions/checkout@v7", workflow)
        self.assertIn("uses: actions/setup-python@v7", workflow)
        self.assertNotIn("uses: actions/checkout@v4", workflow)
        self.assertNotIn("uses: actions/setup-python@v5", workflow)
        self.assertIn("python-version: [\"3.11\", \"3.12\", \"3.13\"]", workflow)
        self.assertIn('cp -R . "$RUNNER_TEMP/bookstudio-install"', workflow)
        self.assertIn(
            'python -m pip install "$RUNNER_TEMP/bookstudio-install"', workflow
        )
        self.assertNotIn("run: python -m pip install .", workflow)
        self.assertIn(
            "PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v",
            workflow,
        )
        self.assertIn('"$RUNNER_TEMP/bookstudio-install/src"', workflow)
        self.assertIn('"$RUNNER_TEMP/bookstudio-install/tests"', workflow)
        self.assertNotIn("python -m compileall -q src tests", workflow)
        self.assertIn("bookstudio public-audit . --json", workflow)
        preflight = (
            "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "
            "python -m bookstudio public-audit . --json"
        )
        self.assertIn(preflight, workflow)
        self.assertLess(workflow.index(preflight), workflow.index("cp -R ."))

        for document in ("AGENTS.md", "CONTRIBUTING.md", "README.md"):
            with self.subTest(document=document):
                text = (self.root / document).read_text(encoding="utf-8")
                self.assertIn(
                    "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "
                    "python3 -m unittest discover -s tests -v",
                    text,
                )
                self.assertIn(
                    "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "
                    "python3 -m bookstudio public-audit . --json",
                    text,
                )


if __name__ == "__main__":
    unittest.main()
