"""Per-workspace temporal memory backed by SQLite.

Each client workspace gets its own memory.db at {workspace}/.claude/memory.db.
Tracks sessions, file/node touches, decisions, and pending items.
Activity scores use exponential decay (30-day half-life).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np

try:
    from tentaqles.privacy import redact_text as _redact_text
except ImportError:  # pragma: no cover - graceful degradation
    def _redact_text(text, strict=False, authorized_emails=None, audit_log_path=None):
        return (text or "", [])


def _redact(text):
    """Safely redact a string, returning the original on any error."""
    if text is None:
        return text
    try:
        redacted, _ = _redact_text(text)
        return redacted
    except Exception:
        return text

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_s  INTEGER,
    summary     TEXT,
    embedding   BLOB,
    tags        TEXT DEFAULT '[]',
    metadata    TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS touches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    node_id     TEXT NOT NULL,
    node_type   TEXT NOT NULL,
    touched_at  TEXT NOT NULL,
    action      TEXT NOT NULL,
    weight      REAL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_touches_node ON touches(node_id, touched_at);
CREATE INDEX IF NOT EXISTS idx_touches_session ON touches(session_id);

CREATE TABLE IF NOT EXISTS decisions (
    id              TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id),
    created_at      TEXT NOT NULL,
    node_ids        TEXT NOT NULL DEFAULT '[]',
    chosen          TEXT NOT NULL,
    rejected        TEXT DEFAULT '[]',
    rationale       TEXT NOT NULL,
    confidence      TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'active',
    superseded_by   TEXT,
    embedding       BLOB,
    tags            TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status, created_at);

CREATE TABLE IF NOT EXISTS pending (
    id          TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id),
    created_at  TEXT NOT NULL,
    description TEXT NOT NULL,
    node_ids    TEXT DEFAULT '[]',
    priority    TEXT DEFAULT 'medium',
    resolved_at TEXT,
    resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_open ON pending(resolved_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class MemoryStore:
    """Per-workspace temporal memory."""

    def __init__(self, workspace_path: str | Path, half_life_days: float = 30.0):
        workspace_path = Path(workspace_path)
        db_dir = workspace_path / ".claude"
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = db_dir / "memory.db"
        self._half_life = half_life_days
        self._active_session_id: str | None = None
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Embedding service — lazy loaded
        self._emb = None

    def _get_emb(self):
        if self._emb is None:
            from tentaqles.embeddings.service import EmbeddingService
            self._emb = EmbeddingService()
        return self._emb

    def _embed(self, text: str) -> bytes:
        emb = self._get_emb()
        vec = emb.embed([text])[0]
        return vec.tobytes()

    def _vec_from_blob(self, blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    # --- Session lifecycle ---

    def start_session(self, tags: list[str] | None = None, metadata: dict | None = None) -> str:
        sid = _uid()
        self._conn.execute(
            "INSERT INTO sessions (id, started_at, tags, metadata) VALUES (?, ?, ?, ?)",
            (sid, _now(), json.dumps(tags or []), json.dumps(metadata or {})),
        )
        self._conn.commit()
        self._active_session_id = sid
        return sid

    def end_session(self, summary: str, tags: list[str] | None = None) -> dict:
        sid = self._active_session_id
        if not sid:
            return {"error": "no active session"}
        now = _now()
        row = self._conn.execute("SELECT started_at, tags FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not row:
            return {"error": "session not found"}
        started = datetime.fromisoformat(row[0])
        duration = int((datetime.now(timezone.utc) - started).total_seconds())
        existing_tags = json.loads(row[1] or "[]")
        all_tags = list(set(existing_tags + (tags or [])))
        embedding = self._embed(summary)
        self._conn.execute(
            "UPDATE sessions SET ended_at=?, duration_s=?, summary=?, embedding=?, tags=? WHERE id=?",
            (now, duration, summary, embedding, json.dumps(all_tags), sid),
        )
        self._conn.commit()
        self._active_session_id = None
        return {"id": sid, "duration_s": duration, "summary": summary}

    # --- Recording ---

    def touch(
        self,
        node_id: str,
        node_type: Literal["file", "function", "concept", "module"] = "file",
        action: Literal["read", "edit", "create", "delete", "debug", "review"] = "edit",
        weight: float = 1.0,
    ) -> None:
        sid = self._active_session_id or "untracked"
        if sid == "untracked":
            # Create a placeholder session if none active
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions (id, started_at) VALUES (?, ?)",
                ("untracked", _now()),
            )
        safe_node_id = _redact(node_id)
        self._conn.execute(
            "INSERT INTO touches (session_id, node_id, node_type, touched_at, action, weight) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, safe_node_id, node_type, _now(), action, weight),
        )
        self._conn.commit()

    def record_decision(
        self,
        chosen: str,
        rationale: str,
        node_ids: list[str] | None = None,
        rejected: list[str] | None = None,
        confidence: Literal["low", "medium", "high"] = "medium",
        tags: list[str] | None = None,
    ) -> str:
        did = _uid()
        safe_chosen = _redact(chosen)
        safe_rationale = _redact(rationale)
        safe_rejected = [_redact(r) for r in (rejected or [])]
        text = f"{safe_chosen}. {safe_rationale}"
        embedding = self._embed(text)
        self._conn.execute(
            "INSERT INTO decisions (id, session_id, created_at, node_ids, chosen, rejected, rationale, confidence, embedding, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                did,
                self._active_session_id or "untracked",
                _now(),
                json.dumps(node_ids or []),
                safe_chosen,
                json.dumps(safe_rejected),
                safe_rationale,
                confidence,
                embedding,
                json.dumps(tags or []),
            ),
        )
        self._conn.commit()
        return did

    def supersede_decision(self, old_id: str, chosen: str, rationale: str, **kwargs) -> str:
        new_id = self.record_decision(chosen, rationale, **kwargs)
        self._conn.execute(
            "UPDATE decisions SET status='superseded', superseded_by=? WHERE id=?",
            (new_id, old_id),
        )
        self._conn.commit()
        return new_id

    def add_pending(
        self,
        description: str,
        node_ids: list[str] | None = None,
        priority: Literal["low", "medium", "high", "critical"] = "medium",
    ) -> str:
        pid = _uid()
        safe_description = _redact(description)
        self._conn.execute(
            "INSERT INTO pending (id, session_id, created_at, description, node_ids, priority) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, self._active_session_id or "untracked", _now(), safe_description, json.dumps(node_ids or []), priority),
        )
        self._conn.commit()
        return pid

    def resolve_pending(self, item_id: str) -> None:
        self._conn.execute(
            "UPDATE pending SET resolved_at=?, resolved_by=? WHERE id=?",
            (_now(), self._active_session_id or "untracked", item_id),
        )
        self._conn.commit()

    # --- Querying ---

    def get_active_nodes(self, limit: int = 20) -> list[dict]:
        """Top nodes by decayed activity score with trend detection."""
        hl = self._half_life
        rows = self._conn.execute(f"""
            SELECT
                node_id, node_type,
                COUNT(*) as touch_count,
                MAX(touched_at) as last_touched,
                SUM(weight * POWER(2.0, -(JULIANDAY('now') - JULIANDAY(touched_at)) / {hl})) as score,
                SUM(CASE WHEN JULIANDAY('now') - JULIANDAY(touched_at) <= 14
                    THEN weight * POWER(2.0, -(JULIANDAY('now') - JULIANDAY(touched_at)) / {hl})
                    ELSE 0 END) as recent_score,
                SUM(CASE WHEN JULIANDAY('now') - JULIANDAY(touched_at) > 14
                              AND JULIANDAY('now') - JULIANDAY(touched_at) <= 60
                    THEN weight * POWER(2.0, -(JULIANDAY('now') - JULIANDAY(touched_at)) / {hl})
                    ELSE 0 END) as older_score
            FROM touches
            GROUP BY node_id, node_type
            ORDER BY score DESC
            LIMIT ?
        """, (limit,)).fetchall()

        results = []
        for node_id, node_type, count, last, score, recent, older in rows:
            if older > 0.01:
                ratio = recent / older
                trend = "rising" if ratio > 1.5 else ("falling" if ratio < 0.5 else "stable")
            else:
                trend = "rising" if recent > 0.01 else "stable"
            results.append({
                "node_id": node_id,
                "node_type": node_type,
                "touch_count": count,
                "last_touched": last,
                "activity_score": round(score, 3),
                "trend": trend,
            })
        return results

    def get_node_history(self, node_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT session_id, touched_at, action, weight FROM touches WHERE node_id=? ORDER BY touched_at DESC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        return [{"session_id": r[0], "touched_at": r[1], "action": r[2], "weight": r[3]} for r in rows]

    def get_recent_decisions(self, days: int = 30, status: str = "active") -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, created_at, chosen, rejected, rationale, confidence, tags FROM decisions WHERE status=? AND JULIANDAY('now') - JULIANDAY(created_at) <= ? ORDER BY created_at DESC",
            (status, days),
        ).fetchall()
        return [
            {"id": r[0], "created_at": r[1], "chosen": r[2], "rejected": json.loads(r[3]),
             "rationale": r[4], "confidence": r[5], "tags": json.loads(r[6])}
            for r in rows
        ]

    def get_open_pending(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, created_at, description, node_ids, priority FROM pending WHERE resolved_at IS NULL ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, created_at DESC",
        ).fetchall()
        return [
            {"id": r[0], "created_at": r[1], "description": r[2],
             "node_ids": json.loads(r[3]), "priority": r[4]}
            for r in rows
        ]

    def search_memory(self, query: str, limit: int = 5) -> list[dict]:
        """Semantic search over session summaries and decisions."""
        emb = self._get_emb()
        query_vec = emb.embed([query])[0]
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)

        results = []

        # Search sessions
        rows = self._conn.execute(
            "SELECT id, summary, embedding, started_at FROM sessions WHERE embedding IS NOT NULL"
        ).fetchall()
        for sid, summary, blob, started in rows:
            vec = self._vec_from_blob(blob)
            vec_norm = vec / (np.linalg.norm(vec) + 1e-10)
            score = float(query_norm @ vec_norm)
            results.append({"type": "session", "id": sid, "text": summary, "date": started, "score": score})

        # Search decisions
        rows = self._conn.execute(
            "SELECT id, chosen, rationale, embedding, created_at FROM decisions WHERE embedding IS NOT NULL AND status='active'"
        ).fetchall()
        for did, chosen, rationale, blob, created in rows:
            vec = self._vec_from_blob(blob)
            vec_norm = vec / (np.linalg.norm(vec) + 1e-10)
            score = float(query_norm @ vec_norm)
            results.append({"type": "decision", "id": did, "text": f"{chosen}: {rationale}", "date": created, "score": score})

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def get_context_summary(self, max_tokens: int = 500) -> str:
        """Generate cross-session context for session start (~500 tokens)."""
        lines = []

        # Last session
        row = self._conn.execute(
            "SELECT id, started_at, duration_s, summary FROM sessions WHERE ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1"
        ).fetchone()
        if row:
            sid, started, dur, summary = row
            dur_str = f"{dur // 60}m" if dur and dur >= 60 else f"{dur}s" if dur else "?"
            lines.append(f"## Last session ({dur_str}, {started[:10]})")
            if summary:
                lines.append(summary)
            # Top files from that session
            touches = self._conn.execute(
                "SELECT node_id, action, COUNT(*) as c FROM touches WHERE session_id=? GROUP BY node_id ORDER BY c DESC LIMIT 5",
                (sid,),
            ).fetchall()
            if touches:
                files = ", ".join(f"{t[0]} ({t[1]})" for t in touches)
                lines.append(f"Files: {files}")

        # Active nodes
        nodes = self.get_active_nodes(limit=8)
        if nodes:
            lines.append("\n## Hot nodes")
            for n in nodes:
                lines.append(f"- {n['node_id']}: score {n['activity_score']}, {n['touch_count']} touches [{n['trend']}]")

        # Open pending
        pending = self.get_open_pending()
        if pending:
            lines.append(f"\n## Open items ({len(pending)})")
            for p in pending[:5]:
                lines.append(f"- [{p['priority']}] {p['description']}")

        # Recent decisions
        decisions = self.get_recent_decisions(days=30)
        if decisions:
            lines.append(f"\n## Recent decisions")
            for d in decisions[:3]:
                rej = f" (over {', '.join(d['rejected'])})" if d['rejected'] else ""
                lines.append(f"- {d['created_at'][:10]}: {d['chosen']}{rej} — {d['rationale'][:100]}")

        text = "\n".join(lines)
        # Rough token budget (4 chars/token)
        if len(text) > max_tokens * 4:
            text = text[: max_tokens * 4] + "\n..."
        return text

    def get_last_session(self) -> dict | None:
        row = self._conn.execute(
            "SELECT id, started_at, ended_at, duration_s, summary, tags FROM sessions WHERE ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "started_at": row[1], "ended_at": row[2], "duration_s": row[3], "summary": row[4], "tags": json.loads(row[5] or "[]")}

    def prune(self, older_than_days: int = 365) -> int:
        cur = self._conn.execute(
            "DELETE FROM touches WHERE JULIANDAY('now') - JULIANDAY(touched_at) > ?",
            (older_than_days,),
        )
        self._conn.commit()
        return cur.rowcount

    def stats(self) -> dict:
        sessions = self._conn.execute("SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL").fetchone()[0]
        touches = self._conn.execute("SELECT COUNT(*) FROM touches").fetchone()[0]
        decisions = self._conn.execute("SELECT COUNT(*) FROM decisions WHERE status='active'").fetchone()[0]
        pending = self._conn.execute("SELECT COUNT(*) FROM pending WHERE resolved_at IS NULL").fetchone()[0]
        return {
            "db_path": str(self._db_path),
            "sessions": sessions,
            "touches": touches,
            "active_decisions": decisions,
            "open_pending": pending,
            "db_size_kb": round(self._db_path.stat().st_size / 1024, 1) if self._db_path.exists() else 0,
        }

    # --- F1: PreCompact re-injection context ---

    def get_compact_context(self, max_tokens: int = 600) -> str:
        """Build a compact re-injection block for PreCompact hook.

        Prioritizes: recent active decisions, hot nodes, open pending.
        Truncates to roughly max_tokens * 4 chars.
        """
        lines: list[str] = ["## Workspace memory (re-injected)"]

        # Last 3 active decisions
        rows = self._conn.execute(
            "SELECT chosen, rationale FROM decisions WHERE status='active' "
            "ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        if rows:
            lines.append("### Recent decisions")
            for chosen, rationale in rows:
                rat = (rationale or "")[:80]
                lines.append(f"- {chosen}: {rat}")

        # Top 5 hot nodes
        try:
            hot = self.get_active_nodes(5)
        except Exception:
            hot = []
        if hot:
            lines.append("### Hot nodes")
            for n in hot:
                lines.append(
                    f"- {n['node_id']} (score {n['activity_score']}, {n['trend']})"
                )

        # Open pending (capped at 10)
        try:
            pending = self.get_open_pending()
        except Exception:
            pending = []
        if pending:
            lines.append(f"### Open items ({len(pending)})")
            for p in pending[:10]:
                lines.append(f"- [{p['priority']}] {p['description']}")

        if len(lines) == 1:
            lines.append("(no prior memory recorded)")

        text = "\n".join(lines)
        budget = max_tokens * 4
        if len(text) > budget:
            text = text[:budget] + "\n... (truncated)"
        return text

    # --- F3: enriched file/node history ---

    def get_node_history_enriched(self, node_id: str, limit: int = 50) -> dict:
        """Return touches joined with sessions plus related decisions."""
        touch_rows = self._conn.execute(
            """
            SELECT t.session_id, t.touched_at, t.action, t.weight,
                   s.summary, s.started_at, s.duration_s
            FROM touches t
            LEFT JOIN sessions s ON s.id = t.session_id
            WHERE t.node_id = ?
            ORDER BY t.touched_at DESC
            LIMIT ?
            """,
            (node_id, limit),
        ).fetchall()
        touches = [
            {
                "session_id": r[0],
                "touched_at": r[1],
                "action": r[2],
                "weight": r[3],
                "session_summary": r[4],
                "session_started_at": r[5],
                "session_duration_s": r[6],
            }
            for r in touch_rows
        ]

        like_pattern = f"%{node_id}%"
        decision_rows = self._conn.execute(
            "SELECT id, created_at, chosen, rationale, confidence, node_ids "
            "FROM decisions WHERE status='active' AND node_ids LIKE ? "
            "ORDER BY created_at DESC",
            (like_pattern,),
        ).fetchall()
        related = []
        for did, created, chosen, rationale, confidence, node_ids_json in decision_rows:
            try:
                nids = json.loads(node_ids_json or "[]")
            except (ValueError, TypeError):
                nids = []
            if node_id in nids:
                related.append(
                    {
                        "id": did,
                        "created_at": created,
                        "chosen": chosen,
                        "rationale": rationale,
                        "confidence": confidence,
                    }
                )

        return {
            "node_id": node_id,
            "touches": touches,
            "related_decisions": related,
        }

    # --- F4: similar pending detection ---

    def find_similar_pending(
        self, description: str, similarity_threshold: float = 0.8
    ) -> list[dict]:
        """Return open pending items whose Jaccard token similarity exceeds threshold."""
        import re as _re

        def _tokens(s: str) -> set:
            return {t for t in _re.split(r"\W+", (s or "").lower()) if t}

        def _jaccard(a: set, b: set) -> float:
            if not a and not b:
                return 0.0
            union = a | b
            if not union:
                return 0.0
            return len(a & b) / len(union)

        target = _tokens(description)
        if not target:
            return []

        rows = self._conn.execute(
            "SELECT id, created_at, description, node_ids, priority "
            "FROM pending WHERE resolved_at IS NULL "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

        results = []
        for r in rows:
            sim = _jaccard(target, _tokens(r[2]))
            if sim > similarity_threshold:
                results.append(
                    {
                        "id": r[0],
                        "created_at": r[1],
                        "description": r[2],
                        "node_ids": json.loads(r[3] or "[]"),
                        "priority": r[4],
                        "similarity": round(sim, 3),
                    }
                )
        return results

    def close(self):
        self._conn.close()
