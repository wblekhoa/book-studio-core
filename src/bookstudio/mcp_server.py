"""Minimal stdio MCP server exposing the Book Studio CLI as structured tools.

Every tool routes through the same argparse dispatch as the CLI, so gates, error
codes and files written are identical. Newline-delimited JSON-RPC 2.0, stdlib only.
The review tool also declares an experimental MCP Apps view (`ui://`).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from . import __version__
from .errors import BookStudioError, error_payload

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
REVIEW_UI = "ui://book-studio/review.html"
APP_MIME = "text/html;profile=mcp-app"

_PROJECT = {"project": {"type": "string", "description": "Private Book Studio project directory."}}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        **extra,
    }


TOOLS = [
    _tool("doctor", "Check that the bundled engine can run here and which optional PDF tools exist.", {}, []),
    _tool("status", "Read-only stage, progress and exact next command for a project.", _PROJECT, ["project"]),
    _tool(
        "start",
        "Assess a source EPUB and, once every required choice is answered, create a guided project. "
        "Never invent answers: pass only what the user decided.",
        {**_PROJECT, "source": {"type": "string"}, "answers": {"type": "object", "description": "Answers keyed by question id."}},
        ["project", "source"],
    ),
    _tool(
        "pilot",
        "Show, approve, or accept the sample (pilot). Accept only after the user explicitly approved the reviewed sample.",
        {**_PROJECT, "action": {"type": "string", "enum": ["status", "approve", "accept"]}, "user_confirmed": {"type": "boolean"}},
        ["project", "action"],
    ),
    _tool("next_packet", "Emit the next bounded translation packet.", _PROJECT, ["project"]),
    _tool("apply_response", "Validate and apply one translation response JSON file.", {**_PROJECT, "response_path": {"type": "string"}}, ["project", "response_path"]),
    _tool("apply_drafts", "Preflight a drafts file, then apply it packet by packet; stops at the sample review.", {**_PROJECT, "drafts_path": {"type": "string"}}, ["project", "drafts_path"]),
    _tool(
        "review",
        "Write the private read-only review page (sample beside source, progress, next command).",
        _PROJECT,
        ["project"],
        _meta={"ui": {"resourceUri": REVIEW_UI}},
    ),
    _tool("finish", "Run the strict reproducible final gate (applies edits.json).", _PROJECT, ["project"]),
    _tool("verify", "Independently validate the final EPUB.", _PROJECT, ["project"]),
    _tool("capture_edits", "Write edits.json from an EPUB edited elsewhere (never overwrites).", {**_PROJECT, "edited_epub": {"type": "string"}}, ["project", "edited_epub"]),
]

REVIEW_APP = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>Book Studio review</title>
<style>html,body{margin:0;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
#note{padding:12px;color:#6b6a64}</style></head>
<body><p id="note">Waiting for the review page from Book Studio…</p>
<script>
(function () {
  var nextId = 1;
  function send(message) { window.parent.postMessage(Object.assign({ jsonrpc: "2.0" }, message), "*"); }
  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.id === 1 && data.result) { send({ method: "ui/notifications/initialized", params: {} }); return; }
    if (data.method === "ui/notifications/tool-result") {
      var content = (data.params && data.params.structuredContent) || {};
      if (typeof content.review_html === "string") {
        // The page is server-escaped and script-free; DOMParser output never executes scripts.
        var page = new DOMParser().parseFromString(content.review_html, "text/html");
        page.querySelectorAll("style").forEach(function (style) { document.head.appendChild(document.importNode(style, true)); });
        document.body.replaceWith(document.importNode(page.body, true));
        send({ method: "ui/notifications/size-changed", params: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight } });
      } else {
        document.getElementById("note").textContent = content.message || "No review page in this result.";
      }
    }
  });
  send({ id: nextId++, method: "ui/initialize", params: { protocolVersion: "2026-01-26", appInfo: { name: "book-studio-review", version: "%VERSION%" }, appCapabilities: {} } });
})();
</script></body></html>
"""


