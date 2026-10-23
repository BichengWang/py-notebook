"""The Pages build: schemas at their $id paths, resolvable vectors and links, refusal of bad input."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "pages.py"
ROOT = SCRIPT.parents[1]
PREFIX = "https://github.com/BichengWang/ai-decision-system/"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href")
        if tag == "a" and href:
            self.hrefs.append(href)


def build(root, out):
    return subprocess.run([sys.executable, str(root / "scripts/pages.py"), "build", "--out", str(out)],
                          capture_output=True, text=True)


class RepositorySiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name) / "site"
        cls.result = build(ROOT, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_build_succeeds(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_every_schema_is_served_at_its_id(self):
        sources = sorted(ROOT.glob("ai-workflows/*/*/schema/*.json"))
        sources.append(ROOT / "scripts/conformance/manifest.schema.json")
        for source in sources:
            schema_id = json.loads(source.read_text(encoding="utf-8"))["$id"]
            served = self.out / schema_id.removeprefix(PREFIX)
            self.assertEqual(served.read_bytes(), source.read_bytes(), source)

    def test_every_manifest_file_resolves_on_the_site(self):
        for manifest_path in sorted((self.out / "conformance").glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for vector in manifest["vectors"]:
                self.assertTrue((manifest_path.parent / vector["path"]).exists(), vector["path"])
                for digest in vector.get("digests", []):
                    canonical = digest.get("canonical_file")
                    if canonical:
                        self.assertTrue((manifest_path.parent / canonical).is_file(), canonical)

    def test_relative_links_on_the_index_resolve(self):
        parser = Links()
        parser.feed((self.out / "index.html").read_text(encoding="utf-8"))
        relative = [href for href in parser.hrefs if not href.startswith(("https://", "#"))]
        self.assertTrue(relative)
        for href in relative:
            self.assertTrue((self.out / href).is_file(), href)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        (self.root / "scripts/conformance").mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.root / "scripts/pages.py")
        shutil.copytree(ROOT / "site", self.root / "site")
        (self.root / "scripts/conformance/manifest.schema.json").write_text(
            json.dumps({"$id": PREFIX + "schema/conformance/manifest.v1.json"}))
        self.schema_dir = self.root / "ai-workflows/project/expgate/schema"
        self.schema_dir.mkdir(parents=True)
        self.out = Path(temp.name) / "site"

    def test_schema_id_naming_another_package_writes_nothing(self):
        (self.schema_dir / "decision.v3.json").write_text(
            json.dumps({"$id": PREFIX + "schema/jevdecision/decision.v3.json"}))
        result = build(self.root, self.out)
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected schema/expgate/decision.v3.json", result.stderr)
        self.assertFalse(self.out.exists())

    def test_existing_output_directory_is_refused(self):
        (self.schema_dir / "decision.v3.json").write_text(
            json.dumps({"$id": PREFIX + "schema/expgate/decision.v3.json"}))
        self.out.mkdir()
        (self.out / "keep.txt").write_text("mine")
        result = build(self.root, self.out)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.out / "keep.txt").read_text(), "mine")


if __name__ == "__main__":
    unittest.main()
