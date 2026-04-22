#!/usr/bin/env python3
"""Novel Writer CLI — interactive novel writing assistant powered by GPT-5.4."""
import json
import os
import sys
from pathlib import Path

import click
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table

from app.config import settings
from app import database as db
from app.database import get_conn, init_schema, seed_project
from app.models import ProjectSeed
from app.orchestrator.planner import propose_chapter_options
from app.orchestrator.reconciler import reconcile_scene, summarize_chapter
from app.orchestrator.writer import write_scene

console = Console()


def _get_client() -> OpenAI:
    api_key = settings.openai_api_key
    if not api_key:
        console.print("[red]OPENAI_API_KEY not set. Add it to your .env file.[/red]")
        sys.exit(1)
    return OpenAI(api_key=api_key)


def _get_conn(project: str | None = None):
    slug = project or settings.active_project
    if not slug:
        console.print("[red]No active project. Use --project or set ACTIVE_PROJECT in .env[/red]")
        sys.exit(1)
    db_path = settings.project_db_path(slug)
    if not db_path.exists():
        console.print(f"[red]Project '{slug}' not found. Run: python cli.py init --project {slug}[/red]")
        sys.exit(1)
    conn = get_conn(db_path)
    return conn, slug


@click.group()
def cli():
    """Novel Writer — stateful AI-assisted novel writing."""
    pass


# ── init ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", required=True, help="Project slug (used as directory name)")
@click.option(
    "--seed",
    default="templates/project_seed.json",
    show_default=True,
    help="Path to filled project_seed.json",
)
def init(project: str, seed: str):
    """Initialize a new novel project from a seed JSON file."""
    seed_path = Path(seed)
    if not seed_path.exists():
        console.print(f"[red]Seed file not found: {seed_path}[/red]")
        console.print("Copy templates/project_seed.json, fill it in, then run init.")
        sys.exit(1)

    with open(seed_path) as f:
        raw = json.load(f)

    try:
        seed_data = ProjectSeed.model_validate(raw)
    except Exception as e:
        console.print(f"[red]Seed file validation error:[/red] {e}")
        sys.exit(1)

    db_path = settings.project_db_path(project)
    if db_path.exists():
        if not Confirm.ask(f"Project '{project}' already exists. Re-seed (overwrites data)?"):
            return

    conn = get_conn(db_path)
    init_schema(conn)
    seed_project(conn, seed_data)
    conn.close()

    console.print(f"[green]✓ Project '{project}' initialized.[/green]")
    console.print(f"  DB: {db_path}")
    console.print(f"  Characters: {len(seed_data.characters)}")
    console.print(f"  Plot threads: {len(seed_data.plot_threads)}")
    console.print(f"  Arc goals seeded: {len(seed_data.arc_goals)}")
    console.print("\nNext step: [bold]python cli.py plan[/bold]")


# ── status ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=None, help="Project slug (overrides .env)")
def status(project: str | None):
    """Show current project status."""
    conn, slug = _get_conn(project)

    chapter = db.get_current_chapter(conn)
    scene = db.get_current_scene(conn)
    issues = db.get_continuity_issues(conn, unresolved_only=True)
    threads = db.get_plot_threads(conn, status="open")
    chars = db.get_all_characters(conn)

    console.print(Rule(f"[bold]Project: {slug}[/bold]"))

    if chapter:
        console.print(f"[bold]Current chapter:[/bold] #{chapter['number']} — {chapter.get('title') or '(untitled)'}")
        console.print(f"  Arc goal: {chapter['arc_goal']}")
        console.print(f"  Status: {chapter['status']}")
    else:
        console.print("[yellow]No active chapter. Run: python cli.py plan[/yellow]")

    if scene:
        console.print(f"\n[bold]Current scene:[/bold] #{scene['scene_id']} (seq {scene['sequence']}) — {scene['status']}")
        console.print(f"  Brief: {scene['brief'][:120]}...")
    else:
        console.print("\n[dim]No pending scene.[/dim]")

    console.print(f"\n[bold]Characters:[/bold] {len(chars)}")
    console.print(f"[bold]Open threads:[/bold] {len(threads)}")
    if issues:
        console.print(f"[bold yellow]Unresolved continuity issues:[/bold yellow] {len(issues)}")

    conn.close()


