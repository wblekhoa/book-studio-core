from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from bookstudio.epub.archive import ArchiveLimits, preflight_archive
from bookstudio.errors import BookStudioError
from tests.fixtures import build_synthetic_epub, make_duplicate_name_zip, make_zip


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.archive = self.root / "sample.epub"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def assert_rejected_unchanged(
        self, code: str, limits: ArchiveLimits | None = None
    ) -> None:
        before = file_hash(self.archive)
        with self.assertRaisesRegex(BookStudioError, code):
            preflight_archive(self.archive, limits=limits or ArchiveLimits())
        self.assertEqual(before, file_hash(self.archive))

    # BSC-PIPE-001
    def test_preflight_rejects_parent_traversal(self) -> None:
        make_zip(self.archive, {"../escape.xhtml": b"bad"})
        self.assert_rejected_unchanged("ARCHIVE_UNSAFE_PATH")
        self.assertFalse((self.root.parent / "escape.xhtml").exists())

    # BSC-PIPE-001
    def test_preflight_rejects_absolute_and_backslash_paths(self) -> None:
        for name in ("/absolute.xhtml", "text\\chapter.xhtml"):
            with self.subTest(name=name):
                make_zip(self.archive, {name: b"bad"})
                self.assert_rejected_unchanged("ARCHIVE_UNSAFE_PATH")

    # BSC-PIPE-002
    def test_preflight_rejects_duplicate_names(self) -> None:
        make_duplicate_name_zip(self.archive, "text/chapter.xhtml")
        self.assert_rejected_unchanged("ARCHIVE_DUPLICATE_ENTRY")

    # BSC-PIPE-002
    def test_preflight_enforces_entry_count(self) -> None:
        make_zip(self.archive, {"one": b"1", "two": b"2"})
        self.assert_rejected_unchanged(
            "ARCHIVE_ENTRY_LIMIT",
            ArchiveLimits(max_entries=1),
        )

    # BSC-PIPE-002
    def test_preflight_enforces_single_and_total_expanded_bytes(self) -> None:
        make_zip(self.archive, {"one": b"123", "two": b"456"})
        self.assert_rejected_unchanged(
            "ARCHIVE_SINGLE_SIZE_LIMIT",
            ArchiveLimits(max_single_uncompressed=2),
        )
        self.assert_rejected_unchanged(
            "ARCHIVE_TOTAL_SIZE_LIMIT",
            ArchiveLimits(max_single_uncompressed=3, max_total_uncompressed=5),
        )

    # BSC-PIPE-002
    def test_preflight_enforces_compression_ratio(self) -> None:
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("large.txt", b"0" * 4096)
        self.assert_rejected_unchanged(
            "ARCHIVE_COMPRESSION_RATIO_LIMIT",
            ArchiveLimits(max_compression_ratio=2),
        )

    def test_preflight_accepts_synthetic_epub(self) -> None:
        build_synthetic_epub(self.archive)

        receipt = preflight_archive(self.archive)

        self.assertTrue(receipt["passed"])
        self.assertEqual(7, receipt["entries"])
        self.assertEqual("sample.epub", receipt["source_name"])
        self.assertNotIn(str(self.root), str(receipt))


if __name__ == "__main__":
    unittest.main()
