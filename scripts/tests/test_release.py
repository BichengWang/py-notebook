"""Consumer-visible release commands against disposable independent projects."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "release.py"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.root / "workspace.json").write_text(json.dumps({"components": {
            name: {"kind": "project", "path": "project", "packages": ["example"]}
            for name in ("experiment-gate", "relia")}}))
        self.metadata = '''[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"
[project]
name = "example-distribution"
dynamic = ["version"]
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
[tool.setuptools.dynamic]
version = {attr = "example.__version__"}
'''
        (self.project / "pyproject.toml").write_text(self.metadata)
        (self.project / "example").mkdir()
        (self.project / "example/__init__.py").write_text('__version__ = "0.1.0"\nraise RuntimeError("must not import")\n')
        (self.project / "README.md").write_text("Example\n")
        (self.project / "LICENSE").write_text("MIT\n")
        self.changelog("Unreleased")

    def changelog(self, date):
        (self.project / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## [0.1.0] - {date}\n\n### Added\n- First release.\n\n"
            "## [0.0.1] - 2026-01-01\n\n- Older.\n")

    def run_cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_dynamic_version_without_import(self):
        self.assertIn("0.1.0", self.run_cli("check", "--component", "experiment-gate"))

    def test_static_version(self):
        (self.project / "pyproject.toml").write_text(self.metadata.replace(
            'dynamic = ["version"]', 'version = "0.1.0"').split('[tool.setuptools.dynamic]')[0])
        self.run_cli("check", "--component", "experiment-gate")

    def test_version_mismatch_and_all_failures(self):
        (self.project / "LICENSE").unlink()
        output = self.run_cli("check", "--tag", "experiment-gate/v0.2.0", code=1)
        self.assertIn("version", output)
        self.assertIn("LICENSE", output)
        self.assertIn("CHANGELOG", output)

    def test_missing_license_target(self):
        (self.project / "LICENSE").unlink()
        self.assertIn("LICENSE", self.run_cli("check", "--component", "experiment-gate", code=1))

    def test_undated_tag(self):
        self.assertIn("dated", self.run_cli("check", "--tag", "experiment-gate/v0.1.0", code=1))

    def test_relia_refusal(self):
        for args in (("check", "--component", "relia"), ("notes", "--tag", "relia/v0.1.0"),
                     ("prepare", "relia", "--date", "2026-10-12")):
            self.assertIn("docs/RELIA_RELEASE.md", self.run_cli(*args, code=1))

    def test_bad_tag_and_unknown_component(self):
        for tag in ("experiment-gate/0.1.0", "experiment-gate/v01.1.0", "experiment-gate/v0.1.0;echo", "unknown/v0.1.0"):
            self.run_cli("check", "--tag", tag, code=2)

    def test_notes_extraction(self):
        self.assertEqual(self.run_cli("notes", "--tag", "experiment-gate/v0.1.0"),
                         "### Added\n- First release.\n")

    def test_prepare_and_repeat_refusal(self):
        self.run_cli("prepare", "experiment-gate", "--date", "2026-10-12")
        self.run_cli("check", "--tag", "experiment-gate/v0.1.0")
        before = (self.project / "CHANGELOG.md").read_bytes()
        self.run_cli("prepare", "experiment-gate", "--date", "2026-10-13", code=1)
        self.assertEqual(before, (self.project / "CHANGELOG.md").read_bytes())

    def test_prepare_preserves_changelog_body(self):
        path = self.project / "CHANGELOG.md"
        before = path.read_text()
        self.run_cli("prepare", "experiment-gate", "--date", "2026-10-12")
        self.assertEqual(path.read_text(), before.replace(" - Unreleased", " - 2026-10-12"))

    def test_prepare_missing_and_invalid_date(self):
        self.run_cli("prepare", "experiment-gate", "--date", "2026-02-30", code=2)
        self.changelog("Unreleased")
        path = self.project / "CHANGELOG.md"
        path.write_text(path.read_text().replace("0.1.0", "0.2.0"))
        self.run_cli("prepare", "experiment-gate", "--date", "2026-10-12", code=1)

    def test_conflicting_version_sources(self):
        path = self.project / "pyproject.toml"
        path.write_text(self.metadata.replace('dynamic = ["version"]', 'dynamic = ["version"]\nversion = "0.1.0"'))
        self.run_cli("check", "--component", "experiment-gate", code=1)

    def test_unreadable(self):
        (self.project / "pyproject.toml").unlink()
        self.run_cli("check", "--component", "experiment-gate", code=2)

    def test_status_json_and_local_tags(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        status = json.loads(self.run_cli("status", "--json"))
        self.assertEqual(status["experiment-gate"]["version"], "0.1.0")
        self.assertFalse(status["experiment-gate"]["changelog_dated"])
        self.assertTrue(status["experiment-gate"]["license_present"])
        self.assertIsNone(status["experiment-gate"]["latest_tag"])
        self.assertFalse(status["relia"]["publishable"])


if __name__ == "__main__":
    unittest.main()
