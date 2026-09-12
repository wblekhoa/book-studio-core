from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bookstudio.safety.public_audit import audit_public_tree


class PublicBoundaryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def minimal_tree(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "README.md").write_text("# Synthetic public project\n", encoding="utf-8")
        (self.root / "src/example.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests/fixtures.py").write_text("SYNTHETIC = True\n", encoding="utf-8")

    def test_minimal_allowlisted_tree_passes(self) -> None:
        self.minimal_tree()
        receipt = audit_public_tree(self.root)
        self.assertTrue(receipt["passed"], receipt["violations"])

    def test_plugin_packaging_does_not_hide_private_content(self) -> None:
        for relative, category in (
            ('plugins/book-studio/runtime/book.epub', 'book_binary'),
            ('.agents/private.txt', 'agent_path_not_allowlisted'),
            ('plugins/book-studio/cache/data.json', 'private_data_directory'),
        ):
            with self.subTest(relative=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic')
                self.assertIn(category, audit_public_tree(self.root)['category_counts'])
                path.unlink()

    def test_forbidden_books_private_directories_and_top_level_paths_fail(self) -> None:
        cases = (
            ("src/book.epub", "book_binary"),
            ("projects/private/data.json", "private_data_directory"),
            ("random.txt", "top_level_not_allowlisted"),
            ("src/cover.png", "binary_asset"),
        )
        for relative, category in cases:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"private")
                    receipt = audit_public_tree(root)
                    self.assertFalse(receipt["passed"])
                    self.assertIn(category, receipt["category_counts"])

    def test_personal_paths_emails_and_secrets_fail_without_echoing_secret(self) -> None:
        self.minimal_tree()
        secret = "sk-" + "A" * 24
        values = (
            ("personal.py", 'PATH = "' + "/" + "Users" + '/someone/book.epub"\n', "personal_path"),
            ("email.py", 'CONTACT = "person' + "@" + 'example.test"\n', "email"),
            ("secret.py", f'TOKEN = "{secret}"\n', "secret"),
        )
        for name, text, category in values:
            path = self.root / "src" / name
            path.write_text(text, encoding="utf-8")
            receipt = audit_public_tree(self.root)
            rendered = json.dumps(receipt)
            self.assertFalse(receipt["passed"])
            self.assertIn(category, receipt["category_counts"])
            self.assertNotIn(secret, rendered)
            path.unlink()

    def test_symlink_fails_closed(self) -> None:
        self.minimal_tree()
        outside = self.root.parent / "bookstudio-audit-outside.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            (self.root / "src/link.py").symlink_to(outside)
            receipt = audit_public_tree(self.root)
            self.assertFalse(receipt["passed"])
            self.assertIn("symlink", receipt["category_counts"])
        finally:
            outside.unlink(missing_ok=True)

    def test_pycache_directory_cannot_hide_blocked_content(self) -> None:
        self.minimal_tree()
        hidden = self.root / "src/__pycache__/private-book.epub"
        hidden.parent.mkdir(parents=True)
        hidden.write_bytes(b"synthetic blocked payload")

        receipt = audit_public_tree(self.root)

        self.assertFalse(receipt["passed"])
        self.assertIn("book_binary", receipt["category_counts"])
        self.assertTrue(
            any(row["path"] == "src/__pycache__/private-book.epub" for row in receipt["violations"])
        )

    def test_only_a_real_root_git_directory_is_opaque(self) -> None:
        self.minimal_tree()
        nested = self.root / "src/.git/private-book.epub"
        nested.parent.mkdir(parents=True)
        nested.write_bytes(b"synthetic blocked payload")

        nested_receipt = audit_public_tree(self.root)

        self.assertFalse(nested_receipt["passed"])
        self.assertTrue(
            any(row["path"] == "src/.git/private-book.epub" for row in nested_receipt["violations"])
        )

        nested.unlink()
        nested.parent.rmdir()
        external = self.root.parent / "bookstudio-fake-git"
        external.mkdir(exist_ok=True)
        try:
            (self.root / ".git").symlink_to(external, target_is_directory=True)
            symlink_receipt = audit_public_tree(self.root)
            self.assertFalse(symlink_receipt["passed"])
            self.assertIn("symlink", symlink_receipt["category_counts"])
        finally:
            external.rmdir()

    def test_generated_metadata_files_are_not_silently_ignored(self) -> None:
        self.minimal_tree()
        (self.root / "src/.DS_Store").write_bytes(b"synthetic metadata")

        receipt = audit_public_tree(self.root)

        self.assertFalse(receipt["passed"])
        self.assertTrue(
            any(row["path"] == "src/.DS_Store" for row in receipt["violations"])
        )

    def test_compiled_artifacts_are_rejected_instead_of_ignored(self) -> None:
        self.minimal_tree()
        payload = (
            "compiled "
            + "/"
            + "Users"
            + "/someone/private "
            + "sk-"
            + "A" * 24
        ).encode("utf-8")
        (self.root / "src/private.pyc").write_bytes(payload)

        receipt = audit_public_tree(self.root)

        self.assertFalse(receipt["passed"])
        self.assertIn("compiled_artifact", receipt["category_counts"])
        self.assertEqual(0, receipt["ignored_artifacts"])

    def test_posix_home_and_any_windows_drive_personal_paths_fail(self) -> None:
        self.minimal_tree()
        values = (
            'PATH = "' + "/" + "home" + '/alice/private/book.epub"\n',
            'PATH = "' + "D:" + "\\" + "Users" + '\\alice\\private\\book.epub"\n',
        )
        for index, value in enumerate(values):
            with self.subTest(index=index):
                path = self.root / "src" / f"private-{index}.py"
                path.write_text(value, encoding="utf-8")
                receipt = audit_public_tree(self.root)
                self.assertFalse(receipt["passed"])
                self.assertIn("personal_path", receipt["category_counts"])
                path.unlink()

    def test_actual_public_core_tree_passes_with_required_docs(self) -> None:
        actual = Path(__file__).resolve().parents[1]
        receipt = audit_public_tree(actual)
        required = (
            "LICENSE",
            "pyproject.toml",
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CHANGELOG.md",
            ".github/workflows/ci.yml",
            "skills/book-translation/SKILL.md",
            "skills/book-translation/agents/openai.yaml",
            "docs/architecture.md",
            "docs/ai-packets.md",
            "docs/safety.md",
        )
        self.assertTrue(all((actual / relative).is_file() for relative in required))
        self.assertTrue(receipt["passed"], receipt["violations"])


if __name__ == "__main__":
    unittest.main()
