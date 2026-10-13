from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.fixtures import build_synthetic_epub
from tests.test_e2e import run_cli


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
CSS = "OEBPS/bookstudio/bookstudio.css"
CHAPTER = "OEBPS/text/chapter.xhtml"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DeclaredEditsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.source = self.root / "synthetic.epub"
        self.project = self.root / "project"
        build_synthetic_epub(self.source)
        self.assertEqual(0, self._cli("init", str(self.project), "--source", str(self.source), "--target", "vi")[0])
        self.assertEqual(0, self._cli("prepare", str(self.project))[0])
        for number in range(20):
            code, packet = self._cli("next", str(self.project))
            if code == 3:
                break
            response = {
                "schema_version": 1,
                "packet_id": packet["packet_id"],
                "source_document": packet["source_document"],
                "translations": [
                    {
                        "block_index": block["block_index"],
                        "source_sha256": block["source_sha256"],
                        "translation": f"Bản dịch {block['block_index']}",
                    }
                    for block in packet["blocks"]
                ],
            }
            path = self.root / f"response-{number}.json"
            path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(0, self._cli("apply", str(self.project), str(path))[0])
        code, built = self._cli("build", str(self.project))
        self.assertEqual(0, code, built)
        with zipfile.ZipFile(self.project / "output/build.epub") as archive:
            self.base = {name: archive.read(name) for name in archive.namelist()}

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _cli(self, *args: str) -> tuple[int, dict]:
        result = run_cli(*args, "--json")
        return result.returncode, json.loads(result.stdout)

    def _edits(self, operations: list[dict]) -> None:
        payload = {"schema_version": 1, "operations": operations}
        (self.project / "edits.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _final(self) -> dict[str, bytes]:
        with zipfile.ZipFile(self.project / "output/final.epub") as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def _asset(self, relative: str, data: bytes) -> str:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return relative

    # BSC-EDIT-001
    def test_finish_certifies_the_edited_book(self) -> None:
        replacement = self.base[CHAPTER].replace("Bản dịch 1".encode(), "Bản dịch đã biên tập".encode())
        self._asset("assets/edits/chapter.xhtml", replacement)
        self._asset("assets/cover/marked.png", PNG)
        self._edits(
            [
                {
                    "op": "replace_member",
                    "member": CHAPTER,
                    "base_sha256": _sha(self.base[CHAPTER]),
                    "from": "assets/edits/chapter.xhtml",
                    "sha256": _sha(replacement),
                    "note": "editor-approved wording",
                },
                {"op": "add_member", "member": "OEBPS/images/marked.png", "from": "assets/cover/marked.png", "sha256": _sha(PNG)},
                {
                    "op": "replace_text",
                    "member": "OEBPS/content.opf",
                    "find": "</ns0:manifest>",
                    "replace": '<ns0:item id="marked" href="images/marked.png" media-type="image/png" /></ns0:manifest>',
                    "count": 1,
                },
            ]
        )
        code, finished = self._cli("finish", str(self.project))
        self.assertEqual(0, code, finished)
        final = self._final()
        self.assertEqual(replacement, final[CHAPTER])
        self.assertEqual(PNG, final["OEBPS/images/marked.png"])
        self.assertEqual(finished["output_sha256"], _sha((self.project / "output/final.epub").read_bytes()))
        self.assertEqual(3, finished["edits"]["applied"])
        self.assertEqual(_sha((self.project / "edits.json").read_bytes()), finished["edits"]["sha256"])
        release = json.loads((self.project / "reports/release.json").read_text(encoding="utf-8"))
        self.assertEqual(finished["edits"], release["edits"])
        self.assertEqual("mimetype", zipfile.ZipFile(self.project / "output/final.epub").infolist()[0].filename)
        self.assertEqual(0, self._cli("verify", str(self.project))[0])

    # BSC-EDIT-002
    def test_without_edits_file_build_is_unchanged(self) -> None:
        code, built = self._cli("build", str(self.project))
        self.assertEqual(0, code, built)
        self.assertEqual({"applied": 0, "sha256": None}, built["edits"])
        with zipfile.ZipFile(self.project / "output/build.epub") as archive:
            self.assertEqual(self.base, {name: archive.read(name) for name in archive.namelist()})

    def _assert_build_fails(self, code_name: str) -> None:
        (self.project / "output/build.epub").unlink(missing_ok=True)
        code, payload = self._cli("build", str(self.project))
        self.assertNotEqual(0, code)
        self.assertEqual(code_name, payload["code"], payload)
        self.assertFalse((self.project / "output/build.epub").exists())
        self.assertEqual([], [p.name for p in (self.project / "output").iterdir()])

    # BSC-EDIT-003
    def test_text_count_mismatch_fails_closed(self) -> None:
        self._edits([{"op": "replace_text", "member": CSS, "find": "no-such-rule", "replace": "x", "count": 1}])
        self._assert_build_fails("EDITS_TEXT_COUNT_MISMATCH")

    # BSC-EDIT-004
    def test_stale_member_base_fails_closed(self) -> None:
        self._asset("assets/edits/chapter.xhtml", self.base[CHAPTER])
        self._edits(
            [
                {
                    "op": "replace_member",
                    "member": CHAPTER,
                    "base_sha256": "0" * 64,
                    "from": "assets/edits/chapter.xhtml",
                    "sha256": _sha(self.base[CHAPTER]),
                }
            ]
        )
        self._assert_build_fails("EDITS_BASE_STALE")

    # BSC-EDIT-005
    def test_asset_hash_and_location_are_pinned(self) -> None:
        self._asset("assets/cover/marked.png", PNG)
        self._edits([{"op": "add_member", "member": "OEBPS/images/marked.png", "from": "assets/cover/marked.png", "sha256": "1" * 64}])
        self._assert_build_fails("EDITS_ASSET_INVALID")
        outside = self.root / "outside.png"
        outside.write_bytes(PNG)
        self._edits([{"op": "add_member", "member": "OEBPS/images/marked.png", "from": "../outside.png", "sha256": _sha(PNG)}])
        self._assert_build_fails("EDITS_ASSET_INVALID")

    # BSC-EDIT-006
    def test_unsafe_markup_is_rejected(self) -> None:
        self._edits([{"op": "replace_text", "member": CHAPTER, "find": "</body>", "replace": "<script>alert(1)</script></body>", "count": 1}])
        self._assert_build_fails("EDITS_UNSAFE_MARKUP")
        self._edits([{"op": "replace_text", "member": CHAPTER, "find": "<section", "replace": '<section onclick="x()"', "count": 1}])
        self._assert_build_fails("EDITS_UNSAFE_MARKUP")

    # BSC-EDIT-007
    def test_schema_and_member_rules(self) -> None:
        self._edits([{"op": "delete_member", "member": CSS}])
        self._assert_build_fails("EDITS_SCHEMA_INVALID")
        self._asset("assets/x.png", PNG)
        self._edits([{"op": "add_member", "member": "OEBPS/images/pixel.png", "from": "assets/x.png", "sha256": _sha(PNG)}])
        self._assert_build_fails("EDITS_MEMBER_EXISTS")
        self._edits([{"op": "replace_text", "member": "OEBPS/missing.css", "find": "a", "replace": "b", "count": 1}])
        self._assert_build_fails("EDITS_MEMBER_MISSING")
        self._edits([{"op": "add_member", "member": "../escape.png", "from": "assets/x.png", "sha256": _sha(PNG)}])
        self._assert_build_fails("EDITS_SCHEMA_INVALID")

    def _edited_copy(self, mutate) -> Path:
        members = dict(self.base)
        mutate(members)
        path = self.root / "edited.epub"
        with zipfile.ZipFile(path, "w") as archive:
            info = zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, members.pop("mimetype"), compress_type=zipfile.ZIP_STORED)
            for name in sorted(members, reverse=True):
                archive.writestr(name, members[name], compress_type=zipfile.ZIP_DEFLATED)
        return path

    # BSC-EDIT-008
    def test_capture_turns_an_edited_epub_into_certified_edits(self) -> None:
        changed = self.base[CHAPTER].replace("Bản dịch 1".encode(), "Đã biên tập".encode())

        def mutate(members: dict[str, bytes]) -> None:
            members[CHAPTER] = changed
            members["OEBPS/images/marked.png"] = PNG

        edited = self._edited_copy(mutate)
        code, payload = self._cli("edits", "capture", str(self.project), "--from", str(edited))
        self.assertEqual(0, code, payload)
        self.assertEqual(2, payload["operations"])
        self.assertEqual("edits.json", payload["written"])
        self.assertNotIn(str(self.root), json.dumps(payload))
        code, finished = self._cli("finish", str(self.project))
        self.assertEqual(0, code, finished)
        final = self._final()
        with zipfile.ZipFile(edited) as archive:
            self.assertEqual({n: archive.read(n) for n in archive.namelist()}, final)

    # BSC-EDIT-009
    def test_capture_refuses_deletions_existing_edits_and_no_change(self) -> None:
        code, payload = self._cli("edits", "capture", str(self.project), "--from", str(self._edited_copy(lambda m: None)))
        self.assertEqual(0, code, payload)
        self.assertEqual("no_changes", payload["status"])
        self.assertFalse((self.project / "edits.json").exists())
        code, payload = self._cli("edits", "capture", str(self.project), "--from", str(self._edited_copy(lambda m: m.pop(CSS))))
        self.assertEqual("EDITS_CAPTURE_DELETION", payload["code"])
        self.assertFalse((self.project / "edits.json").exists())
        self._edits([])
        code, payload = self._cli("edits", "capture", str(self.project), "--from", str(self._edited_copy(lambda m: m.update({CSS: b"x"}))))
        self.assertEqual("EDITS_ALREADY_DECLARED", payload["code"])

    # BSC-EDIT-010
    def test_markup_check_follows_manifest_media_type_and_blocks_active_content(self) -> None:
        chapter = self.base[CHAPTER].decode("utf-8")
        renamed = chapter.replace("</body>", "<script>alert(1)</script></body>").encode("utf-8")
        self._asset("assets/edits/chapter.txt", renamed)
        self._edits(
            [
                {"op": "add_member", "member": "OEBPS/text/chapter.txt", "from": "assets/edits/chapter.txt", "sha256": _sha(renamed)},
                {"op": "replace_text", "member": "OEBPS/content.opf", "find": 'href="text/chapter.xhtml"', "replace": 'href="text/chapter.txt"', "count": 1},
            ]
        )
        self._assert_build_fails("EDITS_UNSAFE_MARKUP")
        unsafe = [
            '<a href="java&#9;script:alert(1)">x</a>',
            '<a href="data:text/html,x">x</a>',
            '<iframe srcdoc="x"></iframe>',
            '<form action="javascript:x"></form>',
            '<object data="x.svg"></object>',
            '<embed src="x.svg"/>',
            '<meta http-equiv="refresh" content="0;url=javascript:x"/>',
            '<img src="https://tracker.example/p.png"/>',
            '<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="href" values="javascript:x"/></svg>',
        ]
        for snippet in unsafe:
            with self.subTest(snippet=snippet):
                self._edits([{"op": "replace_text", "member": CHAPTER, "find": "</body>", "replace": snippet + "</body>", "count": 1}])
                self._assert_build_fails("EDITS_UNSAFE_MARKUP")
        self._edits([{"op": "replace_text", "member": CHAPTER, "find": "</body>", "replace": '<p><a href="https://example.org/">ok</a> <a href="#note-1">n</a></p></body>', "count": 1}])
        code, built = self._cli("build", str(self.project))
        self.assertEqual(0, code, built)

    # BSC-EDIT-011
    def test_capture_never_writes_through_symlinks_or_colliding_names(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.project / "assets").mkdir(exist_ok=True)
        (self.project / "assets/edits").symlink_to(outside, target_is_directory=True)
        edited = self._edited_copy(lambda m: m.update({"OEBPS/pwn.txt": b"x"}))
        code, payload = self._cli("edits", "capture", str(self.project), "--from", str(edited))
        self.assertEqual("EDITS_ASSET_INVALID", payload["code"])
        self.assertEqual([], list(outside.iterdir()))
        (self.project / "assets/edits").unlink()
        for extra in ({"OEBPS/Extra.txt": b"a", "OEBPS/extra.txt": b"b"}, {"OEBPS/aa": b"a", "OEBPS/aa/b.txt": b"b"}, {"OEBPS/a:b.txt": b"a"}):
            with self.subTest(extra=sorted(extra)):
                edited = self._edited_copy(lambda m: m.update(extra))
                code, payload = self._cli("edits", "capture", str(self.project), "--from", str(edited))
                self.assertIn(payload.get("code"), {"EDITS_ASSET_INVALID", "EDITS_SCHEMA_INVALID", "ARCHIVE_UNSAFE_PATH"}, payload)
                self.assertFalse((self.project / "edits.json").exists())
                self.assertFalse((self.project / "assets/edits").exists())


if __name__ == "__main__":
    unittest.main()
