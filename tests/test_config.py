from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bookstudio.config import default_config_text, load_config, validate_output_mode
from bookstudio.errors import BookStudioError


VALID_CONFIG = """\
schema_version = 1

[book]
slug = "sample"
source = "source.epub"
source_language = "en"
target_language = "vi"
output_mode = "vi_only"

[profile]
domain = "ux-design"
audience = "product-designers"
tone = "clear"
terminology_policy = "keep-established-industry-terms"
localization_boundary = "editorial-blocks-only"
image_policy = "original-plus-companion"

[translation]
batch_scope = "chapter"
max_blocks = 40
prompt_version = "1"

[quality]
require_complete = true
require_reproducible_build = true
"""


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        (self.project / "source.epub").write_bytes(b"source")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_config(self, text: str = VALID_CONFIG) -> Path:
        path = self.project / "bookstudio.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_config_resolves_relative_paths_from_config_directory(self) -> None:
        config = load_config(self.write_config())

        self.assertEqual(
            self.project.resolve() / "state/inspection.json", config.paths.inspection
        )
        self.assertEqual((self.project / "source.epub").resolve(), config.source)
        self.assertEqual(self.project.resolve(), config.project_root)
        self.assertEqual(self.write_config().resolve(), config.config_path)
        self.assertEqual("sample", config.slug)
        self.assertEqual("vi_only", config.output_mode)

    def test_load_config_accepts_bcp47_like_languages_and_bilingual_mode(self) -> None:
        path = self.write_config(
            VALID_CONFIG.replace('source_language = "en"', 'source_language = "en-US"')
            .replace('target_language = "vi"', 'target_language = "vi-VN"')
            .replace('output_mode = "vi_only"', 'output_mode = "bilingual"')
        )

        config = load_config(path)

        self.assertEqual("en-US", config.source_language)
        self.assertEqual("vi-VN", config.target_language)
        self.assertEqual("bilingual", config.output_mode)

    def test_target_only_is_canonical_but_vi_only_remains_valid(self) -> None:
        self.assertEqual("target_only", validate_output_mode("target_only"))
        self.assertEqual("vi_only", validate_output_mode("vi_only"))

    def test_default_config_uses_target_only_and_keeps_extra_string_profile_keys(self) -> None:
        text = default_config_text(
            slug="sample",
            source=self.project / "source.epub",
            target_language="vi",
        )
        path = self.write_config(text.replace('[profile]\n', '[profile]\nlayout_policy = "preserve"\n'))

        config = load_config(path)

        self.assertEqual("target_only", config.output_mode)
        self.assertEqual("preserve", config.profile["layout_policy"])

    def test_load_config_rejects_invalid_language_output_mode_and_batch_size(self) -> None:
        cases = (
            (VALID_CONFIG.replace('target_language = "vi"', 'target_language = "not a language"'), "CONFIG_LANGUAGE_INVALID"),
            (VALID_CONFIG.replace('output_mode = "vi_only"', 'output_mode = "parallel"'), "CONFIG_OUTPUT_MODE_INVALID"),
            (VALID_CONFIG.replace("max_blocks = 40", "max_blocks = 0"), "CONFIG_MAX_BLOCKS_INVALID"),
        )
        for text, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(BookStudioError, code):
                    load_config(self.write_config(text))

    def test_load_config_rejects_missing_source(self) -> None:
        path = self.write_config(VALID_CONFIG.replace('source = "source.epub"', 'source = "missing.epub"'))

        with self.assertRaisesRegex(BookStudioError, "SOURCE_NOT_FOUND"):
            load_config(path)

    def test_load_config_rejects_symlinked_managed_directories_and_artifacts(self) -> None:
        cases = (
            ("cache", True, "PROJECT_DIRECTORY_PATH_INVALID"),
            ("state", True, "PROJECT_DIRECTORY_PATH_INVALID"),
            ("output", True, "PROJECT_DIRECTORY_PATH_INVALID"),
            ("glossary.md", False, "PROJECT_ARTIFACT_PATH_INVALID"),
            ("state/pilot.json", False, "PROJECT_ARTIFACT_PATH_INVALID"),
        )
        for relative, is_directory, code in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "source.epub").write_bytes(b"source")
                config_path = root / "bookstudio.toml"
                config_path.write_text(VALID_CONFIG, encoding="utf-8")
                managed = root / relative
                managed.parent.mkdir(parents=True, exist_ok=True)
                external = root / f"external-{managed.name}"
                if is_directory:
                    external.mkdir()
                else:
                    external.write_text("external", encoding="utf-8")
                managed.symlink_to(external, target_is_directory=is_directory)

                with self.assertRaisesRegex(BookStudioError, code):
                    load_config(config_path)

    def test_load_config_rejects_symlinked_config_file_but_allows_root_alias(self) -> None:
        real_config = self.write_config()
        config_alias = self.project / "config-alias.toml"
        config_alias.symlink_to(real_config)

        with self.assertRaisesRegex(BookStudioError, "PROJECT_ARTIFACT_PATH_INVALID"):
            load_config(config_alias)

        root_alias = self.project.parent / f"{self.project.name}-alias"
        root_alias.symlink_to(self.project, target_is_directory=True)
        try:
            config = load_config(root_alias / "bookstudio.toml")
            self.assertEqual(self.project.resolve(), config.project_root)
        finally:
            root_alias.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
