# Novel Writer — System Architecture

## Overview

A stateful novel-writing assistant that uses the OpenAI API as a **writer/planner operating over an external story database**, not as the place where the novel lives. The author steers at every chapter by choosing from model-proposed options; the system handles continuity, state, and compression.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web framework | FastAPI (serves API + static HTML) |
| Database | SQLite (via `sqlite3` stdlib) |
| Primary LLM | `gpt-5.4` |
| Fast/cheap LLM | `gpt-5.4-mini` (summaries, reconciliation, fact extraction) |
| OpenAI SDK | `openai` Python package |
| Frontend | Vanilla HTML/CSS/JS (no build step) |
| Config | `.env` file (`python-dotenv`) |

---

## Directory Layout

```
creative_writer/
├── architecture.md          # this file
├── .env                     # OPENAI_API_KEY, active project path
├── requirements.txt
│
├── app/
│   ├── main.py              # FastAPI app, mounts routes
│   ├── config.py            # settings loaded from .env
│   ├── database.py          # SQLite connection, schema creation
│   ├── models.py            # Pydantic schemas for all domain objects
│   │
│   ├── routers/
│   │   ├── project.py       # /project — load, seed, status
│   │   ├── planning.py      # /plan — propose chapter options, confirm choice
│   │   ├── writing.py       # /scene — write next scene, approve/edit
│   │   ├── state.py         # /state — characters, threads, timeline (read/write)
│   │   └── archive.py       # /archive — browse chapters, scenes, search
│   │
│   ├── orchestrator/
│   │   ├── context.py       # assembles the working context for each LLM call
│   │   ├── tools.py         # OpenAI tool definitions + handler dispatch
│   │   ├── planner.py       # chapter planning loop (proposes options)
│   │   ├── writer.py        # scene writing loop
│   │   └── reconciler.py    # post-scene fact extraction + state update
│   │
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
│
├── templates/
│   └── project_seed.json    # filled by author before first run
│
└── data/
    └── <project-slug>/
        └── novel.db         # one SQLite file per project
```

---

## Database Schema

```sql
-- Stable world facts, themes, rules, taboo items
CREATE TABLE story_bible (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL          -- free prose or JSON
);

-- Character canonical state (machine-friendly facts)
CREATE TABLE characters (
    name          TEXT PRIMARY KEY,
    facts         TEXT NOT NULL,   -- JSON object: age, appearance, traits, status
    voice_samples TEXT,            -- prose excerpts for tone reference
    updated_at    TEXT NOT NULL
);

-- Active and resolved plot threads
CREATE TABLE plot_threads (
    thread_id  TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL,      -- open | resolved | dormant
    summary    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Chapter-level records
CREATE TABLE chapters (
    chapter_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    number      INTEGER NOT NULL,
    title       TEXT,
    arc_goal    TEXT NOT NULL,     -- what this chapter must accomplish
    plan        TEXT NOT NULL,     -- JSON: scene list, POV, beats, reveal schedule
    summary     TEXT,              -- filled after completion
    status      TEXT NOT NULL      -- planned | in_progress | complete
);

-- Scene-level records (primary writing unit)
CREATE TABLE scenes (
    scene_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(chapter_id),
    sequence      INTEGER NOT NULL,
    brief         TEXT NOT NULL,    -- the scene's goal/setup
    full_text     TEXT,             -- final approved prose
    summary       TEXT,             -- 2–4 sentence summary (filled post-approval)
    facts_delta   TEXT,             -- JSON: state changes introduced
    status        TEXT NOT NULL,    -- pending | draft | approved
    created_at    TEXT NOT NULL
);

-- Flat timeline for retrieval and continuity checks
CREATE TABLE timeline_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    story_day   INTEGER,
    description TEXT NOT NULL,
    scene_id    INTEGER REFERENCES scenes(scene_id)
);

-- Continuity issues flagged by model or author
CREATE TABLE continuity_issues (
    issue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    severity    TEXT NOT NULL,   -- low | medium | high
    description TEXT NOT NULL,
    scene_id    INTEGER REFERENCES scenes(scene_id),
    resolved    INTEGER NOT NULL DEFAULT 0
);

-- Style guide entries: voice samples, motifs, rules
CREATE TABLE style_guide (
    entry_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    category  TEXT NOT NULL,     -- voice | motif | rule | sample
    content   TEXT NOT NULL
);
```

---

## Workflow State Machine

```
[Seed project] ──► [Plan next chapter]
                        │
                   (model proposes 3 options)
                        │
                   [Author chooses option]
                        │
                   [Write next scene] ◄──────────────┐
                        │                             │
                   (model writes scene)               │
                        │                             │
                   [Author approves / edits]          │
                        │                             │
                   [Reconcile state]                  │
                        │                             │
                   (model extracts facts delta)       │
                        │                             │
                   [Save + update canon]              │
                        │                             │
                   [More scenes in chapter?] ─── yes ─┘
                        │ no
                   [Chapter complete — plan next]
```

---

## OpenAI Tool Definitions

