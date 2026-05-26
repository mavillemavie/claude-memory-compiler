# Olendris Nightly Sync - Design Spec

## Purpose

Automatically update the Olendris Obsidian vault ("right brain") from claude-memory-compiler daily logs so project notes, strategy, and knowledge stay current without manual effort.

## Architecture

```
daily/YYYY-MM-DD.md ──┐
                      ├──► sync-olendris.py ──► Claude API (single pass) ──► JSON diff ──► apply to Olendris
Olendris Vault/* ─────┘
```

### Location

`/home/mv2/work/info-tools/claude-memory-compiler/scripts/sync-olendris.py`

### Trigger

Cron at 00:05 nightly, after compile (00:00). Skips if no daily log exists for today.

## LLM Contract

### Input

The script sends Claude a single prompt containing:

1. Today's daily log (`daily/YYYY-MM-DD.md`)
2. All files from `Olendris Vault/Projects/` (including `idea-*` files)
3. `Olendris Vault/Areas/Business Strategy.md`
4. `Olendris Vault/Projects/Project Pipeline.md`
5. `Olendris Vault/Home.md`

### System prompt rules

- Never delete existing content. Only append or mark tasks complete.
- Decisions: always prefix with date (`- YYYY-MM-DD: ...`).
- Tasks: mark done with `[x]` if session completed them. Add new tasks discovered.
- Notes: append new insights. Do not rewrite existing notes.
- New projects: use `idea-` filename prefix, `status: idea` frontmatter, full template.
- Strategy: only update if an explicit strategic decision was made.
- Home.md: update project table only if a project status changed.
- Project Pipeline: add new idea-stage projects, update status for existing ones.
- If nothing meaningful happened for a project, omit it from the response.
- Preserve all YAML frontmatter exactly. Only modify fields explicitly listed.

### Output schema

```json
{
  "updates": [
    {
      "file": "Projects/Policy Poutine.md",
      "sections": {
        "Current State": "full replacement content for this section",
        "Decisions": "append: - 2026-04-13: Decision made...",
        "Notes": "append: New insight discovered..."
      }
    }
  ],
  "new_projects": [
    {
      "name": "idea-Project Name",
      "overview": "What this project is",
      "revenue_model": "unknown",
      "decisions": "- 2026-04-13: Initial concept emerged"
    }
  ],
  "pipeline_updates": [
    {
      "project": "Project Name",
      "revenue_potential": "Medium",
      "time_to_revenue": "Unknown",
      "complexity": "Low",
      "status": "idea"
    }
  ],
  "home_updates": true,
  "strategy_updates": {
    "Current Portfolio": "append: - **Project Name** -- description",
    "Key Questions": null
  },
  "skip_reason": null
}
```

- `skip_reason`: if set to a string (e.g. "No meaningful project activity today"), no updates are applied.
- Section values prefixed with `append:` are appended. Otherwise the section body is replaced.
- `null` section values mean "no change."

## New project template

```markdown
---
tags:
  - project
status: idea
start: YYYY-MM-DD
revenue-model: unknown
repo: null
priority: low
---

# Project Name

## Overview

[from daily log context]

## Current State

- [ ] Validate idea and define scope

## Decisions

- YYYY-MM-DD: Initial concept emerged from session

## Notes
```

## Promotion flow

When the sync detects a daily log references an `idea-*` project with language indicating commitment (e.g., "started building", "created repo", status explicitly changed), it:

1. Renames `idea-ProjectName.md` to `ProjectName.md`
2. Updates frontmatter `status: idea` to `status: active` (or `planned`)
3. Updates Project Pipeline table
4. Updates Home.md table

## Scaling guard

Before each run, count files in `Olendris Vault/Projects/` and `Olendris Vault/Areas/`, estimate token size. If over 40 notes or 50K tokens of combined vault content:

```
WARN: Olendris vault at X notes (~Y tokens). Consider switching to per-project sync mode.
```

This is logged to `sync-olendris.log`. The script continues to function; the warning is informational.

## Logging

Output to `scripts/sync-olendris.log`. Each run logs:

- Timestamp and daily log file used
- Files read from Olendris
- Each update applied (file + section + action)
- New projects created
- Approximate token usage
- Scaling warnings if applicable
- Errors with full tracebacks

## Error handling

- Claude API failure: log error, exit without touching any files.
- JSON parse failure on LLM response: retry once with stricter prompt, then log and exit.
- Individual file write failure: log the error, continue applying remaining updates.
- Empty/trivial daily log: skip sync, log reason.
- `skip_reason` in LLM response: log it, exit cleanly.

## Cost

Estimated $0.05-0.15 per nightly sync at current vault size. Scales with vault content size.

## Future: per-project mode

When the scaling guard triggers, the single-pass approach splits into per-project calls. The gather/apply pipeline stays identical; only the LLM call boundary changes. No structural changes needed.
