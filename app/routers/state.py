from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import database as db
from app.deps import get_db

router = APIRouter()


class CharacterPatch(BaseModel):
    changes: dict[str, Any]


class ThreadPatch(BaseModel):
    status: str | None = None
    summary: str | None = None


@router.get("/characters")
async def list_characters(conn=Depends(get_db)) -> list[dict[str, Any]]:
    try:
        return db.get_all_characters(conn)
    finally:
        conn.close()


@router.get("/characters/{name}")
async def get_character(name: str, conn=Depends(get_db)) -> dict[str, Any]:
    try:
        char = db.get_character(conn, name)
        if not char:
            raise HTTPException(404, f"Character '{name}' not found")
        return char
    finally:
        conn.close()


@router.patch("/characters/{name}")
async def patch_character(name: str, req: CharacterPatch, conn=Depends(get_db)) -> dict[str, Any]:
    try:
        ok = db.update_character_manual(conn, name, req.changes)
        if not ok:
            raise HTTPException(404, f"Character '{name}' not found")
        return db.get_character(conn, name)
    finally:
        conn.close()


@router.get("/threads")
async def list_threads(status: str | None = None, conn=Depends(get_db)) -> list[dict[str, Any]]:
    try:
        return db.get_plot_threads(conn, status)
    finally:
        conn.close()


@router.patch("/threads/{thread_id}")
async def patch_thread(thread_id: str, req: ThreadPatch, conn=Depends(get_db)) -> dict[str, Any]:
    try:
        ok = db.update_thread_manual(conn, thread_id, req.status, req.summary)
        if not ok:
            raise HTTPException(404, f"Thread '{thread_id}' not found")
        threads = db.get_plot_threads(conn)
        return next(t for t in threads if t["thread_id"] == thread_id)
    finally:
        conn.close()


@router.get("/timeline")
async def get_timeline(
    from_day: int | None = None,
    to_day: int | None = None,
    conn=Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        return db.get_timeline(conn, from_day, to_day)
    finally:
        conn.close()


@router.get("/issues")
async def list_issues(unresolved_only: bool = True, conn=Depends(get_db)) -> list[dict[str, Any]]:
    try:
        return db.get_continuity_issues(conn, unresolved_only)
    finally:
        conn.close()


@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(issue_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    try:
        db.resolve_continuity_issue(conn, issue_id)
        return {"resolved": issue_id}
    finally:
        conn.close()
