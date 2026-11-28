"""Write a small synthetic text-layer PDF (standard library only): two pages, a heading and prose on each."""
import sys
from pathlib import Path

PAGES = [
    ("Chapter One", [
        "The evening light fell across the quiet harbour.",
        "A small boat waited by the stone steps, its rope loose.",
        "Nobody in the town remembered who had tied it there.",
    ]),
    ("Chapter Two", [
        "In the morning the boat was gone, and so was the rope.",
        "The harbour master wrote one line in his ledger.",
        "Then he closed the book and went home for breakfast.",
    ]),
]


def escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def page_stream(title, lines):
    parts = ["BT", "/F1 20 Tf", "72 720 Td", f"({escape(title)}) Tj", "/F1 12 Tf", "0 -36 Td"]
    for line in lines:
        parts += [f"({escape(line)}) Tj", "0 -18 Td"]
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def build():
    objects = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(PAGES)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(PAGES)} >>".encode())
    font_number = 3 + len(PAGES) * 2
    for index, (title, lines) in enumerate(PAGES):
        content_number = 4 + index * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {content_number} 0 R >>".encode()
        )
        stream = page_stream(title, lines)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info << /Title (Synthetic Harbour) >> >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic.pdf").write_bytes(build())
