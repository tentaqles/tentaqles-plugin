#!/usr/bin/env bash
# Tentaqles plugin runtime bootstrap — source this to get:
#   CLAUDE_PLUGIN_ROOT  absolute path to plugin directory
#   TENTAQLES_PY        absolute path to a working Python interpreter
#   PYTHONPATH           includes plugin root + plugin data lib dir

# Guard: if already resolved, skip entirely
[ -n "$TENTAQLES_PY" ] && [ -x "$TENTAQLES_PY" ] && return 0 2>/dev/null || true

# --- 1. Resolve plugin root ---
if [ -z "$CLAUDE_PLUGIN_ROOT" ]; then
  # Try $BASH_SOURCE (works when this file is sourced by full path)
  if [ -n "${BASH_SOURCE[0]:-}" ]; then
    CLAUDE_PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  else
    # Search the Claude Code plugin cache
    for _d in "$HOME/.claude/plugins/cache/tentaqles/tentaqles"/*/; do
      [ -f "${_d}plugin.json" ] && CLAUDE_PLUGIN_ROOT="${_d%/}" && break
    done
  fi
fi
export CLAUDE_PLUGIN_ROOT

# --- 2. Resolve plugin data dir ---
export CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.tentaqles}"

# --- 3. Find a working Python interpreter ---
# Probe candidates in order; resolve each to its absolute sys.executable
# so broken venv shims (issue #3) are filtered out by the -c check.
TENTAQLES_PY=""
for _probe in "py -3" python3 python; do
  _exe=$($_probe -c "import sys; print(sys.executable)" 2>/dev/null) || continue
  if [ -n "$_exe" ]; then
    TENTAQLES_PY="$_exe"
    break
  fi
done
# Last resort: bare python (may be a broken shim, but better than nothing)
[ -z "$TENTAQLES_PY" ] && TENTAQLES_PY="python"
export TENTAQLES_PY

# --- 4. Set PYTHONPATH for tentaqles imports + bootstrap deps ---
_lib="$CLAUDE_PLUGIN_DATA/lib"
_need_root=true
_need_lib=true
# Don't duplicate if already present
case ":${PYTHONPATH:-}:" in
  *":$CLAUDE_PLUGIN_ROOT:"*) _need_root=false ;;
esac
case ":${PYTHONPATH:-}:" in
  *":$_lib:"*) _need_lib=false ;;
esac
_add=""
$_need_lib && [ -d "$_lib" ] && _add="$_lib"
$_need_root && _add="${_add:+$_add:}$CLAUDE_PLUGIN_ROOT"
[ -n "$_add" ] && export PYTHONPATH="${_add}${PYTHONPATH:+:$PYTHONPATH}"

# --- 5. Ensure deps are installed (runs bootstrap.py if needed) ---
if ! "$TENTAQLES_PY" -c "import yaml, pathspec" >/dev/null 2>&1; then
  "$TENTAQLES_PY" "$CLAUDE_PLUGIN_ROOT/scripts/bootstrap.py" </dev/null 2>/dev/null || true
  # Re-add lib dir if bootstrap just created it
  if [ -d "$_lib" ]; then
    case ":${PYTHONPATH:-}:" in
      *":$_lib:"*) ;;
      *) export PYTHONPATH="$_lib${PYTHONPATH:+:$PYTHONPATH}" ;;
    esac
  fi
fi
