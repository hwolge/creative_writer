import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import database as db
from app.config import settings
from app.database import get_conn, init_schema, seed_project
from app.deps import get_db
from app.models import ProjectSeed

router = APIRouter()


@router.get("/status")
async def project_status(conn=Depends(get_db)) -> dict[str, Any]:
    try:
        chapter = db.get_current_chapter(conn)
        scene = db.get_current_scene(conn)
        issues = db.get_continuity_issues(conn, unresolved_only=True)
        threads = db.get_plot_threads(conn, status="open")
        chars = db.get_all_characters(conn)
        all_chapters = conn.execute(
            "SELECT COUNT(*) FROM chapters WHERE status='complete'"
        ).fetchone()[0]
        return {
            "project": settings.active_project,
            "chapters_complete": all_chapters,
            "current_chapter": chapter,
            "current_scene": scene,
            "open_threads": len(threads),
            "characters": len(chars),
            "continuity_issues": len(issues),
        }
    finally:
        conn.close()
