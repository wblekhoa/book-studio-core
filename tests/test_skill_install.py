from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SkillInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.canonical_skill = cls.repo_root / "skills/book-translation"

    def fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "source/book-translation"
        shutil.copytree(self.canonical_skill, source)
        return source, source / "scripts/install.py"

    def run_installer(
        self,
        script: Path,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments, "--json"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def assert_exact_tree(self, source: Path, destination: Path) -> None:
        source_files = sorted(
            path.relative_to(source).as_posix()
            for path in source.rglob("*")
            if path.is_file()
        )
        destination_files = sorted(
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        )
        self.assertEqual(source_files, destination_files)
        for relative in source_files:
            self.assertEqual(
                (source / relative).read_bytes(),
                (destination / relative).read_bytes(),
                relative,
            )

    def test_default_codex_home_install_and_current_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, script = self.fixture(root)
            codex_home = root / "codex-home"
            env = dict(os.environ)
            env["CODEX_HOME"] = str(codex_home)

            installed = self.run_installer(script, env=env)

            self.assertEqual(0, installed.returncode, installed.stderr)
            receipt = json.loads(installed.stdout)
            destination = codex_home / "skills/book-translation"
            self.assertEqual("installed", receipt["status"])
            self.assertTrue(receipt["changed"])
            self.assertEqual(str(destination.resolve()), receipt["destination"])
            self.assertEqual(receipt["source_sha256"], receipt["destination_sha256"])
            self.assertIsNone(receipt["backup"])
            self.assert_exact_tree(source, destination)

            checked = self.run_installer(script, "--check", env=env)

            self.assertEqual(0, checked.returncode, checked.stderr)
            check_receipt = json.loads(checked.stdout)
            self.assertEqual("current", check_receipt["status"])
            self.assertFalse(check_receipt["changed"])
            self.assertEqual(receipt["source_sha256"], check_receipt["destination_sha256"])

    def test_check_reports_missing_without_creating_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, script = self.fixture(root)
            destination_root = root / "skills"

            checked = self.run_installer(
                script,
                "--check",
                "--dest-root",
                str(destination_root),
            )

            self.assertEqual(2, checked.returncode)
            receipt = json.loads(checked.stdout)
            self.assertEqual("missing", receipt["status"])
            self.assertFalse(receipt["changed"])
            self.assertFalse(destination_root.exists())

    def test_dry_run_reports_stale_without_mutating_or_backing_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, script = self.fixture(root)
            destination_root = root / "skills"
            initial = self.run_installer(
                script,
                "--dest-root",
                str(destination_root),
            )
            self.assertEqual(0, initial.returncode, initial.stderr)
            destination = destination_root / "book-translation"
            skill_file = destination / "SKILL.md"
            stale_bytes = skill_file.read_bytes() + b"\nlocal stale edit\n"
            skill_file.write_bytes(stale_bytes)

            dry_run = self.run_installer(
                script,
                "--dry-run",
                "--dest-root",
                str(destination_root),
            )

            self.assertEqual(0, dry_run.returncode, dry_run.stderr)
            receipt = json.loads(dry_run.stdout)
            self.assertEqual("would_update", receipt["status"])
            self.assertFalse(receipt["changed"])
            self.assertNotEqual(receipt["source_sha256"], receipt["destination_sha256"])
            self.assertEqual(stale_bytes, skill_file.read_bytes())
            self.assertEqual([], list(destination_root.glob(".book-translation.backup-*")))

    def test_update_keeps_backup_and_replaces_destination_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, script = self.fixture(root)
            destination_root = root / "skills"
            initial = self.run_installer(
                script,
                "--dest-root",
                str(destination_root),
            )
            self.assertEqual(0, initial.returncode, initial.stderr)
            destination = destination_root / "book-translation"
            (destination / "stale.txt").write_text("recover me", encoding="utf-8")

            updated = self.run_installer(
                script,
                "--dest-root",
                str(destination_root),
            )

            self.assertEqual(0, updated.returncode, updated.stderr)
            receipt = json.loads(updated.stdout)
            self.assertEqual("updated", receipt["status"])
            self.assertTrue(receipt["changed"])
            self.assertEqual(receipt["source_sha256"], receipt["destination_sha256"])
            backup = Path(receipt["backup"])
            self.assertRegex(backup.name, r"^\.book-translation\.backup-\d{8}T\d{6}Z-[0-9a-f]{8}")
            self.assertTrue((backup / "stale.txt").is_file())
            self.assertFalse((destination / "stale.txt").exists())
            self.assert_exact_tree(source, destination)

    def test_failed_post_install_verification_restores_previous_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, script = self.fixture(root)
            destination_root = root / "skills"
            initial = self.run_installer(
                script,
                "--dest-root",
                str(destination_root),
            )
            self.assertEqual(0, initial.returncode, initial.stderr)
            destination = destination_root / "book-translation"
            stale = destination / "stale.txt"
            stale.write_text("restore me", encoding="utf-8")

            spec = importlib.util.spec_from_file_location("skill_installer_under_test", script)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            original_tree_hash = module.tree_hash
            destination_reads = 0

            def fail_final_destination_hash(path: Path) -> str:
                nonlocal destination_reads
                if path.resolve() == destination.resolve():
                    destination_reads += 1
                    if destination_reads == 2:
                        raise module.InstallError("simulated final verification failure")
                return original_tree_hash(path)

            with mock.patch.object(module, "tree_hash", side_effect=fail_final_destination_hash):
                with self.assertRaises(module.InstallError):
                    module.install_skill(script.parents[1], destination_root)

            self.assertEqual("restore me", stale.read_text(encoding="utf-8"))
            self.assertEqual([], list(destination_root.glob(".book-translation.backup-*")))
            self.assertEqual([], list(destination_root.glob(".book-translation.install-*")))

    def test_invalid_source_never_creates_destination(self) -> None:
        def missing_required(source: Path) -> None:
            (source / "agents/openai.yaml").unlink()

        def broken_reference(source: Path) -> None:
            skill = source / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\n[Missing reference](references/does-not-exist.md)\n",
                encoding="utf-8",
            )

        def symlinked_resource(source: Path) -> None:
            (source / "references/linked.md").symlink_to("editorial-quality.md")

        def generated_bytecode(source: Path) -> None:
            generated = source / "scripts/__pycache__/helper.pyc"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(b"synthetic compiled artifact")

        for name, mutate in (
            ("missing required file", missing_required),
            ("broken reference", broken_reference),
            ("symlinked resource", symlinked_resource),
            ("generated bytecode", generated_bytecode),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, script = self.fixture(root)
                destination_root = root / "skills"
                mutate(source)

                result = self.run_installer(
                    script,
                    "--dest-root",
                    str(destination_root),
                )

                self.assertEqual(3, result.returncode, result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual("SOURCE_SKILL_INVALID", receipt["code"])
                self.assertFalse(receipt["changed"])
                self.assertFalse(destination_root.exists())

    def test_symlinked_source_root_is_rejected_without_destination_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, script = self.fixture(root)
            linked_source = root / "linked-skill"
            linked_source.symlink_to(source, target_is_directory=True)
            destination_root = root / "skills"

            spec = importlib.util.spec_from_file_location("skill_installer_symlink_test", script)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            with self.assertRaises(module.SourceInvalidError):
                module.install_skill(linked_source, destination_root)

            self.assertFalse(destination_root.exists())


if __name__ == "__main__":
    unittest.main()
