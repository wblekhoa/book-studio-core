from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bookstudio.config import load_config
from bookstudio.errors import BookStudioError
from bookstudio.intake import (
    assess_intake,
    load_intake_answers,
    profile_from_answers,
)
from bookstudio.pilot import approve_pilot, require_translation_scope
from bookstudio.project import start_project
from bookstudio.translation.packets import next_packet
from tests.fixtures import build_synthetic_epub


class IntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # BSC-PILOT-002
    def test_assessment_omits_known_answers_and_image_questions_without_images(self) -> None:
        source = self.workspace / "no-images.epub"
        build_synthetic_epub(source, include_image=False)

        receipt = assess_intake(
            source,
            {
                "target_language": "vi",
                "output_mode": "target_only",
            },
        )

        ids = [row["id"] for row in receipt["questions"]]
        self.assertNotIn("target_language", ids)
        self.assertNotIn("output_mode", ids)
        self.assertNotIn("image_text_policy", ids)
        self.assertNotIn("image_annotation_policy", ids)

    # BSC-PILOT-002
    def test_assessment_infers_single_metadata_language_and_orders_missing_questions(self) -> None:
        source = self.workspace / "with-image.epub"
        build_synthetic_epub(source)

        receipt = assess_intake(source, {})

        self.assertEqual("en", receipt["answers"]["source_language"])
        self.assertEqual(
            [
                "target_language",
                "output_mode",
                "audience",
                "translation_approach",
                "image_text_policy",
                "image_annotation_policy",
                "market_context_policy",
                "layout_policy",
            ],
            [row["id"] for row in receipt["questions"]],
        )
        self.assertEqual(1, receipt["book_facts"]["images"])

    # BSC-PILOT-003
    def test_missing_questions_expose_stable_accepted_values_and_recommendations(self) -> None:
        source = self.workspace / "with-image.epub"
        build_synthetic_epub(source)

        questions = {
            question["id"]: question for question in assess_intake(source, {})["questions"]
        }

        for question in questions.values():
            self.assertIn("accepted_values", question)
            self.assertIn("recommendation", question)
        self.assertEqual(
            {
                "accepted_values": None,
                "recommendation": None,
            },
            {
                key: questions["target_language"][key]
                for key in ("accepted_values", "recommendation")
            },
        )
        self.assertEqual(
            ["target_only", "bilingual", "vi_only"],
            questions["output_mode"]["accepted_values"],
        )
        self.assertEqual("target_only", questions["output_mode"]["recommendation"])
        self.assertEqual(None, questions["audience"]["accepted_values"])
        self.assertIsNone(questions["audience"]["recommendation"])
        expected_enums = {
            "translation_approach": (["faithful", "adaptive"], "faithful"),
            "image_text_policy": (["none", "selective", "all"], "selective"),
            "image_annotation_policy": (["none", "selective", "all"], "selective"),
            "market_context_policy": (["none", "labeled_selective"], "labeled_selective"),
            "layout_policy": (["preserve", "adaptive"], "preserve"),
        }
        for question_id, (accepted_values, recommendation) in expected_enums.items():
            with self.subTest(question_id=question_id):
                self.assertEqual(accepted_values, questions[question_id]["accepted_values"])
                self.assertEqual(recommendation, questions[question_id]["recommendation"])

    # BSC-PILOT-004
    def test_assessment_rejects_unknown_non_string_and_invalid_language_answers(self) -> None:
        source = self.workspace / "with-image.epub"
        build_synthetic_epub(source)

        with self.assertRaisesRegex(BookStudioError, "INTAKE_ANSWER_UNKNOWN"):
            assess_intake(source, {"surprise": "value"})
        with self.assertRaisesRegex(BookStudioError, "INTAKE_ANSWER_INVALID"):
            assess_intake(source, {"audience": 12})
        with self.assertRaisesRegex(BookStudioError, "CONFIG_LANGUAGE_INVALID"):
            assess_intake(source, {"target_language": "Vietnamese"})

    def test_blank_required_answers_are_omitted_and_returned_as_missing(self) -> None:
        source = self.workspace / "no-images.epub"
        build_synthetic_epub(source, include_image=False)

        error = None
        receipt = None
        try:
            receipt = assess_intake(
                source,
                {
                    "target_language": "  ",
                    "output_mode": "\t",
                    "audience": "",
                    "translation_approach": " ",
                    "market_context_policy": "\n",
                    "layout_policy": "  ",
                },
            )
        except BookStudioError as exc:
            error = str(exc)
        self.assertIsNone(error, f"Blank required answers must remain missing, not error: {error}")
        assert receipt is not None

        self.assertEqual({"source_language": "en"}, receipt["answers"])
        self.assertEqual(
            [
                "target_language",
                "output_mode",
                "audience",
                "translation_approach",
                "market_context_policy",
                "layout_policy",
            ],
            [question["id"] for question in receipt["questions"]],
        )

    def test_book_facts_include_privacy_safe_per_spine_structure(self) -> None:
        source = self.workspace / "facts.epub"
        build_synthetic_epub(source)

        facts = assess_intake(source, {})["book_facts"]

        self.assertIn("documents", facts)
        self.assertEqual(3, len(facts["documents"]))
        chapter = facts["documents"][1]
        self.assertEqual(
            {
                "spine_index",
                "logical_path",
                "title",
                "size_bytes",
                "block_count",
                "image_count",
            },
            set(chapter),
        )
        self.assertEqual(1, chapter["spine_index"])
        self.assertEqual("OEBPS/text/chapter.xhtml", chapter["logical_path"])
        self.assertEqual("Chapter One", chapter["title"])
        self.assertGreater(chapter["size_bytes"], 0)
        self.assertEqual(5, chapter["block_count"])
        self.assertEqual(1, chapter["image_count"])
        self.assertNotIn(str(self.workspace), json.dumps(facts))

    def test_manifest_image_resource_without_inline_reference_asks_image_questions(self) -> None:
        source = self.workspace / "resource-only.epub"
        build_synthetic_epub(source, include_image=True, image_markup="none")

        receipt = assess_intake(source, {})

        ids = [question["id"] for question in receipt["questions"]]
        self.assertIn("image_text_policy", ids)
        self.assertIn("image_annotation_policy", ids)
        self.assertEqual(1, receipt["book_facts"]["images"])
        self.assertTrue(all(row["image_count"] == 0 for row in receipt["book_facts"]["documents"]))

    def test_inline_image_shapes_without_manifest_resources_ask_image_questions(self) -> None:
        cases = {
            "img": "img",
            "bare-svg": "bare-svg",
            "svg-image": "svg",
        }
        for name, markup in cases.items():
            with self.subTest(name=name):
                source = self.workspace / f"inline-{name}.epub"
                build_synthetic_epub(source, include_image=False, image_markup=markup)

                receipt = assess_intake(source, {})

                ids = [question["id"] for question in receipt["questions"]]
                self.assertIn("image_text_policy", ids)
                self.assertIn("image_annotation_policy", ids)
                self.assertEqual(1, receipt["book_facts"]["images"])
                self.assertEqual(
                    1, receipt["book_facts"]["documents"][1]["image_count"]
                )

    def test_locked_policy_enums_fail_closed(self) -> None:
        source = self.workspace / "with-image.epub"
        build_synthetic_epub(source)
        invalid_answers = {
            "translation_approach": "literal",
            "image_text_policy": "translate-inline",
            "image_annotation_policy": "annotate",
            "market_context_policy": "preserve-context",
            "layout_policy": "preserve-layout",
        }

        for key, value in invalid_answers.items():
            with self.subTest(key=key), self.assertRaisesRegex(
                BookStudioError, "INTAKE_ANSWER_INVALID"
            ):
                assess_intake(source, {key: value})

    def test_load_answers_and_profile_mapping_preserve_explicit_labels(self) -> None:
        answers_path = self.workspace / "answers.json"
        answers_path.write_text(
            json.dumps(
                {
                    "audience": "designers",
                    "domain": "product-design",
                    "tone": "plain",
                    "terminology_policy": "retain-terms",
                    "translation_approach": "faithful",
                    "image_text_policy": "selective",
                    "image_annotation_policy": "all",
                    "market_context_policy": "labeled_selective",
                    "layout_policy": "preserve",
                }
            ),
            encoding="utf-8",
        )

        answers = load_intake_answers(answers_path)

        self.assertEqual({}, load_intake_answers(None))
        self.assertEqual("designers", answers["audience"])
        self.assertEqual(
            {
                "domain": "product-design",
                "audience": "designers",
                "tone": "plain",
                "terminology_policy": "retain-terms",
                "translation_approach": "faithful",
                "image_text_policy": "selective",
                "image_annotation_policy": "all",
                "market_context_policy": "labeled_selective",
                "layout_policy": "preserve",
                "image_policy": "selective",
                "localization_boundary": "labeled_selective",
            },
            profile_from_answers(answers),
        )

    # BSC-PILOT-006
    def test_start_project_writes_deterministic_pilot_after_prepared_artifacts(self) -> None:
        source = self.workspace / "guided.epub"
        target = self.workspace / "guided-project"
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

        assessment = start_project(target, source, answers)
        config = load_config(target / "bookstudio.toml")
        proposal = json.loads(config.paths.pilot.read_text(encoding="utf-8"))

        self.assertEqual("ready", assessment["status"])
        self.assertEqual("pilot_proposed", proposal["status"])
        self.assertEqual("OEBPS/text/chapter.xhtml", proposal["source_document"])
        self.assertTrue(proposal["targets"])
        canonical_policies = {
            key: answers[key]
            for key in (
                "translation_approach",
                "image_text_policy",
                "image_annotation_policy",
                "market_context_policy",
                "layout_policy",
            )
        }
        self.assertEqual(
            canonical_policies,
            {key: config.profile[key] for key in canonical_policies},
        )
        self.assertEqual(
            config.profile["image_text_policy"], config.profile["image_policy"]
        )
        self.assertEqual(
            config.profile["market_context_policy"],
            config.profile["localization_boundary"],
        )

        approve_pilot(config)
        allowed = require_translation_scope(config)
        packet = next_packet(
            config,
            allowed_targets=allowed,
            scope_identity="pilot_active:canonical-policy-test",
        )

        assert packet is not None
        self.assertEqual(
            canonical_policies,
            {key: packet["book_profile"][key] for key in canonical_policies},
        )


if __name__ == "__main__":
    unittest.main()
