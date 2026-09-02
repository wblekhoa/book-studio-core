from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bookstudio.epub.extract import extract_block_map
from bookstudio.epub.inspect import inspect_epub
from bookstudio.errors import BookStudioError
from bookstudio.cli import _dispatch, build_parser
from bookstudio.intake import assess_intake
from bookstudio.pdf.source import (
    build_semantic_epub_from_xml,
    inspect_pdf,
    prepare_pdf,
)
from bookstudio.project import start_project


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "bookstudio", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def write_fake_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.7\n% synthetic fixture\n%%EOF\n")


def fake_runner(*, pages: int, text: str, encrypted: bool = False):
    calls: list[str] = []

    def run(command: list[str], timeout: int):
        del timeout
        tool = Path(command[0]).name
        calls.append(tool)
        if tool == "pdfinfo":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "Title: Synthetic PDF\n"
                    "Author: Example Author\n"
                    f"Pages: {pages}\n"
                    "Tagged: no\n"
                    f"Encrypted: {'yes' if encrypted else 'no'}\n"
                    "Page size: 612 x 792 pts\n"
                    "PDF version: 1.7\n"
                ),
                stderr="",
            )
        if tool == "pdftotext":
            return SimpleNamespace(returncode=0, stdout=text, stderr="")
        raise AssertionError(f"Unexpected tool call: {command!r}")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def inspection_for(source: Path, *, pages: int = 2) -> dict[str, object]:
    return {
        "status": "pass",
        "schema_version": 1,
        "source": {
            "name": source.name,
            "sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
            "size_bytes": source.stat().st_size,
            "format": "pdf",
        },
        "metadata": {
            "title": ["Synthetic PDF"],
            "creator": ["Example Author"],
        },
        "pages": pages,
        "tagged": False,
        "text": {
            "classification": "text_layer_sufficient",
            "pages_with_text": pages,
            "pages_with_substantial_text": pages,
            "total_chars": 640,
            "coverage_ratio": 1.0,
        },
        "source_readiness": "review_required",
    }


def write_pdftohtml_fixture(root: Path) -> Path:
    (root / "page-1.png").write_bytes(_PNG_1X1)
    xml = root / "source.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE pdf2xml SYSTEM "pdf2xml.dtd">
<pdf2xml producer="synthetic" version="1.0">
  <page number="1" position="absolute" top="0" left="0" height="792" width="612">
    <fontspec id="0" size="15" family="serif" color="#000000"/>
    <fontspec id="1" size="28" family="serif" color="#000000"/>
    <text top="42" left="72" width="460" height="32" font="1">A synthetic chapter</text>
    <text top="112" left="72" width="460" height="18" font="0">A complete sentence begins the first paragraph.</text>
    <text top="134" left="72" width="460" height="18" font="0">A second line continues the same idea.</text>
    <image top="180" left="72" width="240" height="160" src="page-1.png"/>
    <text top="754" left="72" width="160" height="16" font="0">Repeated Footer</text>
    <text top="754" left="520" width="12" height="16" font="0">1</text>
  </page>
  <page number="2" position="absolute" top="0" left="0" height="792" width="612">
    <fontspec id="0" size="15" family="serif" color="#000000"/>
    <fontspec id="1" size="24" family="serif" color="#000000"/>
    <text top="62" left="72" width="460" height="28" font="1">A useful section</text>
    <text top="118" left="72" width="460" height="18" font="0">The next page preserves semantic reading order.</text>
    <text top="754" left="72" width="160" height="16" font="0">Repeated Footer</text>
    <text top="754" left="520" width="12" height="16" font="0">2</text>
  </page>
  <outline>
    <item page="1">Opening</item>
    <item page="2">A useful section</item>
  </outline>
