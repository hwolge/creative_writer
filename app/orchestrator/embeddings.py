"""Embedding generation and semantic retrieval for long-range story consistency.

Uses OpenAI text-embedding-3-small (cheapest embedding model, 1536 dimensions).
Cosine similarity is computed in pure Python — fast enough for novel-length
corpora (≤ ~200 scenes; each comparison is just a dot product over 1536 floats).

Embeddings are stored in the scene_embeddings table as JSON blobs.
"""
import json
import math
import sqlite3
import time
from typing import Any

from openai import OpenAI

from app import database as db

_EMBED_MODEL = "text-embedding-3-small"
_MAX_CHARS   = 6000   # well inside the 8191-token window; ~4 500 words


def _log(msg: str) -> None:
    print(msg, flush=True)


# ── Embedding generation ──────────────────────────────────────────────────────

def embed_text(client: OpenAI, text: str) -> list[float]:
    """Call the embeddings API and return the raw float vector."""
    text = text[:_MAX_CHARS]
    t0 = time.perf_counter()
    response = client.embeddings.create(model=_EMBED_MODEL, input=text)
    elapsed = time.perf_counter() - t0
    tokens = response.usage.total_tokens
    _log(f"[EMB] {_EMBED_MODEL}  {len(text):>5} chars  {tokens:>5} tok  {elapsed:.2f}s")
    return response.data[0].embedding


def store_scene_embedding(
    client: OpenAI,
    conn: sqlite3.Connection,
    scene_id: int,
) -> None:
    """Generate and persist an embedding for an approved scene.

    The text fed to the model is: brief + summary + first ~4 000 chars of prose.
    This gives semantic coverage of topic, outcome, and specific details.
    """
    scene = db.get_scene(conn, scene_id)
    if not scene:
        return

    parts = [scene.get("brief", "")]
    if scene.get("summary"):
        parts.append(scene["summary"])
    if scene.get("full_text"):
        parts.append(scene["full_text"][:4000])
    text = "\n".join(parts)

    embedding = embed_text(client, text)
    conn.execute(
        "INSERT OR REPLACE INTO scene_embeddings (scene_id, embedding, created_at) "
        "VALUES (?, ?, ?)",
        (scene_id, json.dumps(embedding), db._now()),
    )
    conn.commit()


# ── Similarity retrieval ──────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def retrieve_similar_scenes(
    client: OpenAI,
    conn: sqlite3.Connection,
    query_text: str,
    top_k: int = 3,
    exclude_scene_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Return the top_k scenes most semantically similar to query_text.

    Each result dict contains scene_id, brief, and summary.
    Returns an empty list if the embedding table is empty (no scenes approved yet).
    """
    rows = conn.execute(
        "SELECT se.scene_id, se.embedding, s.brief, s.summary "
        "FROM scene_embeddings se "
        "JOIN scenes s ON se.scene_id = s.scene_id"
    ).fetchall()

    if not rows:
        return []

    query_emb = embed_text(client, query_text[:_MAX_CHARS])
    exclude   = exclude_scene_ids or set()

    scored: list[tuple[float, dict]] = []
    for row in rows:
        if row["scene_id"] in exclude:
            continue
        score = _cosine(query_emb, json.loads(row["embedding"]))
        scored.append((score, {
            "scene_id": row["scene_id"],
            "brief":    row["brief"],
            "summary":  row["summary"],
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]
