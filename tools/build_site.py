#!/usr/bin/env python3
"""Build the static landing page and its downloadable skill bundle."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site"
OUTPUT = ROOT / "dist" / "site"
SITE_FILES = (
    "favicon.svg",
    "index.html",
    "script.js",
    # The card ships as the PNG only. social-card.svg beside it is the drawing
    # it was rendered from, by tools/render_social_card.py; nothing links to
    # the SVG, and no scraper would render it if anything did.
    "social-card.png",
    "styles.css",
)


def build(output=OUTPUT):
    """Write a self-contained Pages artifact and return its location."""

    # Nothing here names the custom domain, and the page names it only where a
    # relative URL cannot work: Cloudflare Pages attaches splitexpenses.ai to
    # the project, not to a file in the uploaded tree, so the site is reachable
    # under a preview URL too. The exception is index.html's og:image, which a
    # scraper fetches with no page to resolve it against.
    #
    # The skill zip is not built here either. The page links to the release
    # asset, so the archive has exactly one producer — the Release workflow —
    # and a visitor downloads the same bytes a tag published rather than
    # whatever happened to be on main when the page was last deployed.
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for name in SITE_FILES:
        shutil.copy2(SOURCE / name, output / name)

    return output


if __name__ == "__main__":
    print(build())
