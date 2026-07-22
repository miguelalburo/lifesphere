# schema-audit skill is stale — rewrite against config/schema + config/mapping layout

## Problem

The `schema-audit` skill (`.claude/skills/schema-audit/SKILL.md`) is out of date and currently **disabled** (a "NEEDS UPDATING — DO NOT INVOKE" banner has been added to the skill body).

It targets the **old** config layout that no longer exists in the repo:

- `config/schemas/entities.json`
- `config/schemas/edges.json`
- `config/schemas/aliases.json`
- `config/schema_config.yaml`

None of these paths are present anymore. The repo has moved to:

- `config/schema/nodes.yaml`
- `config/schema/edges.yaml`
- `config/mapping/extract.yaml`, `config/mapping/omics.yaml`
- `config/aliases.yaml`
- `config/placeholders.yaml`

Because the inputs and cross-file invariants in the skill reference the old JSON structure, running it would report false drift (or fail outright), so it must not be invoked until rewritten.

## What to do

- [ ] Rewrite the skill's Inputs and Checks against the current `config/schema/*.yaml` + `config/mapping/*.yaml` structure.
- [ ] Re-derive the cross-file invariants for the YAML node/edge/mapping layout (label/id consistency, orphaned edges, entries present in one file but not another).
- [ ] Update `CLAUDE.md` — its schema-config table still documents the old `config/schemas/*.json` + `config/schema_config.yaml` files.
- [ ] Check the sibling skills `schema-change` and `schema-verify` for the same stale-path issue and update them together.
- [ ] Remove the "NEEDS UPDATING — DO NOT INVOKE" banner from `SKILL.md` once the rewrite lands.

## Context

Surfaced while reviewing omics issues #36/#40: #40's acceptance criteria include "schema-audit clean", which could not be verified because the skill no longer matches the repo's config structure.
