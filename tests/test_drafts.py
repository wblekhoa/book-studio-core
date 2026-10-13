from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_synthetic_epub
from tests.test_e2e import run_cli


ANSWERS = {
    "target_language": "vi",
    "output_mode": "target_only",
    "audience": "synthetic readers",
    "translation_approach": "faithful",
    "market_context_policy": "labeled_selective",
    "layout_policy": "preserve",
}


class DraftApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.source = self.root / "synthetic.epub"
        self.project = self.root / "project"
        build_synthetic_epub(self.source, include_image=False)
        answers = self.root / "answers.json"
        answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
        code, payload = self._cli("start", str(self.project), "--source", str(self.source), "--answers", str(answers))
        self.assertEqual(0, code, payload)
        self.assertEqual(0, self._cli("pilot", "approve", str(self.project))[0])
        block_map = json.loads((self.project / "source-blocks/full-block-map.json").read_text(encoding="utf-8"))
        self.source_sha256 = block_map["source"]["sha256"]
        self.targets = [
            {"source_document": file["source_path"], "block_index": block["block_index"], "source_sha256": block["text_sha256"]}
            for file in block_map["files"]
            for block in file["blocks"]
            if block["canonical"] and not block["watermark"]
        ]

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _cli(self, *args: str) -> tuple[int, dict]:
        result = run_cli(*args, "--json")
        self.assertNotIn(str(self.root), result.stdout)
        return result.returncode, json.loads(result.stdout)

    def _drafts(self, rows: list[dict], *, source_sha256: str | None = None) -> Path:
        path = self.root / "drafts.json"
        payload = {"schema_version": 1, "source_sha256": source_sha256 or self.source_sha256, "drafts": rows}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _rows(self, targets: list[dict] | None = None) -> list[dict]:
        return [{**target, "translation": f"Bản nháp {target['block_index']}"} for target in (targets or self.targets)]

    def _cache_count(self) -> int:
        cache = self.project / "cache/translations.json"
        if not cache.exists():
            return 0
        return sum(len(rows) for rows in json.loads(cache.read_text(encoding="utf-8"))["files"].values())

    # BSC-DRAFT-001
    def test_drafts_stop_at_pilot_review_then_finish_full_book(self) -> None:
        drafts = self._drafts(self._rows())
        code, payload = self._cli("apply-drafts", str(self.project), str(drafts))
        self.assertEqual(0, code, payload)
        self.assertEqual("pilot_review_required", payload["status"])
        self.assertGreater(payload["applied_blocks"], 0)
        self.assertIn("pilot accept", payload["next_action"])
        self.assertEqual(0, self._cli("pilot", "accept", str(self.project), "--confirm")[0])
        code, payload = self._cli("apply-drafts", str(self.project), str(drafts))
        self.assertEqual(0, code, payload)
        self.assertEqual("complete", payload["status"])
        code, status = self._cli("status", str(self.project))
        self.assertEqual(0, code, status)
        self.assertEqual(0, status["remaining"])
        self.assertEqual(0, self._cli("finish", str(self.project))[0])

    # BSC-DRAFT-002
    def test_missing_draft_stops_before_that_packet(self) -> None:
        pilot = json.loads((self.project / "state/pilot.json").read_text(encoding="utf-8"))
        keep = [t for t in self.targets if t["source_document"] != pilot["source_document"]]
        drafts = self._drafts(self._rows(keep))
        code, payload = self._cli("apply-drafts", str(self.project), str(drafts))
        self.assertEqual(2, code, payload)
        self.assertEqual("draft_missing", payload["status"])
        self.assertEqual(0, payload["applied_blocks"])
        self.assertTrue(payload["missing"])
        self.assertEqual(pilot["source_document"], payload["missing"][0]["source_document"])
        self.assertEqual(0, self._cache_count())

    # BSC-DRAFT-003
    def test_stale_or_unknown_drafts_fail_before_any_write(self) -> None:
        rows = self._rows()
        rows[0] = {**rows[0], "source_sha256": "0" * 64}
        code, payload = self._cli("apply-drafts", str(self.project), str(self._drafts(rows)))
        self.assertEqual(1, code)
        self.assertEqual("DRAFT_SOURCE_STALE", payload["code"])
        rows = self._rows() + [{"source_document": "OEBPS/text/none.xhtml", "block_index": 0, "source_sha256": "1" * 64, "translation": "x"}]
        code, payload = self._cli("apply-drafts", str(self.project), str(self._drafts(rows)))
        self.assertEqual("DRAFT_TARGET_UNKNOWN", payload["code"])
        code, payload = self._cli("apply-drafts", str(self.project), str(self._drafts(self._rows(), source_sha256="2" * 64)))
        self.assertEqual("DRAFTS_SOURCE_MISMATCH", payload["code"])
        duplicate = self._rows()
        code, payload = self._cli("apply-drafts", str(self.project), str(self._drafts(duplicate + duplicate[:1])))
        self.assertEqual("DRAFTS_SCHEMA_INVALID", payload["code"])
        self.assertEqual(0, self._cache_count())

    # BSC-DRAFT-004
    def test_unsafe_inline_markup_is_rejected_by_the_packet_gate(self) -> None:
        rows = self._rows()
        rows = [{**row, "translation_xhtml": '<a href="javascript:alert(1)">x</a>'} for row in rows]
        code, payload = self._cli("apply-drafts", str(self.project), str(self._drafts(rows)))
        self.assertEqual(1, code)
        self.assertEqual("XHTML_UNSAFE", payload["code"])
        self.assertEqual(0, self._cache_count())
        rows = self._rows()
        rows[-1] = {**rows[-1], "translation_xhtml": "<script>x</script>"}
        code, payload = self._cli("apply-drafts", str(self.project), str(self._drafts(rows)))
        self.assertEqual(1, code)
        self.assertEqual(0, self._cache_count())


if __name__ == "__main__":
    unittest.main()
