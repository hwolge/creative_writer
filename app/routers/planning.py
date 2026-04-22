import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import database as db
from app.deps import get_client, get_db
from app.models import ChapterOption
from app.orchestrator.planner import propose_chapter_options

router = APIRouter()


class ProposeRequest(BaseModel):
    arc_goal: str


class ConfirmRequest(BaseModel):
    chapter_number: int
    option_index: int  # 0-based
    options: list[ChapterOption]


@router.post("/propose")
async def propose(req: ProposeRequest, conn=Depends(get_db)) -> dict[str, Any]:
    client = get_client()
    try:
        options = await asyncio.to_thread(
            propose_chapter_options, client, conn, req.arc_goal
        )
        return {"options": [o.model_dump() for o in options]}
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@router.post("/confirm")
async def confirm(req: ConfirmRequest, conn=Depends(get_db)) -> dict[str, Any]:
    if req.option_index < 0 or req.option_index >= len(req.options):
        raise HTTPException(400, "Invalid option_index")
    selected = req.options[req.option_index]
    try:
        chapter_id = db.save_chapter_plan(
            conn,
            chapter_number=req.chapter_number,
            arc_goal=selected.arc_goal,
            title=selected.title,
            plan=selected.model_dump(),
        )
        chapter = db.get_chapter(conn, chapter_id)
        return {"chapter": chapter, "scenes_queued": len(selected.scenes)}
    finally:
        conn.close()
