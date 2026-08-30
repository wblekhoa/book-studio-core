from __future__ import annotations

import base64
import warnings
import zipfile
from pathlib import Path


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _member(name: str, data: bytes, *, stored: bool = False) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info, data


def make_zip(path: Path, entries: dict[str, bytes], *, compressed: bool = False) -> None:
    compression = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def make_duplicate_name_zip(path: Path, name: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(name, b"first")
            archive.writestr(name, b"second")


def build_synthetic_epub(
    path: Path,
    *,
    include_image: bool = True,
    image_markup: str | None = None,
) -> None:
    container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''
    package = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="book-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:uuid:bookstudio-synthetic</dc:identifier>
    <dc:title>Book Studio Synthetic</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="title" href="text/title.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="legal" href="text/legal.xhtml" media-type="application/xhtml+xml"/>
    <item id="image" href="images/pixel.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="title"/>
    <itemref idref="chapter"/>
    <itemref idref="legal"/>
  </spine>
</package>
'''
    title = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Synthetic Book</title></head>
<body><section><h1>Synthetic Book</h1><p>A safe sample for Book Studio.</p></section></body></html>
'''
    chapter = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter One</title></head>
<body><section id="chapter-one"><h1>Make the important choice obvious</h1>
<p>Readers should not have to <em>decode</em> a primary action. <a href="#note-1">One note</a> explains why.</p>
<ul><li>Choose a clear label.<p>A nested explanation.</p></li></ul>
<figure><img src="../images/pixel.png" alt="A synthetic one-pixel example"/><figcaption>A tiny original image.</figcaption></figure>
<aside id="note-1"><p>Clarity reduces avoidable hesitation.</p></aside>
</section></body></html>
'''
    legal = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Legal</title></head>
<body><section><h1>Legal notice</h1><p>This synthetic document is intentionally excluded.</p></section></body></html>
'''
    if image_markup is None:
        image_markup = "img" if include_image else "none"
    image_block = (
        b'<figure><img src="../images/pixel.png" alt="A synthetic one-pixel example"/><figcaption>A tiny original image.</figcaption></figure>\n'
    )
    if image_markup == "none":
        chapter = chapter.replace(image_block, b"")
    elif image_markup in {"svg", "bare-svg"}:
        svg_reference = (
            b'<image href="../images/pixel.png" width="1" height="1"/>'
            if include_image
            else b'<image href="data:image/png;base64,AA==" width="1" height="1"/>'
        )
        if image_markup == "bare-svg":
            svg_reference = b'<rect width="1" height="1"/>'
        chapter = chapter.replace(
            image_block,
            b'<figure><svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
            + svg_reference
            + b'</svg><figcaption>A tiny vector example.</figcaption></figure>\n',
        )
    elif image_markup != "img":
        raise ValueError(f"Unsupported synthetic image markup: {image_markup}")
    if not include_image:
        package = package.replace(
            b'    <item id="image" href="images/pixel.png" media-type="image/png"/>\n',
            b"",
        )
    members = (
        _member("mimetype", b"application/epub+zip", stored=True),
        _member("META-INF/container.xml", container),
        _member("OEBPS/content.opf", package),
        _member("OEBPS/text/title.xhtml", title),
        _member("OEBPS/text/chapter.xhtml", chapter),
        _member("OEBPS/text/legal.xhtml", legal),
    )
    if include_image:
        members += (_member("OEBPS/images/pixel.png", _PNG_1X1),)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for info, data in members:
            archive.writestr(info, data)


def build_pilot_tie_epub(path: Path) -> None:
    """Build two equally sized chapters where only the later one has an image."""
    build_synthetic_epub(path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}

    entries["OEBPS/content.opf"] = entries["OEBPS/content.opf"].replace(
        b'    <item id="legal" href="text/legal.xhtml" media-type="application/xhtml+xml"/>',
        b'    <item id="chapter-two" href="text/chapter-two.xhtml" media-type="application/xhtml+xml"/>\n'
        b'    <item id="legal" href="text/legal.xhtml" media-type="application/xhtml+xml"/>',
    ).replace(
        b'    <itemref idref="legal"/>',
        b'    <itemref idref="chapter-two"/>\n    <itemref idref="legal"/>',
    )
    image_block = (
        b'<figure><img src="../images/pixel.png" alt="A synthetic one-pixel example"/>'
        b'<figcaption>A tiny original image.</figcaption></figure>\n'
    )
    first = entries["OEBPS/text/chapter.xhtml"].replace(image_block, b"")
    second = entries["OEBPS/text/chapter.xhtml"].replace(
        b"Chapter One", b"Chapter Two"
    ).replace(
        b"Make the important choice obvious",
        b"Make the secondary choice obvious",
    )
    entries["OEBPS/text/chapter.xhtml"] = first
    entries["OEBPS/text/chapter-two.xhtml"] = second

    members = (
        _member("mimetype", entries["mimetype"], stored=True),
        _member("META-INF/container.xml", entries["META-INF/container.xml"]),
        _member("OEBPS/content.opf", entries["OEBPS/content.opf"]),
        _member("OEBPS/text/title.xhtml", entries["OEBPS/text/title.xhtml"]),
        _member("OEBPS/text/chapter.xhtml", entries["OEBPS/text/chapter.xhtml"]),
        _member(
            "OEBPS/text/chapter-two.xhtml",
            entries["OEBPS/text/chapter-two.xhtml"],
        ),
        _member("OEBPS/text/legal.xhtml", entries["OEBPS/text/legal.xhtml"]),
        _member("OEBPS/images/pixel.png", entries["OEBPS/images/pixel.png"]),
    )
    with zipfile.ZipFile(path, "w") as archive:
        for info, data in members:
            archive.writestr(info, data)
