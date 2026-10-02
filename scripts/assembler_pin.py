"""Check that every example pins assembler-python at the same tag, and that each lock resolves it to the same commit.

    python3 scripts/assembler_pin.py                                 # every push: the examples agree with each other
    python3 scripts/assembler_pin.py --release TAG --remote          # a release: they pin TAG, as TAG points now
    python3 scripts/assembler_pin.py --release TAG --notes           # the release-notes line naming the pin

The CWA repositories are released under one tag name: the website, the assemblers, the demo and these examples. An
examples release at TAG must run against assembler-python at TAG. A tag can be moved, and uv.lock keeps the commit
the tag pointed to when the lock was written, so a release also checks that the tag still points there. After the
assembler's tag moves, run this in each example, then review the scenario diffs and commit them together:

    uv lock --upgrade-package contextwindowarchitecture-assembler && uv run scenarios.py --write

Standard library only, so it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "contextwindowarchitecture-assembler"
REPO = "https://github.com/contextwindowarchitecture/assembler-python"
UPGRADE = f"uv lock --upgrade-package {PACKAGE}"

# tag -> the commit it points to on GitHub now, or None when there is no such tag
Remote = Callable[[str], "str | None"]


@dataclass(frozen=True)
class Pin:
    example: str
    tag: str | None          # from pyproject.toml's [tool.uv.sources]
    locked_tag: str | None   # from uv.lock's source URL
    commit: str | None       # from uv.lock's source URL


def pins(root: Path = ROOT) -> list[Pin]:
    """The assembler pin of every example under root: each folder with a pyproject.toml and a uv.lock."""
    found = []
    for project in sorted(root.glob("*/pyproject.toml")):
        folder = project.parent
        if not (folder / "uv.lock").exists():
            continue
        source = tomllib.loads(project.read_text(encoding="utf-8")).get("tool", {}).get("uv", {}).get("sources", {}).get(PACKAGE, {})
        locked_tag = commit = None
        for package in tomllib.loads((folder / "uv.lock").read_text(encoding="utf-8")).get("package", []):
            if package.get("name") == PACKAGE and "git" in package.get("source", {}):
                url = urlsplit(package["source"]["git"])
                locked_tag = parse_qs(url.query).get("tag", [None])[0]
                commit = url.fragment or None
        found.append(Pin(folder.name, source.get("tag"), locked_tag, commit))
    return found


def check(found: list[Pin], *, release: str | None = None, remote: Remote | None = None) -> list[str]:
    """What is wrong with the pins, if anything. release: the tag being released. remote: looks a tag up on GitHub."""
    if not found:
        return ["no examples found"]
    problems = [f"{pin.example} pins the assembler without a tag; pin a tag of {REPO}" for pin in found if pin.tag is None]
    problems += [f"{pin.example}: pyproject.toml pins tag {pin.tag}, but uv.lock resolves tag {pin.locked_tag}; run {UPGRADE}"
                 for pin in found if pin.tag is not None and pin.locked_tag != pin.tag]
    tags = sorted({pin.tag for pin in found if pin.tag is not None})
    commits = sorted({pin.commit for pin in found if pin.commit is not None})
    if len(tags) > 1:
        problems.append("the examples pin different assembler tags: "
                        + ", ".join(f"{pin.example} {pin.tag}" for pin in found))
    if len(commits) > 1:
        problems.append("the examples lock different assembler commits: "
                        + ", ".join(f"{pin.example} {(pin.commit or '?')[:7]}" for pin in found))
    if problems:
        return problems
    tag, commit = tags[0], commits[0]
    if release is not None and tag != release:
        problems.append(f"the examples pin {tag}, not the release tag {release}: pin {release} in every example, then {UPGRADE}")
    if remote is not None:
        now = remote(tag)
        if now is None:
            problems.append(f"tag {tag} does not exist in {REPO}")
        elif now != commit:
            problems.append(f"the locks hold {commit[:7]}, but {tag} now points to {now[:7]}: run {UPGRADE} in every "
                            "example and review the scenario diffs")
    return problems


def github(tag: str) -> str | None:
    """The commit a tag of assembler-python points to now. An annotated tag's peeled line names the commit itself."""
    listed = subprocess.run(["git", "ls-remote", REPO, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                            capture_output=True, text=True, check=True).stdout.split("\n")
    refs = dict(reversed(line.split("\t")) for line in listed if line)
    return refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")


def notes(found: list[Pin]) -> str:
    """The release-notes line naming the assembler every example was tested against."""
    tag, commit = found[0].tag, found[0].commit or ""
    return (f"Every example pins [assembler-python `{tag}`]({REPO}/releases/tag/{tag}), resolved to commit "
            f"[`{commit[:7]}`]({REPO}/commit/{commit}).\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", metavar="TAG", help="the tag being released: every example must pin it")
    parser.add_argument("--remote", action="store_true", help="check the tag still points to the locked commit on GitHub")
    parser.add_argument("--notes", action="store_true", help="print the release-notes line instead of a summary")
    args = parser.parse_args(argv)
    found = pins()
    problems = check(found, release=args.release, remote=github if args.remote else None)
    if problems:
        print("assembler pin:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    if args.notes:
        sys.stdout.write(notes(found))
    else:
        print(f"{len(found)} examples pin assembler-python {found[0].tag} at {(found[0].commit or '')[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
