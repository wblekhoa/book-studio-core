from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bookstudio.config import ProjectPaths, atomic_write_json, load_config
from bookstudio.errors import BookStudioError
from bookstudio.project import GUIDED_MARKER, PROJECT_MARKER, init_project, start_project
from tests.fixtures import build_synthetic_epub


class ProjectInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.source = self.workspace / "source.epub"
        self.source.write_bytes(b"source")
        self.target = self.workspace / "sample"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def init(self):
        return init_project(
            self.target,
            slug="sample",
            source=self.source,
            target_language="vi",
            output_mode="vi_only",
        )

    def test_init_refuses_nonempty_unowned_directory(self) -> None:
        self.target.mkdir()
        (self.target / "unrelated.txt").write_text("user data", encoding="utf-8")

        with self.assertRaisesRegex(BookStudioError, "PROJECT_NOT_OWNED"):
            self.init()

    def test_init_creates_only_owned_project_contract(self) -> None:
        config_path = self.init()

        expected_files = {PROJECT_MARKER, "bookstudio.toml", "glossary.md"}
        expected_dirs = {
            "state",
            "source-blocks",
            "packets",
            "cache",
            "assets/localized",
            "output",
            "reports",
        }
        self.assertEqual((self.target / "bookstudio.toml").resolve(), config_path)
        for relative in expected_files:
            self.assertTrue((self.target / relative).is_file(), relative)
        for relative in expected_dirs:
            self.assertTrue((self.target / relative).is_dir(), relative)
        self.assertFalse((self.target / self.source.name).exists())
        self.assertEqual(
            self.target / ".bookstudio-guided",
            getattr(ProjectPaths.from_root(self.target), "guided_marker", None),
        )
        self.assertFalse((self.target / ".bookstudio-guided").exists())

    def test_init_reopens_owned_project_without_overwriting_user_edits(self) -> None:
        self.init()
        config = self.target / "bookstudio.toml"
        glossary = self.target / "glossary.md"
        config_text = config.read_text(encoding="utf-8") + "\n# user note\n"
        glossary_text = "# Thuật ngữ riêng của tôi\n"
        config.write_text(config_text, encoding="utf-8")
        glossary.write_text(glossary_text, encoding="utf-8")

        reopened_config_path = self.init()

        self.assertEqual(config.resolve(), reopened_config_path)
        self.assertEqual(config_text, config.read_text(encoding="utf-8"))
        self.assertEqual(glossary_text, glossary.read_text(encoding="utf-8"))

    def test_init_rejects_invalid_arguments_before_creating_target(self) -> None:
        cases = (
            ({"target_language": "not a language"}, "CONFIG_LANGUAGE_INVALID"),
            ({"output_mode": "parallel"}, "CONFIG_OUTPUT_MODE_INVALID"),
            ({"source": self.workspace / "missing.epub"}, "SOURCE_NOT_FOUND"),
        )
        for overrides, code in cases:
            with self.subTest(code=code):
                kwargs = {
                    "slug": "sample",
                    "source": self.source,
                    "target_language": "vi",
                    "output_mode": "vi_only",
                }
                kwargs.update(overrides)
                with self.assertRaisesRegex(BookStudioError, code):
                    init_project(self.target, **kwargs)
                self.assertFalse(self.target.exists())

    def test_start_reopens_matching_owned_project_without_overwriting_user_edits(self) -> None:
        source = self.workspace / "guided.epub"
        build_synthetic_epub(source)
        answers = {
            "target_language": "vi",
            "output_mode": "vi_only",
            "audience": "designers",
            "translation_approach": "faithful",
            "image_text_policy": "selective",
            "image_annotation_policy": "selective",
            "market_context_policy": "labeled_selective",
            "layout_policy": "preserve",
        }

        start_project(self.target, source, answers)
        config = self.target / "bookstudio.toml"
        glossary = self.target / "glossary.md"
        config.write_text(config.read_text(encoding="utf-8") + "\n# user note\n", encoding="utf-8")
        glossary.write_text("# My glossary\n", encoding="utf-8")

        result = start_project(self.target, source, answers)

        self.assertEqual("ready", result["status"])
        self.assertIn("# user note", config.read_text(encoding="utf-8"))
        self.assertEqual("# My glossary\n", glossary.read_text(encoding="utf-8"))
        self.assertTrue((self.target / "state/intake.json").is_file())
        self.assertEqual("designers", load_config(config).profile["audience"])

    def test_start_rejects_owned_intake_drift_without_overwriting_user_edits(self) -> None:
        source = self.workspace / "guided.epub"
        build_synthetic_epub(source)
        answers = {
            "target_language": "vi",
            "output_mode": "vi_only",
            "audience": "designers",
            "translation_approach": "faithful",
            "image_text_policy": "selective",
            "image_annotation_policy": "selective",
            "market_context_policy": "labeled_selective",
            "layout_policy": "preserve",
        }
        start_project(self.target, source, answers)
        config = self.target / "bookstudio.toml"
        glossary = self.target / "glossary.md"
        before = (config.read_bytes(), glossary.read_bytes())

        with self.assertRaisesRegex(BookStudioError, "PROJECT_INTAKE_DRIFT"):
            start_project(self.target, source, {**answers, "audience": "authors"})

        self.assertEqual(before, (config.read_bytes(), glossary.read_bytes()))

    def test_start_rejects_source_bytes_changed_at_the_configured_path(self) -> None:
        source = self.workspace / "guided.epub"
        build_synthetic_epub(source)
        answers = {
            "target_language": "vi",
            "output_mode": "vi_only",
            "audience": "designers",
            "translation_approach": "faithful",
            "image_text_policy": "selective",
            "image_annotation_policy": "selective",
            "market_context_policy": "labeled_selective",
            "layout_policy": "preserve",
        }
        start_project(self.target, source, answers)
        receipt_paths = (
            self.target / "state/intake.json",
            self.target / "state/inspection.json",
            self.target / "source-blocks/full-block-map.json",
            self.target / "source-blocks/coverage.json",
        )
        before = {path: path.read_bytes() for path in receipt_paths}
        build_synthetic_epub(source, include_image=False)

        with self.assertRaisesRegex(BookStudioError, "PROJECT_SOURCE_DRIFT"):
            start_project(self.target, source, answers)

        self.assertEqual(before, {path: path.read_bytes() for path in receipt_paths})

    def test_start_fails_closed_for_malformed_locked_intake(self) -> None:
        source = self.workspace / "guided.epub"
        build_synthetic_epub(source)
        answers = {
            "target_language": "vi",
            "output_mode": "vi_only",
            "audience": "designers",
            "translation_approach": "faithful",
            "image_text_policy": "selective",
            "image_annotation_policy": "selective",
            "market_context_policy": "labeled_selective",
            "layout_policy": "preserve",
        }
        start_project(self.target, source, answers)
        intake = self.target / "state/intake.json"
        intake.write_text('{"status": "locked"}', encoding="utf-8")
        receipt_paths = (
            self.target / "state/inspection.json",
            self.target / "source-blocks/full-block-map.json",
            self.target / "source-blocks/coverage.json",
        )
        before = {path: path.read_bytes() for path in receipt_paths}

        with self.assertRaisesRegex(BookStudioError, "PROJECT_INTAKE_INVALID"):
            start_project(self.target, source, answers)

        self.assertEqual(before, {path: path.read_bytes() for path in receipt_paths})


