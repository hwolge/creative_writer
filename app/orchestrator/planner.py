import json
import sqlite3

from openai import OpenAI

from app.config import settings
from app.models import ChapterOption, PlannerOutput
from app.orchestrator.context import build_planner_messages
from app.orchestrator.tools import run_tool_loop


def propose_chapter_options(
    client: OpenAI,
    conn: sqlite3.Connection,
    arc_goal: str,
) -> list[ChapterOption]:
    """Call the planner model and return 3 chapter options for the author to choose from."""
    messages = build_planner_messages(conn, arc_goal)
    content, _ = run_tool_loop(client, settings.primary_model, messages, conn)
    return _parse_options(content)


def _parse_options(content: str) -> list[ChapterOption]:
    # Strip any accidental markdown fences
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(text)
    output = PlannerOutput.model_validate(data)
    return output.options
