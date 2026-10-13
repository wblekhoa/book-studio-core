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
        self.assertEqual(["setuptools>=77"], pyproject["build-system"]["requires"])
        self.assertEqual("bookstudio", project["name"])
        self.assertEqual("0.2.0", project["version"])
        self.assertEqual(">=3.11", project["requires-python"])
        self.assertEqual([], project["dependencies"])
        self.assertIn("PDF", project["description"])
        self.assertIn("epub", project["keywords"])
        self.assertIn("pdf", project["keywords"])
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
        pyproject = tomllib.loads(
            (self.root / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertIn('__version__ = "0.2.0"', package_init)
        self.assertIn("BOOK STUDIO PERSONAL USE LICENSE", license_text)
        self.assertIn("Version 1.0", license_text)
        self.assertIn("Copyright (c) 2026 khoa 'jak' le", license_text)
        self.assertIn("Personal Use", license_text)
        self.assertIn("Commercial Use", license_text)
        self.assertIn(
            "separate written commercial license from the Licensor", license_text
        )
        self.assertIn(
            "written authorization from every applicable Third-Party Rights Holder",
            license_text,
        )
        project = pyproject["project"]
        self.assertEqual(
            "LicenseRef-Book-Studio-Personal-Use-1.0", project["license"]
        )
        self.assertEqual(["LICENSE"], project["license-files"])
        classifiers = project["classifiers"]
        self.assertFalse(any(value.startswith("License ::") for value in classifiers))
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("source-available", readme)
        self.assertIn("not an open-source license", readme)

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

        for relative in (
            "scripts/install.py",
            "scripts/audit_final_epub.py",
            "scripts/audit_editorial_receipt.py",
        ):
            with self.subTest(skill_script=relative):
                self.assertTrue((skill_root / relative).is_file())

        references = re.findall(r"\]\((references/[^)]+)\)", skill_text)
        self.assertGreaterEqual(len(references), 4)
        self.assertIn("references/final-book-quality.md", references)
        self.assertIn("references/pdf-source-preparation.md", references)
        for relative in references:
            with self.subTest(reference=relative):
                self.assertTrue((skill_root / relative).is_file())

    def test_public_skill_exposes_reader_quality_and_fail_closed_pdf_preparation(self) -> None:
        skill_root = self.root / "skills/book-translation"
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        openai_yaml = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")

        self.assertIn("reader-compatible styling", skill_text)
        self.assertIn("semantic EPUB", skill_text)
        self.assertIn("bookstudio pdf inspect", skill_text)
        self.assertIn("bookstudio pdf prepare", skill_text)
        self.assertIn("source_review_required", skill_text)
        self.assertIn("PDF Source Gateway", skill_text)
        self.assertIn("Book Translation & Design", openai_yaml)

    def test_public_skill_requires_book_specific_contextual_editorial_review(self) -> None:
        skill_root = self.root / "skills/book-translation"
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        editorial = (skill_root / "references/editorial-quality.md").read_text(
            encoding="utf-8"
        )
        receipt = (
            skill_root / "references/production-brief-and-visual-receipt.md"
        ).read_text(encoding="utf-8")

        self.assertIn("book-context pass", skill_text)
        self.assertIn("production_brief", skill_text)
        self.assertIn("source-derived chapter context", editorial)
        self.assertIn("content mode", editorial)
        self.assertIn("target-only read", editorial)
        self.assertIn("cross-packet boundary", editorial)
        self.assertIn("front-matter document", skill_text)
        self.assertIn("reports/editorial-review.json", receipt)
        self.assertIn("audit_editorial_receipt.py", skill_text)
        self.assertIn('"meaning_fidelity": "pass | fail | unknown"', receipt)
        self.assertIn(
            '"target_language_naturalness": "pass | fail | unknown"', receipt
        )
        self.assertIn('"production_brief_sha256": "..."', receipt)
        self.assertIn('"material_content_modes": "pass | fail | unknown"', receipt)
        self.assertIn('"front_matter_image_text": "pass | fail | unknown"', receipt)
        self.assertIn("--production-brief PROJECT/production-brief.md", receipt)

    def test_personal_use_boundary_is_explicit_and_portable(self) -> None:
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        skill_root = self.root / "skills/book-translation"
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        policy_path = skill_root / "references/personal-use-and-rights.md"

        self.assertTrue(policy_path.is_file())
        policy = policy_path.read_text(encoding="utf-8")
        normalized_policy = re.sub(r"\s+", " ", policy)

        for text in (readme, agents, skill_text):
            with self.subTest(document=text[:24]):
                self.assertIn("personal-use-and-rights.md", text)

        self.assertIn("private, personal, and non-commercial", normalized_policy)
        self.assertIn("Private local storage", normalized_policy)
        self.assertIn("sell, license, rent, or monetize", normalized_policy)
        self.assertIn(
            "publish, upload, share, transfer, or redistribute", normalized_policy
        )
        self.assertIn(
            "shared archive, library, corpus, dataset, or service", normalized_policy
        )
        self.assertIn(
            "Book Studio Personal Use License applies to the software code",
            normalized_policy,
        )
        self.assertIn("does not grant rights", normalized_policy)
        self.assertIn("does not provide legal advice", normalized_policy)

    def test_ci_runs_install_tests_compile_and_public_boundary_gate(self) -> None:
        workflow = (self.root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("uses: actions/checkout@v7", workflow)
        self.assertIn("uses: actions/setup-python@v7", workflow)
        self.assertNotIn("uses: actions/checkout@v4", workflow)
        self.assertNotIn("uses: actions/setup-python@v5", workflow)
        self.assertIn("python-version: [\"3.11\", \"3.12\", \"3.13\", \"3.14\"]", workflow)
        self.assertIn("os: [ubuntu-latest, macos-latest]", workflow)
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
