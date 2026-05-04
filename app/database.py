import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import ProjectSeed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS story_bible (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS characters (
            name          TEXT PRIMARY KEY,
            facts         TEXT NOT NULL,
            voice_samples TEXT NOT NULL DEFAULT '[]',
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plot_threads (
            thread_id  TEXT PRIMARY KEY,
            title      TEXT NOT NULL,
            status     TEXT NOT NULL,
            summary    TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chapters (
            chapter_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            number      INTEGER NOT NULL UNIQUE,
            title       TEXT,
            arc_goal    TEXT NOT NULL,
            plan        TEXT NOT NULL DEFAULT '{}',
            summary     TEXT,
            status      TEXT NOT NULL DEFAULT 'planned'
        );

        CREATE TABLE IF NOT EXISTS scenes (
            scene_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id    INTEGER NOT NULL REFERENCES chapters(chapter_id),
            sequence      INTEGER NOT NULL,
            brief         TEXT NOT NULL,
            full_text     TEXT,
            summary       TEXT,
            facts_delta   TEXT,
            status        TEXT NOT NULL DEFAULT 'pending',
            created_at    TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS scenes_fts USING fts5(
            scene_id UNINDEXED,
            brief,
            full_text,
            summary,
            content='scenes',
            content_rowid='scene_id'
        );

        CREATE TABLE IF NOT EXISTS timeline_events (
            event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            story_day   INTEGER,
            description TEXT NOT NULL,
            scene_id    INTEGER REFERENCES scenes(scene_id)
        );

        CREATE TABLE IF NOT EXISTS continuity_issues (
            issue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            severity    TEXT NOT NULL,
            description TEXT NOT NULL,
            scene_id    INTEGER REFERENCES scenes(scene_id),
            resolved    INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS style_guide (
            entry_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            category  TEXT NOT NULL,
            content   TEXT NOT NULL
        );
    """)
    conn.commit()


def update_story_bible(conn: sqlite3.Connection, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        conn.execute(
            "INSERT OR REPLACE INTO story_bible (key, value) VALUES (?, ?)",
            (key, value if isinstance(value, str) else json.dumps(value)),
        )
    conn.commit()


def seed_project(conn: sqlite3.Connection, seed: ProjectSeed) -> None:
    for key, value in seed.story_bible.items():
        conn.execute(
            "INSERT OR REPLACE INTO story_bible (key, value) VALUES (?, ?)",
            (key, value if isinstance(value, str) else json.dumps(value)),
        )

    for char in seed.characters:
        conn.execute(
            "INSERT OR REPLACE INTO characters (name, facts, voice_samples, updated_at) VALUES (?, ?, ?, ?)",
            (char.name, char.facts.model_dump_json(), json.dumps(char.voice_samples), _now()),
        )

    for thread in seed.plot_threads:
        conn.execute(
            "INSERT OR REPLACE INTO plot_threads (thread_id, title, status, summary, updated_at) VALUES (?, ?, ?, ?, ?)",
            (thread.thread_id, thread.title, thread.status, thread.summary, _now()),
        )

    for entry in seed.style_guide:
        conn.execute(
            "INSERT INTO style_guide (category, content) VALUES (?, ?)",
            (entry.category, entry.content),
        )

    for arc in seed.arc_goals:
        conn.execute(
            "INSERT OR IGNORE INTO chapters (number, arc_goal, plan, status) VALUES (?, ?, '{}', 'planned')",
            (arc.chapter, arc.goal),
        )

    conn.commit()


# ── Read helpers (used by tools.py) ──────────────────────────────────────────

def get_story_bible(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT key, value FROM story_bible").fetchall()
    result = {}
    for row in rows:
        try:
            result[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            result[row["key"]] = row["value"]
    return result


def get_character(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM characters WHERE name = ?", (name,)).fetchone()
    if not row:
        return None
    return {
        "name": row["name"],
        "facts": json.loads(row["facts"]),
        "voice_samples": json.loads(row["voice_samples"]),
        "updated_at": row["updated_at"],
    }


def get_all_characters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT name, facts FROM characters ORDER BY name").fetchall()
    result = []
    for row in rows:
        facts = json.loads(row["facts"])
        result.append({
            "name": row["name"],
            "role": facts.get("role", ""),
            "status": facts.get("physical_state", ""),
        })
    return result


def get_plot_threads(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM plot_threads WHERE status = ? ORDER BY thread_id", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM plot_threads ORDER BY thread_id").fetchall()
    return [dict(r) for r in rows]


def get_chapter(conn: sqlite3.Connection, chapter_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM chapters WHERE chapter_id = ?", (chapter_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan"]) if d["plan"] else {}
    return d


def get_current_chapter(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM chapters WHERE status IN ('planned', 'in_progress') ORDER BY number LIMIT 1"
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan"]) if d["plan"] else {}
    return d


def get_current_scene(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("""
        SELECT s.* FROM scenes s
        JOIN chapters c ON s.chapter_id = c.chapter_id
        WHERE s.status IN ('pending', 'draft')
        ORDER BY c.number, s.sequence
        LIMIT 1
    """).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("facts_delta"):
        d["facts_delta"] = json.loads(d["facts_delta"])
    return d


def get_scene(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM scenes WHERE scene_id = ?", (scene_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("facts_delta"):
        d["facts_delta"] = json.loads(d["facts_delta"])
    return d


def get_scene_summary(conn: sqlite3.Connection, scene_id: int) -> str | None:
    row = conn.execute("SELECT summary FROM scenes WHERE scene_id = ?", (scene_id,)).fetchone()
    return row["summary"] if row else None


def get_scene_full_text(conn: sqlite3.Connection, scene_id: int) -> str | None:
    row = conn.execute("SELECT full_text FROM scenes WHERE scene_id = ?", (scene_id,)).fetchone()
    return row["full_text"] if row else None


def search_scenes(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT s.scene_id, s.chapter_id, s.sequence, s.brief, s.summary
        FROM scenes_fts f
        JOIN scenes s ON s.scene_id = f.scene_id
        WHERE scenes_fts MATCH ?
        ORDER BY rank
        LIMIT 5
    """, (query,)).fetchall()
    return [dict(r) for r in rows]


def get_timeline(
    conn: sqlite3.Connection,
    from_day: int | None = None,
    to_day: int | None = None,
) -> list[dict[str, Any]]:
    if from_day is not None and to_day is not None:
        rows = conn.execute(
            "SELECT * FROM timeline_events WHERE story_day BETWEEN ? AND ? ORDER BY story_day, event_id",
            (from_day, to_day),
        ).fetchall()
    elif from_day is not None:
        rows = conn.execute(
            "SELECT * FROM timeline_events WHERE story_day >= ? ORDER BY story_day, event_id",
            (from_day,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM timeline_events ORDER BY story_day, event_id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_style_guide(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT category, content FROM style_guide ORDER BY category").fetchall()
    return [dict(r) for r in rows]


def get_continuity_issues(
    conn: sqlite3.Connection, unresolved_only: bool = True
) -> list[dict[str, Any]]:
    if unresolved_only:
        rows = conn.execute(
            "SELECT * FROM continuity_issues WHERE resolved = 0 ORDER BY severity DESC"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM continuity_issues ORDER BY severity DESC").fetchall()
    return [dict(r) for r in rows]


def get_recent_approved_scenes(conn: sqlite3.Connection, limit: int = 3) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT scene_id, chapter_id, sequence, brief, summary
        FROM scenes WHERE status = 'approved'
        ORDER BY scene_id DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_last_chapter_summary(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT summary FROM chapters WHERE status = 'complete' ORDER BY number DESC LIMIT 1"
    ).fetchone()
    return row["summary"] if row else None


# ── Write helpers ─────────────────────────────────────────────────────────────

def save_chapter_plan(
    conn: sqlite3.Connection,
    chapter_number: int,
    arc_goal: str,
    title: str,
    plan: dict[str, Any],
) -> int:
    existing = conn.execute(
        "SELECT chapter_id FROM chapters WHERE number = ?", (chapter_number,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE chapters SET arc_goal=?, title=?, plan=?, status='planned' WHERE number=?",
            (arc_goal, title, json.dumps(plan), chapter_number),
        )
        chapter_id = existing["chapter_id"]
    else:
        cur = conn.execute(
            "INSERT INTO chapters (number, arc_goal, title, plan, status) VALUES (?, ?, ?, ?, 'planned')",
            (chapter_number, arc_goal, title, json.dumps(plan)),
        )
        chapter_id = cur.lastrowid

    # Insert scenes from the plan
    conn.execute("DELETE FROM scenes WHERE chapter_id = ? AND status = 'pending'", (chapter_id,))
    for scene in plan.get("scenes", []):
        conn.execute(
            "INSERT INTO scenes (chapter_id, sequence, brief, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (chapter_id, scene["sequence"], scene["brief"], _now()),
        )

    conn.execute(
        "UPDATE chapters SET status='in_progress' WHERE chapter_id=?", (chapter_id,)
    )
    conn.commit()
    return chapter_id


def save_scene_draft(
    conn: sqlite3.Connection,
    scene_id: int,
    prose: str,
    facts_delta: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE scenes SET full_text=?, facts_delta=?, status='draft' WHERE scene_id=?",
        (prose, json.dumps(facts_delta), scene_id),
    )
    conn.commit()


def approve_scene(
    conn: sqlite3.Connection,
    scene_id: int,
    prose: str,
    summary: str,
    validated_delta: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE scenes SET full_text=?, summary=?, facts_delta=?, status='approved' WHERE scene_id=?",
        (prose, summary, json.dumps(validated_delta), scene_id),
    )
    # Update FTS index
    conn.execute("INSERT OR REPLACE INTO scenes_fts (scene_id, brief, full_text, summary) "
                 "SELECT scene_id, brief, full_text, summary FROM scenes WHERE scene_id=?",
                 (scene_id,))
    conn.commit()

    # Apply validated delta to canon
    _apply_delta(conn, scene_id, validated_delta)
    conn.commit()

    # Check if chapter is now complete
    _maybe_complete_chapter(conn, scene_id)


def _apply_delta(conn: sqlite3.Connection, scene_id: int, delta: dict[str, Any]) -> None:
    for cu in delta.get("character_updates", []):
        row = conn.execute("SELECT facts FROM characters WHERE name=?", (cu["name"],)).fetchone()
        if row:
            facts = json.loads(row["facts"])
            for k, v in cu.get("changes", {}).items():
                if isinstance(v, list) and isinstance(facts.get(k), list):
                    facts[k] = list(set(facts[k] + v))
                else:
                    facts[k] = v
            conn.execute(
                "UPDATE characters SET facts=?, updated_at=? WHERE name=?",
                (json.dumps(facts), _now(), cu["name"]),
            )

    for pu in delta.get("plot_updates", []):
        update_parts = ["status=?", "updated_at=?"]
        params: list[Any] = [pu["status"], _now()]
        if pu.get("summary_update"):
            update_parts.append("summary=?")
            params.append(pu["summary_update"])
        params.append(pu["thread_id"])
        conn.execute(
            f"UPDATE plot_threads SET {', '.join(update_parts)} WHERE thread_id=?",
            params,
        )

    for ev in delta.get("timeline_events", []):
        conn.execute(
            "INSERT INTO timeline_events (story_day, description, scene_id) VALUES (?, ?, ?)",
            (ev.get("story_day"), ev["event"], scene_id),
        )

    for flag in delta.get("continuity_flags", []):
        if flag.get("confidence", "high") == "low":
            conn.execute(
                "INSERT INTO continuity_issues (severity, description, scene_id) VALUES (?, ?, ?)",
                (flag["severity"], flag["description"], scene_id),
            )


def _maybe_complete_chapter(conn: sqlite3.Connection, scene_id: int) -> None:
    row = conn.execute("SELECT chapter_id FROM scenes WHERE scene_id=?", (scene_id,)).fetchone()
    if not row:
        return
    chapter_id = row["chapter_id"]
    pending = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE chapter_id=? AND status != 'approved'",
        (chapter_id,),
    ).fetchone()[0]
    if pending == 0:
        conn.execute(
            "UPDATE chapters SET status='complete' WHERE chapter_id=?", (chapter_id,)
        )
        conn.commit()


def update_character_manual(
    conn: sqlite3.Connection, name: str, changes: dict[str, Any]
) -> bool:
    row = conn.execute("SELECT facts FROM characters WHERE name=?", (name,)).fetchone()
    if not row:
        return False
    facts = json.loads(row["facts"])
    facts.update(changes)
    conn.execute(
        "UPDATE characters SET facts=?, updated_at=? WHERE name=?",
        (json.dumps(facts), _now(), name),
    )
    conn.commit()
    return True


def update_thread_manual(
    conn: sqlite3.Connection, thread_id: str, status: str | None, summary: str | None
) -> bool:
    row = conn.execute(
        "SELECT thread_id FROM plot_threads WHERE thread_id=?", (thread_id,)
    ).fetchone()
    if not row:
        return False
    if status:
        conn.execute(
            "UPDATE plot_threads SET status=?, updated_at=? WHERE thread_id=?",
            (status, _now(), thread_id),
        )
    if summary:
        conn.execute(
            "UPDATE plot_threads SET summary=?, updated_at=? WHERE thread_id=?",
            (summary, _now(), thread_id),
        )
    conn.commit()
    return True


def save_chapter_summary(conn: sqlite3.Connection, chapter_id: int, summary: str) -> None:
    conn.execute(
        "UPDATE chapters SET summary=? WHERE chapter_id=?", (summary, chapter_id)
    )
    conn.commit()


def get_continuity_issue(conn: sqlite3.Connection, issue_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM continuity_issues WHERE issue_id=?", (issue_id,)
    ).fetchone()
    return dict(row) if row else None


def add_continuity_issue(
    conn: sqlite3.Connection,
    severity: str,
    description: str,
    scene_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO continuity_issues (severity, description, scene_id) VALUES (?, ?, ?)",
        (severity, description, scene_id),
    )
    conn.commit()


def resolve_continuity_issue(conn: sqlite3.Connection, issue_id: int) -> None:
    conn.execute(
        "UPDATE continuity_issues SET resolved=1 WHERE issue_id=?", (issue_id,)
    )
    conn.commit()


def apply_resolution_delta(
    conn: sqlite3.Connection,
    character_updates: list[dict[str, Any]],
    plot_updates: list[dict[str, Any]],
) -> None:
    """Apply character/plot updates produced by the auto-resolver."""
    for cu in character_updates:
        row = conn.execute("SELECT facts FROM characters WHERE name=?", (cu["name"],)).fetchone()
        if row:
            facts = json.loads(row["facts"])
            for k, v in cu.get("changes", {}).items():
                facts[k] = v
            conn.execute(
                "UPDATE characters SET facts=?, updated_at=? WHERE name=?",
                (json.dumps(facts), _now(), cu["name"]),
            )

    for pu in plot_updates:
        if not pu.get("thread_id"):
            continue
        parts: list[str] = ["updated_at=?"]
        params: list[Any] = [_now()]
        if pu.get("status"):
            parts.append("status=?")
            params.append(pu["status"])
        if pu.get("summary_update"):
            parts.append("summary=?")
            params.append(pu["summary_update"])
        params.append(pu["thread_id"])
        conn.execute(
            f"UPDATE plot_threads SET {', '.join(parts)} WHERE thread_id=?", params
        )

    conn.commit()
