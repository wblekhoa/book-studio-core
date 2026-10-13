"""Write a tiny synthetic EPUB (no third-party content) for eval workspaces."""
import sys
import zipfile

CHAPTER = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter One</title></head>
<body><section><h1>Make the important choice obvious</h1>
<p>Readers should not have to decode a primary action.</p>
<p>Clarity reduces avoidable hesitation.</p>
<p>A clear label helps people decide quickly.</p></section></body></html>
"""
TITLE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Sample Book</title></head>
<body><section><h1>Sample Book</h1><p>A small synthetic book.</p></section></body></html>
"""
OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="id" xmlns="http://www.idpf.org/2007/opf">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">urn:uuid:book-studio-eval</dc:identifier>
<dc:title>Sample Book</dc:title><dc:language>en</dc:language></metadata>
<manifest><item id="title" href="text/title.xhtml" media-type="application/xhtml+xml"/>
<item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="title"/><itemref idref="chapter"/></spine></package>
"""
CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>
"""

with zipfile.ZipFile(sys.argv[1], "w") as book:
    book.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
    for name, text in (("META-INF/container.xml", CONTAINER), ("OEBPS/content.opf", OPF),
                       ("OEBPS/text/title.xhtml", TITLE), ("OEBPS/text/chapter.xhtml", CHAPTER)):
        book.writestr(name, text, compress_type=zipfile.ZIP_DEFLATED)
