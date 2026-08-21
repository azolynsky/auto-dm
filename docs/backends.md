# Backends — running each role on whatever drives it best

Every role in the pipeline (the `dm` orchestrator, and each specialist:
director, narrator, rules-lawyer, bookkeeper, continuity-checker, session-prep,
prose-editor) picks its own **backend** and its own **model**. A backend is the
thing that runs an agent loop; a model is what that loop thinks with.

This file is the contract. `desktop/backends/*.py` implements it, and
`tests/test_desktop.py` holds it in place — `TestBackendRouting`,
`TestClaudeCliBackend`, `TestClaudeAgentBackend`, `TestMcpServer`,
`TestSubscriptionOnlyTable`.

## Why this exists

Before this, one backend was hard-wired per capability: the `dm` orchestrator
could only run on OpenRouter, and specialists could optionally run on
`claude -p`. The DM was pinned there because it drives our own tools — `dice.py`,
`narrate.py`, `consult_role` — through structured tool calls, and a one-shot
`claude -p` returns text on stdout with no way to hand a tool call back.

That is a missing channel, not a missing capability. Give the local `claude` an
MCP server carrying the campaign tools and it can drive the loop. So the tool
surface moved out of the agent loop and became something any backend can be
handed.

## Model id grammar

```
<backend>:<model>        explicit
<model>                  bare — means openrouter (back-compat)
```

Parsing splits on the **first** colon and checks the head against the backend
registry. A head that isn't a registered backend means the whole string is an
OpenRouter model id, which keeps suffixed ids like
`deepseek/deepseek-v4-flash-latest:free` working.

| Id | Backend | Runs on |
|---|---|---|
| `google/gemini-3.7-flash` | openrouter | OpenRouter credit |
| `openrouter:openai/gpt-5.6-luna-pro` | openrouter | OpenRouter credit |
| `claude-cli:opus` | claude-cli | your Claude subscription |
| `claude-agent:opus` | claude-agent | your Claude subscription |

Neither Claude backend touches `ANTHROPIC_API_KEY`. Both spawn the `claude`
binary already installed on the machine and use its OAuth login — the same
credential `claude -p` uses in a terminal. There is no Claude-via-API and no
Claude-via-OpenRouter path, deliberately: this is subscription compute.

## The three backends

| | openrouter | claude-cli | claude-agent |
|---|---|---|---|
| Mechanism | LangGraph ReAct over an OpenAI-compatible endpoint | `claude -p` subprocess | `claude-agent-sdk` driving the same binary |
| Drives the `dm` loop | yes | yes, with the MCP server | yes |
| Campaign tools | in-process Python | over stdio MCP (`tools/mcp_server.py`) | in-process MCP (`create_sdk_mcp_server`) |
| History | LangGraph SQLite checkpoint | `--resume <session>` | `resume=<session_id>` |
| Cost | OpenRouter credit | subscription | subscription |
| Extra dependency | langgraph, langchain-openai | none | claude-agent-sdk |

`claude-cli` is the honest baseline: literally the command you would type. It
pays a process start per turn and reaches the tools over a stdio pipe, which
means a second Python process per consult. `claude-agent` is the same binary and
the same login with the tools in-process, so a tool call is a Python call rather
than a pipe round trip.

### What the overhead actually is

Measured on this machine, 2026-08-20:

| | cost | how often |
|---|---|---|
| `claude` start-up | ~2–3s (a whole minimal `-p` round trip is 3.7–5.0s) | once per exchange |
| MCP server boot (claude-cli only) | 276ms | once per `claude` launch |
| one tool call, in-process | ~1ms | per call |
| one tool call, over the MCP pipe | 5–7ms | per call |
| a real specialist consult | 9–47s | |
| a real player turn | 42–105s | |

Start-up is **per exchange, not per tool call** — a turn that rolls twelve dice
pays it once, not twelve times. A turn is one DM exchange plus one launch per
consult, so a light turn (DM + narrator) carries ~5s of start-up in ~42s, and a
heavy one (DM + four specialists) carries ~12–15s. Real but not dominant.

