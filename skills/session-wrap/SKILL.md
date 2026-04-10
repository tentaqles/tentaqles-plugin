---
name: session-wrap
description: End-of-session wrap-up that saves what was accomplished, decisions made, and pending items to temporal memory. Use when the user says "done", "wrapping up", "signing off", "that's it for now", "save session", "end session", or any signal that the current work session is ending. Also use when the user explicitly asks to record a decision or add a pending item mid-session.
---

# Session Wrap

Save the current session's context to temporal memory so the next session starts with full awareness of what happened. This captures three things: what was done (summary), what was decided (decisions), and what's left (pending items).

The goal is to make the user's future self — or the next Claude session — able to pick up exactly where this one left off.

## Detect Client Workspace

```bash
python -c "
import sys, os
sys.path.insert(0, os.environ.get('CLAUDE_PLUGIN_ROOT', '.'))
from tentaqles.manifest.loader import load_manifest
manifest = load_manifest(os.getcwd())
if manifest:
    print(f'client={manifest[\"client\"]}')
    print(f'root={manifest[\"_client_root\"]}')
    print(f'display={manifest.get(\"display_name\", manifest[\"client\"])}')
else:
    print('client=unknown')
    print(f'root={os.getcwd()}')
    print('display=Unknown Workspace')
"
```

## Gather Session Context

Look back through the conversation to identify:

1. **Summary** — What was the main thing accomplished? One or two sentences. Don't be vague ("worked on code") — be specific ("Fixed race condition in order_processor.py by switching to optimistic locking. Added retry logic for failed webhooks.").

2. **Decisions** — Any architectural or design choices made during the session. Look for patterns like:
   - "Let's go with X instead of Y"
   - "We chose X because..."
   - "Switched from X to Y"
   - Tradeoffs discussed and resolved
   
   For each decision, capture: what was chosen, what was rejected (if anything), and the rationale.

3. **Pending items** — Anything mentioned as "TODO", "later", "next time", "still need to", or left incomplete. These carry forward as open items for the next session.

4. **Files touched** — Scan the conversation for files that were read, edited, or created. These become activity touches.

If the context isn't clear from the conversation, ask the user briefly: "Before we wrap up — any decisions or pending items I should save for next time?"

Don't over-interview. If the user just said "thanks, done", infer the summary from the conversation and confirm it with them.

## Record to Memory

### Save session end

```bash
echo '{"cwd": "{client_root}", "event": "session_end", "data": {"summary": "{summary}", "tags": ["{relevant_tags}"]}}' | python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-bridge.py"
```

The summary should be 1-3 sentences. Tags should be lowercase keywords (e.g., "auth", "bugfix", "refactor", "api").

### Save decisions (for each one)

```bash
echo '{"cwd": "{client_root}", "event": "decision", "data": {"chosen": "{what was chosen}", "rationale": "{why}", "node_ids": ["{affected_files_or_modules}"], "rejected": ["{alternatives_considered}"], "confidence": "{low|medium|high}", "tags": ["{tags}"]}}' | python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-bridge.py"
```

Only record decisions that would be useful in a future session. "Chose tabs over spaces" is not worth saving. "Chose RS256 over HS256 for JWT signing because our microservice architecture needs public key verification" is.

### Save pending items (for each one)

```bash
echo '{"cwd": "{client_root}", "event": "pending", "data": {"description": "{what needs to be done}", "priority": "{low|medium|high|critical}", "node_ids": ["{related_files}"]}}' | python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-bridge.py"
```

### Record file touches

For each significant file that was edited or created during the session:

```bash
echo '{"cwd": "{client_root}", "event": "touch", "data": {"node_id": "{relative_file_path}", "node_type": "file", "action": "{edit|create|debug|review}", "weight": 1.0}}' | python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-bridge.py" 2>/dev/null || true
```

Use `weight: 2.0` for files that were debugged extensively or were the main focus. Use `weight: 0.5` for files that were only glanced at.

## Show Updated Context

After saving, display the updated context summary so the user can verify:

```bash
echo '{"cwd": "{client_root}", "event": "context", "data": {}}' | python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-bridge.py"
```

This shows: last session summary, hot nodes, open pending items, recent decisions.

## Report

Keep the wrap-up report short:

```
Session saved for {client display_name}:
  Summary: {1-line summary}
  Decisions: {N} recorded
  Pending: {N} items ({priorities})
  Files: {N} touched

Next session will start with this context automatically.
```

## Error Handling

- If the memory bridge script fails: tell the user what you would have saved (print the summary, decisions, pending items as text) so they have a record even if persistence failed.
- If not in a client workspace: still try to save — use cwd as the workspace root. The memory will be less organized but not lost.
- If the user just says "bye" with no context to extract: save a minimal session end with whatever you can infer from the conversation. Something is better than nothing.