# ── plan ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=None, help="Project slug")
@click.option("--goal", default=None, help="Arc goal for this chapter (skip prompt)")
def plan(project: str | None, goal: str | None):
    """Propose 3 chapter options and let the author choose one."""
    conn, slug = _get_conn(project)
    client = _get_client()

    chapter = db.get_current_chapter(conn)
    chapter_number = (chapter["number"] if chapter and chapter["status"] == "planned" else
                      (chapter["number"] + 1 if chapter else 1))

    if not goal:
        # Check if there's a pre-seeded arc goal
        seeded = conn.execute(
            "SELECT arc_goal FROM chapters WHERE number=? AND status='planned'",
            (chapter_number,),
        ).fetchone()
        if seeded:
            console.print(f"[dim]Seeded arc goal:[/dim] {seeded['arc_goal']}")
            use_seeded = Confirm.ask("Use this arc goal?", default=True)
            goal = seeded["arc_goal"] if use_seeded else None

    if not goal:
        goal = Prompt.ask(f"Arc goal for Chapter {chapter_number}")

    console.print(f"\n[bold]Generating 3 chapter options for Chapter {chapter_number}...[/bold]")
    console.print("[dim]This may take a moment.[/dim]\n")

    with console.status("Calling GPT-5.4..."):
        options = propose_chapter_options(client, conn, goal)

    for i, opt in enumerate(options, 1):
        console.print(Panel(
            f"[bold]{opt.title}[/bold]\n\n"
            f"[dim]Arc goal:[/dim] {opt.arc_goal}\n"
            f"[dim]POV:[/dim] {opt.pov}\n"
            f"[dim]Emotional arc:[/dim] {opt.emotional_arc}\n\n"
            f"[dim]Scenes ({len(opt.scenes)}):[/dim]\n" +
            "\n".join(f"  {s.sequence}. {s.brief}" for s in opt.scenes) +
            (f"\n\n[dim]Reveals:[/dim] {', '.join(opt.reveals)}" if opt.reveals else "") +
            (f"\n[dim]Continuity risks:[/dim] {', '.join(opt.continuity_risks)}" if opt.continuity_risks else ""),
            title=f"Option {i}",
            border_style="blue",
        ))

    choice = IntPrompt.ask(
        "Choose an option",
        choices=[str(i) for i in range(1, len(options) + 1)],
    )
    selected = options[choice - 1]

    chapter_id = db.save_chapter_plan(
        conn,
        chapter_number=chapter_number,
        arc_goal=selected.arc_goal,
        title=selected.title,
        plan=selected.model_dump(),
    )
    conn.close()

    console.print(f"\n[green]✓ Chapter {chapter_number} planned: '{selected.title}'[/green]")
    console.print(f"  {len(selected.scenes)} scenes queued.")
    console.print("\nNext step: [bold]python cli.py write[/bold]")


# ── write ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=None, help="Project slug")
def write(project: str | None):
    """Generate prose for the next pending scene, then prompt for approval."""
    conn, slug = _get_conn(project)
    client = _get_client()

    scene = db.get_current_scene(conn)
    if not scene:
        console.print("[yellow]No pending scene. Run: python cli.py plan[/yellow]")
        conn.close()
        return

    chapter = db.get_chapter(conn, scene["chapter_id"])
    pov = chapter["plan"].get("pov") if chapter else None
    chapter_context = (
        f"Chapter: {chapter.get('title', '')} | Arc goal: {chapter.get('arc_goal', '')}"
        if chapter else ""
    )

    rejection_count = 0
    max_rejections = settings.max_scene_rejections
    scene_brief = scene["brief"]

    while True:
        console.print(Rule(f"[bold]Scene {scene['scene_id']} — Chapter {chapter['number'] if chapter else '?'}, seq {scene['sequence']}[/bold]"))
        console.print(f"[dim]Brief:[/dim] {scene_brief}\n")

        with console.status(f"Writing scene (attempt {rejection_count + 1})..."):
            prose, facts_delta = write_scene(client, conn, scene_brief, pov, chapter_context)

        console.print(Panel(Markdown(prose), title="Draft", border_style="green"))

        if facts_delta.get("continuity_flags"):
            console.print("\n[yellow]Continuity flags from writer:[/yellow]")
            for flag in facts_delta["continuity_flags"]:
                console.print(f"  [{flag['severity'].upper()}] {flag['description']}")

        action = Prompt.ask(
            "\nAction",
            choices=["approve", "edit", "reject", "skip"],
            default="approve",
        )

        if action == "approve":
            final_prose = prose
            break

        if action == "edit":
            console.print("[dim]Opening editor... paste edited prose below, end with a line containing only '---'[/dim]")
            lines = []
            while True:
                line = input()
                if line.strip() == "---":
                    break
                lines.append(line)
            final_prose = "\n".join(lines) if lines else prose
            break

        if action == "skip":
            console.print("[yellow]Scene skipped.[/yellow]")
            conn.close()
            return

        # reject
        rejection_count += 1
        if rejection_count >= max_rejections:
            console.print(f"[red]Reached rejection limit ({max_rejections}).[/red]")
            new_brief = Prompt.ask("Enter a revised scene brief (or press Enter to keep current)")
            if new_brief.strip():
                scene_brief = new_brief
            rejection_count = 0
        else:
            note = Prompt.ask("Rejection note for the model (optional)", default="")
            if note:
                scene_brief = f"{scene_brief}\n\nAuthor note: {note}"

    # Save draft
    db.save_scene_draft(conn, scene["scene_id"], final_prose, facts_delta)

    # Reconcile
    console.print("\n[dim]Reconciling state...[/dim]")
    with console.status("Running reconciler (gpt-5.4-mini)..."):
        result = reconcile_scene(client, conn, final_prose, facts_delta)

    console.print(f"\n[bold]Scene summary:[/bold] {result.summary}")
    if result.low_confidence_items:
        console.print("[yellow]Low-confidence items flagged:[/yellow]")
        for item in result.low_confidence_items:
            console.print(f"  • {item}")

    # Approve and commit to DB
    db.approve_scene(
        conn,
        scene["scene_id"],
        final_prose,
        result.summary,
        result.validated_delta.model_dump(),
    )

    console.print(f"\n[green]✓ Scene {scene['scene_id']} approved and canon updated.[/green]")

    # Check if chapter is complete
    next_scene = db.get_current_scene(conn)
    if not next_scene:
        _finish_chapter(client, conn, chapter)

    conn.close()


