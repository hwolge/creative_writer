import sqlite3
from pathlib import Path

from fastapi import HTTPException, Query
from openai import OpenAI

from app.config import settings
from app.database import get_conn

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise HTTPException(500, "OPENAI_API_KEY not configured — check your .env file")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def get_db(project: str = Query(default=None)) -> sqlite3.Connection:
    slug = project or settings.get_active_project()
    if not slug:
        raise HTTPException(400, "No active project. Set ACTIVE_PROJECT in .env or pass ?project=slug")
    db_path = settings.project_db_path(slug)
    if not db_path.exists():
        raise HTTPException(404, f"Project '{slug}' not found — run: python cli.py init --project {slug}")
    conn = get_conn(db_path)
    return conn
