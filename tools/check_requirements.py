#!/usr/bin/env python3
# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check every pinned requirement can actually be installed on this machine.

    python tools/check_requirements.py

WHY THIS EXISTS

"Latest version" and "version that works on your machine" are not the same
thing, and pip's error when they diverge is genuinely misleading. Ask for
vosk 0.3.45 on a Mac and pip says:

    Could not find a version that satisfies the requirement vosk==0.3.45
    (from versions: 0.3.38, ..., 0.3.44)

which reads as "that version does not exist". It does exist. It just ships no
macOS wheel, so pip cannot see it from where you are standing. The same shape
of failure applies to numpy 2.5 on Python 3.11, and to piper-tts 1.2 anywhere
near a Mac.

This asks PyPI directly and reports which of the three it is: the version does
not exist, or it exists but has nothing for your platform, or it exists but
needs a different Python.

Stdlib only, so it runs before anything is installed -- which is the whole
point.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import urllib.error
import urllib.request

PYPI = "https://pypi.org/pypi/{name}/json"
PIN = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._+!-]+)\s*(?:#.*)?$")


def wheel_matches_platform(filename: str) -> bool:
    """Whether a wheel could plausibly install here.

    Deliberately coarse: matching PEP 425 tags properly needs `packaging`,
    which may not be installed yet. Coarse is enough to catch the failure this
    script is for -- a package with NO file for your operating system at all.
    """
    name = filename.lower()
    if name.endswith(".tar.gz") or name.endswith(".zip"):
        return True  # an sdist can at least be attempted
    if "-py3-none-any" in name or "-none-any" in name:
        return True

    system = platform.system()
    if system == "Darwin":
        return "macosx" in name
    if system == "Windows":
        return "win32" in name or "win_amd64" in name or "win_arm64" in name
    return "linux" in name  # manylinux, musllinux, linux_armv7l


def python_ok(requires: str | None) -> bool:
    """Very rough Requires-Python check for the common `>=X.Y` form."""
    if not requires:
        return True
    current = sys.version_info[:2]
    for clause in requires.split(","):
        clause = clause.strip()
        match = re.match(r"^(>=|>|<=|<)\s*(\d+)\.(\d+)", clause)
        if not match:
            continue
        operator, major, minor = match.group(1), int(match.group(2)), int(match.group(3))
        target = (major, minor)
        if operator == ">=" and current < target:
            return False
        if operator == ">" and current <= target:
            return False
        if operator == "<=" and current > target:
            return False
        if operator == "<" and current >= target:
            return False
    return True


def read_pins(path: str) -> list[tuple[str, str]]:
    pins = []
    with open(path) as handle:
        for line in handle:
            if line.lstrip().startswith("#"):
                continue
            match = PIN.match(line)
            if match:
                pins.append((match.group(1), match.group(2)))
    return pins


def check(name: str, version: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(PYPI.format(name=name), timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "no such package on PyPI"
        return False, f"PyPI returned {e.code}"
    except Exception as e:
        return False, f"could not reach PyPI ({e})"

    files = data["releases"].get(version)
    if files is None:
        latest = data["info"]["version"]
        return False, f"version does not exist (latest is {latest})"
    if not files:
        return False, "version exists but has no files at all"

    usable = [f for f in files if wheel_matches_platform(f["filename"])]
    if not usable:
        platforms = sorted({_platform_of(f["filename"]) for f in files})
        return False, (
            f"exists, but ships nothing for {platform.system()} (has: {', '.join(platforms)})"
        )

    if not any(python_ok(f.get("requires_python")) for f in usable):
        needs = next((f.get("requires_python") for f in usable), "?")
        return False, (
            f"exists, but needs Python {needs} "
            f"(you have {sys.version_info.major}.{sys.version_info.minor})"
        )

    return True, f"{len(usable)} usable file(s)"


def _platform_of(filename: str) -> str:
    lowered = filename.lower()
    for tag in ("macosx", "manylinux", "musllinux", "linux_armv7l", "win_amd64", "win32"):
        if tag in lowered:
            return tag
    return "any"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", default="requirements.txt")
    args = parser.parse_args()

    print(
        f"Python {sys.version_info.major}.{sys.version_info.minor} "
        f"on {platform.system()} {platform.machine()}\n"
    )

    pins = read_pins(args.requirements)
    if not pins:
        print(f"No pinned requirements found in {args.requirements}.")
        return 1

    failures = 0
    for name, version in pins:
        ok, detail = check(name, version)
        mark = "ok  " if ok else "FAIL"
        print(f"  [{mark}] {name}=={version}  {detail}")
        if not ok:
            failures += 1

    print()
    if failures:
        print(f"{failures} requirement(s) will not install here.")
        print("A 'ships nothing for your platform' result is NOT a typo in the")
        print("pin -- pip will report it as though the version does not exist.")
        return 1

    print("All requirements have a usable distribution. Safe to install.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
