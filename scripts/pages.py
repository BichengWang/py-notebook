#!/usr/bin/env python3
"""GitHub Pages site
=================
Builds the static site that .github/workflows/pages.yml deploys. It copies site/,
serves every record schema at the path its `$id` names, mirrors each project's
conformance manifest and vectors under conformance/<package>/, and writes the list
of those files into index.html. A schema whose `$id` does not name its own package
and file name fails the build. Standard library only, Python 3.11+.
Exit codes: 0 built, 2 invalid input.
"""
import argparse
import html
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
ID_PREFIX = "https://github.com/BichengWang/ai-decision-system/"
MARKER = "<!-- generated:files -->"
VECTOR_KINDS = ("valid", "tampered", "invalid")


class SiteError(ValueError):
    """The repository cannot be published as it stands."""


def schemas(root):
    """Yield (site path, source path) for every published JSON Schema."""
    sources = sorted(root.glob("ai-workflows/*/*/schema/*.json"))
    sources.append(root / "scripts/conformance/manifest.schema.json")
    for source in sources:
        try:
            schema_id = json.loads(source.read_text(encoding="utf-8"))["$id"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SiteError(f"{source.relative_to(root)}: no readable $id ({error})") from None
        if not schema_id.startswith(ID_PREFIX + "schema/"):
            raise SiteError(f"{source.relative_to(root)}: $id {schema_id!r} is not under {ID_PREFIX}schema/")
        site_path = schema_id[len(ID_PREFIX):]
        if source.parent.name == "schema":
            expected = f"schema/{source.parent.parent.name}/{source.name}"
            if site_path != expected:
                raise SiteError(f"{source.relative_to(root)}: $id names {site_path}, expected {expected}")
        yield site_path, source


def conformance(root):
    """Yield (package, conformance directory, manifest) for every project with vectors."""
    for manifest_path in sorted(root.glob("ai-workflows/*/conformance/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            package = manifest["package"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SiteError(f"{manifest_path.relative_to(root)}: unreadable manifest ({error})") from None
        yield package, manifest_path.parent, manifest


def file_list(schema_paths, vector_sets):
    """Return the HTML that replaces MARKER: schema links and vector counts per package."""
    rows = []
    for site_path in schema_paths:
        name = html.escape(site_path)
        rows.append(f'      <li><a href="{name}"><code>{name}</code></a></li>')
    counts = []
    for package, manifest in vector_sets:
        tally = {kind: 0 for kind in VECTOR_KINDS}
        for vector in manifest["vectors"]:
            tally[vector["expect"]] += 1
        summary = ", ".join(f"{tally[kind]} {kind}" for kind in VECTOR_KINDS)
        link = html.escape(f"conformance/{package}/manifest.json")
        counts.append(f'      <li><a href="{link}"><code>{link}</code></a>: {summary}</li>')
    return "\n".join([
        '    <h3>Schemas</h3>', '    <ul class="files">', *rows, "    </ul>",
        '    <h3>Conformance vectors</h3>', '    <ul class="files">', *counts, "    </ul>",
    ])


def build(root, out):
    root, out = Path(root), Path(out)
    if out.exists():
        raise SiteError(f"{out} already exists; pass a new directory")
    index = (root / "site/index.html").read_text(encoding="utf-8")
    if index.count(MARKER) != 1:
        raise SiteError(f"site/index.html must contain {MARKER} exactly once")
    sources = list(schemas(root))
    claimed = [site_path for site_path, _ in sources]
    duplicates = sorted({site_path for site_path in claimed if claimed.count(site_path) > 1})
    if duplicates:
        raise SiteError(f"several schemas claim {', '.join(duplicates)}")
    vector_dirs = list(conformance(root))
    shutil.copytree(root / "site", out)
    for site_path, source in sources:
        target = out / site_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for package, directory, _ in vector_dirs:
        target = out / "conformance" / package
        target.mkdir(parents=True)
        shutil.copyfile(directory / "manifest.json", target / "manifest.json")
        for kind in VECTOR_KINDS:
            if (directory / kind).is_dir():
                shutil.copytree(directory / kind, target / kind)
    vector_sets = [(package, manifest) for package, _, manifest in vector_dirs]
    (out / "index.html").write_text(index.replace(MARKER, file_list(claimed, vector_sets)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return claimed, vector_sets


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 3)[3], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build", help="write the site into a new directory")
    command.add_argument("--out", required=True, help="new output directory")
    args = parser.parse_args(argv)
    try:
        schema_paths, vector_sets = build(ROOT, args.out)
    except (SiteError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    vectors = sum(len(manifest["vectors"]) for _, manifest in vector_sets)
    print(f"built {args.out}: {len(schema_paths)} schemas, {len(vector_sets)} vector sets, {vectors} vectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
