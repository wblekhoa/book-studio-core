"""Apply prepared whole-book drafts through the normal bounded packet contract."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Collection

from ..config import ProjectConfig, atomic_write_json
from ..errors import BookStudioError
from ..safety.xhtml import validate_inline_xhtml
from .cache import read_json
from .coverage import target_index
from .packets import apply_response, next_packet


_ROW_REQUIRED = {"source_document", "block_index", "source_sha256", "translation"}
_ROW_OPTIONAL = {"translation_xhtml", "note"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
MISSING_REPORT_LIMIT = 20
Scope = Callable[[], tuple[Collection[tuple[str, int]] | None, str | None]]


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _schema(message: str) -> BookStudioError:
    return _fail(
        "DRAFTS_SCHEMA_INVALID",
        message,
        "Use schema_version 1, the project source_sha256, and one row per block with source_document, "
        "block_index, source_sha256 and translation.",
    )


def load_drafts(config: ProjectConfig, path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Validate the whole drafts file against current targets before anything is applied."""
    payload = read_json(path, missing_code="DRAFTS_MISSING", invalid_code="DRAFTS_JSON_INVALID")
    if (
        type(payload) is not dict
        or not {"schema_version", "source_sha256", "drafts"} <= set(payload)
        or set(payload) - {"schema_version", "source_sha256", "drafts", "note"}
        or payload.get("schema_version") != 1
        or type(payload.get("drafts")) is not list
    ):
        raise _schema("Drafts must contain schema_version 1, source_sha256 and a drafts list.")
    targets, _, block_map = target_index(config)
    if payload["source_sha256"] != block_map.get("source", {}).get("sha256"):
        raise _fail(
            "DRAFTS_SOURCE_MISMATCH",
            "Drafts were prepared for a different source EPUB.",
            "Prepare drafts from this project's current source block map.",
        )
    drafts: dict[tuple[str, int], dict[str, Any]] = {}
    for number, row in enumerate(payload["drafts"]):
        keys = set(row) if type(row) is dict else set()
        if (
            not _ROW_REQUIRED <= keys
            or keys - _ROW_REQUIRED - _ROW_OPTIONAL
            or type(row.get("source_document")) is not str
            or type(row.get("block_index")) is not int
            or type(row.get("source_sha256")) is not str
            or not _SHA256.fullmatch(row["source_sha256"])
            or type(row.get("translation")) is not str
            or not row["translation"].strip()
            or ("translation_xhtml" in row and type(row["translation_xhtml"]) is not str)
        ):
            raise _schema(f"Draft row {number} does not match the row contract.")
        key = (row["source_document"], row["block_index"])
        if key in drafts:
            raise _schema(f"Draft row {number} repeats {key[0]} block {key[1]}.")
        target = targets.get(key)
        if target is None:
            raise _fail(
                "DRAFT_TARGET_UNKNOWN",
                f"Draft row {number} is not an eligible block: {key[0]} block {key[1]}.",
                "Remove drafts for excluded, non-canonical or unknown blocks.",
            )
        if target.get("text_sha256") != row["source_sha256"]:
            raise _fail(
                "DRAFT_SOURCE_STALE",
                f"Draft row {number} was written for different source text: {key[0]} block {key[1]}.",
                "Re-draft the block from the current source block map.",
            )
        if "translation_xhtml" in row:
            validate_inline_xhtml(row["translation_xhtml"])
        drafts[key] = row
    return drafts


def apply_drafts(config: ProjectConfig, path: Path, *, scope: Scope) -> dict[str, Any]:
    drafts = load_drafts(config, path)
    applied_packets = applied_blocks = 0
    while True:
        try:
            allowed_targets, scope_identity = scope()
        except BookStudioError as error:
            if error.code == "PILOT_REVIEW_REQUIRED":
                return _result(
                    "pilot_review_required",
                    applied_packets,
                    applied_blocks,
                    "Review the sample, then run 'bookstudio pilot accept PROJECT --confirm' and apply the drafts again.",
                )
            raise
        packet = next_packet(config, allowed_targets=allowed_targets, scope_identity=scope_identity)
        if packet is None:
            return _result(
                "complete",
                applied_packets,
                applied_blocks,
                "Run 'bookstudio status' and 'bookstudio finish'.",
            )
        wanted = [block for block in packet["blocks"] if block.get("translate")]
        missing = [
            {"source_document": packet["source_document"], "block_index": block["block_index"]}
            for block in wanted
            if (packet["source_document"], block["block_index"]) not in drafts
        ]
        if missing:
            return {
                **_result(
                    "draft_missing",
                    applied_packets,
                    applied_blocks,
                    "Add drafts for the listed blocks, or translate this packet with 'bookstudio next', then rerun.",
                ),
                "missing": missing[:MISSING_REPORT_LIMIT],
                "_exit_code": 2,
            }
        translations = []
        for block in wanted:
            draft = drafts[(packet["source_document"], block["block_index"])]
            row = {
                "block_index": block["block_index"],
                "source_sha256": block["source_sha256"],
                "translation": draft["translation"],
            }
            if "translation_xhtml" in draft:
                row["translation_xhtml"] = draft["translation_xhtml"]
            translations.append(row)
        response = {
            "schema_version": 1,
            "packet_id": packet["packet_id"],
            "source_document": packet["source_document"],
            "translations": translations,
        }
        atomic_write_json(config.paths.packets / "next.json", packet)
        response_path = config.paths.packets / "drafts" / f"{applied_packets:04d}-{packet['packet_id'][:16]}.json"
        atomic_write_json(response_path, response)
        apply_response(config, response_path, allowed_targets=allowed_targets, scope_identity=scope_identity)
        applied_packets += 1
        applied_blocks += len(translations)


def _result(status: str, packets: int, blocks: int, next_action: str) -> dict[str, Any]:
    return {
        "status": status,
        "schema_version": 1,
        "applied_packets": packets,
        "applied_blocks": blocks,
        "next_action": next_action,
        "message": f"Applied {blocks} drafted blocks in {packets} packets ({status}).",
    }
