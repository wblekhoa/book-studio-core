# Security

Book Studio treats EPUBs and AI responses as untrusted input. Please report a
suspected vulnerability through GitHub's private vulnerability reporting when
it is available for the repository. Do not attach copyrighted books, private
translations, credentials, or personal paths to a report; use a minimal
synthetic reproduction.

The current safety boundary covers ZIP traversal and resource limits, strict
project ownership, atomic writes, source-hash checks, inline XHTML allowlists,
same-canvas image companions, deterministic builds, independent EPUB
validation, and a public-tree audit. The tool does not sandbox AI providers and
does not upload content itself.
