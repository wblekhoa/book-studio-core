"""Allowlist validator for untrusted inline XHTML translations."""

from __future__ import annotations

from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from ..errors import BookStudioError


ALLOWED_TAGS = frozenset({"a", "em", "strong", "span", "sup", "sub", "br", "code"})
GLOBAL_ATTRIBUTES = frozenset({"id", "class", "title", "lang", "dir"})
TAG_ATTRIBUTES = {"a": frozenset({"href"})}
EPUB_NAMESPACE = "http://www.idpf.org/2007/ops"


def _fail(code: str, message: str) -> BookStudioError:
    return BookStudioError(
        code=code,
        message=message,
        next_action="Return plain text or use only the documented safe inline XHTML allowlist.",
    )


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _validate_href(value: str) -> None:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if (
        not candidate
        or parsed.scheme
        or parsed.netloc
        or candidate.startswith(("/", "//", "\\"))
        or "\\" in candidate
    ):
        raise _fail("XHTML_UNSAFE", f"Unsafe XHTML link target: {value!r}")


def validate_inline_xhtml(value: str) -> dict[str, object]:
    if not isinstance(value, str) or not value.strip():
        raise _fail("XHTML_INVALID", "Inline XHTML must be a nonempty string.")
    lowered = value.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered or "<?xml" in lowered:
        raise _fail("XHTML_UNSAFE", "Declarations and entities are not allowed inline.")
    try:
        root = ET.fromstring(
            f'<bookstudio-root xmlns:epub="{EPUB_NAMESPACE}">{value}</bookstudio-root>'
        )
    except ET.ParseError as exc:
        raise _fail("XHTML_INVALID", f"Inline XHTML is not well formed: {exc}") from exc

    for element in root.iter():
        if element is root:
            continue
        tag = _local_name(element.tag)
        if tag not in ALLOWED_TAGS:
            raise _fail("XHTML_UNSAFE", f"Inline XHTML tag is not allowed: {tag}")
        allowed = GLOBAL_ATTRIBUTES | TAG_ATTRIBUTES.get(tag, frozenset())
        for raw_name, attribute_value in element.attrib.items():
            attribute = _local_name(raw_name)
            is_epub_type = raw_name == f"{{{EPUB_NAMESPACE}}}type"
            if attribute.casefold().startswith("on") or attribute == "style":
                raise _fail("XHTML_UNSAFE", f"Inline XHTML attribute is unsafe: {attribute}")
            if attribute not in allowed and not is_epub_type:
                raise _fail("XHTML_UNSAFE", f"Inline XHTML attribute is not allowed: {attribute}")
            if attribute == "href":
                _validate_href(attribute_value)
    return {"passed": True, "tags": sum(1 for _ in root.iter()) - 1}