def _finish_chapter(client, conn, chapter: dict):
    if not chapter:
        return
    console.print(Rule("[bold green]Chapter complete![/bold green]"))

    summaries = [
        row["summary"] or row["brief"]
        for row in conn.execute(
            "SELECT summary, brief FROM scenes WHERE chapter_id=? AND status='approved' ORDER BY sequence",
            (chapter["chapter_id"],),
        ).fetchall()
    ]

    with console.status("Generating chapter summary..."):
        ch_summary = summarize_chapter(
            client,
            summaries,
            chapter.get("title", f"Chapter {chapter['number']}"),
            chapter.get("arc_goal", ""),
        )

    db.save_chapter_summary(conn, chapter["chapter_id"], ch_summary)
    console.print(Panel(ch_summary, title="Chapter Summary", border_style="cyan"))
    console.print("\nNext step: [bold]python cli.py plan[/bold]")


# ── state commands ────────────────────────────────────────────────────────────

@cli.group()
def state():
    """View and edit story state (characters, threads, timeline, issues)."""
    pass


@state.command("characters")
@click.option("--project", default=None)
@click.argument("name", required=False)
def state_characters(project: str | None, name: str | None):
    """List all characters, or show details for one."""
    conn, _ = _get_conn(project)
    if name:
        char = db.get_character(conn, name)
        if not char:
            console.print(f"[red]Character '{name}' not found.[/red]")
        else:
            console.print(Panel(
                json.dumps(char["facts"], indent=2) +
                (f"\n\nVoice samples:\n" + "\n".join(f'  "{s}"' for s in char["voice_samples"])
                 if char["voice_samples"] else ""),
                title=char["name"],
            ))
    else:
        table = Table(title="Characters")
        table.add_column("Name")
        table.add_column("Role")
        table.add_column("Status")
        for c in db.get_all_characters(conn):
            table.add_row(c["name"], c.get("role", ""), c.get("status", ""))
        console.print(table)
    conn.close()


@state.command("threads")
@click.option("--project", default=None)
@click.option("--status", default=None, help="Filter: open | dormant | resolved")
def state_threads(project: str | None, status: str | None):
    """List plot threads."""
    conn, _ = _get_conn(project)
    threads = db.get_plot_threads(conn, status)
    table = Table(title="Plot Threads")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Summary", max_width=60)
    for t in threads:
        table.add_row(t["thread_id"], t["title"], t["status"], t["summary"])
    console.print(table)
    conn.close()


@state.command("timeline")
@click.option("--project", default=None)
@click.option("--from-day", default=None, type=int)
@click.option("--to-day", default=None, type=int)
def state_timeline(project: str | None, from_day: int | None, to_day: int | None):
    """Show the story timeline."""
    conn, _ = _get_conn(project)
    events = db.get_timeline(conn, from_day, to_day)
    table = Table(title="Timeline")
    table.add_column("Day")
    table.add_column("Event")
    for e in events:
        table.add_row(str(e.get("story_day") or "?"), e["description"])
    console.print(table)
    conn.close()


