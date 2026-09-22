"""Check publishable Markdown paths and GitHub heading fragments, offline.

CommonMark parser with GFM tables, strikethrough and autolinks. HTTP destinations
are listed separately, never certified by this offline check. Install
scripts/requirements-docs.lock before running this developer tool.

Raw HTML contributes explicit id/name anchors only; GitHub sanitization and
renderer-generated HTML IDs require rendered review. Symlinks require review
instead of reading their targets from the working tree.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from github_slugger import GithubSlugger
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Document:
    links: list[tuple[int, str]] = field(default_factory=list)
    anchors: set[str] = field(default_factory=set)


class HTMLReferences(HTMLParser):
    def __init__(self, document: Document, line: int):
        super().__init__(convert_charrefs=True)
        self.document = document
        self.line = line

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if not value:
                continue
            if key in {"href", "src"}:
                self.document.links.append((self.line + self.getpos()[0] - 1, value))
            if key == "id" or (tag == "a" and key == "name"):
                self.document.anchors.add(value)


def parse_document(markdown: str) -> Document:
    document = Document()
    parser = MarkdownIt("gfm-like", {"html": True})
    tokens = parser.parse(markdown)
    slugger = GithubSlugger()
    for index, token in enumerate(tokens):
        line = token.map[0] + 1 if token.map else 1
        if token.type == "heading_open":
            text = "".join(
                child.content
                for child in tokens[index + 1].children or []
                if child.type in {"text", "code_inline", "image"}
            )
            document.anchors.add(slugger.slug(text))
        if token.type == "html_block":
            HTMLReferences(document, line).feed(token.content)
        children = token.children or []
        for child_index, child in enumerate(children):
            if child.type in {"link_open", "image"}:
                target = child.attrGet("href" if child.type == "link_open" else "src")
                if child.markup == "linkify" and child.type == "link_open":
                    # GFM accepts www. URLs, but not arbitrary bare domains or
                    # filenames such as database.py. Explicit Markdown links
                    # and <autolinks> have different markup and remain intact.
                    visible = children[child_index + 1].content.lower()
                    if not visible.startswith(("http://", "https://", "www.")) and not (
                        target and target.startswith("mailto:")
                    ):
                        continue
                if target:
                    document.links.append((line, target))
            elif child.type == "html_inline":
                HTMLReferences(document, line).feed(child.content)
            if child.type in {"softbreak", "hardbreak"}:
                line += 1
    return document


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
        if name and ((root / name).is_file() or (root / name).is_symlink())
    }


def local_path_problem(root: Path, relative: str) -> str | None:
    # GitHub and clones do not necessarily dereference a symlink like this
    # working tree. Require review without opening its target (even if missing).
    candidate = root
    for part in Path(relative).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            return "symlink_requires_review"
    if not candidate.resolve().is_relative_to(root.resolve()):
        return "outside_repository"
    return None


def read_documents(root: Path, files: set[str]) -> dict[str, Document]:
    return {
        name: parse_document((root / name).read_text(encoding="utf-8-sig"))
        for name in sorted(files)
        if name.lower().endswith(".md") and not local_path_problem(root, name)
    }


def displayed_readme(files: set[str], directory: str = "") -> str | None:
    # Repository landing page precedence, as documented by GitHub.
    locations = [directory] if directory else [".github", "", "docs"]
    for location in locations:
        for name in sorted(files):
            if (
                posixpath.dirname(name) == location
                and posixpath.basename(name).lower() == "readme.md"
            ):
                return name
    return None


def check_links(
    root: Path, files: set[str], documents: dict[str, Document] | None = None
) -> list[dict]:
    documents = read_documents(root, files) if documents is None else documents
    problems = [
        {"file": name, "line": 1, "target": name, "reason": reason}
        for name in sorted(files)
        if name.lower().endswith(".md") and (reason := local_path_problem(root, name))
    ]
    for name, document in documents.items():
        for line, target in document.links:
            try:
                parsed = urlsplit(target)
            except ValueError:
                problems.append(
                    {"file": name, "line": line, "target": target, "reason": "invalid_url"}
                )
                continue
            if parsed.scheme in {"http", "https", "mailto", "tel"} or parsed.netloc:
                continue
            reason = None
            if parsed.scheme or "\\" in target:
                reason = "machine_path_or_unsupported_scheme"
            path = unquote(parsed.path)
            relative = (
                posixpath.normpath(
                    path.lstrip("/")
                    if path.startswith("/")
                    else posixpath.join(posixpath.dirname(name), path)
                )
                if path
                else name
            )
            destination = root / relative
            if path_problem := local_path_problem(root, relative):
                reason = path_problem
            elif relative not in files:
                prefix = relative.rstrip("/") + "/" if relative != "." else ""
                if any(item.startswith(prefix) for item in files):
                    relative = (
                        displayed_readme(files, relative if relative != "." else "") or relative
                    )
                else:
                    reason = reason or ("not_in_clone" if destination.exists() else "missing")
            if not reason and parsed.fragment:
                fragment = unquote(parsed.fragment)
                if relative in documents:
                    if fragment not in documents[relative].anchors:
                        reason = "missing_anchor"
                elif destination.suffix.lower() in {".html", ".htm", ".svg"}:
                    html = Document()
                    HTMLReferences(html, 1).feed(destination.read_text(encoding="utf-8-sig"))
                    if fragment not in html.anchors:
                        reason = "missing_anchor"
                # Code-line/PDF-page fragments have other renderers: no Markdown claim.
            if reason:
                problems.append({"file": name, "line": line, "target": target, "reason": reason})
    return problems


def external_urls(documents: dict[str, Document]) -> list[str]:
    urls = set()
    for document in documents.values():
        for _, target in document.links:
            try:
                parsed = urlsplit(target)
            except ValueError:
                continue  # check_links reports malformed HTML URLs.
            if parsed.scheme in {"http", "https"}:
                urls.add(target)
            elif not parsed.scheme and parsed.netloc:
                urls.add("https:" + target)
    return sorted(urls)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--list-external", action="store_true", help="List HTTP links for separate network review"
    )
    args = parser.parse_args()
    files = publishable_files(args.root)
    documents = read_documents(args.root, files)
    problems = check_links(args.root, files, documents)
    external = external_urls(documents)
    result = {
        "documents": len(documents),
        "readme": displayed_readme(files),
        "links": sum(len(doc.links) for doc in documents.values()),
        "external_not_checked": len(external),
        "problems": problems,
    }
    if args.list_external:
        result["external_urls"] = external
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
