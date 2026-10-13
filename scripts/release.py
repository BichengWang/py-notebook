#!/usr/bin/env python3
"""Releasing
=========
Inspect candidates with status, validate with check --component NAME, then date
that version's Unreleased changelog with prepare NAME --date YYYY-MM-DD. Review
and commit separately before creating NAME/vX.Y.Z. check --tag requires dated
notes; notes extracts their body. This tool never creates commits or tags.
RELIA uses docs/RELIA_RELEASE.md instead. Standard library only, Python 3.11+.
Exit codes: 0 success, 1 candidate check/refusal, 2 invalid input or unreadable.
"""
import argparse
import ast
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
TAG = re.compile(rf"([a-z0-9][a-z0-9-]*)/v({VERSION})\Z")
HEADING = re.compile(r"^## \[([^\]\n]+)\] - ([^\n]+?)[ \t]*$", re.M)
PUBLISHABLE = {"experiment-gate", "jev-decision", "decision-control"}
RELIA_REASON = "RELIA requires rights clearance, external reproduction, and maintainer acceptance; see docs/RELIA_RELEASE.md"


class CandidateError(ValueError):
    """Readable candidate does not satisfy the release contract."""


def projects(root):
    manifest = json.loads((root / "workspace.json").read_text(encoding="utf-8"))
    return {name: item for name, item in manifest["components"].items() if item["kind"] == "project"}


def parse_tag(tag, components):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError("tag must be <component>/vX.Y.Z (three nonnegative integers, no leading zeros)")
    name, version = match.groups()
    if name not in components:
        raise ValueError(f"unknown component: {name}")
    return name, version


def version_of(directory, metadata):
    project = metadata.get("project", {})
    dynamic = metadata.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version")
    if "version" in project:
        if dynamic is not None or "version" in project.get("dynamic", []):
            raise CandidateError("version must have a single static or dynamic source")
        version = project["version"]
    else:
        if "version" not in project.get("dynamic", []) or not isinstance(dynamic, dict):
            raise CandidateError("missing static version or dynamic version attr")
        attr = dynamic.get("attr", "")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", attr) or not attr.endswith(".__version__"):
            raise CandidateError("dynamic version attr must reference a module's __version__")
        module, symbol = attr.rsplit(".", 1)
        package_dir = metadata.get("tool", {}).get("setuptools", {}).get("package-dir", {})
        parts = module.split(".")
        if parts[0] in package_dir:
            base = directory / package_dir[parts[0]]
            parts = parts[1:]
        else:
            base = directory / package_dir.get("", "")
        path = base.joinpath(*parts)
        candidates = [path / "__init__.py", path.with_suffix(".py")]
        if not package_dir:
            candidates += [directory / "src" / module.replace(".", "/") / "__init__.py",
                           directory / "src" / (module.replace(".", "/") + ".py")]
        files = [p for p in candidates if p.is_file()]
        if len(files) != 1:
            raise CandidateError("dynamic version module must resolve to exactly one source file")
        tree = ast.parse(files[0].read_text(encoding="utf-8"))
        values = []
        for node in tree.body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(target, ast.Name) and target.id == symbol for target in targets):
                try:
                    values.append(ast.literal_eval(node.value))
                except (ValueError, TypeError):
                    raise CandidateError("__version__ must be a literal string") from None
        if len(values) != 1:
            raise CandidateError("__version__ must have exactly one literal assignment")
        version = values[0]
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise CandidateError("version must be X.Y.Z")
    return version


def sections(text):
    headings = list(HEADING.finditer(text))
    result = []
    for match in headings:
        # Stop at any next level-two heading, including non-version headings.
        end = re.search(r"^## ", text[match.end():], re.M)
        stop = match.end() + end.start() if end else len(text)
        result.append((match.group(1), match.group(2).strip(), text[match.end():stop].strip(), match))
    return result


