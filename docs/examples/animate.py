"""Build docs/images/demo.svg — the example conversation, playing out.

chat.html is reused verbatim: its stylesheet and its four parts are lifted out,
joined into one conversation, and wrapped in an SVG <foreignObject>. GitHub
strips <video> and <iframe> from READMEs, but it serves SVG, and CSS animation
inside an SVG keeps running when the file is referenced by a plain <img>.

It is drawn as a phone. chat.html is written for a wide card, which is how it
renders when you open it in a browser to check the conversation; _compose
restyles a copy of it down to a phone column rather than editing chat.html
itself, so the source stays legible on its own.

The conversation arrives a message at a time: you send, a typing bubble beats,
the reply lands. Nothing is hidden with display:none — every message holds its
final place in the layout from the start and is merely transparent, and the
column is offset just far enough to keep the newest message at the foot of the
screen. Messages that have not arrived yet are therefore below the fold, and the
space they reserve is off-screen and invisible. That is what makes an
opacity-only reveal look like a chat filling up.

Three consequences of the <img> context are worth knowing before editing this:

  * The SVG is parsed as strict XML, not HTML. Void tags have to self-close and
    &nbsp; is not a defined entity, so the markup goes through xmlify() first.
  * Nothing external loads — no webfont request, no stylesheet. The fonts are
    subset to the characters this conversation actually uses and inlined as
    base64, which is most of the file size.
  * prefers-color-scheme does reach the SVG, so one file serves both themes and
    no <picture> element is needed. prefers-reduced-motion does not reach it in
    Chromium, Firefox or WebKit, which is why the pacing here is unhurried and
    why the README's alt text describes the whole conversation.

Usage: python3 docs/examples/render.py   (this module is not a CLI)
Needs playwright to measure the laid-out result, and fonttools+brotli to subset
the fonts; without fonttools the build still runs but falls back to whatever
sans-serif the reader happens to have.
"""

import base64
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "chat.html"

# A phone held against the page. The nav bar is fixed furniture at the top of
# the device; the screen below it is what scrolls. chat.html itself is laid out
# for a wide card, so _compose restyles it down to this column — the still
# screenshots keep the wide look and are not affected.
# Wide enough that the device shadow below falls inside the canvas rather than
# being clipped square against its edge.
FRAME_PAD = 44
PHONE_W = 390
PHONE_H = 760
NAV_H = 52
SCREEN_H = PHONE_H - NAV_H
SCREEN_PAD = 16
VIEW_W = PHONE_W + 2 * FRAME_PAD
VIEW_H = PHONE_H + 2 * FRAME_PAD

NAV_TITLE = "Paris trip"

# Seconds. A message is held long enough to read — DWELL_MIN plus a beat per
# CPS characters, capped at DWELL_MAX — and the reply is preceded by a typing
# bubble. The tail holds the finished conversation, fades it, and rewinds.
#
# SETTLE is how long the column takes to reach a new resting place, and nothing
# fades in until it has arrived. Scrolling and fading at once looks right for a
# one-line bubble and wrong for a table: the opacity ramp finishes first, so the
# message is legible while its last hundred-odd pixels are still below the
# screen edge, and a settlement table reads as clipped every loop.
SETTLE = 0.3
FADE = 0.35
TYPING = 0.6
DWELL_MIN = 0.75
DWELL_MAX = 2.4
CPS = 120.0
FINAL_HOLD = 2.4
FADE_OUT = 0.7
REWIND = 0.6

# Which of chat.html's four parts the demo plays. The whole conversation is 18
# messages and cannot be both unhurried and brief; drop parts here to trade
# coverage for a shorter loop. The still screenshots below it cover all four.
INCLUDE_PARTS = (1, 2, 3, 4)

# (css family, weight, fontconfig pattern). Every weight chat.html asks for.
FONTS = (
    ("Inter", 400, "Inter:style=Regular"),
    ("Inter", 500, "Inter:style=Medium"),
    ("Inter", 600, "Inter:style=SemiBold"),
    ("Inter", 700, "Inter:style=Bold"),
    ("JetBrains Mono", 400, "JetBrains Mono:style=Regular"),
    ("JetBrains Mono", 700, "JetBrains Mono:style=Bold"),
)


