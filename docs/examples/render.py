"""Render the README artwork from chat.html.

Produces the animated demo.svg at the top of the README. See animate.py for
how the animation is built and why it is an SVG.

Usage: python3 docs/examples/render.py
Requires playwright with Chromium: pip install playwright && playwright install chromium
fonttools subsets the animation's fonts, if it happens to be installed.
"""

import sys
from pathlib import Path

import animate

HERE = Path(__file__).resolve().parent
IMAGES = HERE.parent / "images"


def main() -> None:
    if extra := sys.argv[1:]:
        raise SystemExit(f"unexpected argument(s): {' '.join(extra)}")

    IMAGES.mkdir(exist_ok=True)
    target = IMAGES / "demo.svg"
    animate.build(target)
    print(f"wrote {rel(target)} ({target.stat().st_size / 1024:.0f} KB)")


def rel(target: Path) -> str:
    return str(target.relative_to(HERE.parent.parent))


if __name__ == "__main__":
    main()
