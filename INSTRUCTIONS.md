# Claude Memory Compiler - Complete Instructions

> **For any AI agent or human reading this file:** This document is the single authoritative guide to understanding, setting up, operating, and extending the Claude Memory Compiler system. Read it end to end before taking any action.

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Architecture Overview](#2-architecture-overview)
3. [Prerequisites & Installation](#3-prerequisites--installation)
4. [Directory Structure](#4-directory-structure)
5. [How the Automatic Pipeline Works](#5-how-the-automatic-pipeline-works)
6. [Hook System (Automatic Capture)](#6-hook-system-automatic-capture)
7. [Scripts Reference (Manual Commands)](#7-scripts-reference-manual-commands)
8. [Article Schema & Formats](#8-article-schema--formats)
9. [The Knowledge Index (`index.md`)](#9-the-knowledge-index-indexmd)
10. [Wikilink Convention](#10-wikilink-convention)
11. [State Tracking & Deduplication](#11-state-tracking--deduplication)
12. [Cost Breakdown](#12-cost-breakdown)
13. [Customization & Configuration](#13-customization--configuration)
14. [Troubleshooting](#14-troubleshooting)
15. [Design Decisions & Rationale](#15-design-decisions--rationale)
16. [Scaling Considerations](#16-scaling-considerations)
17. [Integration with Other Projects](#17-integration-with-other-projects)

---

## 1. What This System Does

The Claude Memory Compiler is a **persistent knowledge base** that automatically captures what you discuss with Claude Code, extracts the important parts, and compiles them into structured, searchable articles. The next time you start a session, Claude already knows what it learned before.

**The core loop:**

```
Conversations --> Daily Logs --> Compiled Articles --> Injected into Next Session
```

There is no vector database, no embeddings, and no RAG. At personal scale (50-500 articles), an LLM reading a structured markdown index outperforms semantic search. The LLM understands context and intent; cosine similarity just finds similar words.

### What gets captured

- Architecture decisions and why they were made
- Debugging sessions and what fixed the problem
- Library/framework patterns discovered through trial and error
- Configuration gotchas and environment-specific quirks
- Workflows, conventions, and team preferences

### What does NOT get captured

- Trivial Q&A ("what's the syntax for X")
- Conversations with no lasting value
- The flush step uses an LLM to judge what's worth saving -- routine exchanges are discarded

---

## 2. Architecture Overview

```
+------------------+       +------------------+       +--------------------+
|  Claude Code     |       |  Hooks           |       |  Background        |
|  Session         | ----> |  (auto-fire)     | ----> |  Processes         |
+------------------+       +------------------+       +--------------------+
                            |                          |
                            | session-start.py         | flush.py
                            |   Injects KB index       |   Extracts memories
                            |   into session context   |   from transcript
                            |                          |   Appends to daily/
                            | session-end.py           |
                            |   Captures transcript    | compile.py
                            |   Spawns flush.py        |   Reads daily logs
                            |                          |   Creates/updates
                            | pre-compact.py           |   knowledge articles
                            |   Same as session-end    |   Updates index.md
                            |   but fires before       |
                            |   context compaction     |
                            +------------------+       +--------------------+
                                                              |
                                                              v
+-----------------------------------------------------------------------------------+
|  Knowledge Base (knowledge/)                                                       |
|                                                                                    |
|  index.md          -- Master catalog (the LLM reads this to find articles)        |
|  log.md            -- Build log (timestamped compilation operations)               |
|  concepts/*.md     -- Atomic knowledge articles (one concept per file)             |
|  connections/*.md  -- Cross-cutting insights linking 2+ concepts                   |
|  qa/*.md           -- Filed Q&A articles from manual queries                       |
+-----------------------------------------------------------------------------------+
```

### Data Flow (End to End)

1. **Session starts** --> `session-start.py` reads `knowledge/index.md` + recent daily log, injects as context
2. **You work with Claude** --> normal conversation
3. **Context compaction happens** --> `pre-compact.py` captures transcript before it's summarized away
4. **Session ends** --> `session-end.py` captures final transcript, spawns `flush.py` in background
5. **`flush.py` (background)** --> calls Claude Agent SDK, extracts structured knowledge, appends to `daily/YYYY-MM-DD.md`
6. **If past 6 PM** --> `flush.py` auto-spawns `compile.py`
7. **`compile.py` (background)** --> reads daily logs + existing KB, creates/updates articles in `knowledge/`
8. **Next session** --> step 1 repeats with updated knowledge

---

## 3. Prerequisites & Installation

### Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (Python package manager)
- **Claude Code** (CLI, desktop app, or IDE extension)
- **Active Claude subscription** (uses your existing credentials at `~/.claude/.credentials.json`)

### Installation

```bash
# Clone the repository
git clone https://github.com/coleam00/claude-memory-compiler.git
cd claude-memory-compiler

# Install Python dependencies
uv sync
```

This installs:
- `claude-agent-sdk>=0.1.29` -- for making LLM calls with tool use
- `python-dotenv>=1.0.0` -- environment variable management
- `tzdata>=2024.1` -- timezone support (cross-platform)

### Activating the Hooks

The hooks are configured in `.claude/settings.json`. When you open Claude Code in this project directory, the hooks activate automatically. No manual setup needed.

If you want to use this system in **another project**, copy `.claude/settings.json` into that project's root (or merge the `hooks` array if the file already exists), and ensure the hook commands point to the correct paths. See [Integration with Other Projects](#17-integration-with-other-projects).

---

## 4. Directory Structure

```
claude-memory-compiler/
|
|-- README.md                    # Quick-start guide
|-- AGENTS.md                    # Complete technical schema (referenced by compile.py)
|-- INSTRUCTIONS.md              # This file
|-- pyproject.toml               # Dependencies & project config
|-- .gitignore                   # Excludes generated directories
|
|-- .claude/
|   +-- settings.json            # Hook configuration (auto-activates)
|
|-- scripts/                     # CLI tools & utilities
|   |-- config.py                # Path constants, timezone config
|   |-- utils.py                 # Shared utilities (hashing, slugifying, index parsing)
|   |-- compile.py               # Compile daily logs into knowledge articles
|   |-- flush.py                 # Extract memories from conversation transcripts
|   |-- query.py                 # Query the knowledge base
|   |-- lint.py                  # Run 7 health checks on the KB
|   |-- state.json               # Compilation state tracking (gitignored)
|   |-- last-flush.json          # Flush deduplication (gitignored)
|   |-- flush.log                # Background flush logs (gitignored)
|   +-- compile.log              # Background compile logs (gitignored)
|
|-- hooks/                       # Claude Code hooks (fire automatically)
|   |-- session-start.py         # Inject KB context on session open
|   |-- session-end.py           # Capture transcript on session close
|   +-- pre-compact.py           # Capture before context window compaction
|
|-- daily/                       # Daily conversation logs (gitignored, auto-created)
|   +-- YYYY-MM-DD.md            # Append-only, immutable source logs
|
|-- knowledge/                   # Compiled knowledge base (gitignored, auto-created)
|   |-- index.md                 # Master catalog
|   |-- log.md                   # Build log
|   |-- concepts/                # Atomic knowledge articles
|   |-- connections/             # Cross-cutting insight articles
|   +-- qa/                      # Filed Q&A articles
|
+-- reports/                     # Lint reports (gitignored, auto-created)
    +-- lint-YYYY-MM-DD.md       # Health check results
```

**What's gitignored:** `daily/`, `knowledge/`, `reports/`, `scripts/state.json`, `scripts/last-flush.json`, `scripts/*.log`, `.venv/`. These are all generated per-user.

---

## 5. How the Automatic Pipeline Works

### Zero-Maintenance Operation

Once installed, the system requires **no manual intervention** for daily use:

1. **Open Claude Code in this project** -- the session-start hook injects your knowledge base
2. **Have conversations** -- work normally
3. **Close the session** -- transcript is captured and flushed to daily log
4. **After 6 PM local time** -- daily log is automatically compiled into knowledge articles
5. **Next session** -- updated knowledge is injected

### Why "After 6 PM"?

Compilation is expensive ($0.45-0.65 per daily log) and the daily log grows throughout the day as sessions are flushed. Compiling once in the evening captures the full day's work in a single pass rather than recompiling after every session.

### What Triggers Each Step

| Event | Hook/Script | What Happens |
|-------|-------------|--------------|
| Session opens | `session-start.py` | Reads `knowledge/index.md` + recent daily log, injects as context |
| Context window fills up | `pre-compact.py` | Captures transcript before compaction discards detail |
| Session closes | `session-end.py` | Captures transcript, spawns `flush.py` in background |
| `flush.py` runs | Background process | Extracts knowledge via Claude SDK, appends to daily log |
| 6 PM + daily log changed | `flush.py` triggers | Spawns `compile.py` in background |
| `compile.py` runs | Background process | Creates/updates articles in `knowledge/`, updates index |

---

## 6. Hook System (Automatic Capture)

The hooks are configured in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run python hooks/session-start.py",
        "timeout": 15
      }]
    }],
    "PreCompact": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run python hooks/pre-compact.py",
        "timeout": 10
      }]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run python hooks/session-end.py",
        "timeout": 10
      }]
    }]
  }
}
```

### `session-start.py` -- Context Injection

- **When:** Every time Claude Code opens a session in this project
- **What:** Reads `knowledge/index.md` and the last 30 lines of today's daily log
- **Output:** JSON to stdout with `hookSpecificOutput.additionalContext` (max 20,000 chars)
- **Cost:** Free (pure local file I/O, no API calls)
- **Speed:** < 1 second

### `session-end.py` -- Conversation Capture

- **When:** Every time a Claude Code session closes
- **What:**
  1. Reads the session transcript (JSONL format)
  2. Extracts the last ~30 turns of conversation
  3. Writes a temp file: `scripts/session-flush-{session_id}-{timestamp}.md`
  4. Spawns `flush.py` as a **detached background process** (survives hook exit)
- **Recursion guard:** Exits immediately if `CLAUDE_INVOKED_BY` env var is set (prevents flush.py from triggering its own capture)
- **Skips if:** No transcript, empty transcript, or fewer than 1 turn

### `pre-compact.py` -- Compaction Safety Net

- **When:** Before Claude Code auto-compacts the context window (during long sessions)
- **Why this exists:** Auto-compaction summarizes and discards detailed context. Without this hook, intermediate conversation is lost before `session-end.py` fires.
- **Behavior:** Same as `session-end.py` but requires a minimum of 5 turns before flushing
- **Temp file:** `scripts/flush-context-{session_id}-{timestamp}.md`

### Cross-Platform Notes

- **Linux/Mac:** Background processes use `start_new_session=True`
- **Windows:** Uses `CREATE_NO_WINDOW` flag to avoid console flash

---

## 7. Scripts Reference (Manual Commands)

All scripts are run from the project root using `uv run`.

### `compile.py` -- The Compiler

Reads daily logs, calls Claude Agent SDK, and creates/updates knowledge articles.

```bash
# Compile only new/changed daily logs (incremental)
uv run python scripts/compile.py

# Force recompile all daily logs from scratch
uv run python scripts/compile.py --all

# Compile a specific daily log
uv run python scripts/compile.py --file daily/2026-04-01.md

# Preview what would be compiled without executing
uv run python scripts/compile.py --dry-run
```

**How it works:**
1. Reads `AGENTS.md` (the schema specification)
2. Reads `knowledge/index.md` and all existing articles (full context)
3. Reads the target daily log
4. Calls Claude Agent SDK with tools: `Read`, `Write`, `Edit`, `Glob`, `Grep`
5. Claude extracts 3-7 concepts per daily log
6. Creates new articles or updates existing ones
7. Updates `knowledge/index.md` and `knowledge/log.md`
8. Records hash + cost in `scripts/state.json`

**Settings:** `max_turns=30`, `permission_mode="acceptEdits"` (auto-approves file operations)

**Cost:** $0.45-0.65 per daily log (increases as KB grows due to larger context)

### `flush.py` -- Memory Extractor

Normally called automatically by hooks. Can also be called manually:

```bash
uv run python scripts/flush.py <context_file.md> <session_id>
```

**How it works:**
1. Sets `CLAUDE_INVOKED_BY=memory_flush` (prevents recursive hook firing)
2. Reads the conversation context file
3. Calls Claude Agent SDK with **no tools** and `max_turns=2`
4. Claude returns structured daily log entry with sections:
   - **Context:** What was being worked on
   - **Key Exchanges:** Important Q&A pairs
   - **Decisions Made:** Architecture/library/design choices
   - **Lessons Learned:** Gotchas, patterns, insights
   - **Action Items:** Follow-ups needed
5. If nothing worth saving: returns `FLUSH_OK` and exits
6. Appends to `daily/YYYY-MM-DD.md`
7. Deduplicates: skips if same session was flushed within 60 seconds
8. If past 6 PM and today's log was modified: spawns `compile.py` in background

**Cost:** $0.02-0.05 per flush

**Logs:** All output goes to `scripts/flush.log`

### `query.py` -- Knowledge Base Query

Ask questions against your compiled knowledge base:

```bash
# Query and display the answer
uv run python scripts/query.py "How do I handle authentication redirects?"

# Query and save the answer as a Q&A article in knowledge/qa/
uv run python scripts/query.py "What patterns do I use for error handling?" --file-back
```

**How it works:**
1. Loads the entire knowledge base into context (index + all articles)
2. Calls Claude Agent SDK with tools: `Read`, `Glob`, `Grep` (+ `Write`, `Edit` if `--file-back`)
3. Claude reads the index, identifies relevant articles, synthesizes an answer
4. If `--file-back`: creates a Q&A article and updates the index

**Why this works without RAG:** At personal scale, the full KB fits in context. The LLM reads the index to find relevant articles, then reads those articles. This is more accurate than vector similarity because the LLM understands the question's intent.

**Cost:** $0.15-0.25 (display only), $0.25-0.40 (with `--file-back`)

### `lint.py` -- Health Checks

Run 7 checks on your knowledge base to find issues:

```bash
# Run all 7 checks (including LLM-powered contradiction detection)
uv run python scripts/lint.py

# Run structural checks only (free, no API calls)
uv run python scripts/lint.py --structural-only
```

**The 7 Checks:**

| # | Check | Type | Severity |
|---|-------|------|----------|
| 1 | Broken wikilinks | Structural | Error |
| 2 | Orphan pages (zero inbound links) | Structural | Warning |
| 3 | Orphan sources (daily logs not yet compiled) | Structural | Warning |
| 4 | Stale articles (source log changed since compile) | Structural | Warning |
| 5 | Missing backlinks (A links to B but B doesn't link to A) | Structural | Suggestion (auto-fixable) |
| 6 | Sparse articles (under 200 words) | Structural | Suggestion |
| 7 | Contradictions across articles | LLM-powered | Warning |

**Output:** Markdown report saved to `reports/lint-YYYY-MM-DD.md`

**Cost:** Free for `--structural-only`, $0.15-0.25 for full lint

---

## 8. Article Schema & Formats

The knowledge base uses three article types. All use YAML frontmatter + Markdown body.

### Concept Articles (`knowledge/concepts/SLUG.md`)

One concept per file. The atomic unit of knowledge.

```markdown
---
title: "Concept Name"
aliases: [alternate-name, other-name]
tags: [domain, topic, subtopic]
sources:
  - "daily/2026-04-01.md"
  - "daily/2026-04-03.md"
created: 2026-04-01
updated: 2026-04-03
---

# Concept Name

[2-4 sentence core explanation. Should stand alone.]

## Key Points

- [3-5 self-contained bullet points]
- [Each should be useful without reading the rest]

## Details

[Deeper explanation. Encyclopedic paragraphs.]
[Include code snippets, configuration examples, CLI commands as relevant.]

## Related Concepts

- [[concepts/related-concept]] - Brief description of how it connects
- [[connections/cross-cutting-insight]] - Why these relate

## Sources

- [[daily/2026-04-01.md]] - Initial discovery context
- [[daily/2026-04-03.md]] - Updated after debugging
```

### Connection Articles (`knowledge/connections/SLUG.md`)

Link 2+ concepts with non-obvious cross-cutting insights.

```markdown
---
title: "Connection Title"
aliases: []
tags: [integration, cross-cutting]
sources:
  - "daily/2026-04-02.md"
created: 2026-04-02
updated: 2026-04-02
---

# Connection Title

[Explain the non-obvious relationship between concepts]

## Connected Concepts

- [[concepts/concept-a]] - Role in this connection
- [[concepts/concept-b]] - Role in this connection

## Insight

[The cross-cutting insight that isn't captured in either concept alone]

## Sources

- [[daily/2026-04-02.md]] - Where this connection was discovered
```

### Q&A Articles (`knowledge/qa/SLUG.md`)

Created by `query.py --file-back`. Filed answers to questions.

```markdown
---
title: "Q: Original Question"
question: "The exact question that was asked"
consulted:
  - "concepts/article-1"
  - "concepts/article-2"
filed: 2026-04-05
---

# Q: Original Question

## Answer

[Synthesized answer with [[wikilinks]] to source articles]

## Sources Consulted

- [[concepts/article-1]] - What was found here
- [[concepts/article-2]] - What was found here

## Follow-Up Questions

- Question that could be explored next
- Another related question
```

---

## 9. The Knowledge Index (`index.md`)

`knowledge/index.md` is the **master catalog** of all articles. This is the primary retrieval mechanism -- both the session-start hook and query.py load it to find relevant knowledge.

The index is a markdown table with columns for title, type, tags, and a brief description. The compiler (`compile.py`) maintains it automatically.

**This file is critical.** If it becomes corrupted or out of sync, run `compile.py --all` to rebuild it.

---

## 10. Wikilink Convention

Articles reference each other using Obsidian-style wikilinks:

```
[[concepts/supabase-auth]]
[[connections/auth-and-webhooks]]
[[qa/how-to-handle-redirects]]
[[daily/2026-04-01]]
```

**Rules:**
- Path is relative to `knowledge/` directory
- No `.md` extension in the link
- Daily log links are relative to the project root
- The lint tool checks for broken wikilinks (check #1)

---

## 11. State Tracking & Deduplication

### `scripts/state.json` -- Compilation State

Tracks which daily logs have been compiled:

```json
{
  "daily/2026-04-01.md": {
    "hash": "sha256-of-file-contents",
    "compiled_at": "2026-04-01T18:30:00-05:00",
    "cost": 0.52
  }
}
```

- **Purpose:** Incremental compilation. Only recompiles logs whose hash has changed.
- **`--all` flag:** Ignores this state and recompiles everything.
- **Gitignored:** Regenerated automatically.

### `scripts/last-flush.json` -- Flush Deduplication

```json
{
  "session_id_abc123": 1712012345.67
}
```

- **Purpose:** Prevents duplicate flushes. If the same session ID was flushed within 60 seconds, the new flush is skipped.
- **Why needed:** Both `pre-compact.py` and `session-end.py` can fire for the same session.

---

## 12. Cost Breakdown

All costs use your existing Claude subscription via `~/.claude/.credentials.json`. No separate API key needed.

| Operation | API Calls | Approx. Cost |
|-----------|-----------|-------------|
| Session start (inject KB) | 0 (local only) | Free |
| Memory flush (per session) | 1 (Agent SDK, no tools) | $0.02-0.05 |
| Compile one daily log | 1 (Agent SDK, with tools, up to 30 turns) | $0.45-0.65 |
| Query (display only) | 1 (Agent SDK, read tools) | $0.15-0.25 |
| Query (with file-back) | 1 (Agent SDK, read+write tools) | $0.25-0.40 |
| Lint (structural only) | 0 | Free |
| Lint (full, with contradictions) | 1 (Agent SDK) | $0.15-0.25 |

**Typical daily cost:** If you have 3-5 Claude Code sessions per day, that's ~$0.10-0.25 in flushes + ~$0.50-0.65 for the evening compilation = **~$0.60-0.90/day**.

**Cost grows with KB size:** Compilation cost increases as the KB grows because the full index + existing articles are loaded into context for each compilation run.

---

## 13. Customization & Configuration

### Timezone

Edit `scripts/config.py` line 23:

```python
TIMEZONE = "America/Chicago"  # Change to your timezone
```

This affects the 6 PM auto-compilation trigger and daily log dating.

### Compilation Trigger Time

The 6 PM trigger is in `flush.py`. Search for the hour check and adjust:

```python
# In flush.py, look for the evening compilation trigger
if now.hour >= 18:  # Change 18 to your preferred hour (24h format)
```

### Context Injection Size

In `hooks/session-start.py`, the max context is capped at 20,000 characters. Adjust if your sessions need more or less context.

### Minimum Turns for Flush

- `session-end.py`: Flushes after 1+ turns (captures even short sessions)
- `pre-compact.py`: Flushes after 5+ turns (avoids noise from early compactions)

Adjust these thresholds in the respective hook files.

### Adding to an Existing Project

See [Integration with Other Projects](#17-integration-with-other-projects).

---

## 14. Troubleshooting

### Nothing is being captured

1. **Check hooks are active:** Open `.claude/settings.json` and verify the hooks array exists
2. **Check you're in the right directory:** Hooks only fire when Claude Code is opened in a directory that has `.claude/settings.json`
3. **Check flush.log:** `cat scripts/flush.log` -- all background process output goes here
4. **Check for recursion guard:** If `CLAUDE_INVOKED_BY` is set in your environment, hooks will exit early

### Daily logs exist but no knowledge articles

1. **Check the time:** Auto-compilation only triggers after 6 PM local time
2. **Run manually:** `uv run python scripts/compile.py`
3. **Check compile.log:** `cat scripts/compile.log`
4. **Check state.json:** If the daily log hash matches what's in state.json, the compiler thinks it's already compiled. Use `--all` to force.

### Knowledge base is stale or out of sync

```bash
# Rebuild everything from daily logs
uv run python scripts/compile.py --all

# Check for issues
uv run python scripts/lint.py
```

### Hook timeout errors

Hooks have tight timeouts (10-15 seconds). The hooks themselves are fast (they spawn background processes), but if `uv` is slow to start:
- Ensure the `.venv` exists: `uv sync`
- The first `uv run` in a new venv is slower; subsequent runs are fast

### Duplicate entries in daily logs

The deduplication system in `last-flush.json` uses a 60-second window. If you see duplicates, check if sessions are ending and restarting rapidly.

---

## 15. Design Decisions & Rationale

### Why No RAG or Vector Database?

At personal scale (50-500 articles), having the LLM read a structured markdown index is **more accurate** than vector similarity search:
- The LLM understands the *intent* of a question
- Cosine similarity only finds lexically similar content
- A well-structured index lets the LLM do targeted lookup
- No infrastructure to maintain, no embedding model to choose

**When to add RAG:** If your KB exceeds ~2,000 articles or ~2M tokens, consider a hybrid approach with semantic search as a first-pass filter.

### Why Both SessionEnd and PreCompact Hooks?

Long sessions may trigger multiple auto-compactions before the session closes. Without `PreCompact`, all intermediate conversation detail is lost to summarization before `SessionEnd` fires. The PreCompact hook captures knowledge *before* the context window is compacted.

### Why Detached Background Processes?

Hooks must complete within their timeout (10-15 seconds). API calls to Claude can take 30-120 seconds. The hooks write a temp file and spawn a detached process that survives the hook's exit, allowing the API calls to complete in the background without blocking Claude Code.

### Why Append-Only Daily Logs?

Daily logs are the **immutable source of truth**. They are never edited after creation. This means:
- Compilation is deterministic -- re-running `compile.py --all` on the same logs produces equivalent results
- No data loss from accidental edits
- Clear audit trail of what was captured and when

### Why the Flush Step Exists (Instead of Direct Compilation)?

Compilation is expensive ($0.45-0.65). Flushing is cheap ($0.02-0.05). The flush step cheaply extracts and accumulates knowledge throughout the day, then compilation runs once in the evening on the full day's log.

---

## 16. Scaling Considerations

| KB Size | Performance | Action Needed |
|---------|-------------|---------------|
| 0-100 articles | Excellent | None |
| 100-500 articles | Good | None |
| 500-1000 articles | Acceptable | Monitor compile costs |
| 1000-2000 articles | Slower compiles | Consider splitting by domain |
| 2000+ articles | Index may exceed context | Add RAG/semantic search layer |

**Compile cost scaling:** Each compilation loads the full index + all existing articles into context. As the KB grows, this context grows, increasing per-compilation cost.

**Index size scaling:** The session-start hook injects the index (capped at 20K chars). If the index exceeds this, older/less-relevant entries may be truncated.

---

## 17. Integration with Other Projects

To use the memory compiler with a project that isn't the compiler repo itself:

### Option A: Work Inside the Compiler Directory

The simplest approach. Clone your project inside (or alongside) the compiler directory and open Claude Code from the compiler root.

### Option B: Copy Hooks to Your Project

1. Copy `.claude/settings.json` to your project root
2. Update the hook commands to use absolute paths:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --project /path/to/claude-memory-compiler python /path/to/claude-memory-compiler/hooks/session-start.py",
        "timeout": 15
      }]
    }],
    "PreCompact": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --project /path/to/claude-memory-compiler python /path/to/claude-memory-compiler/hooks/pre-compact.py",
        "timeout": 10
      }]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --project /path/to/claude-memory-compiler python /path/to/claude-memory-compiler/hooks/session-end.py",
        "timeout": 10
      }]
    }]
  }
}
```

3. The `config.py` paths are relative to the compiler's `ROOT_DIR`, so all knowledge still lives in the compiler repo's directories.

### Option C: Symlink `.claude/settings.json`

```bash
ln -s /path/to/claude-memory-compiler/.claude/settings.json /your/project/.claude/settings.json
```

---

## Quick Reference Card

```
AUTOMATIC (zero effort):
  Session opens  -->  KB injected into context
  Session closes -->  Transcript captured, flushed to daily log
  After 6 PM     -->  Daily log compiled into knowledge articles

MANUAL COMMANDS:
  uv run python scripts/compile.py              # Compile new daily logs
  uv run python scripts/compile.py --all        # Recompile everything
  uv run python scripts/compile.py --dry-run    # Preview only
  uv run python scripts/query.py "question"     # Ask the KB
  uv run python scripts/query.py "q" --file-back # Ask + save answer
  uv run python scripts/lint.py                 # Full health check
  uv run python scripts/lint.py --structural-only # Free health check

KEY FILES:
  knowledge/index.md     # Master catalog (the brain)
  daily/YYYY-MM-DD.md    # Raw daily logs (the source)
  scripts/state.json     # What's been compiled
  scripts/flush.log      # Background process logs
  AGENTS.md              # Schema specification (read by compiler)

COSTS:
  Flush:   $0.02-0.05/session
  Compile: $0.45-0.65/daily log
  Query:   $0.15-0.40
  Lint:    Free (structural) / $0.15-0.25 (full)
```