@state.command("issues")
@click.option("--project", default=None)
@click.option("--all", "show_all", is_flag=True, help="Include resolved issues")
def state_issues(project: str | None, show_all: bool):
    """Show continuity issues."""
    conn, _ = _get_conn(project)
    issues = db.get_continuity_issues(conn, unresolved_only=not show_all)
    if not issues:
        console.print("[green]No unresolved continuity issues.[/green]")
        conn.close()
        return
    table = Table(title="Continuity Issues")
    table.add_column("ID")
    table.add_column("Severity")
    table.add_column("Description")
    table.add_column("Resolved")
    for issue in issues:
        table.add_row(
            str(issue["issue_id"]),
            issue["severity"],
            issue["description"],
            "yes" if issue["resolved"] else "no",
        )
    console.print(table)
    conn.close()


@state.command("resolve")
@click.option("--project", default=None)
@click.argument("issue_id", type=int)
def state_resolve(project: str | None, issue_id: int):
    """Mark a continuity issue as resolved."""
    conn, _ = _get_conn(project)
    db.resolve_continuity_issue(conn, issue_id)
    console.print(f"[green]✓ Issue {issue_id} resolved.[/green]")
    conn.close()


# ── archive ───────────────────────────────────────────────────────────────────

@cli.group()
def archive():
    """Browse the chapter/scene archive."""
    pass


@archive.command("chapters")
@click.option("--project", default=None)
def archive_chapters(project: str | None):
    """List all chapters."""
    conn, _ = _get_conn(project)
    rows = conn.execute(
        "SELECT chapter_id, number, title, arc_goal, status FROM chapters ORDER BY number"
    ).fetchall()
    table = Table(title="Chapters")
    table.add_column("#")
    table.add_column("Title")
    table.add_column("Arc Goal", max_width=50)
    table.add_column("Status")
    for r in rows:
        table.add_row(str(r["number"]), r["title"] or "", r["arc_goal"], r["status"])
    console.print(table)
    conn.close()


@archive.command("scenes")
@click.option("--project", default=None)
@click.option("--chapter", default=None, type=int, help="Filter by chapter number")
def archive_scenes(project: str | None, chapter: int | None):
    """List scenes, optionally filtered by chapter."""
    conn, _ = _get_conn(project)
    if chapter:
        rows = conn.execute("""
            SELECT s.scene_id, s.sequence, s.brief, s.status, s.summary
            FROM scenes s JOIN chapters c ON s.chapter_id=c.chapter_id
            WHERE c.number=? ORDER BY s.sequence
        """, (chapter,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.scene_id, c.number as ch_num, s.sequence, s.brief, s.status
            FROM scenes s JOIN chapters c ON s.chapter_id=c.chapter_id
            ORDER BY c.number, s.sequence
        """).fetchall()
    table = Table(title="Scenes")
    table.add_column("ID")
    if not chapter:
        table.add_column("Ch#")
    table.add_column("Seq")
    table.add_column("Brief", max_width=60)
    table.add_column("Status")
    for r in rows:
        row_data = [str(r["scene_id"])]
        if not chapter:
            row_data.append(str(r["ch_num"]))
        row_data += [str(r["sequence"]), r["brief"][:80], r["status"]]
        table.add_row(*row_data)
    console.print(table)
    conn.close()


@archive.command("show")
@click.option("--project", default=None)
@click.argument("scene_id", type=int)
def archive_show(project: str | None, scene_id: int):
    """Show the full text of a scene."""
    conn, _ = _get_conn(project)
    scene = db.get_scene(conn, scene_id)
    if not scene:
        console.print(f"[red]Scene {scene_id} not found.[/red]")
        conn.close()
        return
    console.print(Panel(
        scene.get("full_text") or "[no text yet]",
        title=f"Scene {scene_id} — {scene['brief'][:60]}",
    ))
    conn.close()


@archive.command("search")
@click.option("--project", default=None)
@click.argument("query")
def archive_search(project: str | None, query: str):
    """Full-text search over scenes."""
    conn, _ = _get_conn(project)
    results = db.search_scenes(conn, query)
    if not results:
        console.print("[yellow]No results.[/yellow]")
    else:
        for r in results:
            console.print(Panel(
                f"[dim]Brief:[/dim] {r['brief']}\n[dim]Summary:[/dim] {r.get('summary') or '—'}",
                title=f"Scene {r['scene_id']} (Chapter {r['chapter_id']})",
            ))
    conn.close()


if __name__ == "__main__":
    cli()
