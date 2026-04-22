from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app import database as db
from app.deps import get_db

router = APIRouter()


@router.get("/chapters")
async def list_chapters(conn=Depends(get_db)) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT chapter_id, number, title, arc_goal, status, summary FROM chapters ORDER BY number"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/scenes")
async def list_scenes(chapter: int | None = None, conn=Depends(get_db)) -> list[dict[str, Any]]:
    try:
        if chapter:
            rows = conn.execute("""
                SELECT s.scene_id, c.number as chapter_number, s.sequence,
                       s.brief, s.summary, s.status
                FROM scenes s JOIN chapters c ON s.chapter_id = c.chapter_id
                WHERE c.number = ? ORDER BY s.sequence
            """, (chapter,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT s.scene_id, c.number as chapter_number, s.sequence,
                       s.brief, s.summary, s.status
                FROM scenes s JOIN chapters c ON s.chapter_id = c.chapter_id
                ORDER BY c.number, s.sequence
            """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/scenes/{scene_id}")
async def get_scene(scene_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    try:
        scene = db.get_scene(conn, scene_id)
        if not scene:
            raise HTTPException(404, f"Scene {scene_id} not found")
        return scene
    finally:
        conn.close()


@router.get("/search")
async def search(q: str = Query(min_length=2), conn=Depends(get_db)) -> list[dict[str, Any]]:
    try:
        return db.search_scenes(conn, q)
    finally:
        conn.close()
