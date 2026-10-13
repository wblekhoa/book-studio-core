from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bookstudio.mcp_server import APP_MIME, REVIEW_UI, handle
from tests.fixtures import build_synthetic_epub

ROOT = Path(__file__).resolve().parents[1]
ANSWERS = {
    "target_language": "vi",
    "output_mode": "target_only",
    "audience": "synthetic readers",
    "translation_approach": "faithful",
    "market_context_policy": "labeled_selective",
    "layout_policy": "preserve",
}


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        build_synthetic_epub(self.root / "book.epub", include_image=False)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _session(self, calls: list[tuple[str, dict]]) -> list[dict]:
        lines = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        lines += [{"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": args}}
                  for n, (name, args) in enumerate(calls, start=1)]
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", BOOKSTUDIO_PROJECTS_DIR=str(self.root))
        result = subprocess.run([sys.executable, "-m", "bookstudio", "mcp"], input="\n".join(map(json.dumps, lines)) + "\n",
                                capture_output=True, text=True, env=env, cwd=self.root)
        responses = [json.loads(line) for line in result.stdout.splitlines()]  # every stdout line is JSON-RPC
        self.assertEqual(len(calls) + 1, len(responses), result.stderr)
        return [response["result"] for response in responses[1:]]

    # BSC-MCP-001
    def test_protocol_surface_lists_tools_and_the_review_app(self) -> None:
        init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual("2025-06-18", init["result"]["protocolVersion"])
        tools = {tool["name"]: tool for tool in handle({"id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"status", "start", "pilot", "next_packet", "apply_response", "apply_drafts", "review", "finish", "verify", "capture_edits"} <= set(tools))
        self.assertEqual(REVIEW_UI, tools["review"]["_meta"]["ui"]["resourceUri"])
        resources = handle({"id": 3, "method": "resources/list"})["result"]["resources"]
        self.assertEqual([(REVIEW_UI, APP_MIME)], [(r["uri"], r["mimeType"]) for r in resources])
        app = handle({"id": 4, "method": "resources/read", "params": {"uri": REVIEW_UI}})["result"]["contents"][0]
        self.assertEqual(APP_MIME, app["mimeType"])
        self.assertIn("ui/initialize", app["text"])
        self.assertIn("ui/notifications/tool-result", app["text"])
        self.assertNotIn("http", app["text"].split("<script>")[1])
        self.assertEqual(-32601, handle({"id": 5, "method": "nope"})["error"]["code"])
        self.assertIsNone(handle({"method": "notifications/initialized"}))

    # BSC-MCP-002
    def test_guided_flow_through_tools_with_confirmation_gate(self) -> None:
        results = self._session([
            ("start", {"project": "demo", "source": "book.epub"}),
            ("start", {"project": "demo", "source": "book.epub", "answers": ANSWERS}),
            ("pilot", {"project": "demo", "action": "approve"}),
            ("next_packet", {"project": "demo"}),
        ])
        self.assertTrue(results[0]["structuredContent"]["questions"])
        self.assertFalse((self.root / "demo").exists() and results[0]["structuredContent"].get("status") != "needs_input")
        self.assertFalse(results[1]["isError"], results[1])
        packet = results[3]["structuredContent"]
        response = {"schema_version": 1, "packet_id": packet["packet_id"], "source_document": packet["source_document"],
                    "translations": [{"block_index": b["block_index"], "source_sha256": b["source_sha256"], "translation": "Bản dịch"}
                                     for b in packet["blocks"] if b.get("translate", True)]}
        (self.root / "response.json").write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        results = self._session([
            ("apply_response", {"project": "demo", "response_path": "response.json"}),
            ("status", {"project": "demo"}),
            ("pilot", {"project": "demo", "action": "accept"}),
            ("review", {"project": "demo"}),
        ])
        self.assertFalse(results[0]["isError"], results[0])
        self.assertEqual("pilot_review_required", results[1]["structuredContent"]["workflow_status"])
        self.assertTrue(results[2]["isError"])
        self.assertEqual("PILOT_CONFIRMATION_REQUIRED", results[2]["structuredContent"]["code"])
        review = results[3]
        self.assertIn("Bản dịch", review["structuredContent"]["review_html"])
        self.assertNotIn("review_html", review["content"][0]["text"])
        results = self._session([("pilot", {"project": "demo", "action": "accept", "user_confirmed": True})])
        self.assertFalse(results[0]["isError"], results[0])

    # BSC-MCP-003
    def test_errors_are_tool_results_with_stable_codes(self) -> None:
        results = self._session([("status", {"project": "missing"}), ("finish", {}), ("status", {"project": 7})])
        for result in results:
            self.assertTrue(result["isError"])
            self.assertTrue(result["structuredContent"]["code"])


if __name__ == "__main__":
    unittest.main()
