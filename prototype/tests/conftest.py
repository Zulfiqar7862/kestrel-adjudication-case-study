from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prototype" / "src"))

from adjudication.pack import DataPack
from adjudication.engine import AdjudicationEngine

PACK = ROOT / "data" / "KCCS_Sentinel_Reference_Data_Pack.xlsx"


@pytest.fixture(scope="session")
def pack() -> DataPack:
    assert PACK.exists(), f"missing pack at {PACK}"
    return DataPack.load(PACK)


@pytest.fixture(scope="session")
def engine(pack: DataPack) -> AdjudicationEngine:
    return AdjudicationEngine(pack)
