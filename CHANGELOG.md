# Changelog

All notable changes to the Tentaqles plugin. Versions follow [semver](https://semver.org/).

## [0.3.1] — 2026-04-16 — "Portable Runtime"

Fixes plugin breakage on machines where `python` on PATH resolves to a broken venv shim or a venv missing plugin dependencies.

### Added

- **`scripts/tq_env.sh`** — bash runtime bootstrap that resolves `CLAUDE_PLUGIN_ROOT` (env var → `$BASH_SOURCE` → filesystem search of `~/.claude/plugins/cache/`), finds a working Python interpreter (`py -3` → `python3` → `python`, validated via `sys.executable`), exports `PYTHONPATH` with plugin root + lib dir, and runs `bootstrap.py` if core deps are missing. Idempotent — skips if already resolved.
- **`scripts/tq_run.sh`** — thin wrapper: sources `tq_env.sh`, then exec's the target script with the resolved interpreter. Used by all hooks.
- **Touch event acknowledgment.** The `touch` handler in `memory-bridge.py` now prints `{"touch_id": "..."}` on success, matching `decision` and `pending` handler behavior.

### Fixed

- **`session_end` without prior `session_start`.** `MemoryStore.end_session()` now auto-creates a session if none is active (lazy upsert), fixing "no active session" errors on first-run wrap-up and orphaned sessions after compaction.
- **All 17 skills** updated to use `"$TENTAQLES_PY"` instead of bare `python` and `PYTHONPATH` instead of inline `sys.path.insert(0, os.environ.get('CLAUDE_PLUGIN_ROOT', '.'))` hacks. Each bash block gets a 2-line prelude sourcing `tq_env.sh`.
- **`hooks/hooks.json`** updated: all hook commands use `sh tq_run.sh <script>` instead of `python <script>`.
- **`networkx`** added as a transitive dependency (required by embedding service via `graphify_hook.py`).

### Breaking

None. All changes are backward compatible — if `CLAUDE_PLUGIN_ROOT` is set by the harness, it is used; the fallback only fires when it isn't.

## [0.3.0] — 2026-04-13 — "Memory Matures"

Six architectural features that deepen how the plugin remembers, reasons about, and shares knowledge across workspaces.

### Added

- **4-tier memory consolidation with decay.** Brain-inspired tiers: Working → Episodic → Semantic → Procedural. Sessions auto-promote to Episodic on close; important facts climb to Semantic and Procedural over time. Ebbinghaus decay evicts stale entries automatically. New tables `semantic_memories` and `procedural_memories` in `memory.db`; new column `sessions.memory_tier`. Skill: `/tentaqles:compact-memory`. Cron: `scripts/compaction-cron.py`.
- **Contradiction detection and supersession.** When a new decision is recorded, it is embedded and compared cosine-similarity against active decisions. If similarity > 0.82 and the text disagrees, the old decision is auto-superseded — the chain is preserved, not deleted. New column `decisions.contradiction_score`. Skill: `/tentaqles:decision-history`. Programmatic: `MemoryStore.get_decision_lineage()`.
- **Time-travel snapshots.** Append-only JSON snapshots at `{workspace}/.claude/snapshots/{utc_iso}.json` capture the manifest, memory stats, and git identity at a point in time. Auto-fires on identity auto-switch and any Write to `.tentaqles.yaml` via the `snapshot-guard.py` PreToolUse hook. Keeps last 30; older pruned. Skill: `/tentaqles:rollback`.
- **Workspace profiles (learned, not declared).** Auto-generated profile from `memory.db` — hot files, session frequency, top concepts — written to `{workspace}/.claude/profile.json` and injected into the SessionStart preamble. Regenerates automatically when >7 days old. Skill: `/tentaqles:profile-refresh`.
- **Cross-workspace pattern detection.** Weekly background job reads decisions from all registered workspace memory.dbs (read-only), embeds them, clusters them, and surfaces patterns that span two or more workspaces. Output at `{data_dir}/metagraph/patterns.json`, surfaced in `MetaMemory.get_cross_workspace_context()`. Skill: `/tentaqles:cross-patterns`. Cron: `scripts/pattern-cron.py`.
- **Inter-workspace signals (pub/sub).** A `signals` table in the global `meta.db` lets Workspace A emit a message to Workspace B; B reads it on next session start. 48-hour TTL, acknowledge-once. Opt-in per workspace via `signals:` manifest block. Skill: `/tentaqles:emit-signal`.

### Schema

All additions backward compatible (`ALTER TABLE ADD COLUMN` with `OperationalError` catch). Existing v0.2 databases migrate on first open.

- `sessions.memory_tier` column (values: `working`, `episodic`)
- `decisions.contradiction_score` column
- New `semantic_memories` table
- New `procedural_memories` table
- New `signals` table in global `meta.db`

### Manifest

New optional section:

```yaml
signals:
  enabled: true
  subscribe_to: [dirtybird, acme-corp]
```

Missing section = feature disabled. Fully backward compatible.

### Build

- Tests: 60 → 238 (178 new)
- Pip dependencies added: 0
- New modules: 10
- New scripts: 4
- New skills: 6

## [0.2.0] — "Foundation"

The first public release after the rebrand. Six Tier 1 quick wins on top of the workspace identity / temporal memory / knowledge graph foundation.

### Added

- **PreCompact hook re-injection.** Critical state (manifest summary, decisions, hot nodes) is re-injected into the conversation before Claude Code auto-compacts, so important context survives compaction.
- **Privacy filter.** Every observation is scanned for secrets (API keys, JWTs, OAuth tokens, connection strings, private keys, cross-client emails) before touching disk. Integrated into store, session-end, knowledge-capture, and memory-bridge.
- **File history skill.** `/tentaqles:file-history` shows everything the plugin has recorded about a specific file — touches, decisions, pending items, across sessions.
- **Open thread auto-detection.** End-of-session parser detects unresolved threads from the transcript and records them as pending items automatically.
- **Self-improving skills.** User corrections are recorded to the skill's own definition at `{client_root}/.claude/skills/{name}/SKILL.md`. Per-client isolation — one client's corrections never affect another.
- **Real-time dashboard.** Runs at `http://localhost:8765` with a live grid of workspaces, hot nodes, and pending items. Pure stdlib, self-contained HTML, works offline.

Plus the v0.1 foundation: workspace auto-detection via `.tentaqles.yaml`, auto-switching git/gh/az/aws identity, preflight checks, per-client SQLite temporal memory, pluggable knowledge graph engine (graphify or native), and cross-workspace semantic search via the meta-graph.