def build(target: Path) -> None:
    """Write the animated SVG to target."""
    html = SOURCE.read_text(encoding="utf-8")
    css, beats = _parse(html)
    markup, count = _tag(beats)
    fonts = _font_faces(_charset(beats))

    # Pass one has no timeline: it exists only to be laid out and measured.
    target.write_text(_compose(css, fonts, markup, ""), encoding="utf-8")
    messages, typing_h = _measure(target, count)
    timeline = _timeline(messages, typing_h)
    target.write_text(_compose(css, fonts, markup, timeline), encoding="utf-8")


def _parse(html: str) -> tuple[str, list[str]]:
    """Pull the stylesheet and the four parts out of chat.html."""
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)

    frames = re.findall(
        r'^<div class="frame" id="part-\d">\n(.*?)^</div>$', html, re.S | re.M
    )
    if len(frames) != 4:
        raise SystemExit(f"expected 4 parts in chat.html, found {len(frames)}")

    beats = []
    for part, frame in enumerate(frames, start=1):
        if part not in INCLUDE_PARTS:
            continue
        body = re.search(r'<div class="chat">\n(.*?)\n\s*</div>\s*$', frame, re.S)
        if not body:
            raise SystemExit("could not find the .chat block inside a part")
        # It reads as one unbroken conversation here, so the markers that let
        # each still open mid-chat would be wrong.
        beats.append(re.sub(r'\s*<div class="earlier">.*?</div>', "", body.group(1)))
    return css, beats


def _tag(beats: list[str]) -> tuple[str, int]:
    """Number every message, and give each reply a typing bubble to wait behind.

    The bubble is a sibling of the reply, not a child of it: a parent at
    opacity 0 composites its children away whatever their own opacity, so a
    bubble nested inside the reply it announces could never be seen. It is
    positioned absolutely — _timeline pins it to the measured top of its reply
    — which also keeps it out of the flex flow, so it never moves anything.
    """
    markup = "\n".join(xmlify(beat) for beat in beats)
    dots = "".join("<span></span>" for _ in range(3))
    index = 0

    def number(match: re.Match) -> str:
        nonlocal index
        indent, kind = match.group(1), match.group(2)
        tag = f'{indent}<div class="{kind} m{index}">'
        if kind == "assistant":
            tag = f'{indent}<div class="typing t{index}">{dots}</div>\n{tag}'
        index += 1
        return tag

    # Every message is a direct child of .chat, so it sits at one indent level.
    markup = re.sub(r'(?m)^(\s*)<div class="(from-user|assistant)">', number, markup)
    if index == 0:
        raise SystemExit("found no messages to animate")
    return markup, index


def _adapt(css: str) -> str:
    """Retarget chat.html's stylesheet at an SVG that has no html or body."""
    light = re.search(r":root\s*\{(.*?)\}", css, re.S)
    dark = re.search(r'\[data-theme="dark"\]\s*\{(.*?)\}', css, re.S)
    if not (light and dark):
        raise SystemExit("could not find the :root / [data-theme] colour blocks")

    rest = css.replace(light.group(0), "").replace(dark.group(0), "")

    # There is no <body> here, so its rule would match nothing and the text
    # would quietly inherit the document default — a serif face — instead of
    # Inter. .frame is the outermost element, so it inherits the same way.
    rest, swapped = re.subn(r"(?m)^\s*body\s*\{", ".frame {", rest)
    if swapped != 1:
        raise SystemExit(f"expected exactly one body rule, retargeted {swapped}")

    return (
        f".frame {{{light.group(1)}}}\n"
        f"@media (prefers-color-scheme: dark) {{ .frame {{{dark.group(1)}}} }}\n"
        f"{rest}"
    )


def xmlify(markup: str) -> str:
    """HTML a browser forgives, rewritten as the XML an SVG parser demands."""
    markup = markup.replace("&nbsp;", "&#160;")
    return re.sub(r"<(hr|br|img|meta)\b([^>]*?)/?>", r"<\1\2/>", markup)


def _charset(beats: list[str]) -> set[str]:
    """Every character that has to survive font subsetting."""
    # xmlify rewrites &nbsp; as &#160;, so it is a real no-break space that
    # ends up in the file, and the subset has to carry it.
    nbsp = "\u00a0"
    text = re.sub(r"<[^>]+>", "", "\n".join(beats)).replace("&nbsp;", nbsp)
    # "new" is drawn by a ::after content rule, so it is not in the markup, and
    # the nav title is added by _compose rather than coming from chat.html.
    return (set(text) | set("new") | set(NAV_TITLE) | {" ", nbsp}) - set("\n\r\t")