Holding a live `ClaudeSDKClient` open between turns would remove it on the SDK
path, at the cost of a long-lived subprocess per role. That is the upgrade if it
ever starts to matter; it isn't the first thing to optimise while a single
specialist consult can take 47s.

The activity spinner and the dev log need nothing from any of this: the tools
write both themselves, so they land identically whether the tool ran in-process
or inside the MCP subprocess (which writes to the same campaign files). The
per-turn narration flags are the exception, and getting that wrong is what
broke the claude-cli DM path — see below.

## The interface

Two dataclasses and one abstract method. Full definitions in
`desktop/backends/base.py`.

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str          # what the model calls it
    description: str   # the docstring — this is the usage contract
    schema: dict       # JSON Schema for the arguments
    fn: Callable       # the Python implementation

@dataclass(frozen=True)
class AgentSpec:
    role: str              # "dm", or a specialist name
    model: str             # backend-local id, prefix already stripped
    system_prompt: str     # resolved prompt text
    tools: tuple[ToolSpec, ...]
    turn_limit: int        # tool round trips before giving up
    stateful: bool         # True keeps history across run() calls (the dm)


class Backend(ABC):
    name: str          # registry key, and the id prefix
    label: str         # what the settings picker shows
    supports_dm: bool

    def available(self) -> str | None: ...   # None = ready, else the reason
    def run(self, spec: AgentSpec, message: str) -> str: ...
    def is_fresh(self, spec: AgentSpec) -> bool: ...
    def reset(self, spec: AgentSpec) -> None: ...
```

`is_fresh` exists because the caller sends the session brief on a new
conversation and skips it on a resumed one. It is the single thing `agent.py`
needs to know about a history it deliberately doesn't own.

One method covers both capabilities because a consult and a DM turn differ only
in configuration: a consult is `stateful=False` with a role's tool subset, a DM
turn is `stateful=True` with the whole surface. Two `run()` calls on a
`stateful=True` spec continue one conversation, which is what the
never-narrated fallback nudge needs.

Everything a backend does *not* own stays in `agent.py`: the session brief,
interrupted-turn healing, the fallback nudge, the OOC register. Those are table
rules, identical whoever is thinking.

## The tool surface

`desktop/campaign_tools.py` owns it: `read_file`, `write_file`, `edit_file`,
`list_files`, `run_tool`, plus the guardrails (`resolve_path`), the dev log, and
the activity labels. `agent.py` appends `consult_role` and `consult_pair`,
which it must own because they call back into the registry.

The per-role subset is unchanged and is what enforces the firewalls:

- **bookkeeper** — the only role with `write_file` / `edit_file`.
- **narrator** — `read_file` refuses `motivations.md` and `secrets.md`
  (invariant #7), and gets no `run_tool` at all, so it returns prose and never
  publishes (one push per beat, one owner).
- **everyone else** — read, list, run tools.

This is stronger than what the `claude -p` path could manage before. It had no
per-file hook, so the narrator ran with no file access whatsoever and worked
from its brief alone. Now every backend gets the same firewalled `read_file`,
because the firewall is a property of the function, not of the loop calling it.

## The MCP server

`tools/mcp_server.py` exposes the same surface over stdio MCP. It is what lets
the `claude-cli` backend drive the DM loop, and it makes the campaign reachable
from any MCP client — a plain interactive `claude` in a terminal, Codex, or
another harness. That is the multi-LLM promise in `CLAUDE.md` made mechanical
rather than aspirational.

Run it standalone:

```bash
CAMPAIGN_ROOT=~/Library/Application\ Support/Auto-DM/campaigns/table-1 \
  python tools/mcp_server.py
