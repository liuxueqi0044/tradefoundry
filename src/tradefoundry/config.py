from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRADEFOUNDRY_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tradefoundry.db"
    artifact_root: Path = Path("./artifacts")
    environment: Literal["development", "test", "production"] = "development"
    http_timeout_seconds: float = 30.0
    user_agent: str = "TradeFoundry/0.1 (+operations@example.invalid)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
