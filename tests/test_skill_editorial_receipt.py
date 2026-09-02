from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


class EditorialReceiptScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.candidate = self.root / "final.epub"
        self.production_brief = self.root / "production-brief.md"
        self.receipt = self.root / "editorial-review.json"
        self.script = (
            Path(__file__).resolve().parents[1]
            / "skills/book-translation/scripts/audit_editorial_receipt.py"
        )
        self.candidate.write_bytes(b"candidate epub bytes")
        self.production_brief.write_text(
            "# Production brief\n\n- Voice: calm and precise\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def payload(self, *, result: str = "pass", status: str = "pass") -> dict:
        checks = {
            "meaning_fidelity": result,
            "logic_and_qualifiers": "pass",
            "target_language_naturalness": "pass",
            "voice_and_register": "pass",
            "terminology": "pass",
            "cross_block_continuity": "pass",
        }
        return {
            "schema_version": 1,
            "candidate": "final.epub",
            "candidate_sha256": hashlib.sha256(self.candidate.read_bytes()).hexdigest(),
            "production_brief_sha256": hashlib.sha256(
                self.production_brief.read_bytes()
            ).hexdigest(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_kind": "self",
            "samples": [
                {
                    "source_document": "text/chapter.xhtml",
                    "location": "blocks 10-14, cross-packet boundary",
                    "content_mode": "argument",
                    "checks": checks,
                    "note": "Meaning and target-only reading were reviewed.",
                }
            ],
            "whole_book_checks": {
                "source_term_introductions": "pass",
                "author_vs_added_context": "pass",
                "register_consistency": "pass",
            },
            "coverage_checks": {
                "front_matter_inventory": "pass",
                "front_matter_prose": "pass",
                "front_matter_image_text": "pass",
                "opening_voice": "pass",
                "difficult_passage": "pass",
                "material_content_modes": "pass",
                "cross_packet_boundary": "pass",
                "terminology_heavy_passage": "pass",
                "ending_voice": "pass",
            },
            "findings": [],
            "status": status,
        }

    def run_script(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--candidate",
                str(self.candidate),
                "--production-brief",
                str(self.production_brief),
                "--receipt",
                str(self.receipt),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_passes_candidate_bound_independent_criteria(self) -> None:
        self.receipt.write_text(json.dumps(self.payload()), encoding="utf-8")

        result = self.run_script()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("pass", report["status"])
        self.assertTrue(report["passed"])
        self.assertEqual(1, report["samples_reviewed"])
        self.assertEqual(18, report["hard_checks"])

    def test_fail_and_unknown_cannot_hide_behind_pass_status(self) -> None:
        for criterion_result, declared_status in (("fail", "pass"), ("unknown", "pass")):
            with self.subTest(result=criterion_result):
                self.receipt.write_text(
                    json.dumps(
                        self.payload(result=criterion_result, status=declared_status)
                    ),
                    encoding="utf-8",
                )

                result = self.run_script()

                self.assertEqual(1, result.returncode)
                report = json.loads(result.stdout)
                self.assertEqual("error", report["status"])
                self.assertEqual("EDITORIAL_RECEIPT_INVALID", report["code"])

    def test_fail_and_unknown_remain_valid_nonpassing_receipts(self) -> None:
        for criterion_result, declared_status in (
            ("fail", "fail"),
            ("unknown", "incomplete"),
        ):
            with self.subTest(result=criterion_result):
                self.receipt.write_text(
                    json.dumps(
                        self.payload(
                            result=criterion_result, status=declared_status
                        )
                    ),
                    encoding="utf-8",
                )

                result = self.run_script()

                self.assertEqual(1, result.returncode)
                report = json.loads(result.stdout)
                self.assertEqual(declared_status, report["status"])
                self.assertFalse(report["passed"])
                self.assertNotIn("code", report)

    def test_stale_candidate_and_extra_schema_fields_fail_closed(self) -> None:
        stale = self.payload()
        stale["candidate_sha256"] = "0" * 64
        self.receipt.write_text(json.dumps(stale), encoding="utf-8")
        stale_result = self.run_script()

        extra = self.payload()
        extra["overall_score"] = 100
        self.receipt.write_text(json.dumps(extra), encoding="utf-8")
        extra_result = self.run_script()

        for result in (stale_result, extra_result):
            self.assertEqual(1, result.returncode)
            report = json.loads(result.stdout)
            self.assertFalse(report["passed"])
            self.assertEqual("EDITORIAL_RECEIPT_INVALID", report["code"])

    def test_receipt_binds_paths_brief_timestamp_and_review_coverage(self) -> None:
        cases = []

        wrong_candidate = self.payload()
        wrong_candidate["candidate"] = "another.epub"
        cases.append(wrong_candidate)

        stale_brief = self.payload()
        stale_brief["production_brief_sha256"] = "0" * 64
        cases.append(stale_brief)

        invalid_timestamp = self.payload()
        invalid_timestamp["reviewed_at"] = "not-an-iso-date"
        cases.append(invalid_timestamp)

        invalid_content_mode = self.payload()
        invalid_content_mode["samples"][0]["content_mode"] = "not-a-real-mode"
        cases.append(invalid_content_mode)

        hidden_gap = self.payload()
        hidden_gap["coverage_checks"]["ending_voice"] = "unknown"
        cases.append(hidden_gap)

        for payload in cases:
            with self.subTest(payload=payload):
                self.receipt.write_text(json.dumps(payload), encoding="utf-8")

                result = self.run_script()

                self.assertEqual(1, result.returncode)
                report = json.loads(result.stdout)
                self.assertFalse(report["passed"])
                self.assertEqual("EDITORIAL_RECEIPT_INVALID", report["code"])


if __name__ == "__main__":
    unittest.main()
