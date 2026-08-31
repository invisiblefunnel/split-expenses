"""Check the published landing page and the download it points at."""

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tools.build_site import SITE_FILES, build

DOWNLOAD = (
    "https://github.com/invisiblefunnel/split-expenses"
    "/releases/latest/download/split-expenses.zip"
)


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"a", "link", "script"}:
            target = values.get("href") or values.get("src")
            if target:
                self.links.append(target)


class SiteTest(unittest.TestCase):
    def test_build_is_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            output = build(Path(directory) / "public")
            index = (output / "index.html").read_text(encoding="utf-8")
            parser = LinkCollector()
            parser.feed(index)

            for name in SITE_FILES:
                self.assertTrue((output / name).is_file(), name)
            for target in parser.links:
                if target.startswith("./") and target != "./":
                    self.assertTrue((output / target[2:]).is_file(), target)

    def test_page_has_one_primary_heading_and_download(self):
        index = (Path(__file__).parents[1] / "site" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertEqual(index.count("<h1"), 1)
        self.assertIn(f'href="{DOWNLOAD}"', index)
        # A relative link would be a copy of the zip the site does not build.
        self.assertNotIn("downloads/split-expenses.zip", index)


if __name__ == "__main__":
    unittest.main()
