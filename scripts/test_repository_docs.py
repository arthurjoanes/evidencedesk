import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from check_repository_docs import (
    check_links,
    displayed_readme,
    external_urls,
    parse_document,
    publishable_files,
    read_documents,
)


class CloneDocumentationTests(unittest.TestCase):
    def test_gfm_www_autolinks_without_treating_filenames_as_urls(self):
        document = parse_document(
            "www.example.com database.py example.com https://example.org "
            "contact@example.com `[code](missing.md)`\n"
        )
        self.assertEqual(
            [target for _, target in document.links],
            ["http://www.example.com", "https://example.org", "mailto:contact@example.com"],
        )

    def test_external_inventory_includes_protocol_relative_links(self):
        document = parse_document(
            '<img src="//example.com/image.png">\n\n[web](https://example.com)\n'
        )
        self.assertEqual(
            external_urls({"README.md": document}),
            ["https://example.com", "https://example.com/image.png"],
        )

    def test_malformed_html_url_is_reported_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = {"README.md": parse_document('<a href="https://[bad">bad</a>')}
            self.assertEqual(
                check_links(root, {"README.md"}, documents)[0]["reason"], "invalid_url"
            )
            self.assertEqual(external_urls(documents), [])

    def test_symlink_documents_are_not_read_and_links_require_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            outside = Path(directory) / "outside.md"
            outside.write_text("# This must not be read", encoding="utf-8")
            try:
                (root / "alias.md").symlink_to(outside)
                (root / "broken.png").symlink_to(root / "absent.png")
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest(
                        "Windows symlinks require a privilege; also run this test on Linux"
                    )
                raise
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / "README.md").write_text("![UI](broken.png)", encoding="utf-8")
            files = publishable_files(root)
            self.assertIn("broken.png", files)
            documents = read_documents(root, files)
            self.assertNotIn("alias.md", documents)
            result = check_links(root, files, documents)
            self.assertEqual(len(result), 2)
            self.assertEqual({problem["reason"] for problem in result}, {"symlink_requires_review"})

    def test_gfm_links_and_github_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/case (1).md").write_text(
                '# Ação com `código`\n\n## Repetido\n\n## Repetido\n<a name="explicit"></a>\n',
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "[inline](docs/case%20(1).md#ação-com-código)\n\n"
                "[referência][case]\n\n[case]: <docs/case (1).md#repetido-1>\n\n"
                "| Caso | Destino |\n| --- | --- |\n"
                '| HTML | <a href="/docs/case%20(1).md#explicit">ir</a> |\n'
                "\n`[code](missing.md)`\n\n    [indented](missing.md)\n",
                encoding="utf-8",
            )
            self.assertEqual(check_links(root, {"README.md", "docs/case (1).md"}), [])

    def test_missing_anchor_in_same_document_and_case_sensitive_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Ação\n\n[bad](#acao)\n[wrong case](readme.md)\n[ok](#ação)",
                encoding="utf-8",
            )
            result = check_links(root, {"README.md"})
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["reason"], "missing_anchor")
            self.assertEqual(result[1]["target"], "readme.md")

    def test_html_anchors_and_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                '<img src="absent.png" alt="missing">\n'
                '<a href="page.html#bad">bad</a>\n'
                '<a href="page.html#good">good</a>\n',
                encoding="utf-8",
            )
            (root / "page.html").write_text('<h1 id="good">Title</h1>', encoding="utf-8")
            result = check_links(root, {"README.md", "page.html"})
            self.assertEqual([p["reason"] for p in result], ["missing", "missing_anchor"])

    def test_readme_precedence_and_repeated_heading_slugs(self):
        self.assertEqual(
            displayed_readme({"README.md", "docs/README.md", ".github/README.md"}),
            ".github/README.md",
        )
        self.assertEqual(parse_document("# Repeat\n\n## Repeat\n").anchors, {"repeat", "repeat-1"})

    def test_cli_fails_for_each_broken_fixture_and_accepts_valid_cycles(self):
        # A→B→A navigation is valid. Reference definitions are URLs, not aliases:
        # an attempted circular definition must fail as missing, never recurse.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text("cache/\n", encoding="utf-8")
            (root / "cache").mkdir()
            (root / "cache/image.png").write_bytes(b"ignored")
            (root / "other.md").write_text("[back](README.md#title)", encoding="utf-8")
            cases = [
                ("[bad](absent.md)", 1),
                ("[bad](#absent)", 1),
                ("![bad](cache/image.png)", 1),
                ("[a]\n\n[a]: [b]\n[b]: [a]\n", 1),
                ("# Title\n\n[valid](other.md)", 0),
            ]
            for markdown, expected in cases:
                with self.subTest(markdown=markdown):
                    (root / "README.md").write_text(markdown, encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).with_name("check_repository_docs.py")),
                            "--root",
                            str(root),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_ignored_screenshot_does_not_make_a_clone_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("![UI](cache/image.png)\n", encoding="utf-8")
            (root / "cache").mkdir()
            (root / "cache/image.png").write_bytes(b"local only")
            result = check_links(root, {"README.md"})
            self.assertEqual(result[0]["reason"], "not_in_clone")
            self.assertEqual(check_links(root, {"README.md", "cache/image.png"}), [])

    def test_code_examples_remote_urls_and_relative_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "[code](src)\n[web](https://example.com/missing)\n"
                "```md\n[example](missing.md)\n```\n"
                "[document](<docs/a file.md>)\n[ref]: docs/a%20file.md\n",
                encoding="utf-8",
            )
            (root / "docs").mkdir()
            (root / "docs/a file.md").write_text("# Content", encoding="utf-8")
            self.assertEqual(check_links(root, {"README.md", "src/main.py", "docs/a file.md"}), [])


if __name__ == "__main__":
    unittest.main()