These tools are offered to the model during each API call. The model may invoke zero or more before producing its final output. The orchestrator handles all actual DB reads/writes.

| Tool | Model uses it to | DB operation |
|---|---|---|
| `get_story_bible()` | pull world rules, themes, taboo items | `SELECT * FROM story_bible` |
| `get_character_state(name)` | pull a character's canonical facts + voice | `SELECT FROM characters` |
| `get_all_characters()` | list all character names + one-line status | `SELECT name, facts FROM characters` |
| `get_plot_threads(status?)` | see open/dormant/all threads | `SELECT FROM plot_threads` |
| `get_chapter_plan(chapter_id)` | retrieve an already-planned chapter | `SELECT FROM chapters` |
| `get_scene_summary(scene_id)` | pull a compressed past scene | `SELECT summary FROM scenes` |
| `get_scene_full_text(scene_id)` | retrieve exact prose for a past scene | `SELECT full_text FROM scenes` |
| `search_scenes(query)` | find scenes by keyword (SQLite FTS5) | FTS5 full-text search |
| `get_timeline(from_day?, to_day?)` | consult chronology | `SELECT FROM timeline_events` |
| `get_style_guide()` | retrieve voice samples and rules | `SELECT FROM style_guide` |
| `get_continuity_issues(unresolved_only?)` | check known problems | `SELECT FROM continuity_issues` |

> **Tools are read-only during generation.** All writes (state updates, scene saves, timeline entries) happen via structured JSON in the model's final response, which the orchestrator validates before committing.

---

## LLM Call Types

### 1. Chapter Planner (`gpt-5.4`)

**Goal**: propose 3 distinct chapter options for the author to choose from.

**Input context assembled by `context.py`:**
```
story_bible              ~200 tokens
style_guide (abridged)   ~200 tokens
characters (summary)     ~300 tokens
open plot threads        ~300 tokens
timeline (recent)        ~200 tokens
previous chapter summary ~300 tokens
arc goal (author-set)    ~150 tokens
─────────────────────────────────────
Total input              ~1,650 tokens
```

**Expected output**: JSON with 3 chapter plans, each containing:
```json
{
  "options": [
    {
      "title": "string",
      "arc_goal": "string",
      "scenes": [{"sequence": 1, "brief": "...", "pov": "...", "beats": "..."}],
      "reveals": ["string"],
      "continuity_risks": ["string"]
    }
  ]
}
```

---

### 2. Scene Writer (`gpt-5.4`)

**Goal**: write one scene as polished prose.

**Input context assembled by `context.py`:**
```
story_bible (abridged)         ~150 tokens
style_guide                    ~300 tokens
POV character card             ~200 tokens
other involved characters      ~150 tokens each (max 3)
open plot threads              ~200 tokens
previous scene summary         ~300 tokens
retrieved scene excerpts       ~600 tokens  (tool-fetched, if needed)
current scene brief            ~200 tokens
─────────────────────────────────────────────
Total input                    ~2,300 tokens
```

Tools are available during this call. After writing prose, the model also emits a structured `facts_delta`:
```json
{
  "character_updates": [
    {"name": "...", "changes": {"field": "new_value"}}
  ],
  "plot_updates": [
    {"thread_id": "...", "status": "..."}
  ],
  "timeline_events": [
    {"story_day": 12, "event": "..."}
  ],
  "continuity_flags": [
    {"severity": "medium", "description": "..."}
  ]
}
```

---

### 3. Scene Reconciler (`gpt-5.4-mini`)

**Goal**: after author approves a scene, produce its compressed summary and validate the `facts_delta`.

**Input**: approved full text + prior character states + prior thread states.

**Output**:
```json
{
  "summary": "2-4 sentence prose summary",
  "validated_delta": { ... },       // confirmed or corrected facts_delta
  "low_confidence_items": ["..."]   // details the model is uncertain it got right
}
```

---

### 4. Chapter Summarizer (`gpt-5.4-mini`)

Run once all scenes in a chapter are approved.

**Input**: all scene summaries for the chapter.

**Output**: a 1-page chapter summary stored in `chapters.summary`.

---

## Context Assembly (`context.py`)

The orchestrator never sends raw DB dumps. `context.py` is responsible for:

1. Loading relevant rows from SQLite
2. Formatting them into compact, token-efficient strings
3. Respecting a configurable **token budget** per call type
4. Deciding which optional sections (retrieved excerpts, continuity flags) to include based on the scene brief

Token budgets are defined in `config.py` and can be tuned without code changes.

---

## Retrieval Strategy

**No embeddings in v1.** SQLite FTS5 full-text search covers the `scenes` table (scene summaries + full text). This handles "find the scene where Elin found the map" well enough for a single novel's archive.

If retrieval quality proves insufficient, `sqlite-vec` or a local ChromaDB instance can be added as a v2 upgrade without changing the rest of the architecture.

---

## Seeding a New Project

The author fills `templates/project_seed.json` and imports it via the UI or CLI:

```json
{
  "project_slug": "my-novel",
  "story_bible": {
    "setting": "...",
    "themes": ["...", "..."],
    "world_rules": ["..."],
    "taboo_items": ["..."],
    "timeline_anchor": "..."
  },
  "characters": [
    {
      "name": "...",
      "facts": {
        "age": 34,
        "appearance": "...",
        "role": "...",
        "motivation": "...",
        "secrets": ["..."],
        "relationships": {"other_character": "..."}
      },
      "voice_samples": ["\"exact quote from planning chat\""]
    }
  ],
  "plot_threads": [
    {
      "thread_id": "forged-map",
      "title": "The Forged Map",
      "status": "open",
      "summary": "..."
    }
  ],
  "style_guide": [
    {"category": "voice", "content": "..."},
    {"category": "rule", "content": "no omniscient narration; close third only"}
  ],
  "arc_goals": [
    {"chapter": 1, "goal": "..."},
    {"chapter": 2, "goal": "..."}
  ]
}
```

The import script validates this JSON against Pydantic schemas and writes all rows to `novel.db`.

---

## Web UI

Single HTML page served at `http://localhost:8000`. Four panels, navigated by tab:

| Tab | Purpose |
|---|---|
| **Plan** | Shows current story state summary; triggers chapter planning; displays 3 options as cards; author clicks to confirm |
| **Write** | Shows current scene brief; triggers scene generation; displays draft prose; author can edit inline and approve |
| **State** | Read/edit view of characters, plot threads, timeline, style guide |
| **Archive** | Browse chapters/scenes, search full text, view continuity issues |

No JavaScript framework. `fetch()` calls to FastAPI endpoints. All state lives on the server.

---

## API Endpoints

```
POST /project/seed          — import project_seed.json
GET  /project/status        — current chapter, scene, open threads

POST /plan/propose          — trigger chapter planning → returns 3 options
POST /plan/confirm          — author confirms chosen option → saves chapter plan

GET  /scene/current         — get current pending scene brief
POST /scene/write           — trigger scene generation → returns draft
POST /scene/approve         — approve scene (with optional edited text)
POST /scene/reject          — reject draft, optionally with author note → re-generates

GET  /state/characters      — list all characters
GET  /state/characters/{name}
PATCH /state/characters/{name}  — author manual override
GET  /state/threads
PATCH /state/threads/{thread_id}
GET  /state/timeline
GET  /state/continuity_issues

GET  /archive/chapters
GET  /archive/scenes?chapter_id=
GET  /archive/search?q=
```

---

## Canon Integrity Rules

1. **Tools are read-only during generation.** The model cannot write to DB mid-generation.
2. **Structured delta, not prose.** All state changes come through `facts_delta` JSON, not inferred from prose.
3. **Reconciler validates before commit.** The mini model cross-checks the delta against the approved scene before anything is stored.
4. **Tentative vs. confirmed.** `facts_delta` items marked `"confidence": "low"` are stored as `continuity_issues`, not as canon updates, until the author resolves them.
5. **Summaries are views, not canon.** Scene summaries and chapter summaries are re-generatable. The primary source of truth is `characters`, `plot_threads`, `timeline_events`, and `story_bible`.

---

## Tone / Continuity Drift Mitigations

| Risk | Mitigation |
|---|---|
| Eye color / injury continuity | Structured character facts; reconciler cross-checks |
| Summary corruption | Summaries never update `characters` or `plot_threads` directly |
| Tone drift across chapters | Style guide + voice samples included in every scene call |
| Premature canonization | Low-confidence delta items go to `continuity_issues` queue |
| Retrieval misses | FTS5 search + structured timeline lookup as fallbacks |

---

## Implementation Phases

### Phase 1 — Core pipeline (no UI)
- SQLite schema + `database.py`
- Pydantic models
- `project_seed.json` import
- Chapter planner (returns 3 JSON options)
- Scene writer (returns draft + `facts_delta`)
- Scene reconciler
- CLI to drive the workflow

### Phase 2 — Web UI
- FastAPI app + endpoints
- Static HTML/CSS/JS
- Plan, Write, State, Archive tabs

### Phase 3 — Polish
- FTS5 scene search wired into tools
- Continuity issues workflow (review + resolve)
- Chapter summarizer
- Export to `.txt` / `.docx`

---

## Design Decisions (resolved)

- **Arc goals**: defined one chapter ahead — the author sets the arc goal when triggering the planner for the next chapter. This balances structure with flexibility.
- **Scene rejection budget**: configurable via `MAX_SCENE_REJECTIONS` in `.env` (default 3). After the limit, the CLI prompts the author to supply a revised scene brief before trying again.
- **Mini vs. full model boundary**: reconciliation and summarization use `gpt-5.4-mini`; planning and scene writing use `gpt-5.4`. Configurable in `.env` if quality warrants a change.
- **Author steering mode**: shared steering — the planner always proposes exactly 3 distinct chapter options (different POV, pacing, reveals) and the author picks one.
- **Retrieval**: SQLite FTS5 full-text search for v1; no embeddings. Upgrade path noted.
