from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from bookstudio.config import atomic_write_json, load_config
from bookstudio.epub.build import build_epub, finish_project
from bookstudio.epub.extract import extract_block_map
from bookstudio.epub.inspect import inspect_epub
from bookstudio.errors import BookStudioError
from bookstudio.intake import assess_intake, profile_from_answers
from bookstudio.pilot import pilot_receipt, select_pilot
from bookstudio.project import full_coverage, init_project, locked_intake
from bookstudio.translation import coverage as coverage_module
from bookstudio.translation.coverage import coverage_receipt
from bookstudio.translation.packets import next_packet
from tests.fixtures import build_synthetic_epub


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "bookstudio", *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class ExactCoverageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "synthetic.epub"
        build_synthetic_epub(self.source)
        self.block_map = extract_block_map(self.source)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def valid_contract(self) -> dict[str, Any]:
        return full_coverage(self.block_map)

    def new_project(self, name: str, *, with_pilot: bool = False):
        project = self.root / name
        answers = (
            {
                "target_language": "vi",
                "output_mode": "vi_only",
                "audience": "designers",
                "translation_approach": "faithful",
                "image_text_policy": "selective",
                "image_annotation_policy": "selective",
                "market_context_policy": "labeled_selective",
                "layout_policy": "preserve",
            }
            if with_pilot
            else None
        )
        init_project(
            project,
            slug=name,
            source=self.source,
            target_language="vi",
            output_mode="vi_only",
            max_blocks=2,
            profile=profile_from_answers(answers) if answers is not None else None,
        )
        config = load_config(project / "bookstudio.toml")
        atomic_write_json(
            config.paths.source_blocks / "full-block-map.json", self.block_map
        )
        atomic_write_json(
            config.paths.source_blocks / "coverage.json", self.valid_contract()
        )
        if with_pilot:
            assert answers is not None
            assessment = assess_intake(self.source, answers)
            inspection = inspect_epub(self.source)
            atomic_write_json(config.paths.inspection, inspection)
            atomic_write_json(config.paths.intake, locked_intake(assessment))
            atomic_write_json(
                config.paths.pilot,
                select_pilot(inspection, self.block_map, assessment["answers"]),
            )
        return project, config

    @staticmethod
    def snapshot(project: Path) -> dict[str, bytes]:
        return {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in sorted(project.rglob("*"))
            if path.is_file()
        }

    def bypass_contract(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source_sha256": self.block_map["source"]["sha256"],
            "included_files": True,
            "excluded_files": {
                row["source_path"]: True for row in self.block_map["files"]
            },
            "unexpected": "silently accepted before the shared validator",
        }

    def test_validator_requires_the_exact_coverage_contract(self) -> None:
        validator = getattr(coverage_module, "validate_coverage_contract", None)
        self.assertTrue(
            callable(validator),
            "translation.coverage must own the shared exact contract validator",
        )
        assert callable(validator)

        included = [row["source_path"] for row in self.block_map["files"]]
        valid = self.valid_contract()
        cases: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
            ("extra key", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(extra=True)),
            ("missing key", "COVERAGE_SCHEMA_INVALID", lambda value: value.pop("excluded_files")),
            ("boolean schema", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(schema_version=True)),
            ("wrong schema", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(schema_version=2)),
            ("boolean source", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(source_sha256=True)),
            ("stale source", "COVERAGE_SOURCE_STALE", lambda value: value.update(source_sha256="0" * 64)),
            ("included object", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files={})),
            ("included string", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files=included[0])),
            ("included boolean", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files=True)),
            ("included boolean row", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files=[True])),
            ("included duplicate", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files=included + [included[-1]])),
            ("included reordered", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files=list(reversed(included)))),
            ("included omitted", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(included_files=included[:-1])),
            ("excluded object", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(excluded_files={included[0]: True})),
            ("excluded string", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(excluded_files=included[0])),
            ("excluded boolean", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(excluded_files=True)),
            ("excluded boolean row", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(excluded_files=[True])),
            ("excluded duplicate", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(excluded_files=[included[0], included[0]])),
            ("excluded unknown", "COVERAGE_SCHEMA_INVALID", lambda value: value.update(excluded_files=["OEBPS/text/unknown.xhtml"])),
        ]

        self.assertEqual(valid, validator(self.block_map, valid))
        for name, expected_code, mutate in cases:
            with self.subTest(name=name):
                payload = json.loads(json.dumps(valid))
                mutate(payload)
                caught: BookStudioError | None = None
                try:
                    validator(self.block_map, payload)
                except BookStudioError as error:
                    caught = error
                self.assertEqual(expected_code, caught.code if caught else None)

    def test_all_consumers_reject_the_all_excluded_shape_bypass_without_mutation(
        self,
    ) -> None:
        def direct_operation(
            name: str,
            operation: Callable[[Any, Path], Any],
        ) -> None:
            project, config = self.new_project(name)
            atomic_write_json(
                config.paths.source_blocks / "coverage.json", self.bypass_contract()
            )
            before = self.snapshot(project)
            output = self.root / f"{name}.epub"
            caught: BookStudioError | None = None
            try:
                operation(config, output)
            except BookStudioError as error:
                caught = error
            self.assertEqual(
                ("COVERAGE_SCHEMA_INVALID", before, False),
                (
                    caught.code if caught else None,
                    self.snapshot(project),
                    output.exists(),
                ),
            )

        direct_operations = (
            ("receipt", lambda config, _output: coverage_receipt(config, require_complete=True)),
            ("next", lambda config, _output: next_packet(config)),
            ("build", lambda config, output: build_epub(config, output)),
            ("finish", lambda config, _output: finish_project(config)),
        )
        for name, operation in direct_operations:
            with self.subTest(consumer=name):
                direct_operation(name, operation)

        for command_name, command in (
            ("status", ("status",)),
            ("next-cli", ("next",)),
        ):
            with self.subTest(consumer=command_name):
                project, config = self.new_project(command_name)
                atomic_write_json(
                    config.paths.source_blocks / "coverage.json",
                    self.bypass_contract(),
                )
                before = self.snapshot(project)
                result = run_cli(*command, str(project), "--json")
                payload = json.loads(result.stdout)
                self.assertEqual(
                    (1, "COVERAGE_SCHEMA_INVALID", before),
                    (result.returncode, payload.get("code"), self.snapshot(project)),
                )

        with self.subTest(consumer="pilot-status"):
            project, config = self.new_project("pilot-status", with_pilot=True)
            atomic_write_json(
                config.paths.source_blocks / "coverage.json", self.bypass_contract()
            )
            before = self.snapshot(project)
            result = run_cli("pilot", "status", str(project), "--json")
            payload = json.loads(result.stdout)
            self.assertEqual(
                (1, "COVERAGE_SCHEMA_INVALID", before),
                (result.returncode, payload.get("code"), self.snapshot(project)),
            )


if __name__ == "__main__":
    unittest.main()