def _base_dir() -> Path:
    # An unset plugin option may arrive empty or as the literal placeholder; ignore both.
    for key in ("BOOKSTUDIO_PROJECTS_DIR", "CLAUDE_PROJECT_DIR"):
        value = os.environ.get(key, "")
        if value and "${" not in value:
            return Path(value).expanduser()
    return Path.cwd()


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise BookStudioError(code="MCP_ARGUMENT_INVALID", message="A path argument is missing.", next_action="Pass the project or file path.")
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else _base_dir() / path)


def _dispatch(argv: list[str]) -> dict[str, Any]:
    from .cli import _dispatch as cli_dispatch, build_parser

    payload = cli_dispatch(build_parser().parse_args(argv))
    payload.pop("_exit_code", None)
    return payload


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "doctor":
        return _dispatch(["doctor"])
    if name == "status":
        from .config import load_config
        from .review import project_status

        return project_status(load_config(Path(_path(arguments.get("project"))) / "bookstudio.toml"))
    if name == "start":
        from .project import start_project

        answers = arguments.get("answers") or {}
        if not isinstance(answers, dict):
            raise BookStudioError(code="INTAKE_ANSWERS_INVALID", message="Answers must be an object.", next_action="Pass answers keyed by question id.")
        payload = start_project(Path(_path(arguments.get("project"))), Path(_path(arguments.get("source"))), answers)
        payload.pop("_exit_code", None)
        return payload
    if name == "pilot":
        action = arguments.get("action")
        argv = ["pilot", str(action), _path(arguments.get("project"))]
        if action == "accept" and arguments.get("user_confirmed") is True:
            argv.append("--confirm")
        return _dispatch(argv)
    if name == "next_packet":
        return _dispatch(["next", _path(arguments.get("project"))])
    if name == "apply_response":
        return _dispatch(["apply", _path(arguments.get("project")), _path(arguments.get("response_path"))])
    if name == "apply_drafts":
        return _dispatch(["apply-drafts", _path(arguments.get("project")), _path(arguments.get("drafts_path"))])
    if name == "review":
        project = Path(_path(arguments.get("project")))
        payload = _dispatch(["review", str(project)])
        page = project / payload["written"]
        return {**payload, "review_html": page.read_text(encoding="utf-8")}
    if name in {"finish", "verify"}:
        return _dispatch([name, _path(arguments.get("project"))])
    if name == "capture_edits":
        return _dispatch(["edits", "capture", _path(arguments.get("project")), "--from", _path(arguments.get("edited_epub"))])
    raise BookStudioError(code="MCP_TOOL_UNKNOWN", message=f"Unknown tool: {name}", next_action="Call tools/list.")


def _tool_result(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        with contextlib.redirect_stdout(sys.stderr):  # stdout carries JSON-RPC only
            payload = call_tool(name, arguments)
        is_error = False
    except BookStudioError as error:
        payload, is_error = error_payload(error), True
    except SystemExit:
        payload, is_error = {"status": "error", "code": "MCP_ARGUMENT_INVALID", "message": "Invalid arguments."}, True
    visible = {key: value for key, value in payload.items() if key != "review_html"}
    return {
        "content": [{"type": "text", "text": json.dumps(visible, ensure_ascii=False, indent=2)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if request_id is None:
        return None  # notifications (initialized, cancelled) need no reply
    if method == "initialize":
        requested = params.get("protocolVersion")
        result: Any = {
            "protocolVersion": requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "book-studio", "version": __version__},
            "instructions": "Book Studio tools for private, sample-first book translation. Never accept a pilot "
            "without the user's explicit approval; post-build corrections go through edits.json.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        result = _tool_result(str(params.get("name")), arguments)
    elif method == "resources/list":
        result = {"resources": [{"uri": REVIEW_UI, "name": "Book Studio review", "mimeType": APP_MIME}]}
    elif method == "resources/read" and params.get("uri") == REVIEW_UI:
        result = {
            "contents": [
                {
                    "uri": REVIEW_UI,
                    "mimeType": APP_MIME,
                    "text": REVIEW_APP.replace("%VERSION%", __version__),
                    "_meta": {"ui": {"prefersBorder": True}},
                }
            ]
        }
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, log: Callable[[str], None] | None = None) -> int:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            response = handle(message) if isinstance(message, dict) else None
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
