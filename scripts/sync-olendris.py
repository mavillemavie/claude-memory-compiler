"""
Olendris Vault Nightly Sync - updates Obsidian project/area notes from daily logs.

Reads the day's claude-memory-compiler daily log, sends it alongside current
Olendris vault notes to Claude, and applies structured JSON updates back to
the vault files. Designed to run nightly via cron after compile.py.

Usage:
    uv run python scripts/sync-olendris.py              # sync today's log
    uv run python scripts/sync-olendris.py 2026-04-13   # sync a specific date
"""

from __future__ import annotations

import os

os.environ["CLAUDE_INVOKED_BY"] = "olendris_sync"

import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "daily"
SCRIPTS_DIR = ROOT / "scripts"
LOG_FILE = SCRIPTS_DIR / "sync-olendris.log"
STATE_FILE = SCRIPTS_DIR / "sync-olendris-state.json"

OLENDRIS_VAULT = Path("/home/mv2/work/Obsidian Vaults/Olendris Vault")
PROJECTS_DIR = OLENDRIS_VAULT / "Projects"
AREAS_DIR = OLENDRIS_VAULT / "Areas"

# ── Scaling thresholds ───────────────────────────────────────────────────

MAX_NOTES_SINGLE_PASS = 40
MAX_TOKENS_ESTIMATE = 50_000
CHARS_PER_TOKEN = 4  # rough estimate

# ── Logging ──────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ── Vault reading ───────────────────────────────────────────────────────

def read_vault_notes() -> dict[str, str]:
    """Read all relevant Olendris vault notes. Returns {relative_path: content}."""
    notes: dict[str, str] = {}

    # Project notes
    if PROJECTS_DIR.exists():
        for f in sorted(PROJECTS_DIR.glob("*.md")):
            rel = f"Projects/{f.name}"
            notes[rel] = f.read_text(encoding="utf-8")

    # Area notes
    if AREAS_DIR.exists():
        for f in sorted(AREAS_DIR.glob("*.md")):
            rel = f"Areas/{f.name}"
            notes[rel] = f.read_text(encoding="utf-8")

    # Dashboard files
    for name in ["Home.md"]:
        path = OLENDRIS_VAULT / name
        if path.exists():
            notes[name] = path.read_text(encoding="utf-8")

    return notes


def check_scaling(notes: dict[str, str]) -> None:
    """Log a warning if vault is approaching single-pass limits."""
    note_count = len(notes)
    total_chars = sum(len(v) for v in notes.values())
    estimated_tokens = total_chars // CHARS_PER_TOKEN

    if note_count > MAX_NOTES_SINGLE_PASS or estimated_tokens > MAX_TOKENS_ESTIMATE:
        logging.warning(
            "Olendris vault at %d notes (~%d tokens). "
            "Consider switching to per-project sync mode.",
            note_count,
            estimated_tokens,
        )


# ── System prompt ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an Obsidian vault maintainer. Your job is to update project and area \
notes based on what happened in today's work session(s).

## Rules

1. NEVER delete existing content. Only append new information or mark tasks complete.
2. Decisions: always prefix with date (- YYYY-MM-DD: ...).
3. Tasks: mark done with [x] if the session completed them. Add new tasks discovered.
4. Notes: append new insights below existing content. Do not rewrite.
5. New projects: use "idea-" filename prefix, status: idea in frontmatter.
6. Strategy/Areas: only update if an explicit strategic decision was made.
7. Home.md: update the project table ONLY if a project status changed.
8. Project Pipeline: add new idea-stage projects, update status for existing ones.
9. If nothing meaningful happened for a given note, OMIT it from your response.
10. Preserve ALL existing YAML frontmatter fields exactly. Only change "status" if \
explicitly warranted.
11. When a project previously prefixed "idea-" has clearly been started (repo created, \
code written, user committed to building it), flag it for promotion by setting \
"promote": true in the update.

## Response format

Return ONLY valid JSON (no markdown fences, no commentary) matching this schema:

{
  "skip_reason": null or "reason string if nothing to update",
  "updates": [
    {
      "file": "Projects/Policy Poutine.md",
      "sections": {
        "Current State": "full replacement for section body",
        "Decisions": "append: - 2026-04-13: New decision...",
        "Notes": "append: Discovered something new..."
      },
      "promote": false
    }
  ],
  "new_projects": [
    {
      "name": "idea-Project Name",
      "overview": "What this project is about",
      "revenue_model": "unknown",
      "decisions": "- 2026-04-13: Initial concept emerged",
      "notes": ""
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
  "home_updates": false,
  "strategy_updates": {
    "Current Portfolio": "append: - **New Project** — description",
    "Strategic Direction": null
  }
}

- Section values prefixed with "append: " are appended after existing content.
- Section values WITHOUT the prefix REPLACE the section body entirely.
- null section values mean "no change" — omit unchanged sections entirely.
- "skip_reason" set to a string means no updates at all.
- "promote" on an update means rename idea-X.md to X.md and update status.
- Keep pipeline_updates empty array if no pipeline changes needed.
- Keep new_projects empty array if no new projects emerged.
- home_updates: true means regenerate the Home.md project table from current state.
"""


# ── LLM call ─────────────────────────────────────────────────────────────

async def run_sync(daily_log: str, vault_notes: dict[str, str]) -> dict:
    """Send daily log + vault notes to Claude, return structured update dict."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    # Build the user prompt with vault context
    vault_section = ""
    for path, content in vault_notes.items():
        vault_section += f"\n### File: {path}\n```markdown\n{content}\n```\n\n"

    prompt = f"""{SYSTEM_PROMPT}

---

Here is today's daily log from my work sessions:

## Daily Log

{daily_log}

## Current Olendris Vault Notes

{vault_section}

Analyze the daily log and determine what updates, if any, should be applied \
to the Olendris vault notes. Return ONLY valid JSON matching the schema above."""

    response_text = ""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text
            elif isinstance(message, ResultMessage):
                pass
    except Exception as e:
        import traceback
        logging.error("Agent SDK error: %s\n%s", e, traceback.format_exc())
        raise

    # Parse JSON from response (handle markdown fences if present)
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logging.error("Failed to parse LLM response as JSON: %s", e)
        logging.error("Raw response:\n%s", response_text[:2000])
        raise


# ── Update application ───────────────────────────────────────────────────

def update_section(content: str, section_name: str, new_value: str) -> str:
    """Update a specific ## section in a markdown file.

    Handles both 'append: ...' (add after existing) and full replacement.
    """
    is_append = new_value.startswith("append: ")
    if is_append:
        new_value = new_value[len("append: "):]

    # Match ## Section Name followed by content until next ## or end
    pattern = re.compile(
        r"(## " + re.escape(section_name) + r"\s*\n)(.*?)(?=\n## |\Z)",
        re.DOTALL,
    )

    match = pattern.search(content)
    if match:
        header = match.group(1)
        existing_body = match.group(2).rstrip()

        if is_append:
            updated_body = existing_body + "\n" + new_value if existing_body else new_value
        else:
            updated_body = new_value

        return content[:match.start()] + header + updated_body + "\n" + content[match.end():]
    else:
        # Section doesn't exist — append it at the end
        return content.rstrip() + f"\n\n## {section_name}\n\n{new_value}\n"


def apply_updates(updates: list[dict]) -> list[str]:
    """Apply section updates to existing vault files. Returns list of actions taken."""
    actions: list[str] = []

    for update in updates:
        file_rel = update["file"]
        file_path = OLENDRIS_VAULT / file_rel

        if not file_path.exists():
            logging.warning("File not found, skipping: %s", file_rel)
            continue

        content = file_path.read_text(encoding="utf-8")
        original = content

        # Handle promotion (idea- prefix removal)
        if update.get("promote") and file_path.name.startswith("idea-"):
            new_name = file_path.name[len("idea-"):]
            new_path = file_path.parent / new_name
            # Update status in frontmatter
            content = re.sub(
                r"^(status:\s*)idea\s*$",
                r"\g<1>active",
                content,
                flags=re.MULTILINE,
            )
            file_path.write_text(content, encoding="utf-8")
            file_path.rename(new_path)
            file_path = new_path
            actions.append(f"PROMOTED: {file_rel} -> Projects/{new_name}")
            # Re-read after rename
            content = file_path.read_text(encoding="utf-8")
            original = content

        sections = update.get("sections", {})
        for section_name, value in sections.items():
            if value is None:
                continue
            content = update_section(content, section_name, value)
            action_type = "APPENDED" if str(value).startswith("append: ") else "UPDATED"
            actions.append(f"{action_type}: {file_rel} -> ## {section_name}")

        if content != original:
            file_path.write_text(content, encoding="utf-8")

    return actions


def create_new_projects(new_projects: list[dict], today: str) -> list[str]:
    """Create new idea- project files. Returns list of actions taken."""
    actions: list[str] = []

    for proj in new_projects:
        name = proj["name"]
        if not name.startswith("idea-"):
            name = f"idea-{name}"

        file_path = PROJECTS_DIR / f"{name}.md"
        if file_path.exists():
            logging.info("Project file already exists, skipping: %s", file_path.name)
            continue

        overview = proj.get("overview", "")
        revenue_model = proj.get("revenue_model", "unknown")
        decisions = proj.get("decisions", f"- {today}: Initial concept emerged from session")
        notes = proj.get("notes", "")

        content = f"""---
tags:
  - project
status: idea
start: {today}
revenue-model: {revenue_model}
repo: null
priority: low
---

# {name.replace("idea-", "")}

## Overview

{overview}

## Current State

- [ ] Validate idea and define scope

## Decisions

{decisions}

## Notes

{notes}
"""
        file_path.write_text(content, encoding="utf-8")
        actions.append(f"CREATED: Projects/{name}.md")

    return actions


def update_pipeline(pipeline_updates: list[dict]) -> list[str]:
    """Update the Project Pipeline table with new or changed projects."""
    actions: list[str] = []
    pipeline_path = PROJECTS_DIR / "Project Pipeline.md"

    if not pipeline_path.exists() or not pipeline_updates:
        return actions

    content = pipeline_path.read_text(encoding="utf-8")

    for entry in pipeline_updates:
        project = entry["project"]
        # Check if project already in the pipeline table
        if f"[[{project}]]" in content or f"| {project} " in content:
            # Update status in existing row
            pattern = re.compile(
                r"(\|\s*\[\[" + re.escape(project) + r"\]\]\s*\|.*?\|.*?\|.*?\|)\s*(\w+)\s*\|"
            )
            match = pattern.search(content)
            if match:
                old_line = match.group(0)
                new_line = re.sub(r"\|\s*\w+\s*\|$", f" {entry['status']} |", old_line)
                if old_line != new_line:
                    content = content.replace(old_line, new_line)
                    actions.append(f"PIPELINE: Updated {project} status to {entry['status']}")
        else:
            # Add new row to Active Pipeline table
            new_row = (
                f"| [[{project}]] | {entry.get('revenue_potential', 'Unknown')} "
                f"| {entry.get('time_to_revenue', 'Unknown')} "
                f"| {entry.get('complexity', 'Unknown')} "
                f"| {entry['status']} |"
            )
            # Insert before "## Future Ideas" or at end of table
            insert_point = content.find("## Future Ideas")
            if insert_point > 0:
                content = content[:insert_point] + new_row + "\n\n" + content[insert_point:]
            else:
                # Find end of the Active Pipeline table
                table_end = content.rfind("|")
                if table_end > 0:
                    next_newline = content.find("\n", table_end)
                    if next_newline > 0:
                        content = content[:next_newline] + "\n" + new_row + content[next_newline:]

            actions.append(f"PIPELINE: Added {project} ({entry['status']})")

    if actions:
        pipeline_path.write_text(content, encoding="utf-8")

    return actions


def update_home(vault_notes: dict[str, str]) -> list[str]:
    """Regenerate Home.md project table from current project note frontmatter."""
    actions: list[str] = []
    home_path = OLENDRIS_VAULT / "Home.md"

    if not home_path.exists():
        return actions

    # Gather current project statuses
    projects: list[dict] = []
    for f in sorted(PROJECTS_DIR.glob("*.md")):
        if f.name in ("Project Pipeline.md",):
            continue
        content = f.read_text(encoding="utf-8")
        # Extract frontmatter
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            continue

        fm = fm_match.group(1)
        status = "unknown"
        revenue = "unknown"
        for line in fm.split("\n"):
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
            elif line.startswith("revenue-model:"):
                revenue = line.split(":", 1)[1].strip()

        display_name = f.stem.replace("idea-", "")
        projects.append({
            "name": display_name,
            "status": status,
            "revenue": revenue,
            "link": f"[[{display_name}]]",
        })

    if not projects:
        return actions

    # Build new table
    rows = []
    for p in projects:
        rows.append(
            f"| {p['link']} | {p['status']} | {p['revenue']} | See project note |"
        )

    new_table = (
        "| Project | Status | Revenue Model | Next Step |\n"
        "|---------|--------|---------------|----------|\n"
        + "\n".join(rows)
    )

    home_content = home_path.read_text(encoding="utf-8")

    # Replace existing table in ## Active Projects section
    pattern = re.compile(
        r"(## Active Projects\s*\n\s*)\|.*?\|(?:\n\|.*?\|)*",
        re.DOTALL,
    )
    match = pattern.search(home_content)
    if match:
        home_content = home_content[:match.start(1)] + "## Active Projects\n\n" + new_table + home_content[match.end():]
        home_path.write_text(home_content, encoding="utf-8")
        actions.append("HOME: Regenerated project table")

    return actions


def update_strategy(strategy_updates: dict | None) -> list[str]:
    """Update Business Strategy.md sections."""
    actions: list[str] = []

    if not strategy_updates:
        return actions

    strategy_path = AREAS_DIR / "Business Strategy.md"
    if not strategy_path.exists():
        return actions

    content = strategy_path.read_text(encoding="utf-8")
    original = content

    for section_name, value in strategy_updates.items():
        if value is None:
            continue
        content = update_section(content, section_name, value)
        action_type = "APPENDED" if str(value).startswith("append: ") else "UPDATED"
        actions.append(f"STRATEGY: {action_type} ## {section_name}")

    if content != original:
        strategy_path.write_text(content, encoding="utf-8")

    return actions


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    start_time = time.time()

    # Determine which date to sync
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")

    logging.info("=" * 60)
    logging.info("Olendris sync starting for %s", date_str)

    # Check daily log exists
    daily_log_path = DAILY_DIR / f"{date_str}.md"
    if not daily_log_path.exists():
        logging.info("No daily log for %s, skipping sync", date_str)
        return

    daily_log = daily_log_path.read_text(encoding="utf-8").strip()
    if not daily_log or len(daily_log) < 50:
        logging.info("Daily log too short (%d chars), skipping sync", len(daily_log))
        return

    # Check for FLUSH_OK only (nothing worth saving)
    non_flush_content = re.sub(r"FLUSH_OK.*", "", daily_log).strip()
    if not non_flush_content or len(non_flush_content) < 50:
        logging.info("Daily log contains only FLUSH_OK entries, skipping sync")
        return

    # Deduplication: skip if same date was already synced and log hasn't changed
    from hashlib import sha256
    log_hash = sha256(daily_log.encode()).hexdigest()[:16]
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if state.get("date") == date_str and state.get("hash") == log_hash:
                logging.info("Daily log unchanged since last sync, skipping")
                return
        except (json.JSONDecodeError, OSError):
            pass

    # Read vault notes
    vault_notes = read_vault_notes()
    logging.info("Read %d vault notes", len(vault_notes))
    check_scaling(vault_notes)

    # Estimate token usage
    total_input_chars = len(daily_log) + sum(len(v) for v in vault_notes.values())
    estimated_tokens = total_input_chars // CHARS_PER_TOKEN
    logging.info("Estimated input: ~%d tokens", estimated_tokens)

    # Run LLM sync
    try:
        result = asyncio.run(run_sync(daily_log, vault_notes))
    except Exception:
        logging.error("Sync failed, no files modified")
        return

    # Check if LLM decided to skip
    skip_reason = result.get("skip_reason")
    if skip_reason:
        logging.info("LLM skipped sync: %s", skip_reason)
        # Still save state so we don't retry
        STATE_FILE.write_text(
            json.dumps({"date": date_str, "hash": log_hash, "skipped": True}),
            encoding="utf-8",
        )
        return

    # Apply all updates
    all_actions: list[str] = []

    updates = result.get("updates", [])
    if updates:
        all_actions.extend(apply_updates(updates))

    new_projects = result.get("new_projects", [])
    if new_projects:
        all_actions.extend(create_new_projects(new_projects, date_str))

    pipeline_updates = result.get("pipeline_updates", [])
    if pipeline_updates:
        all_actions.extend(update_pipeline(pipeline_updates))

    if result.get("home_updates"):
        all_actions.extend(update_home(vault_notes))

    strategy_updates = result.get("strategy_updates")
    if strategy_updates:
        all_actions.extend(update_strategy(strategy_updates))

    # Log results
    elapsed = time.time() - start_time
    if all_actions:
        logging.info("Applied %d updates in %.1fs:", len(all_actions), elapsed)
        for action in all_actions:
            logging.info("  %s", action)
    else:
        logging.info("No updates to apply (%.1fs)", elapsed)

    # Save state
    STATE_FILE.write_text(
        json.dumps({
            "date": date_str,
            "hash": log_hash,
            "actions": len(all_actions),
            "timestamp": time.time(),
        }),
        encoding="utf-8",
    )

    logging.info("Olendris sync complete for %s", date_str)


if __name__ == "__main__":
    main()
