"""Check that local Markdown links will survive a clone, including images.

Only Git-tracked or non-ignored new files count as publishable. Files in a local
cache do not satisfy a link. Remote URLs are not fetched by this offline check.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
HTML_ASSET = re.compile(r"\b(?:src|href)=[\"']([^\"']+)[\"']")


def publishable_files(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return {
        name
        for name in result.stdout.decode("utf-8").split("\0")
        if name and (root / name).is_file()
    }


def links(markdown: str):
    fence = None
    for line_number, line in enumerate(markdown.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        for pattern in (LINK, REFERENCE, HTML_ASSET):
            for match in pattern.finditer(line):
                yield line_number, match.group(1).strip("<>")


def check_links(root: Path, files: set[str]) -> list[dict]:
    problems = []
    for name in sorted(files):
        if not name.lower().endswith(".md"):
            continue
        document = root / name
        for line, target in links(document.read_text(encoding="utf-8-sig")):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (document.parent / unquote(parsed.path)).resolve()
            try:
                relative = destination.relative_to(root.resolve()).as_posix()
            except ValueError:
                reason = "outside_repository"
            else:
                if relative in files or any(
                    path.startswith(relative.rstrip("/") + "/") for path in files
                ):
                    continue
                reason = "not_in_clone" if destination.exists() else "missing"
            problems.append({"file": name, "line": line, "target": target, "reason": reason})
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    files = publishable_files(args.root)
    problems = check_links(args.root, files)
    print(
        json.dumps(
            {"documents": sum(p.endswith(".md") for p in files), "problems": problems},
            indent=2,
            ensure_ascii=False,
        )
    )
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
