# Backends — running each role on whatever drives it best

Every role in the pipeline (the `dm` orchestrator, and each specialist:
director, narrator, rules-lawyer, bookkeeper, continuity-checker, session-prep,
prose-editor) picks its own **backend** and its own **model**. A backend is the
thing that runs an agent loop; a model is what that loop thinks with.

This file is the contract. `desktop/backends/*.py` implements it, and
`tests/test_backends.py` holds it in place.

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
pays a process start per turn and reaches the tools over a stdio pipe.
`claude-agent` is the same binary and the same login with the tools in-process,
so a tool call is a Python call rather than a pipe round trip, and tool-use
events stream back as they happen — which is what feeds the table's activity
spinner.

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
    def reset(self, spec: AgentSpec) -> None: ...
```

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

## Adding a backend

1. Subclass `Backend` in `desktop/backends/<name>.py`.
2. Register it in `desktop/backends/__init__.py`.
3. Add its ids to `MODEL_CHOICES` in `desktop/config.py` so the picker offers
   them.

Nothing else changes. `agent.py` never names a backend.
