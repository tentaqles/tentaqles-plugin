---
name: workspace-status
description: Show current workspace detection, client context, and preflight check results. Use when the user asks about their current workspace context or identity status.
---

# Workspace Status

Detect the current client workspace and run all preflight checks.

```bash
python -c "
import sys, os; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}')
from tentaqles.manifest.loader import load_manifest, get_client_context, run_preflight_checks, format_context_summary

cwd = os.getcwd()
manifest = load_manifest(cwd)
ctx = get_client_context(cwd)
checks = run_preflight_checks(manifest or ctx)
print(format_context_summary(ctx, checks))

# Show memory stats if available
try:
    from tentaqles.memory.store import MemoryStore
    store = MemoryStore(ctx.get('client_root', cwd))
    stats = store.stats()
    print(f'\nMemory: {stats[\"sessions\"]} sessions, {stats[\"touches\"]} touches, {stats[\"active_decisions\"]} decisions, {stats[\"open_pending\"]} pending')
    store.close()
except Exception:
    print('\nMemory: not initialized')
"
```

Report the results clearly to the user.
