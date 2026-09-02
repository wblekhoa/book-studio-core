from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.fixtures import _member, build_synthetic_epub


class FinalEpubAuditScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source.epub"
        self.output = self.root / "output.epub"
        self.script = (
            Path(__file__).resolve().parents[1]
            / "skills/book-translation/scripts/audit_final_epub.py"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _rewrite(self, source: Path, output: Path, replacements: dict[str, list[tuple[bytes, bytes]]]) -> None:
        with zipfile.ZipFile(source) as archive:
            entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(output, "w") as archive:
            for name, data in entries:
                for old, new in replacements.get(name, []):
                    data = data.replace(old, new)
                archive.writestr(_member(name, data, stored=name == "mimetype")[0], data)

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--source",
                str(self.source),
                "--output",
                str(self.output),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_flags_invisible_translation_collapsed_deep_nav_and_unchanged_image_text(self) -> None:
        build_synthetic_epub(self.source, include_navigation=True)
        intermediate = self.root / "source-with-deep-nav.epub"
        self._rewrite(
            self.source,
            intermediate,
            {
                "OEBPS/text/chapter.xhtml": [
                    (
                        b"</section>",
                        b'<h2 id="section-two">Second section</h2>'
                        b'<svg xmlns="http://www.w3.org/2000/svg"><text>Source diagram label</text></svg>'
                        b"</section>",
                    )
                ],
                "OEBPS/text/nav.xhtml": [
                    (
                        b"</ol>",
                        b'<li><a href="chapter.xhtml#section-two">Second Section</a></li></ol>',
                    )
                ],
            },
        )
        self.source = intermediate
        self._rewrite(
            self.source,
            self.output,
            {
                "OEBPS/text/chapter.xhtml": [
                    (
                        b"<p>Readers should not have to <em>decode</em> a primary action. <a href=\"#note-1\">One note</a> explains why.</p>",
                        (
                            '<p class="bs-translation">\u200b</p>'
                            '<p class="bs-translation">\u034f</p>'
                        ).encode("utf-8"),
                    )
                ],
                "OEBPS/text/nav.xhtml": [
                    (b">Chapter One</a>", b">Chuong</a>"),
                    (b">Second Section</a>", b">Chuong</a>"),
                ],
            },
        )

        result = self._run()

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        hard_by_code = {row["code"]: row["count"] for row in receipt["hard_failures"]}
        hard_codes = set(hard_by_code)
        review_codes = {row["code"] for row in receipt["review_findings"]}
        self.assertIn("invisible_translation", hard_codes)
        self.assertEqual(2, hard_by_code["invisible_translation"])
        self.assertIn("navigation_label_collapse", hard_codes)
        self.assertIn("unchanged_figcaption", review_codes)
        self.assertIn("unchanged_alt", review_codes)
        self.assertIn("unchanged_text", review_codes)
        self.assertIn("unchanged_opening_text", review_codes)
        self.assertNotIn("A tiny original image", result.stdout)

    def test_passes_when_reviewable_strings_and_navigation_are_localized(self) -> None:
        build_synthetic_epub(self.source, include_navigation=True)
        source_with_external_link = self.root / "source-with-external-link.epub"
        self._rewrite(
            self.source,
            source_with_external_link,
            {
                "OEBPS/text/nav.xhtml": [
                    (
                        b"</ol>",
                        b'<li><a href="https://example.com">External resource</a></li></ol>',
                    )
                ]
            },
        )
        self.source = source_with_external_link
        self._rewrite(
            self.source,
            self.output,
            {
                "OEBPS/content.opf": [
                    (b"Book Studio Synthetic", b"Sach mau Book Studio")
                ],
                "OEBPS/text/title.xhtml": [
                    (b"Synthetic Book", b"Sach mau"),
                    (
                        b"A safe sample for Book Studio.",
                        b"Mot mau an toan cho Book Studio.",
                    ),
                ],
                "OEBPS/text/chapter.xhtml": [
                    (b"Chapter One", b"Chuong Mot"),
                    (b"A synthetic one-pixel example", b"Vi du mot diem anh"),
                    (b"A tiny original image.", b"Mot hinh minh hoa nho."),
                ],
                "OEBPS/text/legal.xhtml": [
                    (b"<title>Legal</title>", b"<title>Phap ly</title>")
                ],
                "OEBPS/text/nav.xhtml": [
                    (b"Contents", b"Muc luc"),
                    (b"Synthetic Book", b"Sach mau"),
                    (b"Chapter One", b"Chuong Mot"),
                ],
                "OEBPS/toc.ncx": [
                    (b"Book Studio Synthetic", b"Sach mau Book Studio"),
                    (b"Synthetic Book", b"Sach mau"),
                    (b"Chapter One", b"Chuong Mot"),
                ],
            },
        )

        result = self._run()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual("pass", receipt["status"])
        self.assertEqual([], receipt["hard_failures"])
        self.assertEqual([], receipt["review_findings"])

    def test_unchanged_opening_paragraph_requires_review_without_leaking_text(self) -> None:
        build_synthetic_epub(self.source, include_image=False)
        self._rewrite(
            self.source,
            self.output,
            {
                "OEBPS/content.opf": [
                    (b"Book Studio Synthetic", b"Sach mau Book Studio")
                ],
                "OEBPS/text/title.xhtml": [
                    (b"Synthetic Book", b"Sach mau")
                ],
                "OEBPS/text/chapter.xhtml": [
                    (b"Chapter One", b"Chuong Mot")
                ],
                "OEBPS/text/legal.xhtml": [
                    (b"<title>Legal</title>", b"<title>Phap ly</title>")
                ],
            },
        )

        result = self._run()

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual("review_required", receipt["status"])
        review_by_code = {
            row["code"]: row["count"] for row in receipt["review_findings"]
        }
        self.assertEqual(1, review_by_code["unchanged_opening_text"])
        self.assertEqual(1, receipt["opening_documents_compared"])
        self.assertNotIn("A safe sample for Book Studio", result.stdout)

    def test_bodymatter_does_not_end_front_matter_before_preface(self) -> None:
        build_synthetic_epub(self.source, include_image=False)
        with zipfile.ZipFile(self.source) as archive:
            entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
        preface = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Preface</title></head><body epub:type="bodymatter">
<section><h1>Preface</h1><p>This opening explains how the reader should approach the book.</p></section>
</body></html>
'''
        with zipfile.ZipFile(self.source, "w") as archive:
            for name, data in entries:
                if name == "OEBPS/content.opf":
                    data = data.replace(
                        b'<item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/>',
                        b'<item id="preface" href="text/preface.xhtml" media-type="application/xhtml+xml"/>\n'
                        b'    <item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/>',
                    ).replace(
                        b'<itemref idref="chapter"/>',
                        b'<itemref idref="preface"/>\n    <itemref idref="chapter"/>',
                    )
                archive.writestr(_member(name, data, stored=name == "mimetype")[0], data)
            archive.writestr(_member("OEBPS/text/preface.xhtml", preface)[0], preface)
        self._rewrite(
            self.source,
            self.output,
            {
                "OEBPS/content.opf": [
                    (b"Book Studio Synthetic", b"Sach mau Book Studio")
                ],
                "OEBPS/text/title.xhtml": [
                    (b"Synthetic Book", b"Sach mau"),
                    (b"A safe sample for Book Studio.", b"Mot mau an toan cho Book Studio."),
                ],
                "OEBPS/text/chapter.xhtml": [
                    (b"Chapter One", b"Chuong Mot")
                ],
                "OEBPS/text/legal.xhtml": [
                    (b"<title>Legal</title>", b"<title>Phap ly</title>")
                ],
                "OEBPS/text/preface.xhtml": [
                    (b"<title>Preface</title>", b"<title>Loi noi dau</title>"),
                    (b"<h1>Preface</h1>", b"<h1>Loi noi dau</h1>"),
                ],
            },
        )

        result = self._run()

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        review_by_code = {
            row["code"]: row["count"] for row in receipt["review_findings"]
        }
        self.assertEqual(1, review_by_code["unchanged_opening_text"])
        self.assertEqual(2, receipt["opening_documents_compared"])
        self.assertNotIn("This opening explains", result.stdout)


if __name__ == "__main__":
    unittest.main()
