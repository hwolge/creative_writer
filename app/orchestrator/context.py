"""Assembles compact, token-aware context for each LLM call type."""
import json
import sqlite3
from typing import Any

from app import database as db
from app.config import settings

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def _count(text: str) -> int:
        return len(_enc.encode(text))
except Exception:
    def _count(text: str) -> int:  # fallback: word-based estimate
        return int(len(text.split()) * 1.35)


def _trim(text: str, max_tokens: int) -> str:
    if _count(text) <= max_tokens:
        return text
    words = text.split()
    while words and _count(" ".join(words)) > max_tokens:
        words = words[: int(len(words) * 0.9)]
    return " ".join(words) + " [trimmed]"


def _format_story_bible(bible: dict[str, Any]) -> str:
    lines = []
    for k, v in bible.items():
        val = json.dumps(v) if not isinstance(v, str) else v
        lines.append(f"  {k}: {val}")
    return "STORY BIBLE:\n" + "\n".join(lines)


def _format_characters(chars: list[dict[str, Any]]) -> str:
    lines = ["CHARACTERS:"]
    for c in chars:
        lines.append(f"  {c['name']} — {c.get('role', '')} [{c.get('status', '')}]")
    return "\n".join(lines)


def _format_character_full(char: dict[str, Any]) -> str:
    lines = [f"CHARACTER: {char['name']}"]
    for k, v in char.get("facts", {}).items():
        lines.append(f"  {k}: {v}")
    if char.get("voice_samples"):
        lines.append("  Voice samples:")
        for s in char["voice_samples"][:2]:
            lines.append(f'    "{s}"')
    return "\n".join(lines)


def _format_threads(threads: list[dict[str, Any]]) -> str:
    lines = ["PLOT THREADS:"]
    for t in threads:
        lines.append(f"  [{t['status'].upper()}] {t['thread_id']}: {t['title']}")
        lines.append(f"    {t['summary']}")
    return "\n".join(lines)


def _format_style_guide(entries: list[dict[str, Any]]) -> str:
    lines = ["STYLE GUIDE:"]
    for e in entries:
        lines.append(f"  [{e['category']}] {e['content']}")
    return "\n".join(lines)


def _format_timeline(events: list[dict[str, Any]]) -> str:
    lines = ["TIMELINE:"]
    for e in events:
        day = f"Day {e['story_day']}" if e.get("story_day") else "?"
        lines.append(f"  {day}: {e['description']}")
    return "\n".join(lines)


# ── Planner context ───────────────────────────────────────────────────────────

def build_planner_messages(conn: sqlite3.Connection, arc_goal: str) -> list[dict[str, Any]]:
    bible = _trim(
        _format_story_bible(db.get_story_bible(conn)),
        settings.budget_story_bible,
    )
    style = _trim(
        _format_style_guide(db.get_style_guide(conn)),
        settings.budget_style_guide,
    )
    chars = _trim(
        _format_characters(db.get_all_characters(conn)),
        settings.budget_characters_summary,
    )
    threads = _trim(
        _format_threads(db.get_plot_threads(conn, status="open")),
        settings.budget_plot_threads,
    )
    timeline_events = db.get_timeline(conn)[-20:]  # last 20 events
    timeline = _trim(_format_timeline(timeline_events), settings.budget_timeline)

    prev_summary = db.get_last_chapter_summary(conn) or "This is the first chapter."
    prev = _trim(f"PREVIOUS CHAPTER SUMMARY:\n{prev_summary}", settings.budget_prev_chapter)

    context_block = "\n\n".join([bible, style, chars, threads, timeline, prev])

    system = (
        "You are a master novelist and story architect working in collaboration with the author. "
        "Your task is to propose exactly 3 distinct options for the next chapter.\n\n"
        "Make the 3 options meaningfully different — vary the POV, pacing, which plot threads "
        "advance, and what is revealed. The author will choose one.\n\n"
        "You have access to tools to query story state. Use them as needed.\n\n"
        "Respond with a JSON object (no markdown fences) matching this schema:\n"
        '{"options": [{'
        '"title": "string", '
        '"arc_goal": "string", '
        '"pov": "character name", '
        '"emotional_arc": "string", '
        '"scenes": [{"sequence": 1, "brief": "string", "beats": ["string"], "location": "string"}], '
        '"reveals": ["string"], '
        '"continuity_risks": ["string"]'
        "}]}"
    )

    user = (
        f"STORY CONTEXT:\n{context_block}\n\n"
        f"ARC GOAL FOR THIS CHAPTER:\n{arc_goal}\n\n"
        "Propose 3 distinct chapter options."
    )

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ── Writer context ────────────────────────────────────────────────────────────

