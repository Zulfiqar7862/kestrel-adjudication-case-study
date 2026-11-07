"""Typed settings (env-overridable) and repository paths."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


_DEFAULT_PACK = _REPO_ROOT / "data" / "KCCS_Sentinel_Reference_Data_Pack.xlsx"


@dataclass
class Settings:
    """Runtime settings (env KESTREL_* optional; no third-party settings lib)."""

    data_pack: Path = field(default_factory=lambda: _DEFAULT_PACK)
    db_path: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "kestrel-adjudication" / "kestrel.sqlite"
    )
    evidence_dir: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "kestrel-adjudication" / "evidence"
    )
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    rule_pack_version: str = "0.5.0"
    retention_years: int = 7
    code_version: str = "0.5.0"

    def __post_init__(self) -> None:
        """Normalize Path fields and apply optional KESTREL_* environment overrides."""
        self.data_pack = Path(self.data_pack)
        self.db_path = Path(self.db_path)
        self.evidence_dir = Path(self.evidence_dir)
        # Optional env overrides (stdlib only)
        env = os.environ
        if env.get("KESTREL_DATA_PACK"):
            self.data_pack = Path(env["KESTREL_DATA_PACK"])
        if env.get("KESTREL_DB_PATH"):
            self.db_path = Path(env["KESTREL_DB_PATH"])
        if env.get("KESTREL_EVIDENCE_DIR"):
            self.evidence_dir = Path(env["KESTREL_EVIDENCE_DIR"])
        if env.get("KESTREL_LOG_LEVEL"):
            self.log_level = env["KESTREL_LOG_LEVEL"]
        if env.get("KESTREL_API_HOST"):
            self.api_host = env["KESTREL_API_HOST"]
        if env.get("KESTREL_API_PORT"):
            self.api_port = int(env["KESTREL_API_PORT"])


def get_settings() -> Settings:
    """Return default Settings (fresh instance each call)."""
    return Settings()
