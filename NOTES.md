# Developer Notes

Internal scratchpad — context for continuing development in new sessions.

## Deployment

- **Local**: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` in WSL2
- **WSL2 networking**: mirrored mode — WSL2 shares the Windows host IP (`192.168.68.205`)
- **Apache reverse proxy** (on gateway `wolge.se`):
  ```
  ProxyPass "/writer" "http://192.168.68.205:8000"
  ProxyPassReverse "/writer" "http://192.168.68.205:8000"
  ```
- **External URL**: https://wolge.se/writer/
- **No portproxy needed** — mirrored networking makes WSL2 directly reachable on the LAN IP
- **Windows Firewall**: inbound rule allowing TCP port 8000 (`WSL2-8000`)

## Reverse-proxy path handling

The app has no knowledge of the `/writer` prefix. The JS detects it at runtime:
```javascript
const ROOT = window.location.pathname.replace(/\/$/, '');
```
All `api()` calls prepend ROOT, so they resolve to `/writer/state/...` etc. when
served via the proxy, and plain `/state/...` when running locally. No server-side
config needed.

## Architecture summary

| Layer | Detail |
|---|---|
| API | FastAPI, routes at `/plan`, `/scene`, `/state`, `/archive`, `/project` |
| DB | SQLite per project under `data/<slug>/novel.db`, WAL mode |
| LLM calls | OpenAI — primary model for planner+writer, fast model for reconciler/auto-resolve/summarizer |
| Tool loop | `orchestrator/tools.py` — up to 6 rounds of function calling |
| Context assembly | `orchestrator/context.py` — token-budgeted, tiktoken-based trimming |
| Consistency | (1) verbatim last scene in writer context, (2) FTS5 keyword search, (3) embedding RAG with `text-embedding-3-small` |
| Projects | Multi-project via `data/.active_project` override file, switch without restart |

## Key design decisions

- **ROOT detection client-side** (not server-side): avoids needing a `root_path` config
  and works transparently regardless of proxy prefix. FastAPI `root_path=` constructor
  param was tried and caused Starlette to strip the prefix before routing — don't use it.
- **FTS5 queries sanitized**: `_sanitize_fts()` in `database.py` strips punctuation and
  quotes each token — prevents syntax errors when the LLM passes raw sentences as queries.
- **`_apply_delta` order**: `new_characters` are created *before* `character_updates` are
  processed, so a scene can introduce and immediately update the same character.
- **Migrations**: `_apply_migrations()` called on every `get_conn()` — additive,
  `IF NOT EXISTS` only, safe on existing DBs.

## Pending features

### Modify scene (designed, not yet coded)
Instead of Reject (full regeneration), user can give targeted feedback on an existing draft.

**UX**: Approve | **Modify ✎** | Reject  
Clicking Modify opens a textarea: *"What should change?"*  
Submit → LLM revises the existing prose → new draft shown → same three buttons again.

**Implementation plan**:
1. `build_modifier_messages(conn, existing_prose, note, scene_brief, pov, chapter_context)`
   in `context.py` — system prompt anchors on existing prose, applies only the note.
2. `modify_scene(client, conn, note, ...)` in `writer.py` — like `write_scene` but feeds
   existing prose as base. Still emits `facts_delta`. Still runs tool loop.
3. `POST /scene/modify` in `routers/writing.py` — loads current draft prose, calls
   `modify_scene`, saves result via `save_scene_draft` (overwrites draft).
4. UI: Modify button + collapsible textarea in Write tab (`index.html` + `app.js`).

No DB schema changes needed — `save_scene_draft` already overwrites.

## Project seed

Active project: `den-forfalskarade-kartan` (Swedish historical thriller).  
Seed template at `templates/project_seed.json` — use via Projects tab → Load template.
