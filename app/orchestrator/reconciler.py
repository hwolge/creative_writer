import json
import sqlite3

from openai import OpenAI

from app import database as db
from app.config import settings
from app.models import ReconcilerOutput
from app.orchestrator.context import (
    build_auto_resolver_messages,
    build_chapter_summarizer_messages,
    build_reconciler_messages,
)
from app.orchestrator.llm_log import timed_completion


def reconcile_scene(
    client: OpenAI,
    conn: sqlite3.Connection,
    scene_text: str,
    proposed_delta: dict,
) -> ReconcilerOutput:
    """Validate facts_delta and generate scene summary using the fast model."""
    messages = build_reconciler_messages(conn, scene_text, proposed_delta)

    response = timed_completion(
        client,
        label="reconciler/validate",
        model=settings.fast_model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return _parse_reconciler(content, proposed_delta)


def _parse_reconciler(content: str, fallback_delta: dict) -> ReconcilerOutput:
    try:
        data = json.loads(content)
        return ReconcilerOutput.model_validate(data)
    except Exception:
        return ReconcilerOutput(
            summary="[Summary generation failed — please edit manually.]",
            validated_delta=fallback_delta,  # type: ignore[arg-type]
            low_confidence_items=["Reconciliation failed; delta unvalidated."],
        )


def auto_resolve_issue(
    client: OpenAI,
    conn: sqlite3.Connection,
    issue_id: int,
) -> dict:
    """Use the fast model to resolve a low-confidence continuity issue.

    Returns a dict with keys: resolution (str), character_updates (list), plot_updates (list).
    Applies the updates to the DB and marks the issue resolved.
    """
    issue = db.get_continuity_issue(conn, issue_id)
    if not issue:
        raise ValueError(f"Issue {issue_id} not found")

    # Load scene text if available
    scene_text = ""
    if issue.get("scene_id"):
        scene_text = db.get_scene_full_text(conn, issue["scene_id"]) or ""

    # Load current character + thread state as context block
    chars = db.get_all_characters(conn)
    threads = db.get_plot_threads(conn)
    state_lines = ["CHARACTERS:"]
    for c in chars:
        state_lines.append(f"  {c['name']} — {c.get('role', '')}")
    state_lines.append("PLOT THREADS:")
    for t in threads:
        state_lines.append(f"  [{t['status'].upper()}] {t['thread_id']}: {t['summary']}")
    state_block = "\n".join(state_lines)

    bible_data = db.get_story_bible(conn)
    output_language = str(bible_data.get("output_language", "English")).strip()

    messages = build_auto_resolver_messages(
        issue["description"], scene_text, state_block, output_language
    )

    response = timed_completion(
        client,
        label="reconciler/auto-resolve",
        model=settings.fast_model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"

    try:
        data = json.loads(content)
    except Exception:
        data = {}

    resolution = data.get("resolution", "Issue resolved (no explanation provided).")
    char_updates = data.get("character_updates", [])
    plot_updates = data.get("plot_updates", [])

    # Apply updates and mark resolved
    if char_updates or plot_updates:
        db.apply_resolution_delta(conn, char_updates, plot_updates)
    db.resolve_continuity_issue(conn, issue_id)

    return {
        "resolved": issue_id,
        "resolution": resolution,
        "character_updates": char_updates,
        "plot_updates": plot_updates,
    }


def summarize_chapter(
    client: OpenAI,
    scene_summaries: list[str],
    chapter_title: str,
    arc_goal: str,
    output_language: str = "English",
) -> str:
    """Generate a one-page chapter summary from individual scene summaries."""
    messages = build_chapter_summarizer_messages(
        scene_summaries, chapter_title, arc_goal, output_language
    )
    response = timed_completion(
        client,
        label="reconciler/summarize",
        model=settings.fast_model,
        messages=messages,
    )
    return response.choices[0].message.content or ""