class GuidedRestartOwnershipTests(unittest.TestCase):
    SINGLETON_PATHS = (
        ".bookstudio-project",
        ".bookstudio-guided",
        "bookstudio.toml",
        "glossary.md",
        "state/intake.json",
        "state/inspection.json",
        "state/pilot.json",
        "source-blocks/full-block-map.json",
        "source-blocks/coverage.json",
        "cache/translations.json",
        "assets/image-manifest.json",
        "reference-notes.json",
    )
    MANAGED_DIRECTORY_PATHS = (
        "state",
        "source-blocks",
        "packets",
        "cache",
        "assets",
        "assets/localized",
        "output",
        "reports",
    )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "guided.epub"
        self.project = self.root / "guided-project"
        build_synthetic_epub(self.source)
        self.answers = {
            "target_language": "vi",
            "output_mode": "target_only",
            "audience": "designers",
            "translation_approach": "faithful",
            "image_text_policy": "selective",
            "image_annotation_policy": "selective",
            "market_context_policy": "labeled_selective",
            "layout_policy": "preserve",
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def snapshot(
        self, root: Path | None = None
    ) -> dict[str, tuple[int, int, int, int, str, bytes | str]]:
        tree_root = root or self.project
        if not tree_root.exists() and not tree_root.is_symlink():
            return {}
        nodes = [tree_root]
        if tree_root.is_dir() and not tree_root.is_symlink():
            nodes.extend(sorted(tree_root.rglob("*")))
        receipt = {}
        for path in nodes:
            metadata = path.lstat()
            if path.is_symlink():
                kind = "symlink"
                payload: bytes | str = str(path.readlink())
            elif path.is_file():
                kind = "file"
                payload = path.read_bytes()
            else:
                kind = "directory"
                payload = b""
            relative = "." if path == tree_root else path.relative_to(tree_root).as_posix()
            receipt[relative] = (
                metadata.st_mode,
                metadata.st_ino,
                metadata.st_mtime_ns,
                metadata.st_size,
                kind,
                payload,
            )
        return receipt

    def replace_with_directory(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        path.mkdir(parents=True)

    def replace_with_symlink(self, path: Path, target: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        path.symlink_to(target, target_is_directory=target.is_dir())

    def assert_path_shape_failure_without_mutation(
        self,
        project: Path,
        *,
        expected_code: str,
        outside: Path | None = None,
    ) -> None:
        before = self.snapshot(project)
        outside_before = self.snapshot(outside) if outside is not None else None
        caught: Exception | None = None
        try:
            start_project(project, self.source, self.answers)
        except Exception as error:  # exact type is asserted after the mutation receipt
            caught = error

        self.assertEqual(before, self.snapshot(project))
        if outside is not None:
            self.assertEqual(outside_before, self.snapshot(outside))
        self.assertIsInstance(caught, BookStudioError)
        assert isinstance(caught, BookStudioError)
        self.assertEqual(expected_code, caught.code)

    def test_start_refuses_direct_init_project_before_any_mutation(self) -> None:
        init_project(
            self.project,
            slug="guided-project",
            source=self.source,
            target_language="vi",
            output_mode="target_only",
        )
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "PROJECT_GUIDED_OWNERSHIP_REQUIRED"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())

    def test_guided_start_creates_dedicated_marker_but_direct_init_does_not(self) -> None:
        direct = self.root / "direct"
        init_project(
            direct,
            slug="direct",
            source=self.source,
            target_language="vi",
            output_mode="target_only",
        )

        start_project(self.project, self.source, self.answers)

        self.assertEqual(
            direct / ".bookstudio-guided",
            getattr(ProjectPaths.from_root(direct), "guided_marker", None),
        )
        self.assertFalse((direct / ".bookstudio-guided").exists())
        self.assertTrue((self.project / ".bookstudio-guided").is_file())

    def test_guided_marker_is_first_recoverable_write_and_cannot_claim_unrelated_data(
        self,
    ) -> None:
        from bookstudio import project as project_module

        original_atomic_write_text = project_module.atomic_write_text

        def interrupt_before_generic_marker(path: Path, text: str) -> None:
            if path.name == PROJECT_MARKER:
                raise RuntimeError("simulated interruption before generic ownership")
            original_atomic_write_text(path, text)

        with patch(
            "bookstudio.project.atomic_write_text",
            side_effect=interrupt_before_generic_marker,
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                init_project(
                    self.project,
                    slug="guided-project",
                    source=self.source,
                    target_language="vi",
                    output_mode="target_only",
                    guided=True,
                )

        self.assertEqual({GUIDED_MARKER}, {path.name for path in self.project.iterdir()})

        result = start_project(self.project, self.source, self.answers)

        self.assertEqual("pilot_proposed", result["workflow_status"])
        self.assertTrue((self.project / PROJECT_MARKER).is_file())
        self.assertTrue((self.project / "state/intake.json").is_file())

        unrelated = self.root / "unrelated-marker"
        unrelated.mkdir()
        (unrelated / GUIDED_MARKER).write_text(
            "bookstudio-guided-v1\n", encoding="utf-8"
        )
        (unrelated / "personal-notes.txt").write_text("keep", encoding="utf-8")
        before = {
            path.name: path.read_bytes() for path in unrelated.iterdir() if path.is_file()
        }

        with self.assertRaisesRegex(BookStudioError, "PROJECT_NOT_OWNED"):
            start_project(unrelated, self.source, self.answers)

        self.assertEqual(
            before,
            {path.name: path.read_bytes() for path in unrelated.iterdir() if path.is_file()},
        )

    def test_complete_matching_restart_is_byte_and_metadata_non_mutating(self) -> None:
        start_project(self.project, self.source, self.answers)
        before = self.snapshot()

        result = start_project(self.project, self.source, self.answers)

        self.assertEqual("pilot_proposed", result["workflow_status"])
        self.assertEqual(before, self.snapshot())

    def test_restart_rejects_immutable_config_drift_without_mutation(self) -> None:
        start_project(self.project, self.source, self.answers)
        config_path = self.project / "bookstudio.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'target_language = "vi"', 'target_language = "fr"'
            ),
            encoding="utf-8",
        )
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "PROJECT_CONFIG_DRIFT"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())

    def test_restart_preserves_valid_existing_coverage_decision(self) -> None:
        start_project(self.project, self.source, self.answers)
        coverage_path = self.project / "source-blocks/coverage.json"
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["excluded_files"] = ["OEBPS/text/legal.xhtml"]
        atomic_write_json(coverage_path, coverage)
        before = self.snapshot()

        start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())

    def test_marked_interrupted_restart_reconstructs_only_missing_artifacts(self) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        image_manifest = self.project / "assets/image-manifest.json"
        reference_notes = self.project / "reference-notes.json"
        atomic_write_json(image_manifest, {"schema_version": 1, "images": []})
        atomic_write_json(reference_notes, {"notes": []})
        coverage_before = paths.source_blocks.joinpath("coverage.json").read_bytes()
        config_before = paths.config.read_bytes()
        glossary_before = paths.glossary.read_bytes()
        image_manifest_before = image_manifest.read_bytes()
        reference_notes_before = reference_notes.read_bytes()
        for path in (
            paths.intake,
            paths.inspection,
            paths.source_blocks / "full-block-map.json",
            paths.pilot,
        ):
            path.unlink()

        result = start_project(self.project, self.source, self.answers)

        self.assertEqual("pilot_proposed", result["workflow_status"])
        for path in (
            paths.intake,
            paths.inspection,
            paths.source_blocks / "full-block-map.json",
            paths.pilot,
        ):
            self.assertTrue(path.is_file(), path)
        self.assertEqual(config_before, paths.config.read_bytes())
        self.assertEqual(glossary_before, paths.glossary.read_bytes())
        self.assertEqual(
            coverage_before,
            paths.source_blocks.joinpath("coverage.json").read_bytes(),
        )
        self.assertEqual(image_manifest_before, image_manifest.read_bytes())
        self.assertEqual(reference_notes_before, reference_notes.read_bytes())

    def test_restart_preflights_present_pilot_before_reconstructing_its_dependencies(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        pilot_before = paths.pilot.read_bytes()
        dependency_paths = (
            paths.intake,
            paths.inspection,
            paths.source_blocks / "full-block-map.json",
        )
        for path in dependency_paths:
            path.unlink()

        result = start_project(self.project, self.source, self.answers)

        self.assertEqual("pilot_proposed", result["workflow_status"])
        self.assertEqual(pilot_before, paths.pilot.read_bytes())
        self.assertTrue(all(path.is_file() for path in dependency_paths))

        pilot = json.loads(paths.pilot.read_text(encoding="utf-8"))
        pilot["reason_codes"].append("unexpected-restart-reason")
        atomic_write_json(paths.pilot, pilot)
        for path in dependency_paths:
            path.unlink()
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "PILOT_SELECTION_STALE"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())
        self.assertTrue(all(not path.exists() for path in dependency_paths))

    def test_marked_restart_without_intake_validates_config_profile(self) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        paths.intake.unlink()
        original = paths.config.read_text(encoding="utf-8")
        mutations = (
            ("translation_approach", "faithful", "adaptive"),
            ("image_text_policy", "selective", "all"),
            ("image_annotation_policy", "selective", "all"),
            ("market_context_policy", "labeled_selective", "none"),
            ("layout_policy", "preserve", "adaptive"),
        )
        for key, current, changed in mutations:
            with self.subTest(key=key):
                paths.config.write_text(
                    original.replace(
                        f'{key} = "{current}"', f'{key} = "{changed}"'
                    ),
                    encoding="utf-8",
                )
                self.assertNotEqual(original, paths.config.read_text(encoding="utf-8"))
                before = self.snapshot()

                with self.assertRaisesRegex(BookStudioError, "PROJECT_CONFIG_DRIFT"):
                    start_project(self.project, self.source, self.answers)

                self.assertEqual(before, self.snapshot())

    def test_restart_rejects_invalid_present_coverage_instead_of_overwriting(self) -> None:
        start_project(self.project, self.source, self.answers)
        coverage_path = self.project / "source-blocks/coverage.json"
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["source_sha256"] = "0" * 64
        atomic_write_json(coverage_path, coverage)
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "PROJECT_ARTIFACT_INVALID"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())

    def test_restart_rejects_boolean_locked_intake_schema_without_mutation(self) -> None:
        start_project(self.project, self.source, self.answers)
        intake_path = self.project / "state/intake.json"
        intake = json.loads(intake_path.read_text(encoding="utf-8"))
        intake["schema_version"] = True
        atomic_write_json(intake_path, intake)
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "PROJECT_INTAKE_INVALID"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())

    def test_restart_exact_compares_complete_locked_intake_before_reconstructing_pilot(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        original_intake = json.loads(paths.intake.read_text(encoding="utf-8"))

        def tamper_facts(payload: dict) -> None:
            payload["book_facts"]["spine_items"] += 1

        def tamper_questions(payload: dict) -> None:
            payload["questions"] = [{"id": "unexpected"}]

        def add_extra_key(payload: dict) -> None:
            payload["private_note"] = "must not be accepted"

        for name, mutate in (
            ("book facts", tamper_facts),
            ("questions", tamper_questions),
            ("extra key", add_extra_key),
        ):
            with self.subTest(name=name):
                payload = json.loads(json.dumps(original_intake))
                mutate(payload)
                atomic_write_json(paths.intake, payload)
                paths.pilot.unlink(missing_ok=True)
                before = self.snapshot()

                with self.assertRaisesRegex(BookStudioError, "PROJECT_INTAKE_DRIFT"):
                    start_project(self.project, self.source, self.answers)

                self.assertEqual(before, self.snapshot())
                self.assertFalse(paths.pilot.exists())

    def test_restart_rejects_nested_boolean_number_confusion_before_reconstructing_pilot(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        intake = json.loads(paths.intake.read_text(encoding="utf-8"))
        self.assertIs(type(intake["book_facts"]["images"]), int)
        self.assertEqual(1, intake["book_facts"]["images"])
        intake["book_facts"]["images"] = True
        atomic_write_json(paths.intake, intake)
        paths.pilot.unlink()
        before = self.snapshot()

        caught: BookStudioError | None = None
        try:
            start_project(self.project, self.source, self.answers)
        except BookStudioError as error:
            caught = error

        self.assertIsNotNone(caught)
        assert caught is not None
        self.assertEqual("PROJECT_INTAKE_DRIFT", caught.code)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(paths.pilot.exists())

    def test_restart_rejects_boolean_number_tampering_in_every_present_artifact(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        artifact_paths = {
            "inspection": paths.inspection,
            "block map": paths.source_blocks / "full-block-map.json",
            "coverage": paths.source_blocks / "coverage.json",
        }
        originals = {name: path.read_bytes() for name, path in artifact_paths.items()}

        def tamper_inspection(payload: dict) -> None:
            self.assertIs(type(payload["image_resources"]), int)
            self.assertEqual(1, payload["image_resources"])
            payload["image_resources"] = True

        def tamper_block_map(payload: dict) -> None:
            block = next(
                block
                for file in payload["files"]
                for block in file["blocks"]
                if block["block_index"] == 1
            )
            self.assertIs(type(block["block_index"]), int)
            block["block_index"] = True

        def tamper_coverage(payload: dict) -> None:
            self.assertIs(type(payload["schema_version"]), int)
            payload["schema_version"] = True

        for name, mutate in (
            ("inspection", tamper_inspection),
            ("block map", tamper_block_map),
            ("coverage", tamper_coverage),
        ):
            with self.subTest(name=name):
                for artifact_name, path in artifact_paths.items():
                    path.write_bytes(originals[artifact_name])
                payload = json.loads(artifact_paths[name].read_text(encoding="utf-8"))
                mutate(payload)
                atomic_write_json(artifact_paths[name], payload)
                paths.pilot.unlink(missing_ok=True)
                before = self.snapshot()

                caught: BookStudioError | None = None
                try:
                    start_project(self.project, self.source, self.answers)
                except BookStudioError as error:
                    caught = error

                self.assertIsNotNone(caught)
                assert caught is not None
                self.assertEqual("PROJECT_ARTIFACT_INVALID", caught.code)
                self.assertEqual(before, self.snapshot())
                self.assertFalse(paths.pilot.exists())

    def test_restart_validates_all_present_artifacts_before_reconstructing_any_missing(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        coverage_path = paths.source_blocks / "coverage.json"
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["schema_version"] = True
        atomic_write_json(coverage_path, coverage)
        for path in (paths.intake, paths.inspection, paths.pilot):
            path.unlink()
        before = self.snapshot()

        caught: BookStudioError | None = None
        try:
            start_project(self.project, self.source, self.answers)
        except BookStudioError as error:
            caught = error

        self.assertIsNotNone(caught)
        assert caught is not None
        self.assertEqual("PROJECT_ARTIFACT_INVALID", caught.code)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(paths.intake.exists())
        self.assertFalse(paths.inspection.exists())
        self.assertFalse(paths.pilot.exists())

    def test_restart_preflights_present_cache_before_reconstructing_any_missing(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        cache_path = paths.cache / "translations.json"
        atomic_write_json(
            cache_path,
            {
                "schema_version": 1,
                "source_sha256": "",
                "files": {},
                "unexpected": True,
            },
        )
        paths.inspection.unlink()
        paths.pilot.unlink()
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "CACHE_SCHEMA_INVALID"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())
        self.assertFalse(paths.inspection.exists())
        self.assertFalse(paths.pilot.exists())

    def test_restart_preflights_exact_ownership_markers_before_reconstructing_pilot(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        originals = {
            paths.marker: paths.marker.read_bytes(),
            paths.guided_marker: paths.guided_marker.read_bytes(),
            paths.pilot: paths.pilot.read_bytes(),
        }

        for name, marker in (
            ("project marker", paths.marker),
            ("guided marker", paths.guided_marker),
        ):
            with self.subTest(name=name):
                for path, content in originals.items():
                    path.write_bytes(content)
                marker.write_text("tampered-marker\n", encoding="utf-8")
                paths.pilot.unlink()
                before = self.snapshot()

                with self.assertRaisesRegex(BookStudioError, "PROJECT_NOT_OWNED"):
                    start_project(self.project, self.source, self.answers)

                self.assertEqual(before, self.snapshot())
                self.assertFalse(paths.pilot.exists())

    def test_restart_preflights_image_manifest_before_reconstructing_any_missing(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        atomic_write_json(
            self.project / "assets/image-manifest.json",
            {"schema_version": True, "images": []},
        )
        paths.inspection.unlink()
        paths.pilot.unlink()
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "IMAGE_MANIFEST_SCHEMA_INVALID"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())
        self.assertFalse(paths.inspection.exists())
        self.assertFalse(paths.pilot.exists())

    def test_restart_rejects_boolean_config_schema_before_reconstructing_pilot(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        paths.config.write_text(
            paths.config.read_text(encoding="utf-8").replace(
                "schema_version = 1", "schema_version = true", 1
            ),
            encoding="utf-8",
        )
        paths.pilot.unlink()
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "CONFIG_SCHEMA_UNSUPPORTED"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())
        self.assertFalse(paths.pilot.exists())

    def test_restart_preflights_reference_notes_json_before_reconstructing_any_missing(
        self,
    ) -> None:
        start_project(self.project, self.source, self.answers)
        paths = ProjectPaths.from_root(self.project)
        (self.project / "reference-notes.json").write_text(
            "{not-json", encoding="utf-8"
        )
        paths.inspection.unlink()
        paths.pilot.unlink()
        before = self.snapshot()

        with self.assertRaisesRegex(BookStudioError, "REFERENCE_NOTES_JSON_INVALID"):
            start_project(self.project, self.source, self.answers)

        self.assertEqual(before, self.snapshot())
        self.assertFalse(paths.inspection.exists())
        self.assertFalse(paths.pilot.exists())

    def test_demanded_wrong_node_cases_fail_before_reconstructing_missing_state(
        self,
    ) -> None:
        cases = (
            (
                "config directory",
                "bookstudio.toml",
                ("glossary.md", "state/pilot.json"),
            ),
            ("glossary directory", "glossary.md", ("state/pilot.json",)),
            (
                "image manifest directory",
                "assets/image-manifest.json",
                ("state/pilot.json",),
            ),
        )
        for index, (name, wrong_node, missing_nodes) in enumerate(cases):
            with self.subTest(name=name):
                project = self.root / f"demanded-{index}"
                start_project(project, self.source, self.answers)
                self.replace_with_directory(project / wrong_node)
                for missing_node in missing_nodes:
                    (project / missing_node).unlink()

                self.assert_path_shape_failure_without_mutation(
                    project, expected_code="PROJECT_ARTIFACT_PATH_INVALID"
                )
                self.assertTrue(
                    all(not (project / missing_node).exists() for missing_node in missing_nodes)
                )

    def test_every_singleton_path_rejects_a_directory_before_reconstruction(
        self,
    ) -> None:
        for index, relative in enumerate(self.SINGLETON_PATHS):
            with self.subTest(path=relative):
                project = self.root / f"singleton-directory-{index}"
                start_project(project, self.source, self.answers)
                wrong_node = project / relative
                self.replace_with_directory(wrong_node)
                missing = (
                    project / "state/inspection.json"
                    if relative == "state/pilot.json"
                    else project / "state/pilot.json"
                )
                missing.unlink()

                self.assert_path_shape_failure_without_mutation(
                    project, expected_code="PROJECT_ARTIFACT_PATH_INVALID"
                )
                self.assertTrue(wrong_node.is_dir())
                self.assertFalse(missing.exists())

    def test_every_singleton_path_rejects_regular_and_broken_symlinks(
        self,
    ) -> None:
        optional_content = {
            "cache/translations.json": (
                b'{"schema_version":1,"source_sha256":"","files":{}}\n'
            ),
            "assets/image-manifest.json": b'{"schema_version":1,"images":[]}\n',
            "reference-notes.json": b'{"notes":[]}\n',
        }
        for variant in ("regular", "broken"):
            for index, relative in enumerate(self.SINGLETON_PATHS):
                with self.subTest(variant=variant, path=relative):
                    project = self.root / f"singleton-{variant}-{index}"
                    outside = self.root / f"outside-singleton-{variant}-{index}"
                    outside.mkdir()
                    start_project(project, self.source, self.answers)
                    wrong_node = project / relative
                    original = (
                        wrong_node.read_bytes()
                        if wrong_node.is_file()
                        else optional_content[relative]
                    )
                    outside_target = outside / "node"
                    if variant == "regular":
                        outside_target.write_bytes(original)
                    self.replace_with_symlink(wrong_node, outside_target)
                    missing = (
                        project / "state/inspection.json"
                        if relative == "state/pilot.json"
                        else project / "state/pilot.json"
                    )
                    missing.unlink()

                    self.assert_path_shape_failure_without_mutation(
                        project,
                        expected_code="PROJECT_ARTIFACT_PATH_INVALID",
                        outside=outside,
                    )
                    self.assertTrue(wrong_node.is_symlink())
                    self.assertFalse(missing.exists())

    def test_every_managed_directory_rejects_wrong_node_shapes_before_reconstruction(
        self,
    ) -> None:
        for variant in ("regular_file", "directory_symlink", "broken_symlink"):
            for index, relative in enumerate(self.MANAGED_DIRECTORY_PATHS):
                with self.subTest(variant=variant, path=relative):
                    project = self.root / f"directory-{variant}-{index}"
                    outside = self.root / f"outside-directory-{variant}-{index}"
                    outside.mkdir()
                    start_project(project, self.source, self.answers)
                    wrong_node = project / relative
                    if wrong_node.is_dir():
                        shutil.rmtree(wrong_node)
                    elif wrong_node.is_symlink() or wrong_node.is_file():
                        wrong_node.unlink()
                    if variant == "regular_file":
                        wrong_node.write_text("wrong node\n", encoding="utf-8")
                    else:
                        outside_target = outside / "node"
                        if variant == "directory_symlink":
                            outside_target.mkdir()
                        wrong_node.symlink_to(outside_target, target_is_directory=True)
                    if relative not in {"state", "source-blocks"}:
                        (project / "state/pilot.json").unlink()

                    self.assert_path_shape_failure_without_mutation(
                        project,
                        expected_code="PROJECT_DIRECTORY_PATH_INVALID",
                        outside=outside,
                    )
                    self.assertFalse(wrong_node.is_dir() and not wrong_node.is_symlink())

    def test_project_root_symlink_still_resolves_to_the_owned_project(self) -> None:
        real_project = self.root / "resolved-project"
        project_alias = self.root / "resolved-project-alias"
        start_project(real_project, self.source, self.answers)
        project_alias.symlink_to(real_project, target_is_directory=True)
        (real_project / "state/pilot.json").unlink()

        result = start_project(project_alias, self.source, self.answers)

        self.assertEqual("pilot_proposed", result["workflow_status"])
        self.assertTrue(project_alias.is_symlink())
        self.assertTrue((real_project / "state/pilot.json").is_file())


if __name__ == "__main__":
    unittest.main()