def dated(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def reason(name):
    return RELIA_REASON if name == "relia" else "component is not enabled for publication"


def check(directory, metadata, expected=None):
    problems = []
    build = metadata.get("build-system", {})
    if not build.get("requires") or not build.get("build-backend"):
        problems.append("pyproject must have [build-system] requires and build-backend")
    project = metadata.get("project", {})
    readme = project.get("readme")
    readme = readme.get("file") if isinstance(readme, dict) else readme
    if not isinstance(readme, str) or not (directory / readme).is_file():
        problems.append("readme must reference an existing file")
    if not isinstance(project.get("license"), str) or not project["license"].strip():
        problems.append("license must be an SPDX string")
    patterns = project.get("license-files")
    if not isinstance(patterns, list) or not patterns:
        problems.append("license-files must list existing files")
    else:
        for pattern in patterns:
            if not isinstance(pattern, str) or not any(p.is_file() for p in directory.glob(pattern)):
                problems.append(f"license-files target missing: {pattern}")
    version = None
    try:
        version = version_of(directory, metadata)
    except CandidateError as error:
        problems.append(str(error))
    if expected and version != expected:
        problems.append(f"version {version!r} does not equal tag version {expected}")
    target = expected or version
    entries = sections((directory / "CHANGELOG.md").read_text(encoding="utf-8")) if (directory / "CHANGELOG.md").is_file() else []
    matching = [entry for entry in entries if entry[0] == target]
    if len(matching) != 1:
        problems.append(f"CHANGELOG must contain exactly one section for version {target}")
    elif expected and not dated(matching[0][1]):
        problems.append(f"CHANGELOG version {target} must be dated YYYY-MM-DD")
    return version, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="inspect every project")
    status.add_argument("--json", action="store_true")
    checking = sub.add_parser("check", help="validate a candidate")
    choice = checking.add_mutually_exclusive_group(required=True)
    choice.add_argument("--tag")
    choice.add_argument("--component")
    notes = sub.add_parser("notes", help="extract changelog notes")
    notes.add_argument("--tag", required=True)
    prepare = sub.add_parser("prepare", help="date the current Unreleased entry")
    prepare.add_argument("component")
    prepare.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        components = projects(root)
        if args.command == "status":
            output = {}
            for name, item in components.items():
                directory = root / item["path"]
                metadata = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))
                try:
                    version = version_of(directory, metadata)
                    error = None
                except CandidateError as exc:
                    version, error = None, str(exc)
                path = directory / "CHANGELOG.md"
                entries = sections(path.read_text(encoding="utf-8")) if path.exists() else []
                tags = subprocess.run(["git", "tag", "--list", f"{name}/v*"], cwd=root,
                                      capture_output=True, text=True, check=True).stdout.splitlines()
                valid = [tag for tag in tags if TAG.fullmatch(tag)]
                latest = max(valid, key=lambda tag: tuple(map(int, tag.rsplit("/v", 1)[1].split("."))), default=None)
                output[name] = {"distribution": metadata.get("project", {}).get("name"), "version": version,
                                "version_error": error, "changelog_entry": entries[0][0] if entries else None,
                                "changelog_date": entries[0][1] if entries else None,
                                "changelog_dated": bool(entries and dated(entries[0][1])),
                                "license_present": (directory / "LICENSE").is_file(), "latest_tag": latest,
                                "publishable": name in PUBLISHABLE,
                                "reason": None if name in PUBLISHABLE else reason(name)}
            print(json.dumps(output, indent=2, ensure_ascii=False) if args.json else "\n".join(
                f"{name}: {json.dumps(item, ensure_ascii=False)}" for name, item in output.items()))
            return 0
        name, expected = parse_tag(args.tag, components) if getattr(args, "tag", None) else (args.component, None)
        if name not in components:
            raise ValueError(f"unknown component: {name}")
        if name not in PUBLISHABLE:
            print(reason(name), file=sys.stderr)
            return 1
        directory = root / components[name]["path"]
        if args.command == "notes":
            entries = [entry for entry in sections((directory / "CHANGELOG.md").read_text(encoding="utf-8")) if entry[0] == expected]
            if len(entries) != 1:
                raise CandidateError(f"CHANGELOG must contain exactly one section for {expected}")
            print(entries[0][2])
            return 0
        metadata = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))
        if args.command == "check":
            version, problems = check(directory, metadata, expected)
            for problem in problems:
                print(f"{name}: {problem}", file=sys.stderr)
            if not problems:
                print(f"{name} v{version}: release check passed")
            return int(bool(problems))
        if not dated(args.date):
            raise ValueError("--date must be a valid YYYY-MM-DD date")
        version = version_of(directory, metadata)
        path = directory / "CHANGELOG.md"
        text = path.read_text(encoding="utf-8")
        entries = [entry for entry in sections(text) if entry[0] == version]
        if len(entries) != 1 or entries[0][1] != "Unreleased":
            raise CandidateError(f"CHANGELOG version {version} must have exactly one Unreleased section; already dated or missing")
        match = entries[0][3]
        updated = text[:match.start()] + f"## [{version}] - {args.date}" + text[match.end():]
        with tempfile.TemporaryDirectory(prefix=".release-", dir=directory) as staging:
            staged = Path(staging) / "CHANGELOG.md"
            staged.write_text(updated, encoding="utf-8")
            staged.chmod(path.stat().st_mode & 0o777)
            os.replace(staged, path)
        print(f"{name} v{version}: dated {args.date}")
        return 0
    except CandidateError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, SyntaxError, subprocess.CalledProcessError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
