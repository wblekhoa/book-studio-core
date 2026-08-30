from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

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


class SyntheticCliEndToEndTests(unittest.TestCase):
    def test_complete_guided_pilot_gated_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            source = temp_root / "guided-synthetic.epub"
            project = temp_root / "guided-project"
            answers = temp_root / "answers.json"
            build_synthetic_epub(source, include_image=False)

            missing = run_cli(
                "start", str(project), "--source", str(source), "--json"
            )
            self.assertEqual(2, missing.returncode, missing.stderr)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual("needs_input", missing_payload["status"])
            missing_ids = {question["id"] for question in missing_payload["questions"]}
            self.assertNotIn("source_language", missing_ids)
            self.assertNotIn("image_text_policy", missing_ids)
            self.assertNotIn("image_annotation_policy", missing_ids)
            self.assertFalse(project.exists())

            answers.write_text(
                json.dumps(
                    {
                        "target_language": "vi",
                        "output_mode": "target_only",
                        "audience": "synthetic readers",
                        "translation_approach": "faithful",
                        "market_context_policy": "labeled_selective",
                        "layout_policy": "preserve",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            started = run_cli(
                "start",
                str(project),
                "--source",
                str(source),
                "--answers",
                str(answers),
                "--json",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            started_payload = json.loads(started.stdout)
            self.assertEqual(
                "pilot_proposed", started_payload.get("workflow_status")
            )
            pilot = json.loads(
                (project / "state/pilot.json").read_text(encoding="utf-8")
            )
            self.assertEqual("OEBPS/text/chapter.xhtml", pilot["source_document"])

            approved = run_cli("pilot", "approve", str(project), "--json")
            self.assertEqual(0, approved.returncode, approved.stderr)

            response_index = 0
            emitted_pilot_targets: list[tuple[int, str]] = []

            def apply_packet(packet: dict[str, object]) -> None:
                nonlocal response_index
                translations = []
                for raw_block in packet["blocks"]:
                    block = dict(raw_block)
                    row = {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": f"Synthetic translation {block['block_index']}",
                    }
                    if "One note" in str(block["text"]):
                        row["translation_xhtml"] = (
                            'Synthetic primary action. <a href="#note-1">Synthetic note</a>.'
                        )
                    translations.append(row)
                response = {
                    "schema_version": 1,
                    "packet_id": packet["packet_id"],
                    "source_document": packet["source_document"],
                    "translations": translations,
                }
                response_path = temp_root / f"guided-response-{response_index}.json"
                response_path.write_text(
                    json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                applied = run_cli(
                    "apply", str(project), str(response_path), "--json"
                )
                self.assertEqual(0, applied.returncode, applied.stderr)
                response_index += 1

            while True:
                next_pilot = run_cli("next", str(project), "--json")
                if next_pilot.returncode == 2:
                    self.assertEqual(
                        "PILOT_REVIEW_REQUIRED",
                        json.loads(next_pilot.stdout)["code"],
                    )
                    break
                self.assertEqual(0, next_pilot.returncode, next_pilot.stderr)
                packet = json.loads(next_pilot.stdout)
                self.assertEqual(pilot["source_document"], packet["source_document"])
                self.assertTrue(
                    all(
                        block["source_path"] == pilot["source_document"]
                        for block in packet["blocks"]
                    )
                )
                emitted_pilot_targets.extend(
                    (block["block_index"], block["source_sha256"])
                    for block in packet["blocks"]
                )
                apply_packet(packet)

            self.assertEqual(
                [
                    (target["block_index"], target["source_sha256"])
                    for target in pilot["targets"]
                ],
                emitted_pilot_targets,
            )

            blocked_finish = run_cli("finish", str(project), "--json")
            self.assertEqual(1, blocked_finish.returncode)
            self.assertEqual(
                "PILOT_FULL_SCOPE_BLOCKED",
                json.loads(blocked_finish.stdout)["code"],
            )
            unconfirmed = run_cli("pilot", "accept", str(project), "--json")
            self.assertEqual(1, unconfirmed.returncode)
            self.assertEqual(
                "PILOT_CONFIRMATION_REQUIRED",
                json.loads(unconfirmed.stdout)["code"],
            )
            accepted = run_cli(
                "pilot", "accept", str(project), "--confirm", "--json"
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)

            while True:
                next_remaining = run_cli("next", str(project), "--json")
                if next_remaining.returncode == 3:
                    self.assertEqual(
                        "NO_WORK_REMAINS",
                        json.loads(next_remaining.stdout)["code"],
                    )
                    break
                self.assertEqual(0, next_remaining.returncode, next_remaining.stderr)
                apply_packet(json.loads(next_remaining.stdout))

            status = run_cli("status", str(project), "--json")
            finish = run_cli("finish", str(project), "--json")
            verify = run_cli("verify", str(project), "--json")
            for result in (status, finish, verify):
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertNotIn(str(temp_root), result.stdout)
            self.assertTrue(json.loads(status.stdout)["passed"])
            self.assertTrue(json.loads(finish.stdout)["reproducible"])
            self.assertTrue(json.loads(verify.stdout)["passed"])

    def test_complete_provider_neutral_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            source = temp_root / "synthetic.epub"
            project = temp_root / "project"
            build_synthetic_epub(source)

            commands = [run_cli("doctor", "--json")]
            commands.append(
                run_cli(
                    "init",
                    str(project),
                    "--source",
                    str(source),
                    "--target",
                    "vi",
                    "--output-mode",
                    "vi_only",
                    "--max-blocks",
                    "2",
                    "--json",
                )
            )
            commands.append(run_cli("inspect", str(project), "--json"))
            commands.append(run_cli("prepare", str(project), "--json"))
            for result in commands:
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(json.loads(result.stdout)["status"], {"pass", "ok"})
                self.assertNotIn(str(temp_root), result.stdout)
                self.assertNotIn(str(temp_root.resolve()), result.stdout)

            coverage_path = project / "source-blocks/coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["excluded_files"] = ["OEBPS/text/legal.xhtml"]
            coverage_path.write_text(
                json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with zipfile.ZipFile(source) as archive:
                original_image = archive.read("OEBPS/images/pixel.png")
            companion = project / "assets/localized/pixel-vi.png"
            companion.write_bytes(original_image)
            (project / "assets/image-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "images": [
                            {
                                "source_path": "OEBPS/images/pixel.png",
                                "policy": "original_plus_companion",
                                "companion": "assets/localized/pixel-vi.png",
                                "annotation": "Ảnh tổng hợp dùng để kiểm thử.",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            response_index = 0
            while True:
                next_result = run_cli("next", str(project), "--json")
                if next_result.returncode == 3:
                    self.assertEqual("NO_WORK_REMAINS", json.loads(next_result.stdout)["code"])
                    break
                self.assertEqual(0, next_result.returncode, next_result.stderr)
                packet = json.loads(next_result.stdout)
                rows = []
                for block in packet["blocks"]:
                    row = {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": f"Bản dịch tổng hợp {block['block_index']}",
                    }
                    if "One note" in block["text"]:
                        row["translation_xhtml"] = (
                            'Người đọc cần thấy rõ hành động chính. '
                            '<a href="#note-1">Xem ghi chú</a>.'
                        )
                    rows.append(row)
                response = {
                    "schema_version": 1,
                    "packet_id": packet["packet_id"],
                    "source_document": packet["source_document"],
                    "translations": rows,
                }
                response_path = temp_root / f"response-{response_index}.json"
                response_path.write_text(
                    json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                apply_result = run_cli(
                    "apply", str(project), str(response_path), "--json"
                )
                self.assertEqual(0, apply_result.returncode, apply_result.stderr)
                self.assertNotIn(str(temp_root), apply_result.stdout)
                response_index += 1

            status = run_cli("status", str(project), "--json")
            finish = run_cli("finish", str(project), "--json")
            verify = run_cli("verify", str(project), "--json")
            rebuild = run_cli("build", str(project), "--json")
            for result in (status, finish, verify, rebuild):
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertNotIn(str(temp_root), result.stdout)
                self.assertNotIn(str(temp_root.resolve()), result.stdout)

            status_payload = json.loads(status.stdout)
            finish_payload = json.loads(finish.stdout)
            verify_payload = json.loads(verify.stdout)
            self.assertTrue(status_payload["passed"])
            self.assertTrue(finish_payload["reproducible"])
            self.assertTrue(verify_payload["passed"])
            final = project / "output/final.epub"
            built = project / "output/build.epub"
            self.assertEqual(final.read_bytes(), built.read_bytes())
            self.assertEqual(
                finish_payload["output_sha256"],
                json.loads(rebuild.stdout)["output_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
