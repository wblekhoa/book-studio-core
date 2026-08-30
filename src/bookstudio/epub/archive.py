"""Read-only ZIP preflight for untrusted EPUB inputs."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..errors import BookStudioError


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int = 10_000
    max_total_uncompressed: int = 1_073_741_824
    max_single_uncompressed: int = 268_435_456
    max_compression_ratio: int = 1_000


DEFAULT_LIMITS = ArchiveLimits()


def _fail(code: str, message: str, next_action: str) -> BookStudioError:
    return BookStudioError(code=code, message=message, next_action=next_action)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_member_name(name: str) -> None:
    posix = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or posix.is_absolute()
        or ".." in posix.parts
    ):
        raise _fail(
            "ARCHIVE_UNSAFE_PATH",
            f"Unsafe archive member path: {name!r}",
            "Use an EPUB whose ZIP member names are relative and contain no parent traversal.",
        )


def preflight_archive(
    path: Path, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise _fail(
            "SOURCE_NOT_FOUND",
            f"EPUB source does not exist: {path}",
            "Pass an existing EPUB source path.",
        )
    try:
        with zipfile.ZipFile(source, "r") as archive:
            members = archive.infolist()
            if len(members) > limits.max_entries:
                raise _fail(
                    "ARCHIVE_ENTRY_LIMIT",
                    f"Archive has {len(members)} entries; limit is {limits.max_entries}.",
                    "Use a smaller EPUB or raise the reviewed archive limit explicitly.",
                )

            seen: set[str] = set()
            total_uncompressed = 0
            for member in members:
                _validate_member_name(member.filename)
                if member.filename in seen:
                    raise _fail(
                        "ARCHIVE_DUPLICATE_ENTRY",
                        f"Archive contains duplicate member: {member.filename}",
                        "Rebuild the EPUB with one unique entry per ZIP member name.",
                    )
                seen.add(member.filename)

                if member.file_size > limits.max_single_uncompressed:
                    raise _fail(
                        "ARCHIVE_SINGLE_SIZE_LIMIT",
                        f"Expanded member exceeds the limit: {member.filename}",
                        "Reduce the resource size or raise the reviewed archive limit explicitly.",
                    )
                total_uncompressed += member.file_size
                if total_uncompressed > limits.max_total_uncompressed:
                    raise _fail(
                        "ARCHIVE_TOTAL_SIZE_LIMIT",
                        "Archive expanded-byte total exceeds the configured limit.",
                        "Use a smaller EPUB or raise the reviewed archive limit explicitly.",
                    )
                if member.file_size:
                    ratio = (
                        member.file_size / member.compress_size
                        if member.compress_size
                        else float("inf")
                    )
                    if ratio > limits.max_compression_ratio:
                        raise _fail(
                            "ARCHIVE_COMPRESSION_RATIO_LIMIT",
                            f"Archive member compression ratio is unsafe: {member.filename}",
                            "Rebuild the resource or raise the reviewed ratio limit explicitly.",
                        )
    except zipfile.BadZipFile as exc:
        raise _fail(
            "ARCHIVE_INVALID",
            "Source is not a readable ZIP-based EPUB.",
            "Provide a valid EPUB archive.",
        ) from exc

    return {
        "passed": True,
        "source_name": source.name,
        "source_sha256": _sha256(source),
        "entries": len(members),
        "total_uncompressed_bytes": total_uncompressed,
    }
