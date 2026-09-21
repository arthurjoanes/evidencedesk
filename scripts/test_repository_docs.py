import tempfile
import unittest
from pathlib import Path

from check_repository_docs import check_links


class CloneDocumentationTests(unittest.TestCase):
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
