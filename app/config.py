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

    def project_db_path(self, slug: str) -> Path:
        path = self.data_dir / slug
        path.mkdir(parents=True, exist_ok=True)
        return path / "novel.db"


settings = Settings()
