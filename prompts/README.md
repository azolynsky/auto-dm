# prompts/ — the prompt registry

Every prompt the DM runs on is addressable from here, so a variant can be
swapped in and A/B tested without editing code.

```
prompts/
├── dm/                 # the harness adapter — how the model runs as DM
│   ├── default.md
│   └── brisk.md
└── <role>/             # optional overrides for .claude/agents/<role>.md
    └── <variant>.md
```

## How resolution works

Two roles of prompt, one rule:

- **`dm`** — the system prompt prepended to `CLAUDE.md`. `prompts/dm/default.md`
  is the shipped one. This role has no fallback; a variant must exist.
- **Everything else** — `director`, `narrator`, `rules-lawyer`, `bookkeeper`,
  `continuity-checker`, `session-prep`, `prose-editor`. The DM reads these from
  `.claude/agents/<role>.md` as it works. If `prompts/<role>/<selected>.md`
  exists, the DM is served that file **instead**, transparently — same path in
  the DM's request, different bytes back.

So `.claude/agents/` stays the single source of truth until you actually want to
test an alternative. No copies to keep in sync.

## Running an A/B test

1. Write the variant: `prompts/narrator/terse.md`. It replaces the role file
   wholesale, so start from `.claude/agents/narrator.md` and edit — anything you
   drop (the banned-habits list, the motivations firewall) is genuinely gone for
   that arm of the test.
2. Select it: open the app, add `#dev` to the URL, and pick the variant in the
   **Developer** section of Settings. Or edit `prompts` in the app's
   `config.json` directly.
3. Play a few beats and compare. Selection is per-install, not per-campaign, and
   takes effect on the DM's next turn — no restart.

`prompts/dm/brisk.md` ships as a working second arm: same rules, tuned for
shorter turns at the table. Use it to sanity-check the switch works before
writing your own.

## Rules that survive every variant

The invariants in `CLAUDE.md` are not up for A/B testing. A variant that lets
the DM roll dice in its head, skip state updates, or leak `motivations.md` into
prose is a broken variant, not an interesting result.
