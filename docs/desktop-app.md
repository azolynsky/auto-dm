# The desktop app

Auto-DM packaged for someone who doesn't use a terminal. They need one thing: an
OpenRouter API key. No Python, no `claude` CLI, no cloning.

## What's different from the repo version

On `main` the DM *is* Claude Code — the webapp shells out to `claude -p` and the
CLI does the thinking. That needs a developer's machine and a Claude subscription.

Here the DM is a [LangGraph](https://langchain-ai.github.io/langgraph/) ReAct
agent talking to OpenRouter, living inside the app:

| | `main` | desktop app |
|---|---|---|
| DM brain | `claude -p --continue` subprocess | LangGraph agent (`desktop/agent.py`) |
| Credentials | Claude Code subscription | one OpenRouter key |
| Roles/skills | Claude's `Agent` / `Skill` tools | the model reads `.claude/**` and embodies them |
| History | Claude Code's session | LangGraph SQLite checkpoint in the campaign |
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

## Guardrails

The agent has no shell. It gets five tools: `read_file`, `write_file`,
`edit_file`, `list_files`, and `run_tool` (whitelisted to the five campaign
tools). Writes are confined to the campaign directory; reads can't leave the app
bundle. `tests/test_desktop.py` covers those boundaries, including the traversal
and absolute-path cases.

One turn runs at a time — `SAY_QUEUE` serialises them, which is what keeps two
DMs from writing campaign state at once, and what makes the in-process tool
runner safe.
