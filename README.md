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

---

Released under the [MIT License](LICENSE).
