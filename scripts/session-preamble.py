#!/usr/bin/env python3
"""
SessionStart hook bridge — generates client context preamble for Claude Code.

Reads JSON from stdin (cwd, session_id), loads client manifest,
runs preflight checks, and outputs combined context to stdout.
"""

import io
import json
import os
import sys

# Ensure UTF-8 stdout on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add plugin root to sys.path so tentaqles package is importable
plugin_root = os.environ.get(
    "CLAUDE_PLUGIN_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
sys.path.insert(0, plugin_root)

FALLBACK_CONTEXT = "Tentaqles plugin active. No client manifest found for this workspace."


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = "{}"

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}

    cwd = payload.get("cwd", os.getcwd())

    try:
        from tentaqles.manifest.loader import (
            format_context_summary,
            get_client_context,
            run_preflight_checks,
        )

        context = get_client_context(cwd)

        # If no client identified, output minimal context
        if context.get("client", "unknown") == "unknown":
            print(FALLBACK_CONTEXT)
            return

        checks = run_preflight_checks(context)
        summary = format_context_summary(context, checks)

        # Append temporal context from memory store if available
        temporal = _get_temporal_context(cwd, context)
        if temporal:
            summary += "\n\n" + temporal

        print(summary)

    except ImportError:
        print(FALLBACK_CONTEXT)
    except Exception:
        print(FALLBACK_CONTEXT)


def _get_temporal_context(cwd: str, context: dict) -> str:
    """Attempt to load temporal context from the memory store."""
    try:
        client_root = context.get("client_root", "")
        if not client_root:
            return ""

        # Check if memory.db exists before trying to load it
        from pathlib import Path

        db_path = Path(client_root) / ".claude" / "memory.db"
        if not db_path.is_file():
            return ""

        from tentaqles.memory.store import MemoryStore

        store = MemoryStore(str(db_path))
        return store.get_temporal_context()
    except ImportError:
        return ""
    except Exception:
        return ""


if __name__ == "__main__":
    main()
