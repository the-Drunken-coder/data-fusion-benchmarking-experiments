# Domain docs

These rules describe how engineering skills consume this repo's domain documentation while exploring the codebase.

## Before exploring, read these

- `CONTEXT.md` at the repo root.
- `CONTEXT-MAP.md` at the repo root, if it exists. It points to one `CONTEXT.md` per context. Read each file relevant to the current work.
- Relevant ADRs under `docs/adr/`. In multi-context repos, also check `src/<context>/docs/adr/` for context-specific decisions.

If any of these files do not exist, proceed silently. Do not flag their absence or suggest creating them upfront. The `/matt-domain-modeling` skill, reached through `/matt-grill-with-docs` and `/matt-improve-codebase-architecture`, creates them when the team resolves terms or decisions.

## File structure

This repo uses a single-context layout:

```text
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

For reference, a multi-context repo has `CONTEXT-MAP.md` at the root:

```text
/
├── CONTEXT-MAP.md
├── docs/adr/
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When output names a domain concept in an issue title, refactor proposal, hypothesis, or test name, use the term defined in `CONTEXT.md`. Do not drift to synonyms the glossary rejects.

If a needed concept is absent from the glossary, reconsider whether the term belongs to the project. If it does, note the gap for `/matt-domain-modeling`.

## Flag ADR conflicts

If output contradicts an existing ADR, state the conflict instead of silently overriding it. For example:

> Contradicts ADR-0007, event-sourced orders, but worth reopening because...
