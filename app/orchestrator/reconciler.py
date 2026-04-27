import json
import sqlite3

from openai import OpenAI

from app.config import settings
from app.models import ReconcilerOutput
from app.orchestrator.context import (
    build_chapter_summarizer_messages,
    build_reconciler_messages,
)


def reconcile_scene(
    client: OpenAI,
    conn: sqlite3.Connection,
    scene_text: str,
    proposed_delta: dict,
) -> ReconcilerOutput:
    """Validate facts_delta and generate scene summary using the fast model."""
    messages = build_reconciler_messages(conn, scene_text, proposed_delta)

    response = client.chat.completions.create(
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
    response = client.chat.completions.create(
        model=settings.fast_model,
        messages=messages,
    )
    return response.choices[0].message.content or ""