def _font_faces(chars: set[str]) -> str:
    """Subset each font to chars and inline it as a base64 @font-face."""
    try:
        from fontTools import subset
    except ImportError:
        print("  ! fonttools not installed — skipping font embedding")
        print("    (readers without Inter installed will see a fallback face)")
        return ""

    unicodes = ",".join(f"U+{ord(c):04X}" for c in sorted(chars))
    faces = []
    for family, weight, pattern in FONTS:
        path = _resolve(family, pattern)
        if not path:
            print(f"  ! {family} {weight} not installed — skipping")
            continue
        # The font lives in a system directory, so subset into a temp file.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"subset-{weight}.woff2"
            subset.main(
                [
                    str(path),
                    f"--unicodes={unicodes}",
                    # chat.html asks Inter for these stylistic sets; the
                    # default subsetting profile would drop them.
                    "--layout-features+=cv05,ss03",
                    "--flavor=woff2",
                    f"--output-file={out}",
                ]
            )
            blob = base64.b64encode(out.read_bytes()).decode()
        faces.append(
            f"@font-face {{ font-family: '{family}'; font-weight: {weight};"
            f" font-style: normal;"
            f" src: url(data:font/woff2;base64,{blob}) format('woff2'); }}"
        )
    return "\n".join(faces)


def _resolve(family: str, pattern: str) -> Path | None:
    """Ask fontconfig for a font file, refusing its consolation prizes."""
    if not shutil.which("fc-match"):
        return None
    got = subprocess.run(
        ["fc-match", "-f", "%{family}\t%{file}", pattern],
        capture_output=True,
        text=True,
    )
    if got.returncode != 0 or "\t" not in got.stdout:
        return None
    # fc-match always answers, so check it answered with the font we asked for.
    families, _, path = got.stdout.partition("\t")
    if family.lower() not in families.lower():
        return None
    return Path(path) if path else None


def _compose(css: str, fonts: str, markup: str, timeline: str) -> str:
    """Assemble the SVG. Called twice: once to measure, once for real."""
    layout = f"""
  .frame {{ width: {VIEW_W}px; padding: {FRAME_PAD}px; }}

  .phone {{
    width: {PHONE_W}px; height: {PHONE_H}px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 44px;
    overflow: hidden;
    box-shadow: 0 14px 30px rgba(0, 0, 0, 0.13);
  }}

  .nav {{
    height: {NAV_H}px;
    display: flex;
    align-items: center;
    padding: 0 20px;
    border-bottom: 1px solid var(--line);
  }}
  .nav-side {{ width: 26px; display: flex; align-items: center; }}
  .nav-title {{
    flex: 1;
    text-align: center;
    font-size: 15px;
    font-weight: 600;
  }}
  /* Drawn rather than typed, so the nav needs no glyph the subset might lack. */
  .chevron {{
    width: 9px; height: 9px;
    border-left: 2px solid var(--muted);
    border-bottom: 2px solid var(--muted);
    border-radius: 1px;
    transform: rotate(45deg);
  }}
  .nav-dots {{ justify-content: flex-end; gap: 3px; }}
  .nav-dots span {{
    width: 3.5px; height: 3.5px;
    border-radius: 50%;
    background: var(--muted);
  }}

  /* The screen clips the scroll; the column inside it carries what .chat
     carries in the HTML, minus the box itself. The column hangs from the foot
     of the screen rather than sitting on its head, which is what lets
     _anchor measure backwards from the end of the conversation. */
  .screen {{ height: {SCREEN_H}px; overflow: hidden; position: relative; }}
  .column {{
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: {SCREEN_PAD}px;
    will-change: transform;
  }}

  /* chat.html is sized for an 812px card. Everything below narrows it to the
     phone column — the tables above all, whose 420px minimum would otherwise
     push straight through the side of the device. */
  .bubble {{ font-size: 14px; border-radius: 16px; padding: 9px 13px; }}
  .assistant {{ font-size: 14px; max-width: 100%; }}
  .assistant p {{ margin: 0 0 9px; }}
  .label {{ font-size: 12.5px; margin: 0 0 7px; }}
  table {{ min-width: 0; width: 100%; font-size: 12.5px; }}
  th, td {{ padding: 6px 10px; }}
  .new td:first-child::after {{ font-size: 9.5px; margin-left: 7px; }}
  .photo {{ width: 196px; height: 224px; border-radius: 12px; }}
  .receipt {{ left: 15px; top: 11px; width: 168px; font-size: 7.5px; }}
  .receipt .where, .receipt .foot {{ font-size: 6.2px; }}
  .tool {{ font-size: 11px; padding: 5px 10px; margin-bottom: 11px; }}
  .payment {{
    min-width: 0;
    width: 100%;
    font-size: 13px;
    padding: 9px 13px;
    gap: 12px;
  }}

  /* Every message keeps its place in the layout and only fades in, so the
     column never reflows mid-animation. */
  .from-user, .assistant {{ opacity: 0; }}

  /* Out of flow, pinned by _timeline so it beats where its reply will begin. */
  .typing {{
    position: absolute;
    left: {SCREEN_PAD}px;
    display: flex;
    gap: 5px;
    align-items: center;
    padding: 13px 15px;
    border-radius: 16px;
    background: var(--bubble);
    opacity: 0;
  }}
  .typing span {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--muted);
    animation: blink 1.25s ease-in-out infinite;
  }}
  .typing span:nth-child(2) {{ animation-delay: 0.16s; }}
  .typing span:nth-child(3) {{ animation-delay: 0.32s; }}
  @keyframes blink {{
    0%, 65%, 100% {{ opacity: 0.3; }}
    32% {{ opacity: 1; }}
  }}
"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" role="img"
     width="{VIEW_W}" height="{VIEW_H}" viewBox="0 0 {VIEW_W} {VIEW_H}">
<title>The example conversation: expenses recorded in plain language,
balances updating, and the final settlement.</title>
<style><![CDATA[
{fonts}
{_adapt(css)}
{layout}
{timeline}
]]></style>
<foreignObject x="0" y="0" width="{VIEW_W}" height="{VIEW_H}">
<div xmlns="http://www.w3.org/1999/xhtml" class="frame">
<div class="phone">
<div class="nav">
<div class="nav-side"><div class="chevron"></div></div>
<div class="nav-title">{NAV_TITLE}</div>
<div class="nav-side nav-dots"><span></span><span></span><span></span></div>
</div>
<div class="screen">
<div class="column">
{markup}
</div>
</div>
</div>
</div>
</foreignObject>
</svg>
"""


