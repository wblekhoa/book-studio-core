from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bookstudio.config import atomic_write_json
from tests.fixtures import build_synthetic_epub


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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


class CliContractTests(unittest.TestCase):
    def test_root_version_reports_installed_release(self) -> None:
        result = run_cli("--version")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("bookstudio 0.3.0", result.stdout.strip())

    def test_help_lists_beginner_commands(self) -> None:
        result = run_cli("--help")

        self.assertEqual(0, result.returncode, result.stderr)
        for command in ("doctor", "init", "next", "apply", "finish"):
            self.assertIn(command, result.stdout)
        self.assertIn("pilot", result.stdout)

    def test_root_help_describes_the_guided_workflow_commands(self) -> None:
        result = run_cli("--help")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Start a guided translation project.", result.stdout)
        self.assertIn("Emit the next bounded translation packet.", result.stdout)
        self.assertIn("Run the strict reproducible final-book gate.", result.stdout)

    def test_guided_command_help_explains_inputs_and_pilot_actions(self) -> None:
        start = run_cli("start", "--help")
        pilot = run_cli("pilot", "--help")
        pilot_accept = run_cli("pilot", "accept", "--help")

        self.assertEqual(0, start.returncode, start.stderr)
        self.assertIn("Private project directory to create or resume.", start.stdout)
        self.assertIn("Source EPUB; it is opened read-only.", start.stdout)
        self.assertIn("JSON file keyed by the reported question IDs.", start.stdout)
        self.assertEqual(0, pilot.returncode, pilot.stderr)
        self.assertIn("Show the current pilot gate and next action.", pilot.stdout)
        self.assertIn("Revise translated pilot blocks before acceptance.", pilot.stdout)
        self.assertIn("Accept a completed pilot and unlock full scope.", pilot.stdout)
        self.assertEqual(0, pilot_accept.returncode, pilot_accept.stderr)
        self.assertIn(
            "Confirm that the completed pilot was reviewed.",
            pilot_accept.stdout,
        )

    def test_translation_command_help_explains_packet_inputs(self) -> None:
        next_packet = run_cli("next", "--help")
        apply = run_cli("apply", "--help")

        self.assertEqual(0, next_packet.returncode, next_packet.stderr)
        self.assertIn("Private Book Studio project directory.", next_packet.stdout)
        self.assertEqual(0, apply.returncode, apply.stderr)
        self.assertIn("Private Book Studio project directory.", apply.stdout)
        self.assertIn("AI response JSON file.", apply.stdout)

    def test_help_does_not_advertise_unimplemented_clean_command(self) -> None:
        root_help = run_cli("--help")
        clean_help = run_cli("clean", "--help")

        self.assertEqual(0, root_help.returncode, root_help.stderr)
        self.assertNotIn("clean", root_help.stdout)
        self.assertEqual(2, clean_help.returncode)
        self.assertIn("invalid choice", clean_help.stderr)

    def test_json_error_has_stable_shape(self) -> None:
        result = run_cli("inspect", "/missing", "--json")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertTrue(result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {"status", "code", "message", "evidence", "next_action"},
            set(payload),
        )
        self.assertEqual("PROJECT_CONFIG_MISSING", payload["code"])

    def test_human_error_includes_recovery_action(self) -> None:
        result = run_cli("inspect", "/missing")

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("Book Studio project config not found", result.stderr)
        self.assertIn(
            "Next action: Run 'bookstudio init' or pass an existing project directory.",
            result.stderr,
        )


class StartCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.source = self.workspace / "source.epub"
        self.project = self.workspace / "project"
        self.answers = self.workspace / "answers.json"
        build_synthetic_epub(self.source)
        self.answers.write_text(
            json.dumps(
                {
                    "target_language": "vi",
                    "output_mode": "vi_only",
                    "audience": "designers",
                    "translation_approach": "faithful",
                    "image_text_policy": "selective",
                    "image_annotation_policy": "selective",
                    "market_context_policy": "labeled_selective",
                    "layout_policy": "preserve",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # BSC-PILOT-001
    def test_start_missing_answers_returns_questions_without_creating_project(self) -> None:
        result = run_cli("start", str(self.project), "--source", str(self.source), "--json")

        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("needs_input", payload["status"])
        self.assertTrue(payload["questions"])
        self.assertFalse(self.project.exists())
        self.assertNotIn(str(self.workspace), result.stdout)

    def test_start_missing_answers_renders_questions_and_next_action_for_humans(self) -> None:
        result = run_cli("start", str(self.project), "--source", str(self.source))

        self.assertEqual(2, result.returncode)
        self.assertIn(
            "1. [target_language] What language should the translated book use?",
            result.stdout,
        )
        self.assertNotIn("   Recommended: vi", result.stdout)
        self.assertIn(
            "2. [output_mode] Should the output replace source text or show both languages?",
            result.stdout,
        )
        self.assertIn(
            "   Choices: target_only, bilingual, vi_only",
            result.stdout,
        )
        self.assertIn("   Recommended: target_only", result.stdout)
        self.assertIn(
            "3. [audience] Who is the intended reader?",
            result.stdout,
        )
        self.assertIn("Next action:", result.stdout)

    def test_start_complete_writes_owned_resumable_intake(self) -> None:
        result = run_cli(
            "start", str(self.project), "--source", str(self.source),
            "--answers", str(self.answers), "--json",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.project / "state/intake.json").is_file())
        self.assertTrue((self.project / "source-blocks/full-block-map.json").is_file())
        self.assertNotIn(str(self.workspace), result.stdout)

    def test_start_rejects_malformed_answers_without_creating_project(self) -> None:
        self.answers.write_text("{", encoding="utf-8")

        result = run_cli(
            "start", str(self.project), "--source", str(self.source),
            "--answers", str(self.answers), "--json",
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("INTAKE_ANSWERS_INVALID", json.loads(result.stdout)["code"])
        self.assertFalse(self.project.exists())

    # BSC-PILOT-005
    def test_start_refuses_nonempty_unowned_target_without_mutation(self) -> None:
        self.project.mkdir()
        sentinel = self.project / "user-file.txt"
        sentinel.write_text("keep", encoding="utf-8")

        result = run_cli(
            "start", str(self.project), "--source", str(self.source),
            "--answers", str(self.answers), "--json",
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("PROJECT_NOT_OWNED", json.loads(result.stdout)["code"])
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_expert_init_defaults_to_language_neutral_target_only_output(self) -> None:
        expert_project = self.workspace / "expert-project"

        result = run_cli(
            "init",
            str(expert_project),
            "--source",
            str(self.source),
            "--target",
            "fr",
            "--json",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        config = (expert_project / "bookstudio.toml").read_text(encoding="utf-8")
        self.assertIn('target_language = "fr"', config)
        self.assertIn('output_mode = "target_only"', config)


class PilotCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.source = self.workspace / "source.epub"
        self.project = self.workspace / "project"
        self.answers = self.workspace / "answers.json"
        build_synthetic_epub(self.source)
        atomic_write_json(
            self.answers,
            {
                "target_language": "vi",
                "output_mode": "vi_only",
                "audience": "designers",
                "translation_approach": "faithful",
                "image_text_policy": "selective",
                "image_annotation_policy": "selective",
                "market_context_policy": "labeled_selective",
                "layout_policy": "preserve",
            },
        )
        started = run_cli(
            "start",
            str(self.project),
            "--source",
            str(self.source),
            "--answers",
            str(self.answers),
            "--json",
        )
        self.assertEqual(0, started.returncode, started.stderr)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _complete_pilot(self) -> Path:
        packet_result = run_cli("next", str(self.project), "--json")
        self.assertEqual(0, packet_result.returncode, packet_result.stderr)
        packet = json.loads(packet_result.stdout)
        response_path = self.workspace / "response.json"
        atomic_write_json(
            response_path,
            {
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
            },
        )
        applied = run_cli("apply", str(self.project), str(response_path), "--json")
        self.assertEqual(0, applied.returncode, applied.stderr)
        return response_path

    def _project_snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in sorted(self.project.rglob("*"))
            if path.is_file()
        }

    # BSC-PILOT-007
    def test_pilot_status_and_approve_report_canonical_status_and_next_action(self) -> None:
        proposed = run_cli("pilot", "status", str(self.project), "--json")

        self.assertEqual(0, proposed.returncode, proposed.stderr)
        proposed_payload = json.loads(proposed.stdout)
        self.assertEqual("pilot_proposed", proposed_payload["status"])
        self.assertNotIn("workflow_phase", proposed_payload)
        self.assertTrue(proposed_payload["next_action"])
        human_status = run_cli("pilot", "status", str(self.project))
        self.assertEqual(0, human_status.returncode, human_status.stderr)
        self.assertIn("pilot_proposed", human_status.stdout)
        self.assertIn("Next action:", human_status.stdout)

        blocked = run_cli("next", str(self.project), "--json")
        self.assertEqual(2, blocked.returncode)
        self.assertEqual("PILOT_APPROVAL_REQUIRED", json.loads(blocked.stdout)["code"])

        approved = run_cli("pilot", "approve", str(self.project), "--json")
        self.assertEqual(0, approved.returncode, approved.stderr)
        approved_payload = json.loads(approved.stdout)
        self.assertEqual("pilot_active", approved_payload["status"])
        self.assertNotIn("workflow_phase", approved_payload)
        self.assertTrue(approved_payload["next_action"])

    def test_missing_guided_pilot_blocks_every_scope_entry_without_mutation(self) -> None:
        approved = run_cli("pilot", "approve", str(self.project), "--json")
        self.assertEqual(0, approved.returncode, approved.stderr)
        packet_result = run_cli("next", str(self.project), "--json")
        self.assertEqual(0, packet_result.returncode, packet_result.stderr)
        packet = json.loads(packet_result.stdout)
        response_path = self.workspace / "missing-pilot-response.json"
        atomic_write_json(
            response_path,
            {
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
            },
        )
        (self.project / "state/pilot.json").unlink()
        before = self._project_snapshot()

        commands = (
            ("pilot receipt", ("pilot", "status", str(self.project), "--json")),
            ("next", ("next", str(self.project), "--json")),
            (
                "apply",
                ("apply", str(self.project), str(response_path), "--json"),
            ),
            ("build", ("build", str(self.project), "--json")),
            ("finish", ("finish", str(self.project), "--json")),
        )
        for name, command in commands:
            with self.subTest(name=name):
                result = run_cli(*command)
                self.assertEqual(1, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual("PILOT_STATE_MISSING", payload["code"])
                self.assertIn("state/pilot.json", payload["next_action"])
                self.assertEqual(before, self._project_snapshot())

    # BSC-PILOT-008
    def test_cli_requires_review_after_last_pilot_packet(self) -> None:
        approved = run_cli("pilot", "approve", str(self.project), "--json")
        self.assertEqual(0, approved.returncode, approved.stderr)
        self._complete_pilot()

        before = (self.project / "state/pilot.json").read_bytes()
        result = run_cli("next", str(self.project), "--json")

        self.assertEqual(2, result.returncode)
        self.assertEqual("PILOT_REVIEW_REQUIRED", json.loads(result.stdout)["code"])
        self.assertEqual(before, (self.project / "state/pilot.json").read_bytes())
        status = json.loads(
            run_cli("pilot", "status", str(self.project), "--json").stdout
        )
        self.assertEqual("pilot_review_required", status["status"])
        self.assertNotIn("workflow_phase", status)
        self.assertTrue(status["next_action"])

    # BSC-PILOT-009
    def test_accept_requires_confirm_then_unlocks_full_scope(self) -> None:
        run_cli("pilot", "approve", str(self.project), "--json")
        pilot_response = self._complete_pilot()
        before = (self.project / "state/pilot.json").read_bytes()

        rejected = run_cli("pilot", "accept", str(self.project), "--json")

        self.assertEqual(1, rejected.returncode)
        self.assertEqual("PILOT_CONFIRMATION_REQUIRED", json.loads(rejected.stdout)["code"])
        self.assertEqual(before, (self.project / "state/pilot.json").read_bytes())

        accepted = run_cli(
            "pilot", "accept", str(self.project), "--confirm", "--json"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        accepted_payload = json.loads(accepted.stdout)
        self.assertEqual("full_active", accepted_payload["status"])
        self.assertNotIn("workflow_phase", accepted_payload)
        self.assertTrue(accepted_payload["next_action"])

        cache_path = self.project / "cache/translations.json"
        cache_before_replay = cache_path.read_bytes()
        replay = run_cli(
            "apply", str(self.project), str(pilot_response), "--json"
        )
        self.assertEqual(1, replay.returncode)
        self.assertEqual("RESPONSE_PACKET_STALE", json.loads(replay.stdout)["code"])
        self.assertEqual(cache_before_replay, cache_path.read_bytes())

        next_result = run_cli("next", str(self.project), "--json")
        self.assertEqual(0, next_result.returncode, next_result.stderr)
        self.assertNotEqual(
            "OEBPS/text/chapter.xhtml",
            json.loads(next_result.stdout)["source_document"],
        )

    # BSC-PILOT-010
    def test_completed_pilot_can_be_revised_before_acceptance_but_not_after(self) -> None:
        run_cli("pilot", "approve", str(self.project), "--json")
        response_path = self._complete_pilot()
        response = json.loads(response_path.read_text(encoding="utf-8"))
        response["translations"][0]["translation"] = "Bản dịch pilot đã hiệu đính"
        atomic_write_json(response_path, response)

        revised = run_cli(
            "pilot", "revise", str(self.project), str(response_path), "--json"
        )

        self.assertEqual(0, revised.returncode, revised.stderr)
        self.assertEqual(1, json.loads(revised.stdout)["revised"])
        cache_path = self.project / "cache/translations.json"
        self.assertIn(
            "Bản dịch pilot đã hiệu đính",
            cache_path.read_text(encoding="utf-8"),
        )

        accepted = run_cli(
            "pilot", "accept", str(self.project), "--confirm", "--json"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        before = cache_path.read_bytes()
        blocked = run_cli(
            "pilot", "revise", str(self.project), str(response_path), "--json"
        )
        self.assertEqual(1, blocked.returncode)
        self.assertEqual("PILOT_REVISION_LOCKED", json.loads(blocked.stdout)["code"])
        self.assertEqual(before, cache_path.read_bytes())

    def test_pilot_revision_cannot_add_an_untranslated_row(self) -> None:
        run_cli("pilot", "approve", str(self.project), "--json")
        packet_result = run_cli("next", str(self.project), "--json")
        self.assertEqual(0, packet_result.returncode, packet_result.stderr)
        packet = json.loads(packet_result.stdout)
        first = packet["blocks"][0]
        response_path = self.workspace / "partial-pilot.json"
        atomic_write_json(
            response_path,
            {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": [
                    {
                        "block_index": first["block_index"],
                        "source_sha256": first["source_sha256"],
                        "translation": "Bản dịch đầu tiên",
                    }
                ],
            },
        )
        applied = run_cli("apply", str(self.project), str(response_path), "--json")
        self.assertEqual(0, applied.returncode, applied.stderr)
        cache_path = self.project / "cache/translations.json"
        before = cache_path.read_bytes()

        fresh_result = run_cli("next", str(self.project), "--json")
        self.assertEqual(0, fresh_result.returncode, fresh_result.stderr)
        fresh_packet = json.loads(fresh_result.stdout)
        untranslated = fresh_packet["blocks"][0]
        response = {
            "schema_version": 1,
            "packet_id": fresh_packet["packet_id"],
            "source_document": fresh_packet["source_document"],
            "translations": [
            {
                "block_index": untranslated["block_index"],
                "source_sha256": untranslated["source_sha256"],
                "translation": "Không được thêm qua revise",
            }
            ],
        }
        atomic_write_json(response_path, response)
        rejected = run_cli(
            "pilot", "revise", str(self.project), str(response_path), "--json"
        )

        self.assertEqual(1, rejected.returncode)
        self.assertEqual(
            "CACHE_REPLACEMENT_MISSING", json.loads(rejected.stdout)["code"]
        )
        self.assertEqual(before, cache_path.read_bytes())

    def test_pilot_revision_rejects_symlinked_cache_without_external_mutation(self) -> None:
        run_cli("pilot", "approve", str(self.project), "--json")
        response_path = self._complete_pilot()
        response = json.loads(response_path.read_text(encoding="utf-8"))
        response["translations"][0]["translation"] = "Bản sửa không được thoát project"
        atomic_write_json(response_path, response)

        cache_directory = self.project / "cache"
        external_cache = self.workspace / "external-cache"
        cache_directory.rename(external_cache)
        cache_directory.symlink_to(external_cache, target_is_directory=True)
        external_file = external_cache / "translations.json"
        before = external_file.read_bytes()

        rejected = run_cli(
            "pilot", "revise", str(self.project), str(response_path), "--json"
        )

        self.assertEqual(1, rejected.returncode)
        self.assertEqual(
            "PROJECT_DIRECTORY_PATH_INVALID",
            json.loads(rejected.stdout)["code"],
        )
        self.assertEqual(before, external_file.read_bytes())

    def test_old_packet_is_rejected_after_glossary_context_changes(self) -> None:
        run_cli("pilot", "approve", str(self.project), "--json")
        packet_result = run_cli("next", str(self.project), "--json")
        self.assertEqual(0, packet_result.returncode, packet_result.stderr)
        packet = json.loads(packet_result.stdout)
        response_path = self.workspace / "stale-glossary-response.json"
        atomic_write_json(
            response_path,
            {
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
            },
        )
        with (self.project / "glossary.md").open("a", encoding="utf-8") as glossary:
            glossary.write("| primary action | hành động chính | binding term |\n")

        refreshed = run_cli("next", str(self.project), "--json")
        rejected = run_cli(
            "apply", str(self.project), str(response_path), "--json"
        )

        self.assertEqual(0, refreshed.returncode, refreshed.stderr)
        self.assertNotEqual(packet["packet_id"], json.loads(refreshed.stdout)["packet_id"])
        self.assertEqual(1, rejected.returncode)
        self.assertEqual("RESPONSE_PACKET_STALE", json.loads(rejected.stdout)["code"])
        self.assertFalse((self.project / "cache/translations.json").exists())

    def test_changed_prompt_requires_fresh_pilot_packets_before_acceptance(self) -> None:
        run_cli("pilot", "approve", str(self.project), "--json")
        original_response = self._complete_pilot()
        original_packet_id = json.loads(
            original_response.read_text(encoding="utf-8")
        )["packet_id"]
        config_path = self.project / "bookstudio.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'prompt_version = "1"', 'prompt_version = "2"'
            ),
            encoding="utf-8",
        )

        status = run_cli("pilot", "status", str(self.project), "--json")
        blocked_accept = run_cli(
            "pilot", "accept", str(self.project), "--confirm", "--json"
        )
        refreshed = run_cli("next", str(self.project), "--json")

        self.assertEqual(0, status.returncode, status.stderr)
        self.assertEqual("pilot_active", json.loads(status.stdout)["status"])
        self.assertEqual(0, json.loads(status.stdout)["translated_blocks"])
        self.assertEqual(1, blocked_accept.returncode)
        self.assertEqual("PILOT_INCOMPLETE", json.loads(blocked_accept.stdout)["code"])
        self.assertEqual(0, refreshed.returncode, refreshed.stderr)
        packet = json.loads(refreshed.stdout)
        self.assertNotEqual(original_packet_id, packet["packet_id"])

        refreshed_response = self.workspace / "refreshed-prompt-response.json"
        atomic_write_json(
            refreshed_response,
            {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": [
                    {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": f"Bản dịch đã rà soát {block['block_index']}",
                    }
                    for block in packet["blocks"]
                ],
            },
        )
        revised = run_cli(
            "pilot", "revise", str(self.project), str(refreshed_response), "--json"
        )
        accepted = run_cli(
            "pilot", "accept", str(self.project), "--confirm", "--json"
        )

        self.assertEqual(0, revised.returncode, revised.stderr)
        self.assertGreater(json.loads(revised.stdout)["revised"], 0)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("full_active", json.loads(accepted.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
