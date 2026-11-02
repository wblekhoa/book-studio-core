from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_synthetic_epub
from tests.test_e2e import run_cli


ANSWERS = {
    "target_language": "vi",
    "output_mode": "bilingual",
    "audience": "synthetic readers",
    "translation_approach": "faithful",
    "market_context_policy": "labeled_selective",
    "layout_policy": "preserve",
    "image_text_policy": "selective",
    "image_annotation_policy": "selective",
}
UNSAFE = '<script>alert("x")</script> & <b>bold</b>'


def _snapshot(project: Path) -> dict[str, str]:
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(project.rglob("*"))
        if path.is_file() and "reports" not in path.relative_to(project).parts
    }


class ReviewPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.source = self.root / "synthetic.epub"
        self.project = self.root / "review-project"
        build_synthetic_epub(self.source, include_image=True)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _cli(self, *args: str) -> tuple[int, dict]:
        result = run_cli(*args, "--json")
        return result.returncode, json.loads(result.stdout)

    def _start_guided(self) -> None:
        answers = self.root / "answers.json"
        answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
        code, payload = self._cli(
            "start", str(self.project), "--source", str(self.source), "--answers", str(answers)
        )
        self.assertEqual(0, code, payload)

    def _translate_pilot(self, translation_for=lambda index: f"Bản dịch {index}") -> None:
        self.assertEqual(0, self._cli("pilot", "approve", str(self.project))[0])
        for number in range(20):
            code, packet = self._cli("next", str(self.project))
            if code != 0:
                self.assertEqual("PILOT_REVIEW_REQUIRED", packet["code"])
                return
            response = {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": [
                    {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": translation_for(block["block_index"]),
                    }
                    for block in packet["blocks"]
                ],
            }
            path = self.root / f"response-{number}.json"
            path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            code, applied = self._cli("apply", str(self.project), str(path))
            self.assertEqual(0, code, applied)
        self.fail("pilot did not reach review")

    def _review(self) -> tuple[dict, str]:
        result = run_cli("review", str(self.project), "--json")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout)
        payload = json.loads(result.stdout)
        page = (self.project / payload["written"]).read_text(encoding="utf-8")
        return payload, page

    # BSC-REVIEW-001
    def test_pilot_review_page_shows_source_and_translation_side_by_side(self) -> None:
        self._start_guided()
        self._translate_pilot()
        payload, page = self._review()
        self.assertEqual("reports/review.html", payload["written"])
        self.assertEqual("pilot_review_required", payload["workflow_status"])
        self.assertEqual(4, payload["translated"])
        self.assertIn("pilot accept", payload["next_command"])
        self.assertIn("--confirm", payload["next_command"])
        self.assertIn("Chapter One", page)
        self.assertIn("Bản dịch 1", page)
        self.assertIn("pilot accept", page)
        self.assertIn("faithful", page)
        self.assertRegex(page, r'class="pair')

    # BSC-REVIEW-002
    def test_review_is_read_only_for_lifecycle_state(self) -> None:
        self._start_guided()
        self._translate_pilot()
        before = _snapshot(self.project)
        self._review()
        self.assertEqual(before, _snapshot(self.project))

    # BSC-REVIEW-003
    def test_book_text_is_escaped_and_page_is_self_contained(self) -> None:
        self._start_guided()
        self._translate_pilot(lambda index: UNSAFE)
        _payload, page = self._review()
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("<b>bold</b>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Content-Security-Policy", page)
        self.assertIsNone(re.search(r'(?:src|href)\s*=\s*"(?:https?:)?//', page))
        self.assertNotIn(str(self.root), page)

    # BSC-REVIEW-004
    def test_proposed_pilot_page_lists_untranslated_targets_and_approve_command(self) -> None:
        self._start_guided()
        payload, page = self._review()
        self.assertEqual("pilot_proposed", payload["workflow_status"])
        self.assertEqual(0, payload["translated"])
        self.assertIn("pilot approve", payload["next_command"])
        self.assertIn("Not translated yet", page)

    # BSC-REVIEW-005
    def test_expert_project_without_pilot_still_renders(self) -> None:
        code, payload = self._cli(
            "init", str(self.project), "--source", str(self.source), "--target", "vi"
        )
        self.assertEqual(0, code, payload)
        self.assertEqual(0, self._cli("prepare", str(self.project))[0])
        payload, page = self._review()
        self.assertEqual("legacy", payload["workflow_status"])
        self.assertIn("bookstudio next", payload["next_command"])
        self.assertIn("<h1", page)

    # BSC-REVIEW-007
    def test_finished_page_reports_gate_and_detects_changed_output(self) -> None:
        self._start_guided()
        self._translate_pilot()
        self.assertEqual(0, self._cli("pilot", "accept", str(self.project), "--confirm")[0])
        for number in range(20):
            code, packet = self._cli("next", str(self.project))
            if code != 0:
                self.assertEqual("NO_WORK_REMAINS", packet["code"])
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
            path = self.root / f"full-{number}.json"
            path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(0, self._cli("apply", str(self.project), str(path))[0])
        self.assertEqual(0, self._cli("finish", str(self.project))[0])
        payload, page = self._review()
        self.assertEqual("finished", payload["workflow_status"])
        self.assertEqual(0, payload["remaining"])
        self.assertIn("bookstudio verify", payload["next_command"])
        self.assertIn("Matches the gate receipt", page)
        self.assertIn("Declared edits</dt><dd>0</dd>", page)

        with (self.project / "output/final.epub").open("ab") as handle:
            handle.write(b"tampered")
        payload, page = self._review()
        self.assertEqual("full_active", payload["workflow_status"])
        self.assertIn("bookstudio finish", payload["next_command"])
        self.assertIn("Changed since the gate ran", page)

    # BSC-REVIEW-008
    def test_invalid_cache_fails_review_instead_of_rendering_zero_progress(self) -> None:
        self._start_guided()
        self._translate_pilot()
        (self.project / "cache" / "translations.json").write_text("{not json", encoding="utf-8")
        result = run_cli("review", str(self.project), "--json")
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(json.loads(result.stdout)["code"])

    # BSC-CHAT-002
    def test_snapshot_reports_review_busy_when_the_project_keeps_changing(self) -> None:
        from unittest.mock import patch

        from bookstudio.config import load_config
        from bookstudio.errors import BookStudioError
        from bookstudio import review

        self._start_guided()
        config = load_config(self.project / "bookstudio.toml")
        watched = config.paths.pilot
        original = review._review_snapshot_once

        def changing(current):
            watched.write_text(watched.read_text(encoding="utf-8") + " ", encoding="utf-8")
            return original(current)

        with patch.object(review, "_review_snapshot_once", side_effect=changing):
            with self.assertRaises(BookStudioError) as raised:
                review.review_snapshot(config)
        self.assertEqual("REVIEW_BUSY", raised.exception.code)

    # BSC-CHAT-011
    def test_mcp_review_reads_one_snapshot_and_omits_the_html_page(self) -> None:
        from unittest.mock import patch

        from bookstudio import mcp_server, review

        self._start_guided()
        self._translate_pilot()
        with patch.object(review, "review_snapshot", wraps=review.review_snapshot) as snapshot:
            result = mcp_server.call_tool("review", {"project": str(self.project)})
        self.assertEqual(1, snapshot.call_count)
        self.assertNotIn("review_html", result)
        self.assertEqual("reports/review.html", result["written"])
        self.assertEqual(result["workflow_status"], result["view"]["stage"])
        self.assertTrue(any("Bản dịch" in pair["translation"] for pair in result["view"]["pairs"]))

    # BSC-REVIEW-006
    def test_missing_project_fails_with_stable_code(self) -> None:
        result = run_cli("review", str(self.root / "missing"), "--json")
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(json.loads(result.stdout)["code"])


if __name__ == "__main__":
    unittest.main()