</pdf2xml>
""",
        encoding="utf-8",
    )
    return xml


class PdfInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.source = self.workspace / "source.pdf"
        write_fake_pdf(self.source)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_inspection_classifies_a_substantial_text_layer_without_leaking_prose(self) -> None:
        marker = "private synthetic prose that must not enter the receipt"
        pages = [f"{marker} " + ("useful words " * 20) for _ in range(4)]
        runner = fake_runner(pages=4, text="\f".join(pages))

        receipt = inspect_pdf(self.source, runner=runner)

        self.assertEqual("pass", receipt["status"])
        self.assertEqual("text_layer_sufficient", receipt["text"]["classification"])
        self.assertEqual(4, receipt["text"]["pages_with_substantial_text"])
        self.assertEqual("review_required", receipt["source_readiness"])
        serialized = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn(marker, serialized)
        self.assertNotIn(str(self.workspace), serialized)
        self.assertEqual(["pdfinfo", "pdftotext"], runner.calls)

    def test_inspection_distinguishes_sparse_and_image_only_sources(self) -> None:
        mixed = inspect_pdf(
            self.source,
            runner=fake_runner(
                pages=5,
                text="\f".join(["substantial text " * 12, "", "tiny", "", ""]),
            ),
        )
        image_only = inspect_pdf(
            self.source,
            runner=fake_runner(pages=3, text="\f\f"),
        )

        self.assertEqual("mixed_or_sparse", mixed["text"]["classification"])
        self.assertEqual("image_only", image_only["text"]["classification"])
        self.assertEqual("ocr_required", image_only["source_readiness"])

    def test_encrypted_pdf_is_rejected_before_text_extraction(self) -> None:
        runner = fake_runner(pages=2, text="unused", encrypted=True)

        with self.assertRaises(BookStudioError) as caught:
            inspect_pdf(self.source, runner=runner)

        self.assertEqual("PDF_ENCRYPTED", caught.exception.code)
        self.assertEqual(["pdfinfo"], runner.calls)

    def test_prepare_refuses_image_only_pdf_without_creating_output(self) -> None:
        output = self.workspace / "prepared.epub"

        with self.assertRaises(BookStudioError) as caught:
            prepare_pdf(
                self.source,
                output,
                runner=fake_runner(pages=3, text="\f\f"),
            )

        self.assertEqual("PDF_OCR_REQUIRED", caught.exception.code)
        self.assertFalse(output.exists())

    def test_prepare_refuses_mixed_source_without_creating_output(self) -> None:
        output = self.workspace / "prepared.epub"

        with self.assertRaises(BookStudioError) as caught:
            prepare_pdf(
                self.source,
                output,
                runner=fake_runner(
                    pages=5,
                    text="\f".join(["substantial text " * 12, "", "tiny", "", ""]),
                ),
            )

        self.assertEqual("PDF_MIXED_SOURCE_REVIEW_REQUIRED", caught.exception.code)
        self.assertFalse(output.exists())

    def test_pdf_symlink_is_rejected(self) -> None:
        linked = self.workspace / "linked.pdf"
        linked.symlink_to(self.source)

        with self.assertRaises(BookStudioError) as caught:
            inspect_pdf(linked, runner=fake_runner(pages=1, text="text " * 30))

        self.assertEqual("PDF_INVALID", caught.exception.code)

    def test_inspection_detects_source_mutation_during_external_tool_run(self) -> None:
        base = fake_runner(pages=1, text="text " * 30)

        def mutating_runner(command: list[str], timeout: int):
            result = base(command, timeout)
            if Path(command[0]).name == "pdftotext":
                self.source.write_bytes(self.source.read_bytes() + b"changed")
            return result

        with self.assertRaises(BookStudioError) as caught:
            inspect_pdf(self.source, runner=mutating_runner)

        self.assertEqual("PDF_SOURCE_CHANGED", caught.exception.code)

    def test_missing_poppler_tool_has_a_stable_error_without_mutation(self) -> None:
        before = self.source.read_bytes()

        with patch("bookstudio.pdf.source.shutil.which", return_value=None):
            with self.assertRaises(BookStudioError) as caught:
                inspect_pdf(self.source)

        self.assertEqual("PDF_TOOL_MISSING", caught.exception.code)
        self.assertEqual(before, self.source.read_bytes())


class PdfSemanticEpubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.source = self.workspace / "source.pdf"
        write_fake_pdf(self.source)
        self.xml = write_pdftohtml_fixture(self.workspace)
        self.inspection = inspection_for(self.source)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_semantic_epub_is_deterministic_complete_and_pipeline_compatible(self) -> None:
        first = self.workspace / "first.epub"
        second = self.workspace / "second.epub"

        first_receipt = build_semantic_epub_from_xml(
            self.source,
            self.xml,
            first,
            self.inspection,
            source_language="en",
        )
        second_receipt = build_semantic_epub_from_xml(
            self.source,
            self.xml,
            second,
            self.inspection,
            source_language="en",
        )

        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual("source_review_required", first_receipt["status"])
        self.assertEqual(2, first_receipt["page_anchors"])
        self.assertEqual(1, first_receipt["images_preserved"])
        self.assertTrue(first_receipt["text_nodes_accounted"])
        inspected = inspect_epub(first)
        blocks = extract_block_map(first)
        self.assertEqual("pass", inspected["status"])
        self.assertEqual(2, inspected["spine_items"])
        self.assertGreaterEqual(inspected["image_resources"], 1)
        self.assertGreater(blocks["canonical_targets"], 0)
        started = start_project(
            self.workspace / "guided-project",
            first,
            {
                "target_language": "vi",
                "output_mode": "vi_only",
                "audience": "product designers",
                "translation_approach": "adaptive",
                "image_text_policy": "selective",
                "image_annotation_policy": "selective",
                "market_context_policy": "labeled_selective",
                "layout_policy": "preserve",
            },
        )
        self.assertEqual("ready", started["status"])
        self.assertEqual("pilot_proposed", started["workflow_status"])
        with zipfile.ZipFile(first) as archive:
            all_text = "\n".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith(".xhtml")
            )
            provenance = json.loads(
                archive.read("META-INF/bookstudio-source.json").decode("utf-8")
            )
            package = archive.read("OEBPS/content.opf").decode("utf-8")
        self.assertIn('id="page-1"', all_text)
        self.assertIn('id="page-2"', all_text)
        self.assertNotIn("Repeated Footer", all_text)
        self.assertIn(">Opening<", all_text)
        self.assertIn(">A useful section<", all_text)
        self.assertNotIn("../META-INF", package)
        self.assertEqual("pdf", provenance["source"]["format"])
        self.assertNotIn(str(self.workspace), json.dumps(provenance))

    def test_same_generated_output_is_idempotent(self) -> None:
        output = self.workspace / "prepared.epub"
        first = build_semantic_epub_from_xml(
            self.source,
            self.xml,
            output,
            self.inspection,
            source_language="en",
        )
        second = build_semantic_epub_from_xml(
            self.source,
            self.xml,
            output,
            self.inspection,
            source_language="en",
        )

        self.assertTrue(first["written"])
        self.assertFalse(second["written"])

    def test_omitted_pdf_language_remains_an_explicit_guided_intake_question(self) -> None:
        output = self.workspace / "unknown-language.epub"
        build_semantic_epub_from_xml(
            self.source,
            self.xml,
            output,
            self.inspection,
        )

        assessment = assess_intake(output, {})

        question_ids = [question["id"] for question in assessment["questions"]]
        self.assertIn("source_language", question_ids)
        self.assertNotIn("source_language", assessment["answers"])

    def test_xml_symlink_is_rejected(self) -> None:
        linked = self.workspace / "linked.xml"
        linked.symlink_to(self.xml)

        with self.assertRaises(BookStudioError) as caught:
            build_semantic_epub_from_xml(
                self.source,
                linked,
                self.workspace / "prepared.epub",
                self.inspection,
                source_language="en",
            )

        self.assertEqual("PDF_SOURCE_INCOMPLETE", caught.exception.code)

    def test_source_mutation_before_publish_leaves_no_output(self) -> None:
        output = self.workspace / "prepared.epub"
        original_replace = os.replace

        def mutate_then_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            self.source.write_bytes(self.source.read_bytes() + b"changed")
            original_replace(source, target)

        with patch("bookstudio.pdf.source.os.replace", side_effect=mutate_then_replace):
            with self.assertRaises(BookStudioError) as caught:
                build_semantic_epub_from_xml(
                    self.source,
                    self.xml,
                    output,
                    self.inspection,
                    source_language="en",
                )

        self.assertEqual("PDF_SOURCE_CHANGED", caught.exception.code)
        self.assertFalse(output.exists())

    def test_symlinked_extracted_image_is_rejected(self) -> None:
        image = self.workspace / "page-1.png"
        target = self.workspace / "real.png"
        image.replace(target)
        image.symlink_to(target)

        with self.assertRaises(BookStudioError) as caught:
            build_semantic_epub_from_xml(
                self.source,
                self.xml,
                self.workspace / "prepared.epub",
                self.inspection,
                source_language="en",
            )

        self.assertEqual("PDF_IMAGE_EXTRACTION_FAILED", caught.exception.code)

    def test_artifact_only_conversion_cannot_publish_an_empty_translation_source(self) -> None:
        artifact_xml = self.workspace / "artifact-only.xml"
        artifact_xml.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<pdf2xml>
  <page number="1" top="0" left="0" height="792" width="612">
    <fontspec id="0" size="15" family="serif" color="#000000"/>
    <text top="754" left="72" width="300" height="18" font="0">Repeated edge words with enough characters to appear substantial</text>
  </page>
  <page number="2" top="0" left="0" height="792" width="612">
    <fontspec id="0" size="15" family="serif" color="#000000"/>
    <text top="754" left="72" width="300" height="18" font="0">Repeated edge words with enough characters to appear substantial</text>
  </page>
</pdf2xml>
""",
            encoding="utf-8",
        )
        output = self.workspace / "empty.epub"

        with self.assertRaises(BookStudioError) as caught:
            build_semantic_epub_from_xml(
                self.source,
                artifact_xml,
                output,
                self.inspection,
                source_language="en",
            )

        self.assertEqual("PDF_SOURCE_INCOMPLETE", caught.exception.code)
        self.assertFalse(output.exists())

    def test_existing_different_output_is_preserved(self) -> None:
        output = self.workspace / "prepared.epub"
        output.write_bytes(b"user-owned output")

        with self.assertRaises(BookStudioError) as caught:
            build_semantic_epub_from_xml(
                self.source,
                self.xml,
                output,
                self.inspection,
                source_language="en",
            )

        self.assertEqual("PDF_OUTPUT_EXISTS", caught.exception.code)
        self.assertEqual(b"user-owned output", output.read_bytes())

    def test_full_page_first_image_is_declared_as_cover(self) -> None:
        cover_xml = self.workspace / "cover-source.xml"
        cover_xml.write_text(
            self.xml.read_text(encoding="utf-8").replace(
                '<image top="180" left="72" width="240" height="160"',
                '<image top="0" left="0" width="612" height="792"',
            ),
            encoding="utf-8",
        )
        output = self.workspace / "cover.epub"

        build_semantic_epub_from_xml(
            self.source,
            cover_xml,
            output,
            self.inspection,
            source_language="en",
        )

        with zipfile.ZipFile(output) as archive:
            package = archive.read("OEBPS/content.opf").decode("utf-8")
        self.assertIn('properties="cover-image"', package)
        self.assertIn('name="cover"', package)
        self.assertIn('content="pdf-image-1"', package)


