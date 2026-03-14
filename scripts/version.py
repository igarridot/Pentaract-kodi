#!/usr/bin/env python3

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ADDON_XML_FILES = [
    ROOT / "plugin.video.pentaract" / "addon.xml",
    ROOT / "repository.pentaract" / "addon.xml",
]
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ADDON_VERSION_RE = re.compile(r'(<addon\b[^>]*\bversion=")([^"]+)(")', re.MULTILINE)


def read_addon_version(path):
    text = path.read_text(encoding="utf-8")
    match = ADDON_VERSION_RE.search(text)
    if not match:
        raise ValueError("No version attribute found in %s" % path)
    return match.group(2)


def current_version():
    versions = {read_addon_version(path) for path in ADDON_XML_FILES}
    if len(versions) != 1:
        raise ValueError("Addon versions are not aligned: %s" % ", ".join(sorted(versions)))

    version = versions.pop()
    if not SEMVER_RE.match(version):
        raise ValueError("Current addon version is not semantic: %s" % version)
    return version


def latest_tag():
    result = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=version:refname"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for tag in reversed(tags):
        if TAG_RE.match(tag):
            return tag
    return ""


def next_version():
    tag = latest_tag()
    if not tag:
        return current_version()

    match = TAG_RE.match(tag)
    if not match:
        raise ValueError("Latest tag is not semantic: %s" % tag)

    major, minor, patch = [int(value) for value in match.groups()]
    return "%d.%d.%d" % (major, minor, patch + 1)


def set_version(version):
    if not SEMVER_RE.match(version):
        raise ValueError("Invalid semantic version: %s" % version)

    for path in ADDON_XML_FILES:
        text = path.read_text(encoding="utf-8")
        updated, replacements = ADDON_VERSION_RE.subn(r"\g<1>%s\g<3>" % version, text, count=1)
        if replacements != 1:
            raise ValueError("Failed to update version in %s" % path)
        path.write_text(updated, encoding="utf-8")


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: version.py <current|next|set VERSION>")

    command = argv[1]
    if command == "current":
        print(current_version())
        return
    if command == "next":
        print(next_version())
        return
    if command == "set" and len(argv) == 3:
        set_version(argv[2])
        print(argv[2])
        return

    raise SystemExit("usage: version.py <current|next|set VERSION>")


if __name__ == "__main__":
    main(sys.argv)
