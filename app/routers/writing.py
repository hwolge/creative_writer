import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import database as db
from app.deps import get_client, get_db
from app.orchestrator.reconciler import reconcile_scene, summarize_chapter
from app.orchestrator.writer import write_scene

router = APIRouter()


class WriteRequest(BaseModel):
    author_note: str = ""


class ApproveRequest(BaseModel):
    prose: str  # may differ from draft if user edited


@router.get("/current")
async def current_scene(conn=Depends(get_db)) -> dict[str, Any]:
    try:
        scene = db.get_current_scene(conn)
        if not scene:
            return {"scene": None}
        chapter = db.get_chapter(conn, scene["chapter_id"]) if scene else None
        return {"scene": scene, "chapter": chapter}
    finally:
        conn.close()


@router.post("/write")
async def write(req: WriteRequest, conn=Depends(get_db)) -> dict[str, Any]:
    client = get_client()
    scene = db.get_current_scene(conn)
    if not scene:
        conn.close()
        raise HTTPException(404, "No pending scene. Plan a chapter first.")

    chapter = db.get_chapter(conn, scene["chapter_id"])
    pov = chapter["plan"].get("pov") if chapter else None
    chapter_context = (
        f"Chapter: {chapter.get('title', '')} | Arc goal: {chapter.get('arc_goal', '')}"
        if chapter else ""
    )

    brief = scene["brief"]
    if req.author_note:
        brief = f"{brief}\n\nAuthor note for this attempt: {req.author_note}"

    try:
        prose, facts_delta = await asyncio.to_thread(
            write_scene, client, conn, brief, pov, chapter_context
        )
        db.save_scene_draft(conn, scene["scene_id"], prose, facts_delta)
        return {
            "scene_id": scene["scene_id"],
            "prose": prose,
            "facts_delta": facts_delta,
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@router.post("/approve")
async def approve(req: ApproveRequest, conn=Depends(get_db)) -> dict[str, Any]:
    client = get_client()
    scene = db.get_current_scene(conn)
    if not scene:
        conn.close()
        raise HTTPException(404, "No scene awaiting approval.")

    # Use whatever facts_delta is stored (from the write step)
    facts_delta = scene.get("facts_delta") or {}

    try:
        result = await asyncio.to_thread(
            reconcile_scene, client, conn, req.prose, facts_delta
        )
        db.approve_scene(
            conn,
            scene["scene_id"],
            req.prose,
            result.summary,
            result.validated_delta.model_dump(),
        )

        # Persist reconciler's low_confidence_items so they appear in State → Issues
        for item in result.low_confidence_items:
            db.add_continuity_issue(conn, "low", item, scene["scene_id"])

        # Check if chapter is now complete → generate chapter summary
        next_scene = db.get_current_scene(conn)
        chapter_summary = None
        if not next_scene:
            chapter = db.get_chapter(conn, scene["chapter_id"])
            if chapter:
                summaries = [
                    row["summary"] or row["brief"]
                    for row in conn.execute(
                        "SELECT summary, brief FROM scenes WHERE chapter_id=? AND status='approved' ORDER BY sequence",
                        (chapter["chapter_id"],),
                    ).fetchall()
                ]
                output_language = str(
                    db.get_story_bible(conn).get("output_language", "English")
                ).strip()
                chapter_summary = await asyncio.to_thread(
                    summarize_chapter,
                    client,
                    summaries,
                    chapter.get("title", f"Chapter {chapter['number']}"),
                    chapter.get("arc_goal", ""),
                    output_language,
                )
                db.save_chapter_summary(conn, chapter["chapter_id"], chapter_summary)

        return {
            "scene_id": scene["scene_id"],
            "summary": result.summary,
            "low_confidence_items": result.low_confidence_items,
            "chapter_complete": next_scene is None,
            "chapter_summary": chapter_summary,
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        conn.close()
