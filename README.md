# Tentaqles

Multi-workspace orchestration for developers who work across multiple clients with AI coding assistants.

## What it does

If you freelance, consult, or work across multiple client codebases, Tentaqles solves three problems:

1. **Identity isolation** — Prevents pushing code with the wrong git email, running CLI commands against the wrong cloud subscription, or querying the wrong database. Preflight checks run automatically before every external operation.

2. **Persistent memory** — Tracks what you worked on, what decisions you made, and what's pending across sessions. When you return to a client after days away, the context is already there.

3. **Cross-workspace search** — Builds knowledge graphs per client and connects them via semantic embeddings. Ask "have I solved this problem before?" and find the answer even if it was for a different client.

## Quick start

### Install the plugin

```bash
# From the marketplace
/plugin marketplace add tentaqles/tentaqles-plugin
/plugin install tentaqles-plugin@tentaqles-tentaqles-plugin

# Or test locally
claude --plugin-dir /path/to/tentaqles-plugin
```

### First-run dependencies

On the first session after installing, the plugin's bootstrap hook automatically installs Python dependencies (`pyyaml`, `pathspec`, `fastembed`, `numpy`) into the plugin's data directory (`${CLAUDE_PLUGIN_DATA}/lib`). This is isolated from your system Python and only happens once.

Requirements:
- **Python 3.10+** on PATH (the plugin runs Python subprocesses)
- **pip** available (`python -m pip --version`)
- **git**, and optionally **gh**, **az**, **aws**, **doctl** — whichever CLIs your client manifests use for preflight checks

If the auto-install fails (no network, pip issues, etc.), the plugin runs in degraded mode and prints the manual install command:

```bash
pip install pyyaml pathspec fastembed numpy
```

Optional extras:
- `pip install tentaqles[graph]` — native knowledge graph engine (adds tree-sitter)
- `pip install graphifyy` — use graphify as the graph engine instead
- `pip install docling` — rich PPTX/PDF parsing

### Try the demo

```
/tentaqles:setup-demo ~/tentaqles-demo
```

This creates two mock client workspaces (Acme Corp and Globex Inc) with sample Python code, documentation, and `.tentaqles.yaml` manifests. Use them to explore every feature without touching real projects.

### Set up a real client workspace

Drop a `.tentaqles.yaml` at your client root:

```yaml
schema: tentaqles-client-v1
client: my-client
display_name: "My Client"
language: en

cloud:
  provider: azure
  subscription_name: "My Sub"
  preflight: "az account show --query name -o tsv"
  expected: "My Sub"

database:
  provider: postgresql
  dialect: postgresql
  access: mcp
  mcp_server: postgres

git:
  provider: github
  email: "me@client.com"
  user: my-github-user
  host: github
  preflight: "gh auth status"
  expected_user: my-github-user

stack: [python, flask, postgresql]
```

That's it. Tentaqles will detect this file from any subfolder and enforce the correct identity.

## How it works

### Workspace detection

When a Claude Code session starts, Tentaqles walks up from the current directory looking for `.tentaqles.yaml`. The first one it finds defines the client context. Every subfolder inherits it.

```
~/repos/my-client/
  .tentaqles.yaml          <- defines the client
  project-a/               <- inherits my-client context
    src/
      app.py               <- still my-client context
  project-b/               <- also inherits
```

### Preflight checks

Before any git, cloud CLI, or database operation, Tentaqles verifies:

| Operation | Check | Blocked if wrong |
|-----------|-------|-----------------|
| `git commit/push` | Git email matches manifest | Yes |
| `gh pr create` | GitHub user matches manifest | Yes |
| `az storage list` | Azure subscription matches | Yes |
| `aws s3 ls` | AWS account matches | Yes |
| Any blocked command | Pattern from manifest | Yes |

### Temporal memory

Each client workspace gets a SQLite database tracking:
- **Sessions** — start/end, duration, summary, embedded for search
- **Touches** — which files/functions were accessed, with decay scoring
- **Decisions** — what was chosen, what was rejected, and why
- **Pending items** — open work items that carry forward

Activity scores use exponential decay (30-day half-life). Files touched today score 1.0, a month ago 0.5, six months ago ~0.015.

### Knowledge graphs

Uses [graphify](https://github.com/safishamsi/graphify) to build per-client knowledge graphs, then embeds all nodes with fastembed for semantic search. A meta-graph merges concepts across clients while keeping source code isolated.

## Skills

| Skill | Description |
|-------|-------------|
| `/tentaqles:setup-demo` | Create demo workspaces with mock data |
| `/tentaqles:build-graph` | Build knowledge graph + embeddings |
| `/tentaqles:query-memory` | Semantic search over memory and graphs |
| `/tentaqles:workspace-status` | Show current context and preflight results |

## CLI

```bash
tentaqles demo [path]    # Create demo workspaces
tentaqles status [path]  # Show workspace detection
tentaqles init           # Initialize Tentaqles
```

## Requirements

- Python 3.10+
- Claude Code
- Dependencies: `pyyaml`, `fastembed`, `numpy`, `pathspec`
- Optional: `graphifyy` (for knowledge graphs)

## License

MIT
