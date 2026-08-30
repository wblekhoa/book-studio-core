from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bookstudio.config import atomic_write_json, load_config
from bookstudio.epub.extract import extract_block_map
from bookstudio.errors import BookStudioError
from bookstudio.project import init_project
from bookstudio.safety.xhtml import validate_inline_xhtml
from bookstudio.translation.packets import apply_response, next_packet
from tests.fixtures import build_synthetic_epub


class InlineXhtmlSafetyTests(unittest.TestCase):
    def test_safe_inline_markup_passes(self) -> None:
        receipt = validate_inline_xhtml(
            '<em>Rõ ràng</em> <a href="#note" title="Chú thích">1</a><br/>'
        )
        self.assertTrue(receipt["passed"])

    def test_script_event_style_and_unsafe_url_fail_closed(self) -> None:
        values = (
            "<script>alert(1)</script>",
            '<span onclick="x()">x</span>',
            '<span style="color:red">x</span>',
            '<a href="javascript:x()">x</a>',
            '<a href="https://example.com">x</a>',
            '<img src="data:image/png;base64,x"/>',
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(BookStudioError, "XHTML_UNSAFE"):
                    validate_inline_xhtml(value)

    def test_malformed_markup_fails_closed(self) -> None:
        with self.assertRaisesRegex(BookStudioError, "XHTML_INVALID"):
            validate_inline_xhtml("<em>unclosed")

    def test_apply_validates_xhtml_before_cache_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.epub"
            project = root / "project"
            build_synthetic_epub(source)
            init_project(
                project,
                slug="synthetic",
                source=source,
                target_language="vi",
                output_mode="vi_only",
            )
            config = load_config(project / "bookstudio.toml")
            block_map = extract_block_map(source)
            atomic_write_json(project / "source-blocks/full-block-map.json", block_map)
            atomic_write_json(
                project / "source-blocks/coverage.json",
                {
                    "schema_version": 1,
                    "source_sha256": block_map["source"]["sha256"],
                    "included_files": [file["source_path"] for file in block_map["files"]],
                    "excluded_files": [],
                },
            )
            packet = next_packet(config)
            assert packet is not None
            block = packet["blocks"][0]
            response = {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": [
                    {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": "Bản dịch",
                        "translation_xhtml": '<span onclick="steal()">Bản dịch</span>',
                    }
                ],
            }
            response_path = root / "response.json"
            atomic_write_json(response_path, response)
            cache_path = project / "cache/translations.json"

            with self.assertRaisesRegex(BookStudioError, "XHTML_UNSAFE"):
                apply_response(config, response_path)

            self.assertFalse(cache_path.exists())


if __name__ == "__main__":
    unittest.main()
