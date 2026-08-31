"""Check the published landing page and the download it points at."""

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tools.build_site import SITE_FILES, build
from tools.render_social_card import HEIGHT, WIDTH, png_size

SITE = Path(__file__).parents[1] / "site"
DOWNLOAD = (
    "https://github.com/invisiblefunnel/split-expenses"
    "/releases/latest/download/split-expenses.zip"
)


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"a", "link", "script"}:
            target = values.get("href") or values.get("src")
            if target:
                self.links.append(target)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key:
                self.meta[key] = values.get("content", "")


def read_page():
    parser = LinkCollector()
    parser.feed((SITE / "index.html").read_text(encoding="utf-8"))
    return parser


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
        index = (SITE / "index.html").read_text(encoding="utf-8")

        self.assertEqual(index.count("<h1"), 1)
        self.assertIn(f'href="{DOWNLOAD}"', index)
        # A relative link would be a copy of the zip the site does not build.
        self.assertNotIn("downloads/split-expenses.zip", index)

    def test_social_card_is_fetchable_by_a_scraper(self):
        # A link preview is assembled by a crawler that has the URL and
        # nothing else: it does not run the page, and it does not resolve a
        # relative path the way a browser would. Both failures are silent —
        # the page looks right, and the preview is simply blank.
        meta = read_page().meta
        card = meta["og:image"]

        self.assertTrue(card.startswith("https://"), card)
        self.assertTrue(card.endswith(".png"), card)
        self.assertEqual(meta["og:image:type"], "image/png")
        self.assertTrue(meta["og:url"].startswith("https://"), meta["og:url"])
        self.assertTrue(meta.get("og:image:alt"))

        # Same origin for the page and its card, so one domain move cannot
        # leave the preview pointing at a host the site no longer answers on.
        origin = meta["og:url"].rstrip("/")
        self.assertTrue(card.startswith(f"{origin}/"), card)

        name = card.rsplit("/", 1)[-1]
        with tempfile.TemporaryDirectory() as directory:
            output = build(Path(directory) / "public")
            self.assertTrue((output / name).is_file(), name)

    def test_social_card_matches_the_size_it_declares(self):
        # Scrapers lay the preview out from these numbers before the image
        # arrives, and crop to them, so a re-render at another size has to
        # bring the meta tags along with it.
        meta = read_page().meta
        card = SITE / meta["og:image"].rsplit("/", 1)[-1]

        self.assertEqual(png_size(card), (WIDTH, HEIGHT))
        self.assertEqual(int(meta["og:image:width"]), WIDTH)
        self.assertEqual(int(meta["og:image:height"]), HEIGHT)


if __name__ == "__main__":
    unittest.main()
