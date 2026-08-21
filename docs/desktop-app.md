# The desktop app

Auto-DM packaged for someone who doesn't use a terminal. They need one thing to
run it: either an OpenRouter API key or Claude Code already installed and logged
in. No Python, no cloning.

## What's different from the repo version

On `main` the DM *is* Claude Code — the webapp shells out to `claude -p` and the
CLI does the thinking. That needs a developer's machine and a Claude
subscription.

Here every role picks its own **backend** — see [backends.md](backends.md) for
the contract and the model-id grammar. Two ship: OpenRouter, and the `claude`
binary this machine already has, driven as a library. The orchestrator loop runs
on either, so "the DM is Claude Code" is now a setting rather than a fork.

| | `main` | desktop app |
|---|---|---|
| DM brain | `claude -p --continue` subprocess | either backend, per role (`desktop/backends/`) |
| Credentials | Claude Code subscription | an OpenRouter key, or that same subscription, or both |
| Roles/skills | Claude's `Agent` / `Skill` tools | real subagents — one consult per role, own model |
| History | Claude Code's session | LangGraph SQLite checkpoint, or Claude Code's own session |
| Chat | optional, gated by `web_input` | always under the adventure log |
| Campaign files | `<repo>/campaign` | the OS app-data directory |

Everything else is unchanged and shared: the same tools, the same `CLAUDE.md`
manual, the same state files, the same invariants. A campaign directory moves
between the two without conversion.

## Running from source

```bash
pip install -r desktop/requirements.txt
python desktop/app.py
```

A native window opens (WKWebView on macOS, WebView2 on Windows) on a random
loopback port. Set `AUTODM_PORT` to pin it, or `CAMPAIGN_ROOT` to play a campaign
that lives somewhere else — the same override the tools already honour.

## Where things live

| | macOS | Windows |
|---|---|---|
| Key + settings | `~/Library/Application Support/Auto-DM/config.json` | `%APPDATA%\Auto-DM\config.json` |
| Campaign | `…/Auto-DM/campaign/` | `%APPDATA%\Auto-DM\campaign\` |

`config.json` holds the API key, so it's written `0600`. `OPENROUTER_API_KEY` in
the environment overrides it. On first launch the campaign is copied from
`campaigns/starter/`, so the app is playable before anyone customises anything.

## Building the installable app

CI does it: **Actions → Build desktop app → Run workflow**, then download the
artifact. Locally:

```bash
pip install -r desktop/requirements.txt pyinstaller
pyinstaller --noconfirm desktop/autodm.spec
```

Output is `dist/Auto-DM.app` (macOS, ~70 MB) or `dist/Auto-DM/` (Windows).

The campaign tools ship as **source** and run in-process via `runpy`, because a
frozen app has no `python` to subprocess out to. That's why `tools/` is in the
spec's `datas` rather than analysed as imports.

### The signing gap

Builds are unsigned, so the first launch is awkward for exactly the person this
is meant for:

- **macOS** — right-click the app → **Open** → **Open** again. Ad-hoc signing in
  CI avoids the harsher "damaged and can't be opened" error, but only an Apple
  Developer ID ($99/yr) plus notarisation removes the prompt.
- **Windows** — SmartScreen shows "unrecognised app": **More info** → **Run
  anyway**. An EV code-signing certificate is the only real fix.

Walk them through it once on a call, or notarise.

## Developer mode

Add `#dev` to the URL (or run with the window focused and edit `config.json`) to
reveal a **Developer** section in Settings: model choice, prompt variant per
role, and **New DM thread** — which forgets the conversation while keeping all
campaign state, the clean way to start an A/B arm.

`#nodev` turns it back off. The reveal is remembered per install, and nothing in
this section is visible to players by default because it changes how the DM is
*built*, not how it plays. Prompt variants live in `prompts/` — see
[prompts/README.md](../prompts/README.md).

### Running a role on your own Claude login

Any role — the `dm` orchestrator included — can run on the `claude` binary
already installed on this machine, against the Claude login it already has. No
API key is read and none is needed; it spends subscription usage, not credit.
Pick a **Claude on this Mac** entry for that role in Developer settings, or set
the id by hand:

```
"role_models": { "dm": "claude-agent:opus", "narrator": "google/gemini-3.7-flash" }
```

It runs through `claude-agent-sdk` — Claude Code as a library — with the
campaign tools in-process. Four models, fastest first: `haiku`, `sonnet`,
`opus`, `fable`. The alias passes straight through, so anything the installed
CLI accepts works.

There was briefly a second Claude backend that shelled out to the plain
`claude -p` command. Same binary, same login, same models, so it gave the picker
two indistinguishable rows per model — and both bugs found while building this
reproduced only on it. Removed; `claude-cli:*` ids still resolve as an alias so
saved configs keep working. See [backends.md](backends.md).

**Name the model.** A bare `claude-agent` resolves, but sends no model flag, so
that role inherits whatever the machine's Claude Code is set to — a `model` key
in `~/.claude/settings.json`, else the CLI's default. That setting changes
outside the app, which silently changes who is narrating your game. The picker
offers only the explicit ids.

The role's prompt file becomes the system prompt and the task — pre-read brief
included — the user turn, so a role runs identically on any backend and can be
switched back without touching prompts.

Measured on the same beats (2026-08-19, before the MCP channel existed):
narrator 7.1s local vs 11–15s on OpenRouter; rules-lawyer 32.4s local vs ~14s.
Local is free but the CLI has its own start-up cost per call, so it suits roles
you aren't waiting on more than the ones you are.

What the Claude backend deliberately does *not* get:

- **Claude Code's own tools.** `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`,
  `WebFetch`, `WebSearch` and `Task` are all denied. Every capability arrives
  through the campaign tools instead, which is where the path guardrails and
  the motivations firewall live — Claude Code's own `Read` would walk straight
  past both.
- **Your MCP servers and your `CLAUDE.md`.** `setting_sources=None`. The run is
  the game, not your working directory.
- **A permission prompt.** The allow-list is the whole surface and nobody is
  sitting at a terminal to answer one.

The Narrator's firewall holds here too. It used to run with no file access at
all when this ran through `claude -p`, because there was no per-file hook to
enforce invariant #7; it now gets the same `read_file` that refuses
`motivations.md` and `secrets.md`, because the firewall lives in the function
and the function is what every backend binds.

Requires Claude Code installed. A GUI-launched `.app` gets a bare `PATH`, so
the app also checks `~/.local/bin`, Homebrew, `/usr/local/bin`, and the npm
global prefix; if it still can't find it, Developer settings shows the backend
as unavailable with the fix, instead of failing at the table mid-turn.

## Guardrails

The agent has no shell. It gets five tools: `read_file`, `write_file`,
`edit_file`, `list_files`, and `run_tool` (whitelisted to the five campaign
tools). Writes are confined to the campaign directory; reads can't leave the app
bundle. `tests/test_desktop.py` covers those boundaries, including the traversal
and absolute-path cases.

One turn runs at a time — `SAY_QUEUE` serialises them, which is what keeps two
DMs from writing campaign state at once, and what makes the in-process tool
runner safe.
