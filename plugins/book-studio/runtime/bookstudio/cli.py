"""Command-line interface for Book Studio."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Collection

from . import __version__
from .config import ProjectConfig, atomic_write_json, load_config
from .epub.extract import extract_block_map
from .epub.build import build_epub, finish_project
from .epub.edits import capture_edits
from .epub.inspect import inspect_epub
from .epub.validate import validate_epub
from .errors import BookStudioError, error_payload
from .intake import load_intake_answers
from .pilot import (
    accept_pilot,
    approve_pilot,
    pilot_scope_identity,
    pilot_receipt,
    require_translation_scope,
)
from .pdf.source import inspect_pdf, pdf_tool_status, prepare_pdf
from .project import init_project, start_project
from .review import write_review
from .safety.public_audit import audit_public_tree
from .translation.coverage import coverage_receipt
from .translation.drafts import apply_drafts
from .translation.packets import apply_response, next_packet, revise_pilot_response


BEGINNER_COMMANDS = ("doctor", "start", "init", "next", "apply", "apply-drafts", "finish", "review")
EXPERT_COMMANDS = (
    "inspect",
    "prepare",
    "status",
    "build",
    "verify",
    "release",
    "public-audit",
)

COMMAND_HELP = {
    "doctor": "Check whether the local runtime can run Book Studio.",
    "start": "Start a guided translation project.",
    "init": "Create an expert full-scope translation project.",
    "next": "Emit the next bounded translation packet.",
    "apply": "Validate and apply one AI translation response.",
    "apply-drafts": "Apply prepared drafts packet by packet through the same gates.",
    "finish": "Run the strict reproducible final-book gate.",
    "review": "Write a read-only HTML review page for the project.",
    "inspect": "Inspect a source EPUB and record safe structural facts.",
    "prepare": "Extract the stable source block map and coverage scope.",
    "status": "Check strict translation coverage.",
    "build": "Build a local EPUB candidate.",
    "verify": "Validate the current EPUB output independently.",
    "release": "Alias for the local finish gate; it does not publish.",
    "public-audit": "Check that a source tree is safe to share.",
}

PILOT_COMMAND_HELP = {
    "status": "Show the current pilot gate and next action.",
    "approve": "Approve the proposed pilot scope for translation.",
    "revise": "Revise translated pilot blocks before acceptance.",
    "accept": "Accept a completed pilot and unlock full scope.",
}


def render_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    message = str(payload.get("message") or payload.get("status") or "")
    if message:
        print(message)
    for index, question in enumerate(payload.get("questions", []), start=1):
        if isinstance(question, dict) and question.get("prompt"):
            question_id = question.get("id")
            id_label = f"[{question_id}] " if question_id else ""
            print(f"{index}. {id_label}{question['prompt']}")
            accepted_values = question.get("accepted_values")
            if isinstance(accepted_values, list) and accepted_values:
                print(f"   Choices: {', '.join(str(value) for value in accepted_values)}")
            if question.get("recommendation") is not None:
                print(f"   Recommended: {question['recommendation']}")
    if payload.get("next_action"):
        print(f"Next action: {payload['next_action']}")


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookstudio",
        description="Prepare PDF sources, then translate, build, and verify EPUB projects.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in BEGINNER_COMMANDS + EXPERT_COMMANDS:
        command = subparsers.add_parser(
            name,
            help=COMMAND_HELP[name],
            description=COMMAND_HELP[name],
        )
        _add_json_flag(command)
        if name in {
            "start",
            "init",
            "next",
            "finish",
            "inspect",
            "prepare",
            "status",
            "build",
            "verify",
            "release",
            "review",
        }:
            project_help = (
                "Private project directory to create or resume."
                if name == "start"
                else "Private Book Studio project directory."
            )
            command.add_argument("project", type=Path, help=project_help)
        if name == "start":
            command.add_argument(
                "--source",
                required=True,
                type=Path,
                help="Source EPUB; it is opened read-only.",
            )
            command.add_argument(
                "--answers",
                type=Path,
                help="JSON file keyed by the reported question IDs.",
            )
        if name == "init":
            command.add_argument("--source", required=True, type=Path)
            command.add_argument("--target", required=True, dest="target_language")
            command.add_argument("--source-language", default="en")
            command.add_argument(
                "--output-mode",
                choices=("target_only", "bilingual", "vi_only"),
                default="target_only",
            )
            command.add_argument("--slug")
            command.add_argument("--max-blocks", type=int, default=40)
        if name == "apply-drafts":
            command.add_argument("project", type=Path, help="Private Book Studio project directory.")
            command.add_argument("drafts", type=Path, help="Drafts JSON keyed by source document and block.")
        if name == "apply":
            command.add_argument(
                "project", type=Path, help="Private Book Studio project directory."
            )
            command.add_argument(
                "response", type=Path, help="AI response JSON file."
            )
        if name == "public-audit":
            command.add_argument("root", nargs="?", type=Path, default=Path.cwd())

    packet = subparsers.add_parser(
        "packet",
        help="Use explicit packet next/apply compatibility commands.",
        description="Use explicit packet next/apply compatibility commands.",
    )
    packet_commands = packet.add_subparsers(dest="packet_command", required=True)
    packet_next = packet_commands.add_parser(
        "next",
        help=COMMAND_HELP["next"],
        description=COMMAND_HELP["next"],
    )
    packet_next.add_argument(
        "project", type=Path, help="Private Book Studio project directory."
    )
    _add_json_flag(packet_next)
    packet_apply = packet_commands.add_parser(
        "apply",
        help=COMMAND_HELP["apply"],
        description=COMMAND_HELP["apply"],
    )
    packet_apply.add_argument(
        "project", type=Path, help="Private Book Studio project directory."
    )
    packet_apply.add_argument("response", type=Path, help="AI response JSON file.")
    _add_json_flag(packet_apply)

    pilot = subparsers.add_parser(
        "pilot",
        help="Review and advance the representative pilot gate.",
        description="Review and advance the representative pilot gate.",
    )
    pilot_commands = pilot.add_subparsers(dest="pilot_command", required=True)
    for name in ("status", "approve", "revise", "accept"):
        pilot_command = pilot_commands.add_parser(
            name,
            help=PILOT_COMMAND_HELP[name],
            description=PILOT_COMMAND_HELP[name],
        )
        pilot_command.add_argument(
            "project", type=Path, help="Private Book Studio project directory."
        )
        if name == "accept":
            pilot_command.add_argument(
                "--confirm",
                action="store_true",
                help="Confirm that the completed pilot was reviewed.",
            )
        if name == "revise":
            pilot_command.add_argument(
                "response", type=Path, help="Corrected AI response JSON file."
            )
        _add_json_flag(pilot_command)

    edits = subparsers.add_parser(
        "edits",
        help="Capture post-build edits into edits.json.",
        description="Capture post-build edits into edits.json.",
    )
    edits_commands = edits.add_subparsers(dest="edits_command", required=True)
    edits_capture = edits_commands.add_parser(
        "capture",
        help="Write edits.json from an EPUB edited outside Book Studio.",
        description="Write edits.json from an EPUB edited outside Book Studio.",
    )
    edits_capture.add_argument("project", type=Path, help="Private Book Studio project directory.")
    edits_capture.add_argument("--from", dest="edited", required=True, type=Path, help="Edited EPUB; opened read-only.")
    _add_json_flag(edits_capture)

    pdf = subparsers.add_parser(
        "pdf",
        help="Inspect or prepare a PDF source for the EPUB workflow.",
        description="Inspect or prepare a PDF source for the EPUB workflow.",
    )
    pdf_commands = pdf.add_subparsers(dest="pdf_command", required=True)
    pdf_inspect = pdf_commands.add_parser(
        "inspect",
        help="Classify the PDF text layer without exposing extracted prose.",
        description="Classify the PDF text layer without exposing extracted prose.",
    )
    pdf_inspect.add_argument("source", type=Path, help="Read-only PDF source.")
    _add_json_flag(pdf_inspect)
    pdf_prepare = pdf_commands.add_parser(
        "prepare",
        help="Create a semantic, review-gated EPUB from a text-layer PDF.",
        description="Create a semantic, review-gated EPUB from a text-layer PDF.",
    )
    pdf_prepare.add_argument("source", type=Path, help="Read-only PDF source.")
    pdf_prepare.add_argument(
        "--output", required=True, type=Path, help="New prepared EPUB path."
    )
    pdf_prepare.add_argument(
        "--source-language",
        help="Optional BCP-47-like source language such as en or vi.",
    )
    pdf_prepare.add_argument(
        "--title", help="Optional title override for the prepared EPUB metadata."
    )
    _add_json_flag(pdf_prepare)

    return parser


def _workflow_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    status = str(receipt["status"])
    next_actions = {
        "legacy": "Run 'bookstudio next' to continue full-book translation.",
        "pilot_proposed": "Review the proposal, then run 'bookstudio pilot approve PROJECT'.",
        "pilot_active": "Run 'bookstudio next' and apply each pilot response.",
        "pilot_review_required": "Review the completed pilot, then accept it with --confirm.",
        "full_active": "Run 'bookstudio next' to continue full-book translation.",
    }
    return {
        **receipt,
        "next_action": next_actions[status],
    }


def _translation_scope(
    config: ProjectConfig,
) -> tuple[Collection[tuple[str, int]] | None, str | None]:
    receipt = pilot_receipt(config)
    if receipt["status"] == "legacy":
        return None, None
    try:
        allowed_targets = require_translation_scope(config)
    except BookStudioError as error:
        if error.code in {"PILOT_APPROVAL_REQUIRED", "PILOT_REVIEW_REQUIRED"}:
            raise BookStudioError(
                code=error.code,
                message=error.message,
                next_action=error.next_action,
                exit_code=2,
                evidence=error.evidence,
            ) from error
        raise
    return allowed_targets, pilot_scope_identity(receipt)


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "doctor":
        pdf_tools = pdf_tool_status()
        return {
            "status": "pass",
            "message": "Book Studio can run in this Python environment.",
            "python": platform.python_version(),
            "optional_tools": {
                "ebook-convert": shutil.which("ebook-convert") is not None,
                **pdf_tools,
            },
        }
    if args.command == "pdf":
        if args.pdf_command == "inspect":
            receipt = inspect_pdf(args.source)
            return {
                **receipt,
                "message": f"PDF inspection classified the source as {receipt['text']['classification']}.",
            }
        receipt = prepare_pdf(
            args.source,
            args.output,
            source_language=args.source_language,
            title=args.title,
        )
        return {
            **receipt,
            "message": "Prepared EPUB requires source-fidelity review before translation.",
            "_exit_code": 2,
        }
    if args.command == "start":
        payload = start_project(
            args.project,
            args.source,
            load_intake_answers(args.answers),
        )
        if payload.get("questions"):
            payload = {
                **payload,
                "next_action": "Answer the listed questions in a JSON file and rerun start with --answers.",
            }
        return payload
    if args.command == "init":
        created = not (args.project.expanduser().resolve() / ".bookstudio-project").is_file()
        config_path = init_project(
            args.project,
            slug=args.slug or args.project.name,
            source=args.source,
            source_language=args.source_language,
            target_language=args.target_language,
            output_mode=args.output_mode,
            max_blocks=args.max_blocks,
        )
        config = load_config(config_path)
        return {
            "status": "pass",
            "message": "Book Studio project is ready.",
            "created": created,
            "project": args.project.name,
            "config": "bookstudio.toml",
            "slug": config.slug,
        }
    if args.command == "inspect":
        config = load_config(args.project / "bookstudio.toml")
        receipt = inspect_epub(config.source)
        atomic_write_json(config.paths.inspection, receipt)
        return {
            **receipt,
            "message": "EPUB inspection passed.",
            "written": "state/inspection.json",
        }
    if args.command == "prepare":
        config = load_config(args.project / "bookstudio.toml")
        block_map = extract_block_map(config.source)
        block_map_path = config.paths.source_blocks / "full-block-map.json"
        coverage_path = config.paths.source_blocks / "coverage.json"
        coverage = {
            "schema_version": 1,
            "source_sha256": block_map["source"]["sha256"],
            "included_files": [file["source_path"] for file in block_map["files"]],
            "excluded_files": [],
        }
        atomic_write_json(block_map_path, block_map)
        atomic_write_json(coverage_path, coverage)
        return {
            "status": "pass",
            "message": "Stable source blocks are ready.",
            "canonical_targets": block_map["canonical_targets"],
            "written": [
                "source-blocks/full-block-map.json",
                "source-blocks/coverage.json",
            ],
        }
    operation = args.packet_command if args.command == "packet" else args.command
    if operation == "next":
        config = load_config(args.project / "bookstudio.toml")
        allowed_targets, scope_identity = _translation_scope(config)
        packet = next_packet(
            config,
            allowed_targets=allowed_targets,
            scope_identity=scope_identity,
        )
        if packet is None:
            raise BookStudioError(
                code="NO_WORK_REMAINS",
                message="No untranslated eligible blocks remain.",
                next_action="Run 'bookstudio status' or finish the project.",
                exit_code=3,
            )
        atomic_write_json(config.paths.packets / "next.json", packet)
        return {**packet, "message": "The next bounded translation packet is ready."}
    if operation == "apply":
        config = load_config(args.project / "bookstudio.toml")
        allowed_targets, scope_identity = _translation_scope(config)
        return apply_response(
            config,
            args.response,
            allowed_targets=allowed_targets,
            scope_identity=scope_identity,
        )
    if args.command == "pilot":
        config = load_config(args.project / "bookstudio.toml")
        if args.pilot_command == "status":
            payload = _workflow_payload(pilot_receipt(config))
            return {
                **payload,
                "message": f"Workflow status: {payload['status']}.",
            }
        if args.pilot_command == "approve":
            approve_pilot(config)
            return {
                **_workflow_payload(pilot_receipt(config)),
                "message": "Pilot translation is active.",
            }
        if args.pilot_command == "revise":
            return revise_pilot_response(config, args.response)
        accept_pilot(config, confirmed=args.confirm)
        return {
            **_workflow_payload(pilot_receipt(config)),
            "message": "Full-book translation is active.",
        }
    if args.command == "status":
        config = load_config(args.project / "bookstudio.toml")
        receipt = coverage_receipt(config, require_complete=config.require_complete)
        if receipt["status"] == "error":
            raise BookStudioError(
                code="COVERAGE_INVALID",
                message="Translation cache contains invalid coverage records.",
                next_action="Repair the reported cache records before building.",
                evidence=(json.dumps(receipt, sort_keys=True),),
            )
        if not receipt["passed"]:
            return {
                **receipt,
                "code": "PROJECT_INCOMPLETE",
                "message": f"{receipt['remaining']} eligible blocks remain untranslated.",
                "evidence": [],
                "next_action": "Run 'bookstudio next' and apply the response.",
                "_exit_code": 2,
            }
        return {**receipt, "message": "Strict translation coverage passed."}
    if args.command == "build":
        config = load_config(args.project / "bookstudio.toml")
        return build_epub(config, config.paths.output / "build.epub")
    if args.command == "verify":
        config = load_config(args.project / "bookstudio.toml")
        final = config.paths.output / "final.epub"
        candidate = final if final.is_file() else config.paths.output / "build.epub"
        receipt = validate_epub(config, candidate)
        if not receipt["passed"]:
            raise BookStudioError(
                code="INTEGRITY_FAILED",
                message="EPUB failed independent integrity validation.",
                next_action="Review the validation receipt and rebuild after corrections.",
                evidence=(json.dumps(receipt["violations"], sort_keys=True),),
            )
        return {**receipt, "message": "EPUB integrity validation passed."}
    if args.command == "edits":
        return capture_edits(load_config(args.project / "bookstudio.toml"), args.edited)
    if args.command == "apply-drafts":
        config = load_config(args.project / "bookstudio.toml")
        return apply_drafts(config, args.drafts, scope=lambda: _translation_scope(config))
    if args.command == "review":
        return write_review(load_config(args.project / "bookstudio.toml"))
    if args.command in {"finish", "release"}:
        config = load_config(args.project / "bookstudio.toml")
        return finish_project(config)
    if args.command == "public-audit":
        receipt = audit_public_tree(args.root)
        if receipt["passed"]:
            return {**receipt, "message": "Public source-tree boundary passed."}
        return {
            **receipt,
            "code": "PUBLIC_BOUNDARY_FAILED",
            "message": "Public source-tree boundary contains blocked material.",
            "evidence": receipt["violations"],
            "next_action": "Remove or relocate every reported item, then rerun public-audit.",
            "_exit_code": 1,
        }
    raise BookStudioError(
        code="FEATURE_NOT_READY",
        message=f"Command is not implemented yet: {args.command}",
        next_action="Use --help to inspect the v0.1 command surface.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _dispatch(args)
        exit_code = int(payload.pop("_exit_code", 0))
        render_payload(payload, as_json=bool(args.json))
        return exit_code
    except BookStudioError as error:
        payload = error_payload(error)
        if args.json:
            render_payload(payload, as_json=True)
        else:
            print(error.message, file=sys.stderr)
            if error.next_action:
                print(f"Next action: {error.next_action}", file=sys.stderr)
        return error.exit_code
