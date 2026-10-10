from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from bookstudio.config import atomic_write_json, load_config
from bookstudio.epub.extract import extract_block_map
from bookstudio.epub.inspect import inspect_epub
from bookstudio.errors import BookStudioError
from bookstudio.intake import assess_intake, profile_from_answers
from bookstudio.pilot import (
    accept_pilot,
    approve_pilot,
    load_pilot,
    pilot_receipt,
    require_full_scope,
    require_translation_scope,
    select_pilot,
)
from bookstudio.project import full_coverage, init_project, locked_intake
from bookstudio.translation.context import current_translation_context_sha256
from tests.fixtures import build_pilot_tie_epub, build_synthetic_epub


class PilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "synthetic.epub"
        self.project = self.root / "project"
        build_synthetic_epub(self.source)
        self.answers = {
            "target_language": "vi",
            "output_mode": "vi_only",
            "audience": "designers",
            "translation_approach": "faithful",
            "image_text_policy": "selective",
            "image_annotation_policy": "selective",
            "market_context_policy": "labeled_selective",
            "layout_policy": "preserve",
        }
        assessment = assess_intake(self.source, self.answers)
        self.answers = assessment["answers"]
        init_project(
            self.project,
            slug="synthetic",
            source=self.source,
            target_language="vi",
            output_mode="vi_only",
            profile=profile_from_answers(self.answers),
        )
        self.config = load_config(self.project / "bookstudio.toml")
        self.inspection = inspect_epub(self.source)
        self.block_map = extract_block_map(self.source)
        atomic_write_json(self.config.paths.inspection, self.inspection)
        atomic_write_json(
            self.config.paths.source_blocks / "full-block-map.json", self.block_map
        )
        atomic_write_json(
            self.config.paths.source_blocks / "coverage.json",
            full_coverage(self.block_map),
        )
        atomic_write_json(self.config.paths.intake, locked_intake(assessment))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_proposal(self) -> dict:
        proposal = select_pilot(self.inspection, self.block_map, self.answers)
        atomic_write_json(self.config.paths.pilot, proposal)
        return proposal

    def target_row(
        self, proposal: dict, target: dict, translation: str = "Bản dịch"
    ) -> dict:
        source_file = next(
            row for row in self.block_map["files"]
            if row["source_path"] == proposal["source_document"]
        )
        source_block = next(
            row for row in source_file["blocks"]
            if row["block_index"] == target["block_index"]
        )
        return {
            "block_index": target["block_index"],
            "source_role": source_block["role"],
            "source_sha256": target["source_sha256"],
            "translation": translation,
            "packet_id": "0" * 64,
            "context_sha256": current_translation_context_sha256(self.config),
        }

    def complete_active_pilot(self) -> dict:
        proposal = self.write_proposal()
        approve_pilot(self.config)
        atomic_write_json(
            self.config.paths.cache / "translations.json",
            {
                "schema_version": 1,
                "source_sha256": proposal["source_sha256"],
                "files": {
                    proposal["source_document"]: [
                        self.target_row(proposal, target)
                        for target in proposal["targets"]
                    ]
                },
            },
        )
        return proposal

    # BSC-PILOT-006
    def test_selector_chooses_chapter_not_title_or_legal(self) -> None:
        proposal = select_pilot(self.inspection, self.block_map, self.answers)

        self.assertEqual("OEBPS/text/chapter.xhtml", proposal["source_document"])
        self.assertIn("front_matter_excluded", proposal["reason_codes"])
        self.assertIn("representative_block_count", proposal["reason_codes"])
        self.assertTrue(proposal["targets"])
        self.assertEqual(
            self.block_map["source"]["sha256"], proposal["source_sha256"]
        )
        self.assertIn("selection_facts", proposal)
        self.assertEqual(
            {
                "selected_title": "Chapter One",
                "selected_spine_index": 1,
                "selected_block_count": 4,
                "selected_image_count": 1,
                "nonempty_candidate_count": 3,
                "non_excluded_candidate_count": 1,
                "non_trivial_candidate_count": 1,
                "ranked_candidate_count": 1,
                "median_block_count": 4,
                "all_nonempty_excluded": False,
            },
            proposal["selection_facts"],
        )

    def test_selector_prefers_image_document_before_spine_tie_break(self) -> None:
        source_hash = "a" * 64
        inspection = {
            "source": {"sha256": source_hash},
            "text": {
                "files": [
                    {"source_path": "OEBPS/text/first.xhtml", "images": 0},
                    {"source_path": "OEBPS/text/second.xhtml", "images": 1},
                ]
            },
        }
        block = lambda index: {
            "block_index": index,
            "canonical": True,
            "watermark": False,
            "text_sha256": f"{index:064x}",
        }
        block_map = {
            "schema_version": 1,
            "source": {"sha256": source_hash},
            "files": [
                {
                    "source_path": "OEBPS/text/first.xhtml",
                    "spine_index": 0,
                    "blocks": [block(0), block(1)],
                },
                {
                    "source_path": "OEBPS/text/second.xhtml",
                    "spine_index": 1,
                    "blocks": [block(2), block(3)],
                },
            ],
        }

        proposal = select_pilot(inspection, block_map, {"image_text_policy": "selective"})

        self.assertEqual("OEBPS/text/second.xhtml", proposal["source_document"])
        self.assertIn("image_document_preferred", proposal["reason_codes"])

    def test_selector_falls_back_to_first_nonempty_spine_when_all_are_excluded(self) -> None:
        source_hash = "b" * 64
        block_map = {
            "schema_version": 1,
            "source": {"sha256": source_hash},
            "files": [
                {
                    "source_path": "OEBPS/text/title.xhtml",
                    "spine_index": 0,
                    "blocks": [
                        {
                            "block_index": 0,
                            "canonical": True,
                            "watermark": False,
                            "text_sha256": "c" * 64,
                        }
                    ],
                },
                {
                    "source_path": "OEBPS/text/legal.xhtml",
                    "spine_index": 1,
                    "blocks": [
                        {
                            "block_index": 0,
                            "canonical": True,
                            "watermark": False,
                            "text_sha256": "d" * 64,
                        },
                        {
                            "block_index": 1,
                            "canonical": True,
                            "watermark": False,
                            "text_sha256": "e" * 64,
                        },
                        {
                            "block_index": 2,
                            "canonical": True,
                            "watermark": False,
                            "text_sha256": "f" * 64,
                        },
                    ],
                },
            ],
        }
        inspection = {
            "source": {"sha256": source_hash},
            "text": {"files": []},
        }

        proposal = select_pilot(inspection, block_map, {})

        self.assertEqual("OEBPS/text/title.xhtml", proposal["source_document"])
        self.assertIn("front_matter_fallback", proposal["reason_codes"])
        self.assertIn("first_nonempty_spine", proposal["reason_codes"])
        self.assertEqual(1, proposal["eligible_blocks"])
        self.assertTrue(proposal["selection_facts"]["all_nonempty_excluded"])
        self.assertIsNone(proposal["selection_facts"]["median_block_count"])

    def test_selector_excludes_normalized_path_and_inspected_title(self) -> None:
        source_hash = "1" * 64
        inspection = {
            "source": {"sha256": source_hash},
            "text": {
                "files": [
                    {
                        "source_path": "OEBPS/text/chapter-a.xhtml",
                        "title": "Navigation",
                        "images": 0,
                    },
                    {
                        "source_path": "OEBPS/text/parts/../INDEX.XHTML",
                        "title": "Reference entries",
                        "images": 0,
                    },
                    {
                        "source_path": "OEBPS/text/chapter-b.xhtml",
                        "title": "Working chapter",
                        "images": 0,
                    },
                ]
            },
        }
        make_block = lambda index: {
            "block_index": index,
            "canonical": True,
            "watermark": False,
            "text_sha256": f"{index + 1:064x}",
        }
        block_map = {
            "schema_version": 1,
            "source": {"sha256": source_hash},
            "files": [
                {
                    "source_path": "OEBPS/text/chapter-a.xhtml",
                    "spine_index": 0,
                    "blocks": [make_block(0), make_block(1)],
                },
                {
                    "source_path": "OEBPS/text/parts/../INDEX.XHTML",
                    "spine_index": 1,
                    "blocks": [make_block(2), make_block(3)],
                },
                {
                    "source_path": "OEBPS/text/chapter-b.xhtml",
                    "spine_index": 2,
                    "blocks": [make_block(4), make_block(5)],
                },
            ],
        }

        proposal = select_pilot(inspection, block_map, {})

        self.assertEqual("OEBPS/text/chapter-b.xhtml", proposal["source_document"])
        self.assertEqual("Working chapter", proposal["selection_facts"]["selected_title"])
        self.assertEqual(1, proposal["selection_facts"]["non_excluded_candidate_count"])

    def test_selector_does_not_exclude_words_that_only_contain_reserved_substrings(self) -> None:
        source_hash = "4" * 64
        safe_documents = [
            ("stock.xhtml", "Stock choices"),
            ("discover.xhtml", "Discover patterns"),
            ("illegal.xhtml", "Illegal constraints"),
            ("entitlement.xhtml", "Entitlement rules"),
        ]
        excluded_documents = [
            ("titlepage.xhtml", "Opening leaf"),
            ("cover-page.xhtml", "Cover Page"),
            ("front-matter.xhtml", "Preface"),
            ("table-of-contents.xhtml", "Contents"),
            ("copyright-page.xhtml", "Rights"),
            ("acknowledgements.xhtml", "Thanks"),
            ("nav.xhtml", "Navigation"),
            ("index.xhtml", "Reference entries"),
            ("appendix.xhtml", "Legal notice"),
        ]
        documents = safe_documents + excluded_documents
        inspection_files = []
        block_files = []
        for spine_index, (filename, title) in enumerate(documents):
            source_path = f"OEBPS/text/{filename}"
            inspection_files.append(
                {"source_path": source_path, "title": title, "images": 0}
            )
            block_files.append(
                {
                    "source_path": source_path,
                    "spine_index": spine_index,
                    "blocks": [
                        {
                            "block_index": spine_index * 2 + offset,
                            "canonical": True,
                            "watermark": False,
                            "text_sha256": f"{spine_index * 2 + offset + 1:064x}",
                        }
                        for offset in range(2)
                    ],
                }
            )
        inspection = {
            "source": {"sha256": source_hash},
            "text": {"files": inspection_files},
        }
        block_map = {
            "schema_version": 1,
            "source": {"sha256": source_hash},
            "files": block_files,
        }

        proposal = select_pilot(inspection, block_map, {})

        self.assertEqual("OEBPS/text/stock.xhtml", proposal["source_document"])
        self.assertEqual(4, proposal["selection_facts"]["non_excluded_candidate_count"])
        self.assertFalse(proposal["selection_facts"]["all_nonempty_excluded"])
        self.assertIn("front_matter_excluded", proposal["reason_codes"])

    def test_selector_ranks_only_non_trivial_candidates_when_available(self) -> None:
        source_hash = "2" * 64
        make_block = lambda index: {
            "block_index": index,
            "canonical": True,
            "watermark": False,
            "text_sha256": f"{index + 1:064x}",
        }
        counts = [1, 1, 2, 8]
        files = []
        next_index = 0
        for spine_index, count in enumerate(counts):
            blocks = [make_block(index) for index in range(next_index, next_index + count)]
            next_index += count
            files.append(
                {
                    "source_path": f"OEBPS/text/chapter-{spine_index}.xhtml",
                    "spine_index": spine_index,
                    "blocks": blocks,
                }
            )
        inspection = {
            "source": {"sha256": source_hash},
            "text": {
                "files": [
                    {
                        "source_path": row["source_path"],
                        "title": f"Chapter {index}",
                        "images": 0,
                    }
                    for index, row in enumerate(files)
                ]
            },
        }
        block_map = {
            "schema_version": 1,
            "source": {"sha256": source_hash},
            "files": files,
        }

        proposal = select_pilot(inspection, block_map, {})

        self.assertEqual("OEBPS/text/chapter-2.xhtml", proposal["source_document"])
        self.assertIn("non_trivial_document_preferred", proposal["reason_codes"])
        self.assertEqual(2, proposal["selection_facts"]["non_trivial_candidate_count"])
        self.assertEqual(2, proposal["selection_facts"]["ranked_candidate_count"])
        self.assertEqual(5, proposal["selection_facts"]["median_block_count"])

    def test_selector_uses_image_preference_only_when_an_image_policy_enables_it(self) -> None:
        source_hash = "3" * 64
        inspection = {
            "source": {"sha256": source_hash},
            "text": {
                "files": [
                    {"source_path": "OEBPS/text/first.xhtml", "title": "First", "images": 0},
                    {"source_path": "OEBPS/text/second.xhtml", "title": "Second", "images": 1},
                ]
            },
        }
        make_block = lambda index: {
            "block_index": index,
            "canonical": True,
            "watermark": False,
            "text_sha256": f"{index + 1:064x}",
        }
        block_map = {
            "schema_version": 1,
            "source": {"sha256": source_hash},
            "files": [
                {
                    "source_path": "OEBPS/text/first.xhtml",
                    "spine_index": 0,
                    "blocks": [make_block(0), make_block(1)],
                },
                {
                    "source_path": "OEBPS/text/second.xhtml",
                    "spine_index": 1,
                    "blocks": [make_block(2), make_block(3)],
                },
            ],
        }

        disabled = select_pilot(
            inspection,
            block_map,
            {"image_text_policy": "none", "image_annotation_policy": "none"},
        )
        annotation_enabled = select_pilot(
            inspection,
            block_map,
            {"image_text_policy": "none", "image_annotation_policy": "selective"},
        )
        text_all = select_pilot(
            inspection,
            block_map,
            {"image_text_policy": "all", "image_annotation_policy": "none"},
        )
        annotation_all = select_pilot(
            inspection,
            block_map,
            {"image_text_policy": "none", "image_annotation_policy": "all"},
        )

        self.assertEqual("OEBPS/text/first.xhtml", disabled["source_document"])
        self.assertNotIn("image_document_preferred", disabled["reason_codes"])
        self.assertEqual("OEBPS/text/second.xhtml", annotation_enabled["source_document"])
        self.assertIn("image_document_preferred", annotation_enabled["reason_codes"])
        self.assertEqual("OEBPS/text/second.xhtml", text_all["source_document"])
        self.assertEqual("OEBPS/text/second.xhtml", annotation_all["source_document"])

    def test_legacy_project_without_pilot_state_keeps_full_scope(self) -> None:
        self.config.paths.intake.unlink()
        self.assertFalse(self.config.paths.guided_marker.exists())
        self.assertIsNone(load_pilot(self.config))
        self.assertIsNone(require_translation_scope(self.config))
        self.assertIsNone(require_full_scope(self.config))
        self.assertEqual("legacy", pilot_receipt(self.config)["status"])

    def test_locked_intake_without_pilot_state_fails_closed(self) -> None:
        before = self.config.paths.intake.read_bytes()

        for operation in (
            lambda: load_pilot(self.config),
            lambda: pilot_receipt(self.config),
            lambda: require_translation_scope(self.config),
            lambda: require_full_scope(self.config),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(BookStudioError) as raised:
                    operation()
                self.assertEqual("PILOT_STATE_MISSING", raised.exception.code)
                self.assertIn("state/pilot.json", raised.exception.next_action)
                self.assertEqual(before, self.config.paths.intake.read_bytes())
                self.assertFalse(self.config.paths.pilot.exists())

    def test_guided_marker_without_pilot_state_fails_closed(self) -> None:
        self.config.paths.intake.unlink()
        self.config.paths.guided_marker.write_text(
            "bookstudio-guided-v1\n", encoding="utf-8"
        )
        before = self.config.paths.guided_marker.read_bytes()

        with self.assertRaises(BookStudioError) as raised:
            pilot_receipt(self.config)

        self.assertEqual("PILOT_STATE_MISSING", raised.exception.code)
        self.assertIn("state/pilot.json", raised.exception.next_action)
        self.assertEqual(before, self.config.paths.guided_marker.read_bytes())
        self.assertFalse(self.config.paths.pilot.exists())

    def test_persisted_pilot_requires_complete_source_bound_locked_intake(self) -> None:
        intake_path = self.config.paths.intake
        original_intake = json.loads(intake_path.read_text(encoding="utf-8"))

        def remove_intake() -> None:
            intake_path.unlink()

        def remove_required_answer() -> None:
            payload = json.loads(json.dumps(original_intake))
            payload["answers"].pop("translation_approach")
            atomic_write_json(intake_path, payload)

        def stale_source_binding() -> None:
            payload = json.loads(json.dumps(original_intake))
            payload["source"]["sha256"] = "0" * 64
            atomic_write_json(intake_path, payload)

        for name, mutate in (
            ("missing", remove_intake),
            ("incomplete", remove_required_answer),
            ("stale source", stale_source_binding),
        ):
            with self.subTest(name=name):
                atomic_write_json(intake_path, original_intake)
                self.write_proposal()
                mutate()
                pilot_before = self.config.paths.pilot.read_bytes()
                intake_before = intake_path.read_bytes() if intake_path.exists() else None

                with self.assertRaisesRegex(BookStudioError, "PILOT_INTAKE_INVALID"):
                    pilot_receipt(self.config)

                self.assertEqual(pilot_before, self.config.paths.pilot.read_bytes())
                self.assertEqual(
                    intake_before,
                    intake_path.read_bytes() if intake_path.exists() else None,
                )

    def test_persisted_pilot_must_be_the_exact_winner_for_locked_answers(self) -> None:
        source = self.root / "tie.epub"
        project = self.root / "tie-project"
        build_pilot_tie_epub(source)
        assessment = assess_intake(source, self.answers)
        answers = assessment["answers"]
        init_project(
            project,
            slug="tie",
            source=source,
            target_language=answers["target_language"],
            output_mode=answers["output_mode"],
            profile=profile_from_answers(answers),
        )
        config = load_config(project / "bookstudio.toml")
        inspection = inspect_epub(source)
        block_map = extract_block_map(source)
        atomic_write_json(config.paths.inspection, inspection)
        atomic_write_json(
            config.paths.source_blocks / "full-block-map.json", block_map
        )
        atomic_write_json(
            config.paths.source_blocks / "coverage.json", full_coverage(block_map)
        )
        atomic_write_json(config.paths.intake, locked_intake(assessment))

        winner = select_pilot(inspection, block_map, answers)
        alternate = select_pilot(
            inspection,
            block_map,
            {
                **answers,
                "image_text_policy": "none",
                "image_annotation_policy": "none",
            },
        )
        self.assertEqual("OEBPS/text/chapter-two.xhtml", winner["source_document"])
        self.assertEqual("OEBPS/text/chapter.xhtml", alternate["source_document"])
        atomic_write_json(config.paths.pilot, alternate)
        before = {
            path: path.read_bytes()
            for path in (
                config.paths.intake,
                config.paths.pilot,
                config.paths.source_blocks / "full-block-map.json",
            )
        }

        with self.assertRaisesRegex(BookStudioError, "PILOT_SELECTION_STALE"):
            pilot_receipt(config)

        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_persisted_pilot_reason_codes_must_match_exact_winner(self) -> None:
        proposal = self.write_proposal()
        proposal["reason_codes"].append("spine_tie_break")
        atomic_write_json(self.config.paths.pilot, proposal)
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "PILOT_SELECTION_STALE"):
            pilot_receipt(self.config)

        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    # BSC-PILOT-007
    def test_approve_creates_translation_scope_and_derived_review_requirement(self) -> None:
        proposal = self.write_proposal()

        approved = approve_pilot(self.config)

        self.assertEqual("pilot_active", approved["status"])
        self.assertEqual(
            frozenset(
                (proposal["source_document"], target["block_index"])
                for target in proposal["targets"]
            ),
            require_translation_scope(self.config),
        )
        atomic_write_json(
            self.config.paths.cache / "translations.json",
            {
                "schema_version": 1,
                "source_sha256": proposal["source_sha256"],
                "files": {
                    proposal["source_document"]: [
                        self.target_row(proposal, target)
                        for target in proposal["targets"]
                    ]
                },
            },
        )
        before = self.config.paths.pilot.read_bytes()

        receipt = pilot_receipt(self.config)

        self.assertEqual("pilot_review_required", receipt["status"])
        self.assertEqual(len(proposal["targets"]), receipt["translated_blocks"])
        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    # BSC-PILOT-011
    def test_pre_acceptance_pilot_rejects_config_drift_from_locked_intake(self) -> None:
        self.write_proposal()
        approve_pilot(self.config)
        config_path = self.config.paths.config
        original_config = config_path.read_text(encoding="utf-8")
        pilot_before = self.config.paths.pilot.read_bytes()
        cases = (
            (
                "target language",
                original_config.replace(
                    'target_language = "vi"', 'target_language = "fr"'
                ),
            ),
            (
                "audience profile",
                original_config.replace(
                    'audience = "designers"', 'audience = "general readers"'
                ),
            ),
        )
        for name, changed_config in cases:
            with self.subTest(name=name):
                self.assertNotEqual(original_config, changed_config)
                config_path.write_text(changed_config, encoding="utf-8")
                with self.assertRaisesRegex(BookStudioError, "PILOT_CONFIG_DRIFT"):
                    pilot_receipt(load_config(config_path))
                self.assertEqual(pilot_before, self.config.paths.pilot.read_bytes())
        config_path.write_text(original_config, encoding="utf-8")

    # BSC-PILOT-009
    def test_accept_fails_without_complete_pilot_and_preserves_state(self) -> None:
        self.write_proposal()
        approve_pilot(self.config)
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "PILOT_INCOMPLETE"):
            accept_pilot(self.config, confirmed=True)

        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_accept_requires_confirmation_and_complete_canonical_target_rows(self) -> None:
        proposal = self.write_proposal()
        approve_pilot(self.config)
        atomic_write_json(
            self.config.paths.cache / "translations.json",
            {
                "schema_version": 1,
                "source_sha256": proposal["source_sha256"],
                "files": {
                    proposal["source_document"]: [
                        self.target_row(proposal, target)
                        for target in proposal["targets"]
                    ]
                },
            },
        )
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "PILOT_CONFIRMATION_REQUIRED"):
            accept_pilot(self.config, confirmed=False)
        self.assertEqual(before, self.config.paths.pilot.read_bytes())

        accepted = accept_pilot(self.config, confirmed=True)

        self.assertEqual("full_active", accepted["status"])
        self.assertIn("policy_identity", accepted)
        self.assertIsNone(require_translation_scope(self.config))
        self.assertIsNone(require_full_scope(self.config))

    def test_pre_release_active_status_normalizes_without_rewriting_state(self) -> None:
        proposal = self.write_proposal()
        proposal["status"] = "pilot_approved"
        atomic_write_json(self.config.paths.pilot, proposal)
        before = self.config.paths.pilot.read_bytes()

        loaded = load_pilot(self.config)

        assert loaded is not None
        self.assertEqual("pilot_active", loaded["status"])
        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_pre_release_accepted_state_without_policy_identity_fails_closed(self) -> None:
        proposal = self.write_proposal()
        proposal["status"] = "pilot_accepted"
        atomic_write_json(self.config.paths.pilot, proposal)
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "PILOT_POLICY_STALE"):
            load_pilot(self.config)

        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_proposed_and_active_states_reject_acceptance_identity(self) -> None:
        for status in ("pilot_proposed", "pilot_active"):
            with self.subTest(status=status):
                proposal = self.write_proposal()
                proposal["status"] = status
                proposal["policy_identity"] = {"sha256": "0" * 64}
                atomic_write_json(self.config.paths.pilot, proposal)
                before = self.config.paths.pilot.read_bytes()

                with self.assertRaisesRegex(BookStudioError, "PILOT_SCHEMA_INVALID"):
                    load_pilot(self.config)

                self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_acceptance_identity_is_stable_closed_and_contains_no_private_content(self) -> None:
        absolute_like = "/private/library/source-project/book.epub"
        recognizable_prose = "Readers should never decode this recognizable source sentence."
        assessment = assess_intake(
            self.source,
            {
                **self.answers,
                "audience": absolute_like,
                "tone": recognizable_prose,
            },
        )
        self.answers = assessment["answers"]
        atomic_write_json(self.config.paths.intake, locked_intake(assessment))
        config_path = self.config.paths.config
        config_text = config_path.read_text(encoding="utf-8")
        config_text = config_text.replace(
            'audience = "designers"',
            f"audience = {json.dumps(absolute_like)}",
        ).replace(
            'tone = "clear, conversational, domain-aware"',
            f"tone = {json.dumps(recognizable_prose)}",
        )
        config_path.write_text(config_text, encoding="utf-8")
        self.config = load_config(config_path)
        production_brief = (
            "# Production brief\n\n"
            f"- Private source location: {absolute_like}\n"
            f"- Voice evidence: {recognizable_prose}\n"
        )
        self.config.paths.production_brief.write_text(
            production_brief, encoding="utf-8"
        )
        self.complete_active_pilot()

        accepted = accept_pilot(self.config, confirmed=True)
        receipt = pilot_receipt(self.config)

        self.assertIn("policy_identity", accepted)
        identity = accepted["policy_identity"]
        self.assertEqual(identity, receipt["policy_identity"])
        self.assertEqual(
            {
                "schema_version",
                "policy_sha256",
                "glossary_sha256",
                "reference_notes_sha256",
                "image_manifest_sha256",
                "production_brief_sha256",
                "sha256",
            },
            set(identity),
        )
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        persisted = self.config.paths.pilot.read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn(self.source.name, encoded)
        self.assertNotIn("Bản dịch", encoded)
        self.assertNotIn(absolute_like, persisted)
        self.assertNotIn(recognizable_prose, persisted)
        self.assertEqual(64, len(identity["policy_sha256"]))
        self.assertEqual(64, len(identity["sha256"]))
        self.assertEqual(
            hashlib.sha256(self.config.paths.glossary.read_bytes()).hexdigest(),
            identity["glossary_sha256"],
        )
        self.assertEqual("absent", identity["reference_notes_sha256"])
        self.assertEqual("absent", identity["image_manifest_sha256"])
        self.assertEqual(
            hashlib.sha256(production_brief.encode("utf-8")).hexdigest(),
            identity["production_brief_sha256"],
        )

        pilot_before = self.config.paths.pilot.read_bytes()
        config_path.write_text(
            config_text.replace(recognizable_prose, "Changed policy text"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(BookStudioError, "PILOT_POLICY_STALE"):
            pilot_receipt(load_config(config_path))
        self.assertEqual(pilot_before, self.config.paths.pilot.read_bytes())

    # BSC-PILOT-011
    def test_full_active_load_rejects_each_policy_component_drift_without_mutation(self) -> None:
        self.complete_active_pilot()
        accept_pilot(self.config, confirmed=True)
        config_path = self.config.paths.config
        glossary_path = self.config.paths.glossary
        reference_notes_path = self.config.paths.root / "reference-notes.json"
        manifest_path = self.config.paths.root / "assets/image-manifest.json"
        production_brief_path = self.config.paths.production_brief
        original_config = config_path.read_bytes()
        original_glossary = glossary_path.read_bytes()
        original_pilot = self.config.paths.pilot.read_bytes()

        def change_target() -> None:
            config_path.write_text(
                original_config.decode("utf-8").replace(
                    'target_language = "vi"', 'target_language = "fr"'
                ),
                encoding="utf-8",
            )

        def change_prompt() -> None:
            config_path.write_text(
                original_config.decode("utf-8").replace(
                    'prompt_version = "1"', 'prompt_version = "2"'
                ),
                encoding="utf-8",
            )

        def change_glossary() -> None:
            glossary_path.write_bytes(original_glossary + b"\npolicy drift\n")

        def add_reference_notes() -> None:
            atomic_write_json(reference_notes_path, {"notes": []})

        def add_manifest() -> None:
            atomic_write_json(manifest_path, {"schema_version": 1, "images": []})

        def add_production_brief() -> None:
            production_brief_path.write_text(
                "# Production brief\n\n- Voice: calm and direct\n",
                encoding="utf-8",
            )

        for name, mutate in (
            ("target language", change_target),
            ("prompt version", change_prompt),
            ("glossary", change_glossary),
            ("reference notes", add_reference_notes),
            ("image manifest", add_manifest),
            ("production brief", add_production_brief),
        ):
            with self.subTest(name=name):
                config_path.write_bytes(original_config)
                glossary_path.write_bytes(original_glossary)
                reference_notes_path.unlink(missing_ok=True)
                manifest_path.unlink(missing_ok=True)
                production_brief_path.unlink(missing_ok=True)
                self.config.paths.pilot.write_bytes(original_pilot)
                mutate()
                before = self.config.paths.pilot.read_bytes()
                current = load_config(config_path)

                with self.assertRaisesRegex(BookStudioError, "PILOT_POLICY_STALE"):
                    pilot_receipt(current)

                self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_full_active_load_rejects_each_canonical_policy_drift_without_mutation(
        self,
    ) -> None:
        canonical = {
            "translation_approach": ("faithful", "adaptive"),
            "image_text_policy": ("selective", "all"),
            "image_annotation_policy": ("selective", "all"),
            "market_context_policy": ("labeled_selective", "none"),
            "layout_policy": ("preserve", "adaptive"),
        }
        self.assertTrue(set(canonical).issubset(self.config.profile))
        self.complete_active_pilot()
        accept_pilot(self.config, confirmed=True)
        config_path = self.config.paths.config
        original_config = config_path.read_bytes()
        original_pilot = self.config.paths.pilot.read_bytes()

        for key, (current, changed) in canonical.items():
            with self.subTest(key=key):
                config_path.write_bytes(original_config)
                self.config.paths.pilot.write_bytes(original_pilot)
                config_path.write_text(
                    original_config.decode("utf-8").replace(
                        f'{key} = "{current}"', f'{key} = "{changed}"'
                    ),
                    encoding="utf-8",
                )
                self.assertNotEqual(original_config, config_path.read_bytes())
                before = self.config.paths.pilot.read_bytes()

                with self.assertRaisesRegex(BookStudioError, "PILOT_POLICY_STALE"):
                    pilot_receipt(load_config(config_path))

                self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_full_active_load_rejects_policy_identity_tampering_without_mutation(self) -> None:
        self.complete_active_pilot()
        accept_pilot(self.config, confirmed=True)
        original = json.loads(self.config.paths.pilot.read_text(encoding="utf-8"))
        self.assertIn("policy_identity", original)

        mutations = {
            "overall hash": lambda value: value["policy_identity"].update(
                sha256="0" * 64
            ),
            "component hash": lambda value: value["policy_identity"].update(
                glossary_sha256="0" * 64
            ),
            "policy hash type": lambda value: value["policy_identity"].update(
                policy_sha256=[]
            ),
            "boolean schema": lambda value: value["policy_identity"].update(
                schema_version=True
            ),
            "extra key": lambda value: value["policy_identity"].update(private_path="/tmp/book"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                tampered = json.loads(json.dumps(original))
                mutate(tampered)
                atomic_write_json(self.config.paths.pilot, tampered)
                before = self.config.paths.pilot.read_bytes()

                with self.assertRaisesRegex(BookStudioError, "PILOT_POLICY_STALE"):
                    pilot_receipt(self.config)

                self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_pilot_state_rejects_boolean_schema_without_mutation(self) -> None:
        proposal = self.write_proposal()
        proposal["schema_version"] = True
        atomic_write_json(self.config.paths.pilot, proposal)
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "PILOT_SCHEMA_INVALID"):
            pilot_receipt(self.config)

        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_pilot_gates_reject_tampered_optional_image_records_without_mutation(
        self,
    ) -> None:
        companion = self.config.paths.localized_assets / "pixel-vi.png"
        with zipfile.ZipFile(self.source) as archive:
            companion.write_bytes(archive.read("OEBPS/images/pixel.png"))
        malformed = (
            ("image_annotations", {}),
            (
                "image_companions",
                {
                    "source_path": "OEBPS/images/pixel.png",
                    "companion": "assets/localized/pixel-vi.png",
                    "private_path": "/private/source/pixel.png",
                },
            ),
        )
        operations = (
            ("receipt", lambda: pilot_receipt(self.config)),
            ("accept", lambda: accept_pilot(self.config, confirmed=True)),
        )
        for field, record in malformed:
            for operation_name, operation in operations:
                with self.subTest(field=field, operation=operation_name):
                    (self.config.paths.cache / "translations.json").unlink(
                        missing_ok=True
                    )
                    proposal = self.complete_active_pilot()
                    cache_path = self.config.paths.cache / "translations.json"
                    cache = json.loads(cache_path.read_text(encoding="utf-8"))
                    cache["files"][proposal["source_document"]][0][field] = [record]
                    atomic_write_json(cache_path, cache)
                    cache_before = cache_path.read_bytes()
                    pilot_before = self.config.paths.pilot.read_bytes()

                    with self.assertRaisesRegex(
                        BookStudioError, "IMAGE_MANIFEST_SCHEMA_INVALID"
                    ):
                        operation()

                    self.assertEqual(cache_before, cache_path.read_bytes())
                    self.assertEqual(pilot_before, self.config.paths.pilot.read_bytes())

    # BSC-PILOT-012
    def test_pilot_cache_scope_is_strict_until_acceptance_then_allows_global_rows(self) -> None:
        proposal = self.complete_active_pilot()
        outside_file = next(
            row for row in self.block_map["files"]
            if row["source_path"] != proposal["source_document"]
            and any(block["canonical"] and not block["watermark"] for block in row["blocks"])
        )
        outside_block = next(
            block for block in outside_file["blocks"]
            if block["canonical"] and not block["watermark"]
        )
        outside_row = {
            "block_index": outside_block["block_index"],
            "source_role": outside_block["role"],
            "source_sha256": outside_block["text_sha256"],
            "translation": "Ngoài pilot",
            "packet_id": "0" * 64,
            "context_sha256": current_translation_context_sha256(self.config),
        }
        cache_path = self.config.paths.cache / "translations.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        cache["files"][outside_file["source_path"]] = [outside_row]
        atomic_write_json(cache_path, cache)
        before = cache_path.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "CACHE_SCOPE_INVALID"):
            pilot_receipt(self.config)
        self.assertEqual(before, cache_path.read_bytes())

        cache["files"].pop(outside_file["source_path"])
        atomic_write_json(cache_path, cache)
        accept_pilot(self.config, confirmed=True)
        cache["files"][outside_file["source_path"]] = [outside_row]
        atomic_write_json(cache_path, cache)

        receipt = pilot_receipt(self.config)

        self.assertEqual("full_active", receipt["status"])

    def test_receipt_and_accept_reject_deleted_canonical_target_without_rewriting_state(self) -> None:
        self.write_proposal()
        approve_pilot(self.config)
        tampered = json.loads(self.config.paths.pilot.read_text(encoding="utf-8"))
        tampered["targets"].pop()
        tampered["eligible_blocks"] -= 1
        tampered["translated_blocks"] = 0
        atomic_write_json(self.config.paths.pilot, tampered)
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "PILOT_TARGET_SET_INVALID"):
            pilot_receipt(self.config)
        self.assertEqual(before, self.config.paths.pilot.read_bytes())

        with self.assertRaisesRegex(BookStudioError, "PILOT_TARGET_SET_INVALID"):
            accept_pilot(self.config, confirmed=True)
        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_receipt_rejects_malformed_selection_facts_without_rewriting_state(self) -> None:
        mutations = {
            "missing": lambda payload: payload.pop("selection_facts"),
            "extra source prose": lambda payload: payload["selection_facts"].update(
                source_prose="synthetic source sentence"
            ),
            "altered title": lambda payload: payload["selection_facts"].update(
                selected_title="Different chapter"
            ),
            "altered spine": lambda payload: payload["selection_facts"].update(
                selected_spine_index=0
            ),
            "altered block count": lambda payload: payload["selection_facts"].update(
                selected_block_count=5
            ),
            "altered image count": lambda payload: payload["selection_facts"].update(
                selected_image_count=2
            ),
            "altered candidate count": lambda payload: payload["selection_facts"].update(
                nonempty_candidate_count=4
            ),
            "altered non-excluded count": lambda payload: payload["selection_facts"].update(
                non_excluded_candidate_count=2
            ),
            "altered non-trivial count": lambda payload: payload["selection_facts"].update(
                non_trivial_candidate_count=0
            ),
            "altered ranked count": lambda payload: payload["selection_facts"].update(
                ranked_candidate_count=2
            ),
            "altered median": lambda payload: payload["selection_facts"].update(
                median_block_count=5
            ),
            "nan median": lambda payload: payload["selection_facts"].update(
                median_block_count=float("nan")
            ),
            "infinite median": lambda payload: payload["selection_facts"].update(
                median_block_count=float("inf")
            ),
            "altered fallback": lambda payload: payload["selection_facts"].update(
                all_nonempty_excluded=True
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.write_proposal()
                tampered = json.loads(self.config.paths.pilot.read_text(encoding="utf-8"))
                mutate(tampered)
                atomic_write_json(self.config.paths.pilot, tampered)
                before = self.config.paths.pilot.read_bytes()

                with self.assertRaisesRegex(BookStudioError, "PILOT_SCHEMA_INVALID"):
                    pilot_receipt(self.config)

                self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_receipt_rejects_json_coercion_shaped_selection_fact_types_without_rewriting_state(
        self,
    ) -> None:
        mutations = [
            ("non-string selected title", "selected_title", 1),
            ("bool selected spine", "selected_spine_index", True),
            ("float selected spine", "selected_spine_index", 1.0),
            ("bool selected block count", "selected_block_count", True),
            ("float selected block count", "selected_block_count", 4.0),
            ("bool selected image count", "selected_image_count", True),
            ("float selected image count", "selected_image_count", 1.0),
            ("bool nonempty count", "nonempty_candidate_count", True),
            ("float nonempty count", "nonempty_candidate_count", 3.0),
            ("bool non-excluded count", "non_excluded_candidate_count", True),
            ("float non-excluded count", "non_excluded_candidate_count", 1.0),
            ("bool non-trivial count", "non_trivial_candidate_count", True),
            ("float non-trivial count", "non_trivial_candidate_count", 1.0),
            ("bool ranked count", "ranked_candidate_count", True),
            ("float ranked count", "ranked_candidate_count", 1.0),
            ("numeric false fallback", "all_nonempty_excluded", 0),
            ("numeric true fallback", "all_nonempty_excluded", 1),
        ]
        for name, key, value in mutations:
            with self.subTest(name=name):
                self.write_proposal()
                tampered = json.loads(self.config.paths.pilot.read_text(encoding="utf-8"))
                tampered["selection_facts"][key] = value
                atomic_write_json(self.config.paths.pilot, tampered)
                before = self.config.paths.pilot.read_bytes()

                with self.assertRaisesRegex(BookStudioError, "PILOT_SCHEMA_INVALID"):
                    pilot_receipt(self.config)

                self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_pilot_gates_require_the_exact_full_prepared_block_map(self) -> None:
        prepared_path = self.config.paths.source_blocks / "full-block-map.json"

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
        operations = {
            "pilot receipt": lambda: pilot_receipt(self.config),
            "next scope gate": lambda: require_translation_scope(self.config),
            "full scope gate": lambda: require_full_scope(self.config),
        }
        for mutation_name, mutate in mutations.items():
            for operation_name, operation in operations.items():
                with self.subTest(mutation=mutation_name, operation=operation_name):
                    atomic_write_json(prepared_path, self.block_map)
                    self.write_proposal()
                    approve_pilot(self.config)
                    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
                    mutate(prepared)
                    atomic_write_json(prepared_path, prepared)
                    before = {
                        prepared_path: prepared_path.read_bytes(),
                        self.config.paths.pilot: self.config.paths.pilot.read_bytes(),
                    }

                    with self.assertRaises(BookStudioError) as raised:
                        operation()

                    self.assertEqual("BLOCK_MAP_STALE", raised.exception.code)
                    self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_receipt_uses_fresh_source_inspection_not_persisted_facts(self) -> None:
        self.write_proposal()
        persisted = json.loads(self.config.paths.inspection.read_text(encoding="utf-8"))
        persisted["text"]["files"][1]["title"] = "Tampered persisted title"
        persisted["text"]["files"][1]["images"] = 99
        atomic_write_json(self.config.paths.inspection, persisted)

        receipt = pilot_receipt(self.config)

        self.assertEqual("Chapter One", receipt["selection_facts"]["selected_title"])
        self.assertEqual(1, receipt["selection_facts"]["selected_image_count"])

    def test_accept_rejects_matching_rows_when_cache_source_hash_is_empty(self) -> None:
        proposal = self.write_proposal()
        approve_pilot(self.config)
        atomic_write_json(
            self.config.paths.cache / "translations.json",
            {
                "schema_version": 1,
                "source_sha256": "",
                "files": {
                    proposal["source_document"]: [
                        {
                            **self.target_row(proposal, target),
                        }
                        for target in proposal["targets"]
                    ]
                },
            },
        )
        before = self.config.paths.pilot.read_bytes()

        with self.assertRaisesRegex(BookStudioError, "CACHE_SOURCE_STALE"):
            accept_pilot(self.config, confirmed=True)

        self.assertEqual(before, self.config.paths.pilot.read_bytes())

    def test_transition_rejects_stale_source_without_rewriting_pilot(self) -> None:
        self.write_proposal()
        before = self.config.paths.pilot.read_bytes()
        build_synthetic_epub(self.source, include_image=False)

        with self.assertRaisesRegex(BookStudioError, "PILOT_SOURCE_STALE"):
            approve_pilot(self.config)

        self.assertEqual(before, self.config.paths.pilot.read_bytes())


if __name__ == "__main__":
    unittest.main()