```

Or register it for a terminal `claude`:

```bash
claude mcp add campaign -- python tools/mcp_server.py
```

### Protocol version

The current MCP revision is **2026-07-28**, whose headline change is a stateless
core: the `initialize`/`initialized` handshake is gone, every request carries
its protocol version in `_meta`, and the `Mcp-Session-Id` header is gone from
Streamable HTTP. Three consequences worth recording, because they shaped what
this server does *not* do:

- **Sampling is deprecated.** The old trick of having a server borrow the
  client's model is on the way out; the migration note says to call the
  provider directly. Our per-role backends already do exactly that, so the
  narrator-on-OpenRouter case is a config choice, not a protocol feature.
- **Roots is deprecated.** Pass directories as tool arguments or server
  config. We root the server with `CAMPAIGN_ROOT`, which is already how every
  other tool in `tools/` finds the campaign.
- **Tasks moved to an extension** (`io.modelcontextprotocol/tasks`) with
  polling via `tasks/get`. A slow consult is the obvious candidate later;
  nothing needs it yet.

We build on the `mcp` Python SDK's stdio server, which negotiates whatever the
client speaks. The installed SDK's own latest is `2025-11-25`; the transport
shape for a local stdio pipe is unaffected by the stateless-core change, so
there is no reason to chase the version for this server.

## Credentials

An OpenRouter key is required only if some role is set to spend credit.
`config.needs_api_key()` answers that by asking whether every configured role
is on a subscription backend, and both readiness and the setup screen defer to
it — so a table running entirely on the machine's Claude login is never asked
for a key it doesn't have. Move one role onto OpenRouter and the key becomes
required again.

Neither Claude backend reads `ANTHROPIC_API_KEY`. Verified on a machine with no
key, no auth token and no `primaryApiKey`: both run off the `claude` binary's
OAuth login, the same credential `claude -p` uses in a terminal.

## Adding a backend

1. Subclass `Backend` in `desktop/backends/<name>.py`, and expose it as
   `BACKEND` at module scope.
2. Add a `BackendInfo` row to `BACKENDS` in `desktop/backends/base.py` — the
   registry is data there so `config.py` can build the settings picker without
   importing any implementation.
3. Add its ids to `MODEL_CHOICES` in `desktop/config.py` so the picker offers
   them.

Nothing else changes. `agent.py` never names a backend, and
`backends/__init__.py` imports implementations by name at first use, so a
backend whose dependency isn't installed costs nothing until someone selects
it — and then reports itself unavailable, with the fix.

## What was verified live

Real runs against a throwaway campaign, not inferred from mocks (2026-08-20):

| Check | Result |
|---|---|
| Consult on `claude-agent:haiku` | 14s; flagged an impossible premise from its brief |
| Consult on `claude-cli:haiku` over MCP | 9s; cited `rules/combat-flow.md`, which it had actually read |
| `tools/mcp_server.py` driven by a real MCP client | 5 tools unscoped, 2 for the narrator; `motivations.md` refused; `dice.py` rolled |
| Full turn, DM `claude-agent:sonnet`, narrator on OpenRouter | 105s; director consult, narrator consult, `narrate.py` push, one chronicle entry |
| Full turn, everything on `claude-cli` | 42s; nested narrator consult, push, one entry with its effect |
| Two turns, backend instances cleared between them | the second resumed the session and answered from the transcript |
| Full turn with no OpenRouter key at all | `needs_api_key` false; turn completed and narrated |

Running a whole turn is not optional coverage. A specialist consult exercises
neither the narration gate nor `consult_role`, and both were broken on the
claude-cli path while its consult test passed:

- **The gate was in memory.** On that backend the tools run in the MCP
  subprocess, which gets its own copy of every module global — so every
  narration push was refused there, and the parent never learned one had
  landed. The flags moved to `campaign/state/dm-turn.json`, the only thing both
  processes see. Unreadable means locked; a lost gate must refuse prose rather
  than wave it through.
- **The DM had no consults.** The server was built from the `campaign_tools`
  surface, which has no `consult_role` — those live in `agent.py` because they
  run the backends. An orchestrator that can't reach the Narrator can't publish
  anything, since the gate exists to refuse prose the Narrator didn't write.
  The unscoped surface is now `agent.DM_TOOLS`, so this process runs the
  consults; a specialist on claude-cli spawns its own `claude` and its own copy
  of this server, one level down and no further.