def _measure(svg: Path, count: int) -> tuple[list[dict], float]:
    """Lay the SVG out for real and read back where every message sits."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H})
        page.goto(svg.as_uri())
        page.wait_for_timeout(300)
        messages, typing_h = page.evaluate("""() => {
            const column = document.querySelector('.column');
            const pad = parseFloat(getComputedStyle(column).paddingTop);
            const typing = document.querySelector('.typing');
            // The typing bubbles are children too, but they are out of flow.
            const flow = column.querySelectorAll(
                ':scope > .from-user, :scope > .assistant');
            return [
              [...flow].map(el => {
                // The receipt is a photograph. Its printed text is not
                // something the viewer reads, so it must not drive the dwell;
                // a flat beat to register the image stands in for it.
                const photo = el.querySelector('.photo');
                const read = el.innerText.trim().length
                           - (photo ? photo.innerText.trim().length : 0);
                return {
                  top: el.offsetTop - pad,
                  bottom: el.offsetTop - pad + el.offsetHeight,
                  reply: el.classList.contains('assistant'),
                  chars: read + (photo ? 90 : 0),
                };
              }),
              typing ? typing.offsetHeight : 0,
            ];
        }""")
        browser.close()

    if len(messages) != count:
        raise SystemExit(f"tagged {count} messages but laid out {len(messages)}")
    return messages, typing_h


def _anchor(mark: float, floor: float) -> int:
    """How far the column drops to bring mark to the foot of the screen.

    The column hangs from the foot of the screen, so a position is a distance
    back from the end of the conversation — floor being where the conversation
    ends — rather than a distance from its start. That is what keeps the finish
    safe. These offsets are laid out here and then read by whatever engine
    renders the SVG, and engines break lines slightly differently: one bubble
    wrapping to a line more than it does here shifts everything after it. Any
    such drift is above the mark it displaces, so measuring backwards absorbs
    it into the messages already scrolled off the top. Measured forwards it
    accumulated instead, and pushed the closing settlement off the bottom.
    """
    return round(floor - mark)


def _timeline(messages: list[dict], typing_h: float) -> str:
    """Turn the measured layout into one shared, looping timeline.

    Every element gets an animation of the same total length so they stay in
    step; what differs is the percentage at which each one does its bit.
    """
    # Walk the conversation once, in seconds, recording what happens when.
    reveals: list[tuple[float, float]] = []  # (fade start, fade end)
    typings: list[tuple[int, float, float]] = []  # (index, show, hide)
    # Where the conversation ends, and so where every position is measured back
    # from. The column's content stops at the last message; the padding below it
    # is the gap the finished chat rests on.
    floor = messages[-1]["bottom"]
    # Open where the first message will land, so it arrives against the foot of
    # the screen instead of sliding in from wherever the column happens to sit.
    scroll: list[tuple[float, int]] = [(0.0, _anchor(messages[0]["bottom"], floor))]
    clock = 0.0

    # A move that lands on something the viewer has yet to see can start early
    # and run under the dwell before it — the screen is quiet, and arriving
    # settled costs the loop nothing. Only the move out from behind a typing
    # bubble has to be paid for in full.
    def early(at: float) -> float:
        return max(0.0, at - SETTLE)

    for i, message in enumerate(messages):
        if message["reply"]:
            # Hold the typing bubble where the reply is about to appear.
            scroll.append((early(clock), _anchor(message["top"] + typing_h, floor)))
            typings.append((i, clock, clock + TYPING))
            clock += TYPING
            # The bubble has to be gone before the column moves again, or it
            # slides up the screen on its way out, so this one cannot borrow.
            scroll.append((clock, _anchor(message["bottom"], floor)))
            clock += SETTLE
        else:
            scroll.append((early(clock), _anchor(message["bottom"], floor)))
        reveals.append((clock, clock + FADE))
        clock += FADE + _dwell(message["chars"])

    end = clock + FINAL_HOLD
    blank = end + FADE_OUT
    total = blank + REWIND

    def pct(at: float) -> float:
        return at / total * 100

    rules = [
        f"  .column {{ animation: scroll {total:.1f}s ease-in-out infinite; }}",
        f"  .from-user, .assistant {{ animation-duration: {total:.1f}s;"
        " animation-iteration-count: infinite; }",
        f"  .typing {{ animation-duration: {total:.1f}s;"
        " animation-iteration-count: infinite; }",
    ]

    # A position is how much conversation is still to come, and the column
    # carries that much of itself below the screen — so it is pushed down by it.
    def shift(offset: int) -> str:
        return f"transform: translateY({offset}px);"

    # The scroll holds each position until the next event asks it to move.
    steps = [f"    0% {{ {shift(scroll[0][1])} }}"]
    for (_, y), (at, next_y) in zip(scroll, scroll[1:]):
        if next_y != y:
            steps.append(f"    {pct(at):.3f}% {{ {shift(y)} }}")
            steps.append(f"    {pct(at + SETTLE):.3f}% {{ {shift(next_y)} }}")
    steps.append(f"    {pct(blank):.3f}% {{ {shift(scroll[-1][1])} }}")
    steps.append(f"    100% {{ {shift(scroll[0][1])} }}")
    rules.append("  @keyframes scroll {\n" + "\n".join(steps) + "\n  }")

    # Each message: invisible, then it arrives, then it stays until the rewind.
    for i, (show, shown) in enumerate(reveals):
        rules.append(f"  .m{i} {{ animation-name: appear{i}; }}")
        rules.append(
            f"""  @keyframes appear{i} {{
    0%, {pct(show):.3f}% {{ opacity: 0; transform: translateY(9px); }}
    {pct(shown):.3f}%, {pct(end):.3f}% {{ opacity: 1; transform: none; }}
    {pct(blank):.3f}%, 100% {{ opacity: 0; transform: none; }}
  }}"""
        )

    # Each typing bubble: up while the reply is being written, then gone. It is
    # pinned from the column's foot for the same reason _anchor measures from
    # there, and lands the bubble's own foot where its reply's first line will.
    for i, show, hide in typings:
        pin = SCREEN_PAD + floor - messages[i]["top"] - typing_h
        rules.append(f"  .t{i} {{ bottom: {pin:.0f}px; animation-name: type{i}; }}")
        rules.append(
            f"""  @keyframes type{i} {{
    0%, {pct(show):.3f}% {{ opacity: 0; }}
    {pct(show + 0.18):.3f}%, {pct(hide - 0.12):.3f}% {{ opacity: 1; }}
    {pct(hide):.3f}%, 100% {{ opacity: 0; }}
  }}"""
        )

    print(f"  {len(messages)} messages, {total:.1f}s loop")
    return "\n".join(rules)


def _dwell(chars: int) -> float:
    """Long enough to read the message, within reason."""
    return min(DWELL_MAX, max(DWELL_MIN, DWELL_MIN + chars / CPS))
