"""Make command contracts exercised with temporary, database-free recipes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VerifyCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ("check_expected_coverage.py", "normalize_output.sh"):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)

    def example(self, directory: str = "recipes", name: str = "ok", code: str = "print('row')"):
        folder = self.root / directory
        expected = folder / "expected"
        expected.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.py").write_text(code + "\n", encoding="utf-8")
        (expected / f"{name}.expected").write_text("row\n", encoding="utf-8")

    def fake_command(self, name: str, body: str) -> dict[str, str]:
        binaries = self.root / "bin"
        binaries.mkdir(exist_ok=True)
        command = binaries / name
        command.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        command.chmod(0o755)
        return {**os.environ, "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}"}

    def verify(self, paths: str | None = None, *, env=None, normalize: str | None = None):
        command = ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), "verify"]
        command.append(f"PYTHON={sys.executable}")
        if paths is not None:
            command.append(f"VERIFY_PATHS={paths}")
        if normalize is not None:
            command.append(f"NORMALIZE={normalize}")
        return subprocess.run(
            command, cwd=self.root, env=env, capture_output=True, text=True, timeout=5
        )

    def test_missing_root_fails(self) -> None:
        self.assertNotEqual(self.verify("missing").returncode, 0)

    def test_empty_roots_fail(self) -> None:
        self.example()
        for paths in ("", "   "):
            with self.subTest(paths=paths):
                self.assertNotEqual(self.verify(paths).returncode, 0)

    def test_non_directory_root_fails(self) -> None:
        (self.root / "file.txt").touch()
        self.assertNotEqual(self.verify("file.txt").returncode, 0)

    def test_zero_expected_targets_fail(self) -> None:
        (self.root / "empty").mkdir()
        self.assertNotEqual(self.verify("empty").returncode, 0)

    def test_orphan_expected_fails(self) -> None:
        expected = self.root / "recipes" / "expected"
        expected.mkdir(parents=True)
        (expected / "orphan.expected").write_text("row\n", encoding="utf-8")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_mixed_orphan_and_valid_recipe_fail(self) -> None:
        self.example()
        (self.root / "recipes/expected/orphan.expected").write_text("row\n", encoding="utf-8")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1 passed", result.stdout)

    def test_find_error_cannot_be_hidden_by_sort(self) -> None:
        self.example()
        env = self.fake_command("find", "printf '%s\\n' recipes/expected/ok.expected; exit 7")
        self.assertNotEqual(self.verify(env=env).returncode, 0)

    def test_golden_read_error_cannot_report_a_match(self) -> None:
        self.example()
        env = self.fake_command("cat", "printf '%s\\n' row; exit 7")
        self.assertNotEqual(self.verify(env=env).returncode, 0)

    def test_symlinked_golden_is_still_verified(self) -> None:
        self.example()
        expected = self.root / "recipes/expected/ok.expected"
        source = self.root / "row.txt"
        source.write_text("row\n", encoding="utf-8")
        expected.unlink()
        expected.symlink_to(source)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 passed, 0 failed, 0 skipped", result.stdout)

    def test_expected_directory_is_not_silently_omitted(self) -> None:
        self.example()
        self.example(name="unreadable")
        expected = self.root / "recipes/expected/unreadable.expected"
        expected.unlink()
        expected.mkdir()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_recipe_failure_is_reported_and_other_recipes_still_run(self) -> None:
        self.example(name="bad", code="raise SystemExit(7)")
        self.example(name="good")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1 passed, 1 failed", result.stdout)

    def test_normalizer_failure_is_reported(self) -> None:
        self.example()
        self.assertNotEqual(self.verify(normalize="false").returncode, 0)

    def test_mismatched_golden_fails(self) -> None:
        self.example(code="print('different')")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_full_and_scoped_selection(self) -> None:
        self.example("first")
        self.example("second")
        for paths, count in ((None, 2), ("first", 1), ("first second", 2)):
            with self.subTest(paths=paths):
                result = self.verify(paths)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"{count} passed, 0 failed, 0 skipped", result.stdout)

    def test_expected_file_names_with_spaces(self) -> None:
        self.example(name="two words")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 passed, 0 failed, 0 skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
