from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bookstudio.config import atomic_write_json, load_config
from bookstudio.epub.extract import extract_block_map
from bookstudio.errors import BookStudioError
from bookstudio.project import init_project
from bookstudio.translation.cache import load_cache
from bookstudio.translation.context import (
    MAX_PRODUCTION_BRIEF_BYTES,
    current_translation_context_sha256,
)
from bookstudio.translation.coverage import coverage_receipt
from bookstudio.translation.packets import apply_response, next_packet
from tests.fixtures import build_synthetic_epub


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


class PacketAndCacheTests(unittest.TestCase):
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
            max_blocks=2,
        )
        self.config = load_config(self.project / "bookstudio.toml")
        self.block_map = extract_block_map(self.source)
        atomic_write_json(
            self.project / "source-blocks/full-block-map.json", self.block_map
        )
        chapter_path = "OEBPS/text/chapter.xhtml"
        atomic_write_json(
            self.project / "source-blocks/coverage.json",
            {
                "schema_version": 1,
                "source_sha256": self.block_map["source"]["sha256"],
                "included_files": [
                    file["source_path"] for file in self.block_map["files"]
                ],
                "excluded_files": ["OEBPS/text/title.xhtml", "OEBPS/text/legal.xhtml"],
            },
        )
        (self.project / "glossary.md").write_text(
            """# Glossary

| Source term | Preferred rendering | Usage note |
| --- | --- | --- |
| primary action | hành động chính | UX term |
| unrelated term | thuật ngữ khác | Not in this chapter |
""",
            encoding="utf-8",
        )
        atomic_write_json(
            self.project / "reference-notes.json",
            {
                "notes": [
                    {
                        "source_path": chapter_path,
                        "provenance": "Vietnamese design reference, chapter 1",
                        "text": "Prefer familiar UX wording.",
                    },
                    {
                        "source_path": "OEBPS/text/legal.xhtml",
                        "provenance": "Unrelated legal reference",
                        "text": "Must not leak into the chapter packet.",
                    },
                ]
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def response_for(self, packet: dict, *, count: int | None = None) -> dict:
        blocks = packet["blocks"] if count is None else packet["blocks"][:count]
        return {
            "schema_version": 1,
            "packet_id": packet["packet_id"],
            "source_document": packet["source_document"],
            "translations": [
                {
                    "block_index": block["block_index"],
                    "source_sha256": block["source_sha256"],
                    "translation": f"Bản dịch {block['block_index']}",
                }
                for block in blocks
            ],
        }

    def write_response(self, payload: dict, name: str = "response.json") -> Path:
        path = self.root / name
        atomic_write_json(path, payload)
        return path

    def cache_row(self, source_path: str, block_index: int) -> dict:
        source_file = next(
            row for row in self.block_map["files"]
            if row["source_path"] == source_path
        )
        block = next(
            row for row in source_file["blocks"]
            if row["block_index"] == block_index
        )
        return {
            "block_index": block_index,
            "source_role": block["role"],
            "source_sha256": block["text_sha256"],
            "translation": f"Bản dịch {block_index}",
            "packet_id": "0" * 64,
            "context_sha256": current_translation_context_sha256(self.config),
        }

    def cache_payload(self, source_path: str, rows: list[dict]) -> dict:
        return {
            "schema_version": 1,
            "source_sha256": self.block_map["source"]["sha256"],
            "files": {source_path: rows},
        }

    def test_next_packet_never_crosses_source_document_or_max_blocks(self) -> None:
        packet = next_packet(self.config)

        self.assertIsNotNone(packet)
        assert packet is not None
        self.assertLessEqual(len(packet["blocks"]), self.config.max_blocks)
        self.assertEqual(1, len({block["source_path"] for block in packet["blocks"]}))
        self.assertEqual("OEBPS/text/chapter.xhtml", packet["source_document"])

    def test_next_never_crosses_active_pilot_scope(self) -> None:
        pilot_target = frozenset({("OEBPS/text/chapter.xhtml", 2)})

        packet = next_packet(
            self.config,
            allowed_targets=pilot_target,
            scope_identity="pilot_active:pilot-v1",
        )

        assert packet is not None
        self.assertEqual("OEBPS/text/chapter.xhtml", packet["source_document"])
        self.assertEqual([2], [block["block_index"] for block in packet["blocks"]])

    def test_next_rejects_invalid_cache_rows_without_mutation(self) -> None:
        source_path = "OEBPS/text/chapter.xhtml"
        valid = self.cache_payload(source_path, [self.cache_row(source_path, 1)])
        cases: list[tuple[str, str, dict]] = []

        bad_schema = copy.deepcopy(valid)
        bad_schema["schema_version"] = 2
        cases.append(("schema", "CACHE_SCHEMA_INVALID", bad_schema))
        boolean_schema = copy.deepcopy(valid)
        boolean_schema["schema_version"] = True
        cases.append(("boolean schema", "CACHE_SCHEMA_INVALID", boolean_schema))
        extra_top_level = copy.deepcopy(valid)
        extra_top_level["unexpected"] = True
        cases.append(("top-level key", "CACHE_SCHEMA_INVALID", extra_top_level))
        stale_source = copy.deepcopy(valid)
        stale_source["source_sha256"] = "0" * 64
        cases.append(("source binding", "CACHE_SOURCE_STALE", stale_source))
        empty_source_with_rows = copy.deepcopy(valid)
        empty_source_with_rows["source_sha256"] = ""
        cases.append(("empty source with rows", "CACHE_SOURCE_STALE", empty_source_with_rows))
        rows_not_list = copy.deepcopy(valid)
        rows_not_list["files"][source_path] = {}
        cases.append(("rows type", "CACHE_SCHEMA_INVALID", rows_not_list))
        missing_required = copy.deepcopy(valid)
        missing_required["files"][source_path][0].pop("source_role")
        cases.append(("missing required key", "CACHE_ROW_INVALID", missing_required))
        missing_identity = copy.deepcopy(valid)
        missing_identity["files"][source_path][0].pop("packet_id")
        missing_identity["files"][source_path][0].pop("context_sha256")
        cases.append(("missing context identity", "CACHE_ROW_INVALID", missing_identity))
        partial_identity = copy.deepcopy(valid)
        partial_identity["files"][source_path][0].pop("context_sha256")
        cases.append(("partial context identity", "CACHE_ROW_INVALID", partial_identity))
        null_identity = copy.deepcopy(valid)
        null_identity["files"][source_path][0]["packet_id"] = None
        null_identity["files"][source_path][0]["context_sha256"] = None
        cases.append(("null context identity", "CACHE_ROW_INVALID", null_identity))
        unknown_key = copy.deepcopy(valid)
        unknown_key["files"][source_path][0]["private_note"] = "not canonical"
        cases.append(("unknown row key", "CACHE_ROW_INVALID", unknown_key))
        boolean_index = copy.deepcopy(valid)
        boolean_index["files"][source_path][0]["block_index"] = True
        cases.append(("boolean index", "CACHE_ROW_INVALID", boolean_index))
        non_string_role = copy.deepcopy(valid)
        non_string_role["files"][source_path][0]["source_role"] = 1
        cases.append(("role type", "CACHE_ROW_INVALID", non_string_role))
        empty_translation = copy.deepcopy(valid)
        empty_translation["files"][source_path][0]["translation"] = "  "
        cases.append(("empty translation", "CACHE_ROW_INVALID", empty_translation))
        wrong_hash = copy.deepcopy(valid)
        wrong_hash["files"][source_path][0]["source_sha256"] = "f" * 64
        cases.append(("target hash", "CACHE_TARGET_STALE", wrong_hash))
        unknown_target = copy.deepcopy(valid)
        unknown_target["files"][source_path][0]["block_index"] = 999
        cases.append(("unknown target", "CACHE_TARGET_UNKNOWN", unknown_target))
        duplicate = copy.deepcopy(valid)
        duplicate["files"][source_path].append(
            copy.deepcopy(duplicate["files"][source_path][0])
        )
        cases.append(("duplicate", "CACHE_DUPLICATE", duplicate))
        empty_annotation = copy.deepcopy(valid)
        empty_annotation["files"][source_path][0]["image_annotations"] = [{}]
        cases.append(
            ("empty image annotation", "IMAGE_MANIFEST_SCHEMA_INVALID", empty_annotation)
        )
        private_companion = copy.deepcopy(valid)
        private_companion["files"][source_path][0]["image_companions"] = [
            {
                "source_path": "OEBPS/images/pixel.png",
                "companion": "assets/localized/pixel-vi.png",
                "private_path": "/private/source/pixel.png",
            }
        ]
        cases.append(
            ("private image companion field", "IMAGE_MANIFEST_SCHEMA_INVALID", private_companion)
        )

        companion = self.project / "assets/localized/pixel-vi.png"
        with zipfile.ZipFile(self.source) as archive:
            companion.write_bytes(archive.read("OEBPS/images/pixel.png"))

        cache_path = self.project / "cache/translations.json"
        for name, code, payload in cases:
            with self.subTest(name=name):
                atomic_write_json(cache_path, payload)
                before = cache_path.read_bytes()

                with self.assertRaisesRegex(BookStudioError, code):
                    next_packet(self.config)

                self.assertEqual(before, cache_path.read_bytes())

    def test_next_accepts_empty_unbound_cache_and_all_documented_optional_row_fields(
        self,
    ) -> None:
        cache_path = self.project / "cache/translations.json"
        atomic_write_json(
            cache_path,
            {"schema_version": 1, "source_sha256": "", "files": {}},
        )
        self.assertIsNotNone(next_packet(self.config))

        source_path = "OEBPS/text/chapter.xhtml"
        row = self.cache_row(source_path, 1)
        companion = self.project / "assets/localized/pixel-vi.png"
        with zipfile.ZipFile(self.source) as archive:
            companion.write_bytes(archive.read("OEBPS/images/pixel.png"))
        row.update(
            {
                "translation_xhtml": "<em>Bản dịch</em>",
                "explanation": "Giữ thuật ngữ UX.",
                "image_annotations": [
                    {
                        "source_path": "OEBPS/images/pixel.png",
                        "annotation": "Một pixel dùng làm ví dụ.",
                    }
                ],
                "image_companions": [
                    {
                        "source_path": "OEBPS/images/pixel.png",
                        "companion": "assets/localized/pixel-vi.png",
                    }
                ],
                "market_contexts": [{"text": "Ví dụ thị trường."}],
            }
        )
        atomic_write_json(cache_path, self.cache_payload(source_path, [row]))

        packet = next_packet(self.config)

        self.assertIsNotNone(packet)
        assert packet is not None
        self.assertNotIn(1, [block["block_index"] for block in packet["blocks"]])

    def test_next_rejects_globally_valid_cache_row_outside_active_scope(self) -> None:
        source_path = "OEBPS/text/chapter.xhtml"
        atomic_write_json(
            self.project / "cache/translations.json",
            self.cache_payload(source_path, [self.cache_row(source_path, 1)]),
        )
        before = (self.project / "cache/translations.json").read_bytes()

        with self.assertRaisesRegex(BookStudioError, "CACHE_SCOPE_INVALID"):
            next_packet(
                self.config,
                allowed_targets=frozenset({(source_path, 2)}),
                scope_identity="pilot_active:strict-scope",
            )

        self.assertEqual(before, (self.project / "cache/translations.json").read_bytes())

    def test_packet_id_is_stable_and_guided_packet_id_binds_scope(self) -> None:
        legacy = next_packet(self.config)
        assert legacy is not None
        repeated_legacy = next_packet(self.config)
        assert repeated_legacy is not None
        allowed = frozenset(
            (legacy["source_document"], block["block_index"])
            for block in legacy["blocks"]
        )

        first = next_packet(
            self.config,
            allowed_targets=allowed,
            scope_identity="pilot_active:scope-a",
        )
        second = next_packet(
            self.config,
            allowed_targets=allowed,
            scope_identity="full_active:scope-a",
        )

        self.assertEqual(legacy["packet_id"], repeated_legacy["packet_id"])
        self.assertEqual(64, len(legacy["packet_id"]))
        assert first is not None and second is not None
        self.assertNotEqual(legacy["packet_id"], first["packet_id"])
        self.assertNotEqual(first["packet_id"], second["packet_id"])

    def test_packet_id_binds_source_and_adjacent_context_changes(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        self.assertTrue(packet["context"])
        response_path = self.write_response(
            self.response_for(packet), "pre-context-change.json"
        )

        with zipfile.ZipFile(self.source) as archive:
            members = [
                (info, archive.read(info.filename)) for info in archive.infolist()
            ]
        with zipfile.ZipFile(self.source, "w") as archive:
            for info, payload in members:
                if info.filename == "OEBPS/text/chapter.xhtml":
                    payload = payload.replace(
                        b"Choose a clear label.",
                        b"Choose an unmistakable label.",
                    )
                archive.writestr(info, payload)

        changed_map = extract_block_map(self.source)
        atomic_write_json(
            self.project / "source-blocks/full-block-map.json", changed_map
        )
        coverage_path = self.project / "source-blocks/coverage.json"
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["source_sha256"] = changed_map["source"]["sha256"]
        atomic_write_json(coverage_path, coverage)

        current = next_packet(self.config)
        assert current is not None
        self.assertEqual(
            [block["source_sha256"] for block in packet["blocks"]],
            [block["source_sha256"] for block in current["blocks"]],
        )
        self.assertNotEqual(packet["context"], current["context"])
        self.assertNotEqual(packet["packet_id"], current["packet_id"])

        with self.assertRaisesRegex(BookStudioError, "RESPONSE_PACKET_STALE"):
            apply_response(self.config, response_path)
        self.assertFalse((self.project / "cache/translations.json").exists())

    def test_packet_id_binds_the_source_name_exposed_to_the_model(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        response_path = self.write_response(
            self.response_for(packet), "pre-source-rename.json"
        )
        renamed_source = self.root / "renamed-source.epub"
        renamed_source.write_bytes(self.source.read_bytes())
        config_path = self.project / "bookstudio.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                str(self.source), str(renamed_source)
            ),
            encoding="utf-8",
        )
        renamed_map = extract_block_map(renamed_source)
        self.assertEqual(
            self.block_map["source"]["sha256"], renamed_map["source"]["sha256"]
        )
        atomic_write_json(
            self.project / "source-blocks/full-block-map.json", renamed_map
        )

        fresh_config = load_config(config_path)
        current = next_packet(fresh_config)
        assert current is not None
        self.assertNotEqual(
            packet["project"]["source_name"],
            current["project"]["source_name"],
        )
        self.assertNotEqual(packet["packet_id"], current["packet_id"])

        with self.assertRaisesRegex(BookStudioError, "RESPONSE_PACKET_STALE"):
            apply_response(fresh_config, response_path)
        self.assertFalse((self.project / "cache/translations.json").exists())

    def test_stale_loaded_config_cannot_emit_or_apply_a_mixed_snapshot(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        response_path = self.write_response(
            self.response_for(packet), "pre-config-change.json"
        )
        config_path = self.project / "bookstudio.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'target_language = "vi"', 'target_language = "fr"'
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(BookStudioError, "CONFIG_STALE"):
            next_packet(self.config)
        with self.assertRaisesRegex(BookStudioError, "CONFIG_STALE"):
            apply_response(self.config, response_path)
        self.assertFalse((self.project / "cache/translations.json").exists())

        fresh_config = load_config(config_path)
        current = next_packet(fresh_config)
        assert current is not None
        self.assertEqual("fr", current["project"]["target_language"])
        self.assertNotEqual(packet["packet_id"], current["packet_id"])

    def test_cache_rows_cannot_downgrade_by_removing_context_identity(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        apply_response(
            self.config,
            self.write_response(self.response_for(packet, count=1), "current.json"),
        )
        cache_path = self.project / "cache/translations.json"
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        row = next(iter(payload["files"].values()))[0]
        row.pop("packet_id")
        row.pop("context_sha256")
        atomic_write_json(cache_path, payload)
        before = cache_path.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "CACHE_ROW_INVALID"):
            next_packet(self.config)

        self.assertEqual(before, cache_path.read_bytes())

    def test_packet_contains_bounded_context_glossary_reference_and_schema(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None

        self.assertEqual(dict(self.config.profile), packet["book_profile"])
        self.assertNotIn("production_brief", packet)
        self.assertIn("response_schema", packet)
        self.assertTrue(all("source_sha256" in block for block in packet["blocks"]))
        self.assertTrue(all(context["translate"] is False for context in packet["context"]))
        self.assertEqual(["primary action"], [row["source_term"] for row in packet["glossary"]])
        self.assertEqual(1, len(packet["reference_notes"]))
        self.assertEqual(packet["source_document"], packet["reference_notes"][0]["source_path"])
        self.assertNotIn(str(self.root), json.dumps(packet))

    def test_packet_emits_and_binds_the_private_production_brief(self) -> None:
        original = next_packet(self.config)
        assert original is not None
        old_response = self.write_response(
            self.response_for(original), "pre-production-brief.json"
        )
        brief = """# Production brief

- Voice: calm, precise, and natural for experienced practitioners
- Target-language rhythm: prefer direct verbs and connected paragraphs
"""
        (self.project / "production-brief.md").write_text(brief, encoding="utf-8")

        current = next_packet(self.config)
        assert current is not None
        self.assertEqual(brief, current["production_brief"])
        self.assertNotEqual(original["packet_id"], current["packet_id"])
        self.assertNotIn(str(self.root), json.dumps(current))

        with self.assertRaisesRegex(BookStudioError, "RESPONSE_PACKET_STALE"):
            apply_response(self.config, old_response)
        self.assertFalse((self.project / "cache/translations.json").exists())

    def test_production_brief_must_be_nonempty_bounded_utf8(self) -> None:
        path = self.project / "production-brief.md"
        cases = (
            ("empty", b" \n", "PRODUCTION_BRIEF_INVALID"),
            ("non-utf8", b"\xff\xfe", "PRODUCTION_BRIEF_INVALID"),
            (
                "oversized",
                b"x" * (MAX_PRODUCTION_BRIEF_BYTES + 1),
                "PRODUCTION_BRIEF_TOO_LARGE",
            ),
        )

        for name, payload, code in cases:
            with self.subTest(name=name):
                path.write_bytes(payload)
                with self.assertRaisesRegex(BookStudioError, code):
                    next_packet(self.config)
        self.assertFalse((self.project / "cache/translations.json").exists())

    def test_packet_declares_the_exact_response_and_translation_key_sets(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None

        self.assertEqual(
            ["schema_version", "packet_id", "source_document", "translations"],
            packet["response_schema"]["required"],
        )
        self.assertEqual(
            ["schema_version", "packet_id", "source_document", "translations"],
            packet["response_schema"]["allowed"],
        )
        self.assertEqual(
            ["block_index", "source_sha256", "translation"],
            packet["response_schema"]["translation_required"],
        )
        self.assertEqual(
            [
                "translation_xhtml",
                "explanation",
                "image_annotations",
                "image_companions",
                "market_contexts",
            ],
            packet["response_schema"]["translation_optional"],
        )

    def test_apply_exact_shape_failures_precede_target_and_cache_work(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        valid = self.response_for(packet, count=1)

        cases: list[tuple[str, object]] = []
        for value in (True, 1.0):
            payload = copy.deepcopy(valid)
            payload["schema_version"] = value
            cases.append((f"schema type {type(value).__name__}", payload))
        for key in ("schema_version", "packet_id", "source_document", "translations"):
            payload = copy.deepcopy(valid)
            payload.pop(key)
            cases.append((f"missing top-level {key}", payload))
        payload = copy.deepcopy(valid)
        payload["unexpected"] = True
        cases.append(("unknown top-level key", payload))
        for key in ("block_index", "source_sha256", "translation"):
            payload = copy.deepcopy(valid)
            payload["translations"][0].pop(key)
            cases.append((f"missing row {key}", payload))
        payload = copy.deepcopy(valid)
        payload["translations"][0]["unexpected"] = True
        cases.append(("unknown row key", payload))
        for value in (True, 1.0):
            payload = copy.deepcopy(valid)
            payload["translations"][0]["block_index"] = value
            cases.append((f"block index type {type(value).__name__}", payload))
        wrong_types = (
            ("packet_id", True),
            ("source_document", True),
            ("translations", {}),
        )
        for key, value in wrong_types:
            payload = copy.deepcopy(valid)
            payload[key] = value
            cases.append((f"top-level type {key}", payload))
        for key, value in (("source_sha256", True), ("translation", True)):
            payload = copy.deepcopy(valid)
            payload["translations"][0][key] = value
            cases.append((f"row type {key}", payload))
        cases.append(("response must be object", []))
        payload = copy.deepcopy(valid)
        payload["translations"][0] = []
        cases.append(("row must be object", payload))

        for index, (name, payload) in enumerate(cases):
            with self.subTest(name=name):
                response_path = self.write_response(payload, f"shape-{index}.json")
                with (
                    patch(
                        "bookstudio.translation.packets.target_index",
                        side_effect=AssertionError("target work reached"),
                    ),
                    patch(
                        "bookstudio.translation.packets.load_cache",
                        side_effect=AssertionError("cache read reached"),
                    ),
                    patch(
                        "bookstudio.translation.packets.validate_cache_payload",
                        side_effect=AssertionError("cache validation reached"),
                    ),
                    patch(
                        "bookstudio.translation.packets.save_cache",
                        side_effect=AssertionError("cache write reached"),
                    ),
                ):
                    with self.assertRaises(BookStudioError) as caught:
                        apply_response(self.config, response_path)
                self.assertEqual("RESPONSE_SCHEMA_MISMATCH", caught.exception.code)

    def test_apply_exact_shape_failures_never_mutate_an_existing_cache(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        valid = self.response_for(packet, count=1)
        cases: list[tuple[str, dict]] = []

        for value in (True, 1.0):
            payload = copy.deepcopy(valid)
            payload["schema_version"] = value
            cases.append((f"schema type {type(value).__name__}", payload))
        for value in (True, 1.0):
            payload = copy.deepcopy(valid)
            payload["translations"][0]["block_index"] = value
            cases.append((f"block index type {type(value).__name__}", payload))
        payload = copy.deepcopy(valid)
        payload["unexpected"] = True
        cases.append(("unknown top-level key", payload))
        payload = copy.deepcopy(valid)
        payload["translations"][0]["unexpected"] = True
        cases.append(("unknown row key", payload))

        cache_path = self.project / "cache/translations.json"
        empty_cache = {"schema_version": 1, "source_sha256": "", "files": {}}
        for index, (name, payload) in enumerate(cases):
            with self.subTest(name=name):
                atomic_write_json(cache_path, empty_cache)
                before = cache_path.read_bytes()

                with self.assertRaises(BookStudioError) as caught:
                    apply_response(
                        self.config,
                        self.write_response(payload, f"no-mutation-{index}.json"),
                    )

                self.assertEqual("RESPONSE_SCHEMA_MISMATCH", caught.exception.code)
                self.assertEqual(before, cache_path.read_bytes())

    def test_apply_preserves_every_supported_optional_translation_field(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        response = self.response_for(packet, count=1)
        companion = self.project / "assets/localized/pixel-vi.png"
        with zipfile.ZipFile(self.source) as archive:
            companion.write_bytes(archive.read("OEBPS/images/pixel.png"))
        optional = {
            "translation_xhtml": "<em>Bản dịch</em>",
            "explanation": "Giữ thuật ngữ UX.",
            "image_annotations": [
                {
                    "source_path": "OEBPS/images/pixel.png",
                    "annotation": "Một pixel dùng làm ví dụ.",
                }
            ],
            "image_companions": [
                {
                    "source_path": "OEBPS/images/pixel.png",
                    "companion": "assets/localized/pixel-vi.png",
                }
            ],
            "market_contexts": [{"text": "Ví dụ thị trường."}],
        }
        response["translations"][0].update(optional)

        apply_response(self.config, self.write_response(response, "optional.json"))

        cache = load_cache(self.config)
        row = next(iter(cache["files"].values()))[0]
        self.assertEqual(optional, {key: row[key] for key in optional})

    def test_apply_rejects_unsafe_response_shapes_without_cache_mutation(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        valid = self.response_for(packet)
        cases: list[tuple[str, dict]] = []

        wrong_schema = {**valid, "schema_version": 2}
        cases.append(("RESPONSE_SCHEMA_MISMATCH", wrong_schema))
        unknown = json.loads(json.dumps(valid))
        unknown["translations"][0]["block_index"] = 999
        cases.append(("RESPONSE_BLOCK_UNKNOWN", unknown))
        duplicate = json.loads(json.dumps(valid))
        duplicate["translations"].append(dict(duplicate["translations"][0]))
        cases.append(("RESPONSE_BLOCK_DUPLICATE", duplicate))
        empty = json.loads(json.dumps(valid))
        empty["translations"][0]["translation"] = "  "
        cases.append(("RESPONSE_TRANSLATION_EMPTY", empty))
        stale = json.loads(json.dumps(valid))
        stale["translations"][0]["source_sha256"] = "0" * 64
        cases.append(("RESPONSE_SOURCE_STALE", stale))
        empty_annotation = json.loads(json.dumps(valid))
        empty_annotation["translations"][0]["image_annotations"] = [{}]
        cases.append(("IMAGE_MANIFEST_SCHEMA_INVALID", empty_annotation))
        private_companion = json.loads(json.dumps(valid))
        private_companion["translations"][0]["image_companions"] = [
            {
                "source_path": "OEBPS/images/pixel.png",
                "companion": "assets/localized/pixel-vi.png",
                "private_path": "/private/source/pixel.png",
            }
        ]
        cases.append(("IMAGE_MANIFEST_SCHEMA_INVALID", private_companion))

        companion = self.project / "assets/localized/pixel-vi.png"
        with zipfile.ZipFile(self.source) as archive:
            companion.write_bytes(archive.read("OEBPS/images/pixel.png"))

        cache_path = self.project / "cache/translations.json"
        for index, (code, payload) in enumerate(cases):
            with self.subTest(code=code):
                with self.assertRaises(BookStudioError) as caught:
                    apply_response(self.config, self.write_response(payload, f"bad-{index}.json"))
                self.assertEqual(code, caught.exception.code)
                self.assertFalse(cache_path.exists())

    def test_valid_apply_merges_and_collision_fails_closed(self) -> None:
        first_packet = next_packet(self.config)
        assert first_packet is not None
        first_response = self.response_for(first_packet, count=1)
        apply_response(self.config, self.write_response(first_response, "first.json"))

        second_packet = next_packet(self.config)
        assert second_packet is not None
        second_response = self.response_for(second_packet, count=1)
        apply_response(self.config, self.write_response(second_response, "second.json"))

        cache = load_cache(self.config)
        self.assertEqual(2, sum(len(rows) for rows in cache["files"].values()))
        cache_path = self.project / "cache/translations.json"
        before = hashlib.sha256(cache_path.read_bytes()).hexdigest()
        collision = json.loads(json.dumps(first_response))
        collision["translations"][0]["translation"] = "Bản dịch bị thay thế"
        with self.assertRaisesRegex(BookStudioError, "CACHE_COLLISION"):
            apply_response(self.config, self.write_response(collision, "collision.json"))
        self.assertEqual(before, hashlib.sha256(cache_path.read_bytes()).hexdigest())

    def test_legacy_unscoped_response_replay_remains_idempotent(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        response_path = self.write_response(self.response_for(packet), "legacy-replay.json")
        apply_response(self.config, response_path)
        cache_path = self.project / "cache/translations.json"
        before = cache_path.read_bytes()

        replay = apply_response(self.config, response_path)

        self.assertEqual(0, replay["applied"])
        self.assertEqual(before, cache_path.read_bytes())

    def test_apply_rechecks_the_identical_target_scope_and_identity(self) -> None:
        allowed = frozenset({("OEBPS/text/chapter.xhtml", 1)})
        packet = next_packet(
            self.config,
            allowed_targets=allowed,
            scope_identity="pilot_active:scope-a",
        )
        assert packet is not None
        response_path = self.write_response(self.response_for(packet), "scoped.json")

        with self.assertRaisesRegex(BookStudioError, "RESPONSE_PACKET_STALE"):
            apply_response(
                self.config,
                response_path,
                allowed_targets=allowed,
                scope_identity="full_active:scope-a",
            )

        applied = apply_response(
            self.config,
            response_path,
            allowed_targets=allowed,
            scope_identity="pilot_active:scope-a",
        )
        self.assertEqual(1, applied["applied"])

    def test_apply_rejects_a_block_outside_the_allowed_scope(self) -> None:
        packet = next_packet(self.config)
        assert packet is not None
        allowed = frozenset(
            {(packet["source_document"], packet["blocks"][0]["block_index"])}
        )
        response = self.response_for(packet)

        with self.assertRaisesRegex(BookStudioError, "RESPONSE_BLOCK_UNKNOWN"):
            apply_response(
                self.config,
                self.write_response(response, "outside-scope.json"),
                allowed_targets=allowed,
                scope_identity="pilot_active:scope-a",
            )

    def test_coverage_and_no_work_exit_contract(self) -> None:
        incomplete = run_cli("status", str(self.project), "--json")
        self.assertEqual(2, incomplete.returncode)
        self.assertEqual("PROJECT_INCOMPLETE", json.loads(incomplete.stdout)["code"])

        while True:
            packet = next_packet(self.config)
            if packet is None:
                break
            apply_response(self.config, self.write_response(self.response_for(packet)))

        receipt = coverage_receipt(self.config, require_complete=True)
        result = run_cli("next", str(self.project), "--json")

        self.assertTrue(receipt["passed"])
        self.assertEqual(0, receipt["remaining"])
        self.assertGreater(receipt["excluded"], 0)
        self.assertEqual(3, result.returncode)
        self.assertEqual("NO_WORK_REMAINS", json.loads(result.stdout)["code"])

        complete = run_cli("status", str(self.project), "--json")
        self.assertEqual(0, complete.returncode)
        self.assertTrue(json.loads(complete.stdout)["passed"])

    def test_coverage_fails_closed_on_invalid_cache_before_reporting_counts(self) -> None:
        block_map = json.loads(
            (self.project / "source-blocks/full-block-map.json").read_text(encoding="utf-8")
        )
        chapter = next(
            file
            for file in block_map["files"]
            if file["source_path"] == "OEBPS/text/chapter.xhtml"
        )
        targets = [
            block
            for block in chapter["blocks"]
            if block["canonical"] and not block["watermark"]
        ]
        good = {
            "block_index": targets[0]["block_index"],
            "source_role": targets[0]["role"],
            "source_sha256": targets[0]["text_sha256"],
            "translation": "Hợp lệ",
            "packet_id": "0" * 64,
            "context_sha256": current_translation_context_sha256(self.config),
        }
        atomic_write_json(
            self.project / "cache/translations.json",
            {
                "schema_version": 1,
                "source_sha256": block_map["source"]["sha256"],
                "files": {
                    chapter["source_path"]: [
                        good,
                        dict(good),
                        {
                            "block_index": targets[1]["block_index"],
                            "source_role": targets[1]["role"],
                            "source_sha256": targets[1]["text_sha256"],
                            "translation": " ",
                        },
                        {
                            "block_index": targets[2]["block_index"],
                            "source_role": targets[2]["role"],
                            "source_sha256": "0" * 64,
                            "translation": "Cũ",
                        },
                        {
                            "block_index": 999,
                            "source_role": "paragraph",
                            "source_sha256": "1" * 64,
                            "translation": "Thừa",
                        },
                    ]
                },
            },
        )

        cache_path = self.project / "cache/translations.json"
        before = cache_path.read_bytes()
        with self.assertRaisesRegex(BookStudioError, "CACHE_DUPLICATE"):
            coverage_receipt(self.config, require_complete=True)
        status = run_cli("status", str(self.project), "--json")

        self.assertEqual(1, status.returncode)
        self.assertEqual("CACHE_DUPLICATE", json.loads(status.stdout)["code"])
        self.assertEqual(before, cache_path.read_bytes())

    def test_coverage_next_and_status_require_the_exact_full_prepared_map(self) -> None:
        prepared_path = self.project / "source-blocks/full-block-map.json"

        def legal_file(payload: dict) -> dict:
            return next(
                row
                for row in payload["files"]
                if row["source_path"] == "OEBPS/text/legal.xhtml"
            )

        mutations = {
            "deleted document": lambda payload: payload["files"].pop(),
            "reordered documents": lambda payload: payload["files"].reverse(),
            "deleted block": lambda payload: legal_file(payload)["blocks"].pop(),
            "reordered blocks": lambda payload: legal_file(payload)["blocks"].reverse(),
            "changed block index": lambda payload: legal_file(payload)["blocks"][0].update(
                block_index=999
            ),
            "changed block hash": lambda payload: legal_file(payload)["blocks"][0].update(
                text_sha256="0" * 64
            ),
            "changed role": lambda payload: legal_file(payload)["blocks"][0].update(
                role="tampered-role"
            ),
            "changed source text": lambda payload: legal_file(payload)["blocks"][0].update(
                text="Changed prepared source text"
            ),
            "changed source metadata": lambda payload: payload["source"].update(
                name="different.epub"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                atomic_write_json(prepared_path, self.block_map)
                prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
                mutate(prepared)
                atomic_write_json(prepared_path, prepared)
                before = prepared_path.read_bytes()

                for operation in (
                    lambda: coverage_receipt(self.config, require_complete=True),
                    lambda: next_packet(self.config),
                ):
                    with self.assertRaises(BookStudioError) as raised:
                        operation()
                    self.assertEqual("BLOCK_MAP_STALE", raised.exception.code)
                    self.assertEqual(before, prepared_path.read_bytes())

                status = run_cli("status", str(self.project), "--json")
                self.assertEqual(1, status.returncode)
                self.assertEqual("BLOCK_MAP_STALE", json.loads(status.stdout)["code"])
                self.assertEqual(before, prepared_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
