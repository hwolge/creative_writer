from typing import Any
from pydantic import BaseModel, Field


# ── Seed import models ────────────────────────────────────────────────────────

class CharacterFacts(BaseModel):
    age: int | None = None
    appearance: str | None = None
    role: str | None = None
    motivation: str | None = None
    secrets: list[str] = []
    relationships: dict[str, str] = {}
    physical_state: str | None = None
    model_config = {"extra": "allow"}


class CharacterSeed(BaseModel):
    name: str
    facts: CharacterFacts
    voice_samples: list[str] = []


class PlotThreadSeed(BaseModel):
    thread_id: str
    title: str
    status: str = "open"
    summary: str


class StyleGuideEntry(BaseModel):
    category: str  # voice | motif | rule | sample
    content: str


class ArcGoalEntry(BaseModel):
    chapter: int
    goal: str


class ProjectSeed(BaseModel):
    project_slug: str
    story_bible: dict[str, Any]
    characters: list[CharacterSeed]
    plot_threads: list[PlotThreadSeed]
    style_guide: list[StyleGuideEntry] = []
    arc_goals: list[ArcGoalEntry] = []


# ── Runtime domain models ─────────────────────────────────────────────────────

class Character(BaseModel):
    name: str
    facts: dict[str, Any]
    voice_samples: list[str] = []
    updated_at: str


class PlotThread(BaseModel):
    thread_id: str
    title: str
    status: str
    summary: str
    updated_at: str


class Scene(BaseModel):
    scene_id: int
    chapter_id: int
    sequence: int
    brief: str
    full_text: str | None = None
    summary: str | None = None
    facts_delta: dict[str, Any] | None = None
    status: str  # pending | draft | approved
    created_at: str


class Chapter(BaseModel):
    chapter_id: int
    number: int
    title: str | None
    arc_goal: str
    plan: dict[str, Any]
    summary: str | None = None
    status: str  # planned | in_progress | complete


# ── Planner output ────────────────────────────────────────────────────────────

class SceneBrief(BaseModel):
    sequence: int
    brief: str
    pov: str | None = None
    beats: list[str] = []
    location: str | None = None


class ChapterOption(BaseModel):
    title: str
    arc_goal: str
    pov: str
    scenes: list[SceneBrief]
    reveals: list[str] = []
    continuity_risks: list[str] = []
    emotional_arc: str = ""


class PlannerOutput(BaseModel):
    options: list[ChapterOption] = Field(min_length=1, max_length=3)


# ── Writer / reconciler output ────────────────────────────────────────────────

class CharacterUpdate(BaseModel):
    name: str
    changes: dict[str, Any]


class PlotUpdate(BaseModel):
    thread_id: str
    status: str
    summary_update: str = ""


class TimelineEvent(BaseModel):
    story_day: int | None = None
    event: str


class ContinuityFlag(BaseModel):
    severity: str  # low | medium | high
    description: str
    confidence: str = "high"  # high | low


class FactsDelta(BaseModel):
    character_updates: list[CharacterUpdate] = []
    plot_updates: list[PlotUpdate] = []
    timeline_events: list[TimelineEvent] = []
    continuity_flags: list[ContinuityFlag] = []


class ReconcilerOutput(BaseModel):
    summary: str
    validated_delta: FactsDelta
    low_confidence_items: list[str] = []
