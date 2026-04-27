import json
import sqlite3
from typing import Any

from app import database as db
from app.orchestrator.llm_log import timed_completion

# ── Tool definitions (sent to OpenAI) ─────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_story_bible",
            "description": "Retrieve world rules, setting, themes, and taboo items for the novel.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_character_state",
            "description": "Get canonical facts and voice samples for a specific character.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact character name"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_characters",
            "description": "List all characters with their name, role, and current physical status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plot_threads",
            "description": "Retrieve plot threads. Optionally filter by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["open", "dormant", "resolved"],
                        "description": "Filter by thread status. Omit for all threads.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_summary",
            "description": "Retrieve the compressed 2-4 sentence summary of a past scene.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_id": {"type": "integer", "description": "Scene ID"}
                },
                "required": ["scene_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_full_text",
            "description": "Retrieve the exact approved prose of a past scene. Use sparingly — prefer summaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_id": {"type": "integer", "description": "Scene ID"}
                },
                "required": ["scene_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_scenes",
            "description": "Full-text search over past scene briefs, summaries, and prose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms, e.g. 'Elin forged map harbor'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline",
            "description": "Retrieve chronological story events. Optionally bounded by story day.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_day": {"type": "integer", "description": "Start story day (inclusive)"},
                    "to_day": {"type": "integer", "description": "End story day (inclusive)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_style_guide",
            "description": "Retrieve the novel's style guide: voice rules, motifs, sample prose.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_continuity_issues",
            "description": "Retrieve flagged continuity issues that may need attention.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unresolved_only": {
                        "type": "boolean",
                        "description": "If true (default), only return unresolved issues.",
                    }
                },
                "required": [],
            },
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    conn: sqlite3.Connection,
) -> Any:
    handlers = {
        "get_story_bible": lambda a: db.get_story_bible(conn),
        "get_character_state": lambda a: db.get_character(conn, a["name"]),
        "get_all_characters": lambda a: db.get_all_characters(conn),
        "get_plot_threads": lambda a: db.get_plot_threads(conn, a.get("status")),
        "get_scene_summary": lambda a: db.get_scene_summary(conn, a["scene_id"]),
        "get_scene_full_text": lambda a: db.get_scene_full_text(conn, a["scene_id"]),
        "search_scenes": lambda a: db.search_scenes(conn, a["query"]),
        "get_timeline": lambda a: db.get_timeline(conn, a.get("from_day"), a.get("to_day")),
        "get_style_guide": lambda a: db.get_style_guide(conn),
        "get_continuity_issues": lambda a: db.get_continuity_issues(
            conn, a.get("unresolved_only", True)
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return handler(arguments)


def run_tool_loop(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    conn: sqlite3.Connection,
    max_rounds: int = 6,
    label: str = "tool_loop",
) -> tuple[str, list[dict[str, Any]]]:
    """Drive the tool-calling loop until the model produces a final text response.
    Returns (final_content, updated_messages)."""
    round_num = 0
    for _ in range(max_rounds):
        round_num += 1
        round_label = f"{label}:round{round_num}"
        response = timed_completion(
            client,
            label=round_label,
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # Append assistant turn
        assistant_turn: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_turn)

        if not msg.tool_calls:
            return msg.content or "", messages

        # Log which tools were dispatched this round
        tool_names = [tc.function.name for tc in msg.tool_calls]
        print(f"         tools → {', '.join(tool_names)}", flush=True)

        # Execute tool calls
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = dispatch_tool(tc.function.name, args, conn)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    # Exceeded max rounds — ask for a plain response
    messages.append({"role": "user", "content": "Please produce your final response now."})
    response = timed_completion(
        client,
        label=f"{label}:forced",
        model=model,
        messages=messages,
    )
    content = response.choices[0].message.content or ""
    messages.append({"role": "assistant", "content": content})
    return content, messages