def build_writer_messages(
    conn: sqlite3.Connection,
    scene_brief: str,
    pov_character: str | None = None,
    chapter_context: str = "",
) -> list[dict[str, Any]]:
    bible_data = db.get_story_bible(conn)
    output_language = str(bible_data.get("output_language", "English")).strip()
    bible = _trim(_format_story_bible(bible_data), settings.budget_story_bible)
    style = _trim(
        _format_style_guide(db.get_style_guide(conn)),
        settings.budget_style_guide,
    )

    pov_block = ""
    if pov_character:
        char = db.get_character(conn, pov_character)
        if char:
            pov_block = _trim(
                _format_character_full(char), settings.budget_pov_char
            )

    # Recent approved scenes for immediate continuity
    recent = db.get_recent_approved_scenes(conn, limit=2)
    recent_text = ""
    if recent:
        lines = ["RECENT SCENES:"]
        for s in recent:
            lines.append(f"  Scene {s['scene_id']}: {s.get('summary') or s['brief']}")
        recent_text = _trim("\n".join(lines), settings.budget_prev_scene)

    open_threads = _trim(
        _format_threads(db.get_plot_threads(conn, status="open")),
        settings.budget_plot_threads,
    )

    context_parts = [p for p in [bible, style, pov_block, open_threads, recent_text] if p]
    context_block = "\n\n".join(context_parts)

    lang_instruction = (
        f"Write ALL prose in {output_language}. "
        "The facts_delta JSON block must remain in English regardless of output language.\n\n"
        if output_language.lower() != "english" else ""
    )

    system = (
        "You are a skilled novelist writing compelling literary fiction. "
        "Write fully realized prose for the scene described — not a summary, not an outline. "
        "Stay in close third-person POV unless the scene brief specifies otherwise.\n\n"
        f"{lang_instruction}"
        "You have tools to query story state. Use them proactively to ensure continuity "
        "(character facts, voice samples, past scene excerpts, timeline).\n\n"
        "After your prose, output a facts_delta block enclosed in ```json ... ``` fences "
        "containing ONLY the state changes introduced in this scene:\n"
        "```json\n"
        "{\n"
        '  "character_updates": [{"name": "...", "changes": {"field": "new_value"}}],\n'
        '  "plot_updates": [{"thread_id": "...", "status": "...", "summary_update": "..."}],\n'
        '  "timeline_events": [{"story_day": 1, "event": "..."}],\n'
        '  "continuity_flags": [{"severity": "low|medium|high", "description": "...", "confidence": "high|low"}]\n'
        "}\n"
        "```\n"
        "If a field has no updates, use an empty array. "
        'Mark items confidence "low" if you are uncertain they are accurate.'
    )

    user_parts = [f"STORY CONTEXT:\n{context_block}"]
    if chapter_context:
        user_parts.append(f"CHAPTER CONTEXT:\n{chapter_context}")
    user_parts.append(f"SCENE TO WRITE:\n{scene_brief}")
    user_parts.append("Write the scene now.")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


# ── Reconciler context ────────────────────────────────────────────────────────

def build_reconciler_messages(
    conn: sqlite3.Connection,
    scene_text: str,
    proposed_delta: dict[str, Any],
) -> list[dict[str, Any]]:
    # Provide current state for the characters mentioned in the delta
    char_names = [u.get("name", "") for u in proposed_delta.get("character_updates", [])]
    char_blocks = []
    for name in char_names:
        char = db.get_character(conn, name)
        if char:
            char_blocks.append(_format_character_full(char))
    current_state = "\n\n".join(char_blocks) if char_blocks else "No specific character state loaded."

    system = (
        "You are a continuity editor reviewing a freshly written scene. Your tasks:\n"
        "1. Write a 2-4 sentence prose summary of the scene.\n"
        "2. Validate the proposed facts_delta against the actual scene content. "
        "Correct any inaccuracies. Remove changes not actually present in the scene.\n"
        "3. List any details you are uncertain about as low_confidence_items.\n\n"
        "Respond with a JSON object (no markdown fences):\n"
        '{"summary": "...", '
        '"validated_delta": {<same structure as input delta>}, '
        '"low_confidence_items": ["..."]}'
    )

    user = (
        f"CURRENT CHARACTER STATE:\n{current_state}\n\n"
        f"SCENE TEXT:\n{scene_text}\n\n"
        f"PROPOSED FACTS DELTA:\n{json.dumps(proposed_delta, indent=2)}\n\n"
        "Validate and summarize."
    )

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ── Chapter summarizer context ────────────────────────────────────────────────

def build_chapter_summarizer_messages(
    scene_summaries: list[str],
    chapter_title: str,
    arc_goal: str,
) -> list[dict[str, Any]]:
    scenes_text = "\n\n".join(
        f"Scene {i + 1}: {s}" for i, s in enumerate(scene_summaries)
    )
    system = (
        "You are a story editor. Write a concise one-page chapter summary "
        "suitable for use as continuity reference in future chapters. "
        "Cover: what happened, what changed (characters, plot threads, relationships), "
        "and what threads remain open. Prose format, no bullet points."
    )
    user = (
        f"CHAPTER: {chapter_title}\nARC GOAL: {arc_goal}\n\n"
        f"SCENE SUMMARIES:\n{scenes_text}\n\n"
        "Write the chapter summary."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
