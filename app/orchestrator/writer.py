import json
import re
import sqlite3

from openai import OpenAI

from app.config import settings
from app.models import FactsDelta
from app.orchestrator.context import build_writer_messages
from app.orchestrator.embeddings import retrieve_similar_scenes
from app.orchestrator.tools import run_tool_loop

_DELTA_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

_EMPTY_DELTA: dict = {
    "character_updates": [],
    "plot_updates": [],
    "timeline_events": [],
    "continuity_flags": [],
}


def write_scene(
    client: OpenAI,
    conn: sqlite3.Connection,
    scene_brief: str,
    pov_character: str | None = None,
    chapter_context: str = "",
) -> tuple[str, dict]:
    """Generate prose + facts_delta for a scene.
    Returns (prose_text, facts_delta_dict).
    """
    # Retrieve semantically similar past scenes for long-range consistency (RAG).
    # Returns empty list gracefully when no embeddings exist yet (first scene).
    rag_scenes = retrieve_similar_scenes(
        client, conn, scene_brief, top_k=settings.rag_top_k
    )

    messages = build_writer_messages(
        conn, scene_brief, pov_character, chapter_context, rag_scenes=rag_scenes
    )
    content, _ = run_tool_loop(client, settings.primary_model, messages, conn, label="writer")
    return _parse_response(content)


def _parse_response(content: str) -> tuple[str, dict]:
    match = _DELTA_RE.search(content)
    if not match:
        return content.strip(), _EMPTY_DELTA.copy()

    json_str = match.group(1)
    prose = content[: match.start()].strip()

    try:
        raw = json.loads(json_str)
        FactsDelta.model_validate(raw)  # validate shape; don't discard on failure
        return prose, raw
    except (json.JSONDecodeError, Exception):
        return prose, _EMPTY_DELTA.copy()
