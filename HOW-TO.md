# Tentaqles — How-To Guide

Practical walkthroughs for using the plugin day to day. Assumes you've already installed it per the [README](README.md).

---

## Table of contents

1. [Onboarding a new client](#1-onboarding-a-new-client)
2. [Starting a new project inside a client](#2-starting-a-new-project-inside-a-client)
3. [Switching between clients safely](#3-switching-between-clients-safely)
4. [Inspecting and modifying client settings](#4-inspecting-and-modifying-client-settings)
5. [Querying memory across sessions](#5-querying-memory-across-sessions)
6. [Looking up a file's history](#6-looking-up-a-files-history)
7. [Building and searching knowledge graphs](#7-building-and-searching-knowledge-graphs)
8. [Using the dashboard](#8-using-the-dashboard)
9. [Recording decisions and pending items](#9-recording-decisions-and-pending-items)
10. [Teaching the plugin your preferences](#10-teaching-the-plugin-your-preferences)
11. [Troubleshooting identity mismatches](#11-troubleshooting-identity-mismatches)
12. [Recovering from a broken manifest](#12-recovering-from-a-broken-manifest)
13. [Privacy: what's captured and what isn't](#13-privacy-what-is-captured-and-what-isnt)

---

## 1. Onboarding a new client

**Scenario**: You signed a new client "Acme Corp" that uses Azure, PostgreSQL, and GitHub.

```
/tentaqles:add-client
```

The skill will ask you for:
- Client name (required)
- Display name (defaults to slugified name)
- Language (en / pt-BR / other)
- Cloud provider (azure / aws / digitalocean / none)
- Database provider (postgresql / snowflake / databricks / supabase / none)
- Git provider (github / gitlab / azure-devops)
- Git email
- Git username
- PM tool (asana / jira / github-projects / azure-devops / none)
- Workspace root path (where the client folder will live)

After you answer, it:
1. Creates the directory at `{workspaces_root}/{slug}/`
2. Generates `.tentaqles.yaml` with all your answers + the right preflight commands for your chosen providers
3. Creates `.claude/rules/identity.md` with git identity enforcement rules
4. Creates a `CLAUDE.md` skeleton at the client root
5. Configures git identity (via `git includeIf` in your global config, so any repo under that path inherits the right email automatically)
6. Registers the workspace in the Tentaqles meta-graph config
7. Runs initial preflight checks so you know what's already correct and what needs manual setup (e.g., `gh auth login`, `az login`)

**After running it**, you'll be told exactly what's left to configure manually — usually one or two login commands.

---

## 2. Starting a new project inside a client

**Scenario**: Acme wants an inventory API. You're already in `~/repos/acme/`.

```
/tentaqles:add-project
```

The skill detects the current client from the nearest `.tentaqles.yaml` and asks:
- Project name
- Description / goal
- Tech stack (optional)
- External ticket URL (optional — Asana, Jira, GitHub issue, etc.)

If you provide a ticket URL, it fetches the ticket (via `gh issue view` for GitHub, WebFetch otherwise) and extracts title, description, acceptance criteria, assignees, and due date.

Then it creates:
- `{client_root}/{project-slug}/` directory
- `CLAUDE.md` with the project's goal + inherited client context (cloud, database, git)
- `brief.md` if you provided a description or ticket (skipped otherwise — no empty briefs)
- Git repo initialized with the correct email/name from the client manifest (only if the directory isn't already a repo)

**If the parent is a mono-repo** (the client root itself is a git repo), the project folder stays as a subfolder inside that repo — no new git init.

---

## 3. Switching between clients safely

**Scenario**: You've been working on Acme (Azure) and need to switch to Globex (AWS + Snowflake).

**Option A — automatic**: Just `cd` to the Globex workspace and open Claude Code there. The `SessionStart` hook auto-switches git identity, gh account, cloud CLI, etc. You'll see a summary in the session preamble like:

```
Client: Globex Inc (en)
Cloud: aws (globex-prod)
Database: snowflake via python-connector
Git: github as globex-dev (dev@globex.io)
PM: jira
Stack: python, fastapi, snowflake

Auto-switch:
  * gh: acme-dev -> globex-dev
  * aws: profile -> globex
```

**Option B — explicit with safety verification**:

```
/tentaqles:switch-client globex
```

This shows you the target client's full state, runs all preflight checks, and tells you exactly what's still wrong (e.g., "AWS not logged in — run `aws sso login --profile globex`"). You can choose whether to apply fix commands interactively.

**Option C — just ask what's active**:

```
/tentaqles:workspace-status
```

Shows current client, cloud, database, git, active pending items, memory stats, and any preflight failures.

---

## 4. Inspecting and modifying client settings

**See the current settings**:

```
/tentaqles:client-settings
```

or

```
/tentaqles:client-settings show
```

**Change something**:

```
/tentaqles:client-settings change email to new@email.com
/tentaqles:client-settings set cloud to aws
/tentaqles:client-settings add fastapi to stack
/tentaqles:client-settings change database to snowflake
/tentaqles:client-settings switch to gitlab
```

The skill parses your natural-language request, edits `.tentaqles.yaml`, and auto-updates dependent fields (e.g., changing cloud provider regenerates the preflight command and blocked commands). It then re-runs preflight checks so you can confirm the change worked.

---

## 5. Querying memory across sessions

**Scenario**: You're debugging an auth bug in Dirtybird and vaguely remember you already solved something similar.

```
/tentaqles:query-memory JWT signature validation
```

The skill embeds your query via fastembed and semantically searches:
- Session summaries from past sessions
- Recorded decisions and their rationale
- Knowledge graph nodes (if a graph exists for this workspace)

It returns the top matches with scores, dates, and enough context for you to decide whether to pull up the full session.

**Tips**:
- Use natural language — "how did I handle X" works better than "X"
- The query is scoped to the **current** client workspace by default; to search across all workspaces, mention "across all clients"

---

## 6. Looking up a file's history

**Scenario**: You open `src/auth.py` and want to know when it was last touched, by which sessions, and why.

```
/tentaqles:file-history src/auth.py
```

Shows:
- **Touches** — every session that touched this file, with action (read/edit/debug/create), weight, session date, and session summary
- **Related decisions** — decisions whose `node_ids` include this file

Works with absolute or relative paths. If the file was renamed, the history is split — the old path and the new path are separate entries.

**Good for**:
- Understanding why code is the way it is before changing it
- Debugging a regression ("when did this start?")
- Onboarding to unfamiliar code in your own workspace

---

## 7. Building and searching knowledge graphs

**Build a graph for the current workspace**:

```
/tentaqles:build-graph
```

This runs either graphify (if installed) or the native Tentaqles graph engine on the current workspace, producing:
- `graphify-out/graph.json` — the full graph
- `graphify-out/graph.html` — offline-viewable interactive graph
- `graphify-out/GRAPH_REPORT.md` — audit trail with god nodes, clusters, surprising connections

After the graph is built, all nodes are embedded with fastembed so they're searchable semantically.

**Query the graph**:

```
/tentaqles:query-memory show me the authentication flow
```

This searches both memory AND graph nodes, returning matches ranked by semantic similarity.

**Which engine should I use?**

| Engine | Install | Best for |
|--------|---------|----------|
| graphify | `pip install graphifyy` | Most mature, broader language support via tree-sitter + subagent semantic extraction |
| native | `pip install tentaqles[graph]` | Built-in, no extra dependency, includes `.gitignore` support and docling integration |

Set preference via plugin config:

```
graph_engine: native   # or graphify, or empty for auto-detect
```

---

## 8. Using the dashboard

**Launch**:

```
/tentaqles:dashboard
```

Opens a local server at `http://localhost:8765` (falls back to 8766-8770 if occupied). The skill checks if a server is already running before spawning a new one.

**What you'll see**:
- Grid of cards, one per known workspace
- Each card shows: session count, touch count, decision count, open pending count
- Hot nodes with trend arrows (↑ attention rising / → stable / ↓ falling)
- Open pending items sorted by priority

**Live updates**: every 5 seconds via Server-Sent Events. Open it in any browser — no plugin state needed.

**Privacy**: all summaries and descriptions are run through the privacy filter before being served, so secrets don't appear in the HTML.

**Stop the server**: just close the terminal that spawned it, or kill the `dashboard_server.py` process.

---

## 9. Recording decisions and pending items

**Most of the time you don't need to do this manually** — the `SessionEnd` hook automatically:
- Parses your conversation transcript
- Extracts file touches from tool calls
- Detects open threads (TODO, "come back to this", "still need to", etc.) from your messages
- Saves a session summary

**When you want to record something explicit**, use:

```
/tentaqles:session-wrap
```

The skill will ask you (or infer from the conversation):
- What was accomplished (summary)
- Any decisions made, with rationale and rejected alternatives
- Any pending items with priority

Everything goes through the privacy filter, then into the workspace's `memory.db` via `memory-bridge.py`.

**Recording a decision mid-session** via the bridge directly:

```bash
echo '{"cwd": "'$PWD'", "event": "decision", "data": {"chosen": "RS256", "rationale": "allows public key verification in microservice arch", "rejected": ["HS256", "ES256"], "node_ids": ["src/auth.py"]}}' | python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-bridge.py"
```

The skill is easier, but this is handy in scripts.

---

## 10. Teaching the plugin your preferences

Tentaqles has a self-improving skills feature. When you correct the agent during a session (e.g., "no, we always use RS256 here" or "remember that the staging env is called 'qa'"), the `/tentaqles:session-wrap` skill picks up the correction and appends it to the relevant skill's `SKILL.md` file.

**Where corrections are stored**: corrections go to client-local skills at `{client_root}/.claude/skills/{skill_name}/SKILL.md` (not the shared plugin directory). This means corrections never bleed across clients — Acme's preferences don't affect Globex's sessions.

**Idempotent**: if you tell it the same rule twice, it's only recorded once. Jaccard similarity > 0.85 triggers deduplication.

**What counts as a correction**: explicit rules that apply to future behavior. Things like:
- "actually we always..."
- "remember for next time..."
- "that's wrong — do X not Y"
- "correction: ..."

Not: casual questions, reformulations, or polite disagreement that doesn't set a rule.

**Example flow**:
1. Claude makes a code suggestion
2. You say: "no, in Acme we always use black for formatting, not ruff"
3. Session wraps up (either by `/tentaqles:session-wrap` or auto on terminal close — wait, the auto path doesn't detect corrections; only the skill does)
4. Next time you work in Acme, the skill's `## Learned from user feedback` section includes your rule, so Claude picks it up automatically

---

## 11. Troubleshooting identity mismatches

**Symptom**: Your git push fails, or `gh pr create` errors out, or `az` says you're in the wrong subscription.

**Most of the time**, the `SessionStart` hook auto-switches these for you. If it didn't:

1. **Check what Tentaqles thinks is correct**:
   ```
   /tentaqles:workspace-status
   ```
   Shows expected git email, gh user, cloud subscription, and the current values of each.

2. **See all failing preflight checks** and get the exact fix commands:
   ```
   /tentaqles:switch-client {current-client-name}
   ```

3. **Manual fix patterns**:

   | Mismatch | Fix |
   |----------|-----|
   | Git email wrong | `cd {client_root} && git config user.email "expected@email.com"` (or, better, verify `includeIf` is set up globally) |
   | gh account wrong | `gh auth switch --user expected-user` |
   | gh user not authenticated | `gh auth login` then switch |
   | Azure sub wrong | `az account set --subscription "expected-sub"` |
   | AWS profile wrong | `export AWS_PROFILE=expected-profile` (env var, must be set in shell) |
   | DO context wrong | `doctl auth switch --context expected` |

4. **Persistent mismatch across sessions**: Your `.tentaqles.yaml` might have the wrong `expected_user`. Common mistake: putting the email in `expected_user` instead of the username. Fix:
   ```
   /tentaqles:client-settings
   ```
   and check the git section. `expected_user` must be the CLI username (e.g., `renatond`), never the email.

---

## 12. Recovering from a broken manifest

**Symptom**: Session preamble prints errors, or `workspace-status` can't load the manifest.

1. **Check the YAML syntax**:
   ```bash
   python -c "import yaml; yaml.safe_load(open('.tentaqles.yaml'))"
   ```
   If it prints an error, fix the syntax (common issues: unescaped colons, missing quotes, wrong indentation).

2. **Check required fields**:
   ```yaml
   schema: tentaqles-client-v1    # required
   client: <slug>                  # required
   display_name: <string>          # optional but recommended
   language: en                    # optional, defaults to en
   ```

3. **If the manifest is unsalvageable**: delete it and recreate with the skill:
   ```bash
   rm .tentaqles.yaml
   ```
   Then in a new Claude Code session at the client root:
   ```
   /tentaqles:add-client
   ```
   and re-answer the questions.

4. **If memory.db is corrupted**: it's at `{client_root}/.claude/memory.db`. Back up first (`copy memory.db memory.db.bak`), then delete it. The next session will create a fresh one. You'll lose temporal history but not your manifest or skills.

---

## 13. Privacy: what's captured and what isn't

**What Tentaqles captures**:
- Session start/end timestamps and duration
- Files touched with action type (read/edit/create/debug)
- Bash commands run (only to detect decision patterns, not stored verbatim)
- Explicit decisions you record via `/tentaqles:session-wrap` or `memory-bridge` event
- Pending items you record or that are auto-detected from "TODO" phrases in your messages
- Session summaries auto-generated from transcript
- A subset of your user messages (the ones flagged as containing decision patterns or open-thread phrases)

**What it does NOT capture**:
- Full conversation transcripts (only summaries and extracted items)
- Full file contents (only paths)
- Tool outputs (scanned for decisions but not stored)
- Private key material, API keys, JWTs, OAuth tokens, connection strings with credentials (redacted before storage via the privacy filter)

**Where it's stored**:
- `{client_root}/.claude/memory.db` — SQLite file, local only, gitignored by default
- `{CLAUDE_PLUGIN_DATA}/meta.db` — cross-workspace meta-memory
- `{CLAUDE_PLUGIN_DATA}/cache/` — embedding cache

**What crosses client boundaries**:
- Workspace status summaries in the meta-memory (so the dashboard and `switch-client` can show all workspaces)
- Client display names and stats

**What never crosses client boundaries**:
- Source code or file contents
- Decisions and their rationale (per-client)
- Pending items (per-client)
- Skill corrections (client-local overrides)
- Cross-client email leaks (detected and redacted when `authorized_emails` is set in the manifest)

**To audit redactions**, enable the audit log by setting an `audit_log_path` in the privacy section of your manifest (planned, not yet wired into config).

---

## One more thing

If you find something unclear or want a new workflow documented, run:

```
/tentaqles:session-wrap
```

and say "record a pending item: document X workflow in HOW-TO.md". The next session will pick up the pending item and you (or the plugin) can knock it out.

---

See [README.md](README.md) for architecture overview and [ROADMAP.md](ROADMAP.md) (local, not committed) for future features.