class PdfCliContractTests(unittest.TestCase):
    def test_pdf_help_exposes_inspect_and_prepare_without_changing_start_contract(self) -> None:
        root = run_cli("--help")
        pdf_help = run_cli("pdf", "--help")
        prepare_help = run_cli("pdf", "prepare", "--help")
        start_help = run_cli("start", "--help")

        self.assertEqual(0, root.returncode, root.stderr)
        self.assertIn("pdf", root.stdout)
        self.assertEqual(0, pdf_help.returncode, pdf_help.stderr)
        self.assertIn("inspect", pdf_help.stdout)
        self.assertIn("prepare", pdf_help.stdout)
        self.assertEqual(0, prepare_help.returncode, prepare_help.stderr)
        self.assertIn("--output", prepare_help.stdout)
        self.assertIn("--source-language", prepare_help.stdout)
        self.assertIn("Source EPUB; it is opened read-only.", start_help.stdout)

    def test_pdf_dispatch_preserves_the_source_review_gate(self) -> None:
        parser = build_parser()
        inspect_args = parser.parse_args(["pdf", "inspect", "source.pdf", "--json"])
        prepare_args = parser.parse_args(
            [
                "pdf",
                "prepare",
                "source.pdf",
                "--output",
                "prepared.epub",
                "--json",
            ]
        )
        inspected = {
            "status": "pass",
            "text": {"classification": "text_layer_sufficient"},
            "source_readiness": "review_required",
        }
        prepared = {
            "status": "source_review_required",
            "source_readiness": "review_required",
        }

        with patch("bookstudio.cli.inspect_pdf", return_value=inspected):
            inspect_payload = _dispatch(inspect_args)
        with patch("bookstudio.cli.prepare_pdf", return_value=prepared):
            prepare_payload = _dispatch(prepare_args)

        self.assertEqual("pass", inspect_payload["status"])
        self.assertEqual("source_review_required", prepare_payload["status"])
        self.assertEqual(2, prepare_payload["_exit_code"])


if __name__ == "__main__":
    unittest.main()
