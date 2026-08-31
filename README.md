# split-expenses

An [Agent Skill](https://agentskills.io) for splitting shared costs with friends.

Tell your assistant what happened, the way you'd tell a friend. It keeps a
running balance table in the chat. When the trip's over, it works out who pays
whom — in the fewest payments possible.

No app, no account, no group to set up first: one `SKILL.md` and one
dependency-free Python script, running in your assistant's own sandbox.

<img src="docs/images/demo.svg" width="478"
     alt="The example conversation playing out a message at a time on a phone: a trip's
     expenses described in plain language — one of them as a photo of a receipt — each
     one answered with an updated balance table, a fourth person joining the roster by
     paying for something, an earlier expense corrected in place, and a closing
     settlement of three payments.">

## Install

**A coding agent with filesystem access.** Drop `skills/split-expenses/` into
its skills directory — `~/.claude/skills/` for Claude Code, or a project's
`.claude/skills/`:

```bash
git clone https://github.com/invisiblefunnel/split-expenses
cp -r split-expenses/skills/split-expenses ~/.claude/skills/
```

**The Claude app**, on a plan with code execution: download
[`split-expenses.zip`](https://github.com/invisiblefunnel/split-expenses/releases/latest/download/split-expenses.zip)
and upload it under Settings → Skills. **ChatGPT** reads the same `SKILL.md`
and takes the same zip under Plugins → Skills, where personal skills are a
business-plan feature.

Then just start talking about a shared cost. Python 3.9 or newer, nothing else
— no server, no account, and no service to send your balances to.

## Landing page

The static site lives in [`site/`](site/) and serves from
[splitexpenses.ai](https://splitexpenses.ai). Cloudflare builds and deploys it
from this repository directly — no deploy workflow and no repository secrets,
since Cloudflare checks the code out itself. Its build command is

```
python3 -m unittest discover -s tests && python3 tools/build_site.py
```

and its deploy command is `npx wrangler@4 deploy`, which uploads the
`dist/site/` that [`wrangler.jsonc`](wrangler.jsonc) names as the Worker's
static assets. The suite runs inside the build rather than ahead of it, so a
failing test fails the build and nothing is deployed. A pull request touching
the site gets its own preview URL.

The domain is attached to the Worker by the `routes` in
[`wrangler.jsonc`](wrangler.jsonc), which claim the hostname and create its DNS
record as part of deploying, so nothing in the uploaded tree needs to know
where it will be served from. The build output names the domain only in the two
tags that cannot take a relative URL: `og:url`, and the `og:image` a
link-preview crawler fetches on its own, with no page to resolve a relative
path against — which also has to be a PNG, because none of the platforms
render an SVG preview. The card is drawn as
[`site/social-card.svg`](site/social-card.svg) and rasterized by hand with

```
python3 tools/render_social_card.py
```

which needs playwright and Chromium. Its output is committed: the build only
copies files, and nothing rasterizes at deploy time.

---

Released under the [MIT License](LICENSE).
