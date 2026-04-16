from functools import lru_cache
from pathlib import Path

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    usda_api_key: str = "DEMO_KEY"
    tandoor_base_url: str = "http://localhost:8080"
    tandoor_api_token: str = ""
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    tmp_dir: str = "tmp"
    ffmpeg_location: str = ""  # Optional: full path to ffmpeg binary dir (for Windows local dev)
    @field_validator("tmp_dir", "ffmpeg_location", mode="before")
    @classmethod
    def _resolve_project_relative_paths(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith(("/", "\\")):
            return value
        path = Path(value).expanduser()
        if path.is_absolute():
            return str(path)
        return str((BASE_DIR / path).resolve())

    @computed_field
    @property
    def data_dir(self) -> str:
        return str(BASE_DIR / "data")

    @computed_field
    @property
    def images_dir(self) -> str:
        return str(Path(self.data_dir) / "images")

    @computed_field
    @property
    def history_db_path(self) -> str:
        return str(Path(self.data_dir) / "history.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
