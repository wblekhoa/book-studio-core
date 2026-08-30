"""Stable Book Studio error and exit-code contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BookStudioError(Exception):
    code: str
    message: str
    next_action: str
    exit_code: int = 1
    evidence: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def error_payload(error: BookStudioError) -> dict[str, object]:
    return {
        "status": "error",
        "code": error.code,
        "message": error.message,
        "evidence": list(error.evidence),
        "next_action": error.next_action,
    }
