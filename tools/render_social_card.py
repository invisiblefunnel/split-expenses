#!/usr/bin/env python3
"""Render site/social-card.png from site/social-card.svg.

The card is drawn as an SVG, but the SVG is not what ships. X, Facebook,
LinkedIn and Slack all decline to render an SVG link preview, so index.html
points og:image at a PNG and this is what produces it. Run it by hand after
editing the card and commit the result: the Pages build only copies files, and
nothing rasterizes at deploy time.

Usage: python3 tools/render_social_card.py
Requires playwright with Chromium: pip install playwright && playwright install chromium

Chromium does the rasterizing because the card asks for its type through a CSS
font stack, and only a browser resolves that stack the way the page itself
does. The type you get is therefore the renderer's, not the file's: macOS has
the Iowan Old Style the stack names first, while on Linux the Palatino entry
needs fonts-urw-base35, which supplies the P052 clone it resolves to. Render
without those and the headline falls back to something the page never uses.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site" / "social-card.svg"
TARGET = ROOT / "site" / "social-card.png"

# The size every scraper documents, and the size index.html declares in
# og:image:width and og:image:height. A preview is cropped to those numbers
# whatever the file holds, so test_site.py reads them back out of the PNG and
# fails if the two ever drift apart.
WIDTH = 1200
HEIGHT = 630


def render(source=SOURCE, target=TARGET):
    """Rasterize the card at exactly WIDTH x HEIGHT and return its location."""

    # Imported here so the module stays readable without playwright installed:
    # png_size below is what the test suite wants, and CI installs no browser.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        # A standalone SVG document has no page margin to zero out, so a
        # viewport cut to the card's own size frames it exactly, edge to edge.
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.goto(Path(source).as_uri())
        page.screenshot(path=target)
        browser.close()

    return Path(target)


def png_size(path) -> tuple[int, int]:
    """Read a PNG's pixel dimensions out of the IHDR chunk of its header."""

    header = Path(path).read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return (
        int.from_bytes(header[16:20], "big"),
        int.from_bytes(header[20:24], "big"),
    )


def main() -> None:
    if extra := sys.argv[1:]:
        raise SystemExit(f"unexpected argument(s): {' '.join(extra)}")

    target = render()
    size = png_size(target)
    if size != (WIDTH, HEIGHT):
        raise SystemExit(f"expected {WIDTH}x{HEIGHT}, rendered {size[0]}x{size[1]}")

    kb = target.stat().st_size / 1024
    print(f"wrote {target.relative_to(ROOT)} ({WIDTH}x{HEIGHT}, {kb:.0f} KB)")


if __name__ == "__main__":
    main()
