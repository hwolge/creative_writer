from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    active_project: str = ""
    primary_model: str = "gpt-5.4"
    fast_model: str = "gpt-5.4-mini"
    max_scene_rejections: int = 3

    # Token budgets (approximate; used by context.py to trim content)
    budget_story_bible: int = 200
    budget_style_guide: int = 300
    budget_characters_summary: int = 300
    budget_plot_threads: int = 300
    budget_timeline: int = 200
    budget_prev_chapter: int = 300
    budget_pov_char: int = 200
    budget_other_chars: int = 150
    budget_prev_scene: int = 400
    budget_retrieved_excerpts: int = 600

    @property
    def data_dir(self) -> Path:
        return Path("data")

    @property
    def _active_project_file(self) -> Path:
        return self.data_dir / ".active_project"

    def get_active_project(self) -> str:
        """Return the active project slug.

        Reads from data/.active_project (written by the switch endpoint) first,
        falling back to the ACTIVE_PROJECT env-var so the CLI/startup default
        still works when no override file exists.
        """
        try:
            p = self._active_project_file
            if p.exists():
                slug = p.read_text(encoding="utf-8").strip()
                if slug:
                    return slug
        except Exception:
            pass
        return self.active_project

    def set_active_project(self, slug: str) -> None:
        """Persist the active project override without touching .env."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._active_project_file.write_text(slug, encoding="utf-8")

    def project_db_path(self, slug: str) -> Path:
        path = self.data_dir / slug
        path.mkdir(parents=True, exist_ok=True)
        return path / "novel.db"

    def list_projects(self) -> list[str]:
        """Return all project slugs that have an initialised novel.db."""
        if not self.data_dir.exists():
            return []
        return sorted(
            d.name for d in self.data_dir.iterdir()
            if d.is_dir() and (d / "novel.db").exists()
        )


settings = Settings()
