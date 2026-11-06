"""Small shared helpers (date parsing, UTC clock, worksheet rows).

These were defined more than once in the single-file prototype; the definitions
kept here are the ones that were in effect at runtime, so behaviour is unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime (tzinfo stripped)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a datetime-like value into a naive datetime, or None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 else text, fmt)
        except ValueError:
            continue
    return None


def parse_date(value: Optional[str]) -> Optional[date]:
    """Parse a date-like value into a date, or None if unparseable."""
    if not value:
        return None
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def sheet_rows(worksheet: Any) -> list[dict[str, Any]]:
    """Read an openpyxl worksheet into a list of header-keyed dict rows."""
    headers = [cell.value for cell in worksheet[1]]
    out = []
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        if all(cell_value is None for cell_value in row):
            continue
        out.append({headers[col]: row[col] for col in range(len(headers))})
    return out


def to_float(value: Any) -> Optional[float]:
    """Coerce a workbook cell to float; blank or non-numeric becomes None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def revision_number(revision: Any) -> int:
    """Numeric part of an SOP revision label ("Rev 03" -> 3); 0 when there is none."""
    digits = "".join(ch for ch in str(revision or "") if ch.isdigit())
    return int(digits) if digits else 0
