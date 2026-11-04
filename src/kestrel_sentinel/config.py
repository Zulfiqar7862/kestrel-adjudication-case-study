from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KESTREL_", env_file=".env", extra="ignore")

    data_pack: Path = Path("data/KCCS_Sentinel_Reference_Data_Pack.xlsx")
    db_path: Path = Path(".data/kestrel.sqlite")
    evidence_dir: Path = Path(".data/evidence")
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    rule_pack_version: str = "0.2.0"
    retention_years: int = 7
    code_version: str = "0.2.0"


def get_settings() -> Settings:
    return Settings()
