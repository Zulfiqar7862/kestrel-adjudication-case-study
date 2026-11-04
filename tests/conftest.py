from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kestrel_sentinel.config import Settings
from kestrel_sentinel.service import AdjudicationService

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "KCCS_Sentinel_Reference_Data_Pack.xlsx"


@pytest.fixture()
def tmp_svc(tmp_path: Path) -> AdjudicationService:
    settings = Settings(
        data_pack=PACK,
        db_path=tmp_path / "t.sqlite",
        evidence_dir=tmp_path / "evidence",
        log_level="WARNING",
        rule_pack_version="0.2.0",
        code_version="0.2.0",
        retention_years=7,
    )
    svc = AdjudicationService(settings)
    svc.bootstrap(reload=True)
    return svc
