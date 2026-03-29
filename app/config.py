from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str = ""
    usda_api_key: str = "DEMO_KEY"
    tandoor_base_url: str = "http://localhost:8080"
    tandoor_api_token: str = ""
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    tmp_dir: str = "/app/tmp"
    ffmpeg_location: str = ""  # Optional: full path to ffmpeg binary dir (for Windows local dev)


@lru_cache
def get_settings() -> Settings:
    return Settings()
