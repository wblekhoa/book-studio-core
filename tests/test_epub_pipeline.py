from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from bookstudio.config import atomic_write_json, load_config
from bookstudio.epub.build import build_epub, finish_project
from bookstudio.epub.extract import extract_block_map
from bookstudio.epub.inspect import inspect_epub
from bookstudio.epub.validate import validate_epub
from bookstudio.errors import BookStudioError
from bookstudio.images.manifest import load_image_manifest
from bookstudio.intake import assess_intake
from bookstudio.project import init_project, locked_intake
from bookstudio.translation.coverage import coverage_receipt
from bookstudio.translation.packets import apply_response, next_packet
from tests.fixtures import build_synthetic_epub, make_zip


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "bookstudio", *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class EpubInspectExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "synthetic.epub"
        build_synthetic_epub(self.source)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_inspect_measures_structure_without_absolute_source_path(self) -> None:
        receipt = inspect_epub(self.source)

        self.assertEqual(3, receipt["spine_items"])
        self.assertEqual(7, receipt["zip_entries"])
        self.assertEqual("Book Studio Synthetic", receipt["metadata"]["title"][0])
        self.assertNotIn(str(self.root), json.dumps(receipt))

    def test_extract_uses_stable_source_hashes_and_canonical_nesting(self) -> None:
        first = extract_block_map(self.source)
        second = extract_block_map(self.source)

        self.assertEqual(first, second)
        blocks = [block for file in first["files"] for block in file["blocks"]]
        self.assertTrue(all("text_sha256" in block for block in blocks))
        nested = next(block for block in blocks if block["text"] == "A nested explanation.")
        parent = next(block for block in blocks if block["tag"] == "li")
        self.assertFalse(nested["canonical"])
        self.assertTrue(parent["canonical"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), first["source"]["sha256"])
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_inspect_rejects_missing_container_without_mutating_source(self) -> None:
        make_zip(self.source, {"mimetype": b"application/epub+zip"})
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()

        with self.assertRaisesRegex(BookStudioError, "EPUB_CONTAINER_MISSING"):
            inspect_epub(self.source)

        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_cli_inspect_and_prepare_write_atomic_project_receipts(self) -> None:
        project = self.root / "project"
        init_project(
            project,
            slug="synthetic",
            source=self.source,
            target_language="vi",
            output_mode="vi_only",
        )

        inspect_result = run_cli("inspect", str(project), "--json")
        prepare_result = run_cli("prepare", str(project), "--json")

        self.assertEqual(0, inspect_result.returncode, inspect_result.stderr)
        self.assertEqual(0, prepare_result.returncode, prepare_result.stderr)
        inspection = json.loads((project / "state/inspection.json").read_text(encoding="utf-8"))
        block_map = json.loads((project / "source-blocks/full-block-map.json").read_text(encoding="utf-8"))
        coverage = json.loads((project / "source-blocks/coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(3, inspection["spine_items"])
        self.assertEqual(3, block_map["spine_files"])
        self.assertEqual([], coverage["excluded_files"])
        self.assertNotIn(str(self.root), json.dumps({"inspection": inspection, "coverage": coverage}))
        self.assertFalse(list(project.rglob("*.tmp")))


class ImageManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "synthetic.epub"
        self.project = self.root / "project"
        build_synthetic_epub(self.source)
        init_project(
            self.project,
            slug="synthetic",
            source=self.source,
            target_language="vi",
            output_mode="vi_only",
        )
        self.config = load_config(self.project / "bookstudio.toml")
        with zipfile.ZipFile(self.source) as archive:
            self.original_png = archive.read("OEBPS/images/pixel.png")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_manifest(self, record: dict) -> None:
        path = self.project / "assets/image-manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": 1, "images": [record]}),
            encoding="utf-8",
        )

    def test_original_only_and_annotation_policies_pass(self) -> None:
        for record in (
            {"source_path": "OEBPS/images/pixel.png", "policy": "original_only"},
            {
                "source_path": "OEBPS/images/pixel.png",
                "policy": "annotation",
                "annotation": "Một pixel dùng làm ví dụ.",
            },
        ):
            with self.subTest(policy=record["policy"]):
                self.write_manifest(record)
                receipt = load_image_manifest(self.config)
                self.assertTrue(receipt["passed"])

    def test_companion_must_be_project_owned_and_match_source_canvas(self) -> None:
        localized = self.project / "assets/localized/pixel-vi.png"
        localized.write_bytes(self.original_png)
        record = {
            "source_path": "OEBPS/images/pixel.png",
            "policy": "original_plus_companion",
            "companion": "assets/localized/pixel-vi.png",
        }
        self.write_manifest(record)
        self.assertEqual(1, load_image_manifest(self.config)["companion_matches"])

        outside = self.root / "outside.png"
        outside.write_bytes(self.original_png)
        self.write_manifest({**record, "companion": "../outside.png"})
        with self.assertRaisesRegex(BookStudioError, "IMAGE_COMPANION_OUTSIDE_PROJECT"):
            load_image_manifest(self.config)

        wrong_canvas = bytearray(self.original_png)
        wrong_canvas[16:20] = struct.pack(">I", 2)
        localized.write_bytes(wrong_canvas)
        self.write_manifest(record)
        with self.assertRaisesRegex(BookStudioError, "IMAGE_CANVAS_MISMATCH"):
            load_image_manifest(self.config)

    def test_manifest_rejects_missing_annotation_companion_and_source(self) -> None:
        cases = (
            ({"source_path": "OEBPS/images/pixel.png", "policy": "annotation"}, "IMAGE_ANNOTATION_MISSING"),
            ({"source_path": "OEBPS/images/pixel.png", "policy": "original_plus_companion"}, "IMAGE_COMPANION_MISSING"),
            ({"source_path": "OEBPS/images/missing.png", "policy": "original_only"}, "IMAGE_SOURCE_MISSING"),
        )
        for record, code in cases:
            with self.subTest(code=code):
                self.write_manifest(record)
                with self.assertRaisesRegex(BookStudioError, code):
                    load_image_manifest(self.config)


class BuildFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "synthetic.epub"
        build_synthetic_epub(self.source)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def ready_project(
        self,
        mode: str = "vi_only",
        *,
        target_language: str = "vi",
        profile: dict[str, str] | None = None,
        with_companion: bool = False,
    ):
        project = self.root / f"{mode}-{target_language}"
        init_project(
            project,
            slug=f"synthetic-{mode}-{target_language}",
            source=self.source,
            target_language=target_language,
            output_mode=mode,
            max_blocks=3,
            profile=profile,
        )
        config = load_config(project / "bookstudio.toml")
        if with_companion:
            self.register_companion(project, config)
        block_map = extract_block_map(self.source)
        atomic_write_json(project / "source-blocks/full-block-map.json", block_map)
        atomic_write_json(
            project / "source-blocks/coverage.json",
            {
                "schema_version": 1,
                "source_sha256": block_map["source"]["sha256"],
                "included_files": [file["source_path"] for file in block_map["files"]],
                "excluded_files": ["OEBPS/text/legal.xhtml"],
            },
        )
        response_number = 0
        while True:
            packet = next_packet(config)
            if packet is None:
                break
            response = {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": [
                    {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": f"Bản dịch {block['block_index']}",
                    }
                    for block in packet["blocks"]
                ],
            }
            response_path = self.root / f"{mode}-response-{response_number}.json"
            atomic_write_json(response_path, response)
            apply_response(config, response_path)
            response_number += 1
        return project, config

    def register_companion(self, project: Path, config) -> str:
        with zipfile.ZipFile(self.source) as archive:
            source_image = archive.read("OEBPS/images/pixel.png")
        companion = project / "assets/localized/pixel-vi.png"
        companion.write_bytes(source_image)
        manifest = {
            "schema_version": 1,
            "images": [
                {
                    "source_path": "OEBPS/images/pixel.png",
                    "policy": "original_plus_companion",
                    "companion": "assets/localized/pixel-vi.png",
                    "annotation": "Một pixel minh họa đã được Việt hóa.",
                }
            ],
        }
        (project / "assets/image-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return "OEBPS/bookstudio-localized/pixel-vi.png"


class DeterministicBuildTests(BuildFixture):

    def test_direct_build_and_finish_reject_unaccepted_guided_project(self) -> None:
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
        from bookstudio.intake import profile_from_answers
        from bookstudio.pilot import select_pilot

        project, config = self.ready_project(profile=profile_from_answers(answers))
        block_map = json.loads(
            (project / "source-blocks/full-block-map.json").read_text(encoding="utf-8")
        )
        inspection = inspect_epub(self.source)
        assessment = assess_intake(self.source, answers)
        atomic_write_json(config.paths.intake, locked_intake(assessment))

        atomic_write_json(
            config.paths.pilot,
            select_pilot(inspection, block_map, assessment["answers"]),
        )

        with self.assertRaisesRegex(BookStudioError, "PILOT_FULL_SCOPE_BLOCKED"):
            build_epub(config, self.root / "blocked.epub")
        with self.assertRaisesRegex(BookStudioError, "PILOT_FULL_SCOPE_BLOCKED"):
            finish_project(config)

        config.paths.pilot.unlink()
        before = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in sorted(project.rglob("*"))
            if path.is_file()
        }
        missing_output = self.root / "missing-pilot.epub"
        for operation in (
            lambda: build_epub(config, missing_output),
            lambda: finish_project(config),
        ):
            with self.assertRaisesRegex(BookStudioError, "PILOT_STATE_MISSING"):
                operation()
            self.assertFalse(missing_output.exists())
            self.assertEqual(
                before,
                {
                    path.relative_to(project).as_posix(): path.read_bytes()
                    for path in sorted(project.rglob("*"))
                    if path.is_file()
                },
            )

    def test_strict_coverage_status_build_and_finish_share_exact_cache_validation(
        self,
    ) -> None:
        project, config = self.ready_project()
        cache_path = project / "cache/translations.json"
        valid = json.loads(cache_path.read_text(encoding="utf-8"))
        first_document = next(iter(valid["files"]))

        def add_top_level(payload: dict) -> None:
            payload["unexpected"] = True

        def add_row_field(payload: dict) -> None:
            payload["files"][first_document][0]["private_note"] = "not canonical"

        def unsafe_xhtml(payload: dict) -> None:
            payload["files"][first_document][0]["translation_xhtml"] = "<script>bad</script>"

        def invalid_image_field(payload: dict) -> None:
            payload["files"][first_document][0]["image_annotations"] = [{}]

        def stale_role(payload: dict) -> None:
            payload["files"][first_document][0]["source_role"] = "wrong-role"

        def stale_block_hash(payload: dict) -> None:
            payload["files"][first_document][0]["source_sha256"] = "0" * 64

        def stale_source(payload: dict) -> None:
            payload["source_sha256"] = "f" * 64

        cases = (
            ("top-level key", "CACHE_SCHEMA_INVALID", add_top_level),
            ("row key", "CACHE_ROW_INVALID", add_row_field),
            ("unsafe XHTML", "XHTML_UNSAFE", unsafe_xhtml),
            (
                "invalid image annotation",
                "IMAGE_MANIFEST_SCHEMA_INVALID",
                invalid_image_field,
            ),
            ("stale role", "CACHE_ROW_INVALID", stale_role),
            ("stale block hash", "CACHE_TARGET_STALE", stale_block_hash),
            ("stale source identity", "CACHE_SOURCE_STALE", stale_source),
        )

        for name, code, mutate in cases:
            with self.subTest(name=name):
                payload = json.loads(json.dumps(valid))
                mutate(payload)
                atomic_write_json(cache_path, payload)
                before = {
                    path.relative_to(project).as_posix(): path.read_bytes()
                    for path in sorted(project.rglob("*"))
                    if path.is_file()
                }
                output = self.root / f"strict-{name.replace(' ', '-')}.epub"

                for operation in (
                    lambda: coverage_receipt(config, require_complete=True),
                    lambda: build_epub(config, output),
                    lambda: finish_project(config),
                ):
                    with self.assertRaisesRegex(BookStudioError, code):
                        operation()
                    self.assertFalse(output.exists())
                    self.assertEqual(
                        before,
                        {
                            path.relative_to(project).as_posix(): path.read_bytes()
                            for path in sorted(project.rglob("*"))
                            if path.is_file()
                        },
                    )

                status = run_cli("status", str(project), "--json")
                self.assertEqual(1, status.returncode, status.stderr)
                self.assertEqual(code, json.loads(status.stdout)["code"])
                self.assertEqual(
                    before,
                    {
                        path.relative_to(project).as_posix(): path.read_bytes()
                        for path in sorted(project.rglob("*"))
                        if path.is_file()
                    },
                )

    def test_two_builds_are_byte_identical_and_self_identified(self) -> None:
        project, config = self.ready_project(with_companion=True)
        localized_path = "OEBPS/bookstudio-localized/pixel-vi.png"
        first_path = self.root / "first.epub"
        second_path = self.root / "second.epub"

        first = build_epub(config, first_path)
        second = build_epub(config, second_path)

        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
        self.assertEqual(first["output_sha256"], second["output_sha256"])
        with zipfile.ZipFile(first_path) as output, zipfile.ZipFile(self.source) as source:
            infos = output.infolist()
            self.assertEqual("mimetype", infos[0].filename)
            self.assertEqual(zipfile.ZIP_STORED, infos[0].compress_type)
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos))
            self.assertEqual(
                source.read("OEBPS/images/pixel.png"),
                output.read("OEBPS/images/pixel.png"),
            )
            self.assertIn(localized_path, output.namelist())
            self.assertIn(b"bookstudio-localized/pixel-vi.png", output.read("OEBPS/content.opf"))
            chapter = output.read("OEBPS/text/chapter.xhtml").decode("utf-8")
            self.assertIn("bs-localized-image-block", chapter)
            self.assertIn("bs-translation", chapter)
            self.assertNotIn("bs-source", chapter)
            self.assertNotIn("Bản Việt hóa", chapter)

    def test_bilingual_build_marks_source_and_translation_blocks(self) -> None:
        _, config = self.ready_project("bilingual")
        output_path = self.root / "bilingual.epub"

        build_epub(config, output_path)

        with zipfile.ZipFile(output_path) as archive:
            chapter = archive.read("OEBPS/text/chapter.xhtml").decode("utf-8")
        self.assertIn("bs-source", chapter)
        self.assertIn("bs-translation", chapter)

    def test_non_vietnamese_editorial_labels_use_fallbacks_and_profile_overrides(self) -> None:
        cases = (
            (None, "Market context", "Image annotation"),
            (
                {
                    "market_context_label": "Contexte du marché",
                    "image_annotation_label": "Annotation de l’image",
                },
                "Contexte du marché",
                "Annotation de l’image",
            ),
        )
        for index, (profile, market_label, image_label) in enumerate(cases):
            with self.subTest(profile=profile):
                target_language = ("fr-FR", "fr-CA")[index]
                project, config = self.ready_project(
                    "target_only",
                    target_language=target_language,
                    profile=profile,
                    with_companion=True,
                )
                cache_path = config.paths.cache / "translations.json"
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                first_document = next(iter(cache["files"]))
                cache["files"][first_document][0]["market_contexts"] = [
                    "A market-specific note."
                ]
                atomic_write_json(cache_path, cache)
                output_path = self.root / f"fr-{index + 1}.epub"

                build_epub(config, output_path)

                with zipfile.ZipFile(output_path) as archive:
                    markup = "\n".join(
                        archive.read(name).decode("utf-8")
                        for name in archive.namelist()
                        if name.endswith(".xhtml")
                    )
                self.assertIn(market_label, markup)
                self.assertIn(image_label, markup)
                self.assertNotIn("Bối cảnh Việt Nam", markup)
                self.assertNotIn("Chú giải ảnh", markup)


