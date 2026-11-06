"""Shared test fixture: a fresh temp DB and evidence store per test class."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kestrel.config import _DEFAULT_PACK, Settings
from kestrel.service import AdjudicationService


def _make_tmp_svc(tmpdir: Path) -> AdjudicationService:
    """Create a bootstrapped service rooted at tmpdir for unit tests."""
    settings = Settings(
        data_pack=_DEFAULT_PACK,
        db_path=tmpdir / "t.sqlite",
        evidence_dir=tmpdir / "evidence",
        log_level="WARNING",
        rule_pack_version="0.3.0",
        code_version="0.3.0",
        retention_years=7,
    )
    svc = AdjudicationService(settings)
    svc.bootstrap(reload=True)
    return svc


class _KestrelTestCase(unittest.TestCase):
    """Shared fixture: fresh temp DB + evidence dir per test class or method."""

    svc: AdjudicationService
    _tmpdir: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        """Create a temporary DB/evidence dir and bootstrap a shared service."""
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="kestrel-test-")
        cls.svc = _make_tmp_svc(Path(cls._tmpdir.name))

    @classmethod
    def tearDownClass(cls) -> None:
        """Remove the temporary test directory."""
        cls._tmpdir.cleanup()
