import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import database as db
from app.config import settings
from app.database import get_conn, init_schema, seed_project
from app.deps import get_db
from app.models import ProjectSeed

router = APIRouter()


# ── Status (existing) ─────────────────────────────────────────────────────────

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
            "project": settings.get_active_project(),
            "chapters_complete": all_chapters,
            "current_chapter": chapter,
            "current_scene": scene,
            "open_threads": len(threads),
            "characters": len(chars),
            "continuity_issues": len(issues),
        }
    finally:
        conn.close()


# ── Project list ──────────────────────────────────────────────────────────────

@router.get("/list")
async def list_projects() -> dict[str, Any]:
    """Return all initialised projects and which one is currently active."""
    active = settings.get_active_project()
    projects = settings.list_projects()
    return {
        "active": active,
        "projects": [
            {"slug": slug, "active": slug == active}
            for slug in projects
        ],
    }


# ── Create project ────────────────────────────────────────────────────────────

class CreateRequest(BaseModel):
    slug: str
    seed: ProjectSeed


@router.post("/create")
async def create_project(req: CreateRequest) -> dict[str, Any]:
    """Initialise a new project DB from a seed object."""
    slug = req.slug.strip()
    if not slug:
        raise HTTPException(400, "Project slug cannot be empty.")
    if "/" in slug or "\\" in slug:
        raise HTTPException(400, "Project slug must not contain path separators.")

    db_path = settings.project_db_path(slug)
    if db_path.exists():
        raise HTTPException(409, f"Project '{slug}' already exists.")

    conn = get_conn(db_path)
    try:
        init_schema(conn)
        seed_project(conn, req.seed)
    finally:
        conn.close()

    return {
        "created": slug,
        "characters": len(req.seed.characters),
        "plot_threads": len(req.seed.plot_threads),
        "arc_goals": len(req.seed.arc_goals),
    }


# ── Switch active project ─────────────────────────────────────────────────────

@router.post("/switch/{slug}")
async def switch_project(slug: str) -> dict[str, Any]:
    """Switch the active project (takes effect immediately — no restart needed)."""
    db_path = settings.data_dir / slug / "novel.db"
    if not db_path.exists():
        raise HTTPException(404, f"Project '{slug}' not found.")
    settings.set_active_project(slug)
    return {"active": slug}


# ── Delete project ────────────────────────────────────────────────────────────

@router.delete("/{slug}")
async def delete_project(slug: str) -> dict[str, Any]:
    """Permanently delete a project and all its data."""
    if slug == settings.get_active_project():
        raise HTTPException(400, "Cannot delete the currently active project. Switch to another project first.")
    project_dir = settings.data_dir / slug
    if not project_dir.exists() or not (project_dir / "novel.db").exists():
        raise HTTPException(404, f"Project '{slug}' not found.")
    shutil.rmtree(project_dir)
    return {"deleted": slug}


# ── Seed template ─────────────────────────────────────────────────────────────

@router.get("/seed-template")
async def get_seed_template() -> Any:
    """Return the project_seed.json template for use in the New Project form."""
    template_path = Path("templates/project_seed.json")
    if not template_path.exists():
        raise HTTPException(404, "No seed template found at templates/project_seed.json")
    return json.loads(template_path.read_text(encoding="utf-8"))