class IntegrityTests(BuildFixture):
    def test_valid_build_passes_independent_integrity(self) -> None:
        project, config = self.ready_project(with_companion=True)
        output_path = self.root / "valid.epub"
        build_epub(config, output_path)

        receipt = validate_epub(config, output_path)

        self.assertTrue(receipt["passed"], receipt["violations"])
        self.assertEqual(0, len(receipt["violations"]))

    def test_broken_fragment_fails_and_finish_preserves_previous_final(self) -> None:
        project = self.root / "broken"
        init_project(
            project,
            slug="broken",
            source=self.source,
            target_language="vi",
            output_mode="vi_only",
        )
        config = load_config(project / "bookstudio.toml")
        block_map = extract_block_map(self.source)
        atomic_write_json(project / "source-blocks/full-block-map.json", block_map)
        atomic_write_json(
            project / "source-blocks/coverage.json",
            {
                "schema_version": 1,
                "source_sha256": block_map["source"]["sha256"],
                "included_files": [file["source_path"] for file in block_map["files"]],
                "excluded_files": ["OEBPS/text/legal.xhtml"],
            },
        )
        first = True
        response_index = 0
        while True:
            packet = next_packet(config)
            if packet is None:
                break
            rows = []
            for block in packet["blocks"]:
                row = {
                    "block_index": block["block_index"],
                    "source_sha256": block["source_sha256"],
                    "translation": "Bản dịch",
                }
                if first:
                    row["translation_xhtml"] = '<a href="#missing-fragment">Bản dịch</a>'
                    first = False
                rows.append(row)
            response = {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": rows,
            }
            response_path = self.root / f"broken-response-{response_index}.json"
            atomic_write_json(response_path, response)
            apply_response(config, response_path)
            response_index += 1

        candidate = self.root / "broken.epub"
        build_epub(config, candidate)
        receipt = validate_epub(config, candidate)
        final = project / "output/final.epub"
        final.write_bytes(b"previous-good-output")

        self.assertFalse(receipt["passed"])
        self.assertTrue(any(row["category"] == "missing_fragment" for row in receipt["violations"]))
        with self.assertRaisesRegex(BookStudioError, "INTEGRITY_FAILED"):
            finish_project(config)
        self.assertEqual(b"previous-good-output", final.read_bytes())


if __name__ == "__main__":
    unittest.main()
