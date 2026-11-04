"""Regulatory notification windows — measured from alert_ts, not disposition.

Source of truth for windows: tab 13_Volume_And_Cost row on 'Regulatory notification
windows in the book', plus tab 12 tenant-specific notes (Campos = 5 calendar days).
The pack is silent on a per-tenant table; we take an explicit position below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional


# Position taken (brief §Kavitha + pack tab 13 row 22 + tab 12 T-CAMPOS):
# - EU tenants default 72h where market requires notification (we mark reportable
#   when historical row says Y, else compute window for tenant region).
# - Brazil (T-CAMPOS): 5 calendar days.
# - US: next-business-day programme is one state — without a state field we use
#   24h as the conservative operational SLA for reportable US cases.
# - India: 15 days for notifiable products only.
DEFAULT_WINDOWS_HOURS = {
    "T-AURA": 72,
    "T-NORDIA": 72,
    "T-CAMPOS": 5 * 24,
    "T-PINNACLE": 24,
    "T-MERIDIAN": 24,
    "T-VIRENT": 15 * 24,
    "T-SAHYADRI": 15 * 24,
    "T-KAVERI": 15 * 24,
}

REGION_DEFAULTS = {
    "EMEA": 72,
    "AMER": 24,
    "APAC": 15 * 24,
    "LATAM": 5 * 24,
}


@dataclass
class RegulatoryClock:
    reportable: bool
    window_hours: Optional[float]
    deadline_utc: Optional[datetime]
    basis: str
    hours_remaining_at_eval: Optional[float] = None


def regulatory_clock(
    tenant_code: str,
    alert_ts: Optional[datetime],
    tenant_row: Optional[dict[str, Any]] = None,
    historically_reportable: Any = None,
    historical_window_hours: Any = None,
    eval_ts: Optional[datetime] = None,
) -> RegulatoryClock:
    """Compute the notification deadline.

    Prefer the pack's historical reg_window_hours when present (ground truth for
    that case). Otherwise apply our tenant/region position.
    """
    reportable = str(historically_reportable or "").upper() == "Y"
    window = None
    basis = ""
    if historical_window_hours not in (None, ""):
        try:
            window = float(historical_window_hours)
            basis = "pack.reg_window_hours"
        except (TypeError, ValueError):
            window = None

    if window is None:
        if tenant_code in DEFAULT_WINDOWS_HOURS:
            window = float(DEFAULT_WINDOWS_HOURS[tenant_code])
            basis = f"tenant_default[{tenant_code}]"
        elif tenant_row and tenant_row.get("region") in REGION_DEFAULTS:
            window = float(REGION_DEFAULTS[tenant_row["region"]])
            basis = f"region_default[{tenant_row['region']}]"
        else:
            window = 72.0
            basis = "fallback_72h"

    # If not marked reportable historically and no historical window, keep window
    # for operational awareness but flag reportable=False unless tenant is Campos
    # (always track) — disposition path still uses it when reportable.
    deadline = None
    remaining = None
    if alert_ts is not None and window is not None:
        deadline = alert_ts + timedelta(hours=window)
        if eval_ts is None:
            eval_ts = alert_ts
        remaining = (deadline - eval_ts).total_seconds() / 3600.0

    return RegulatoryClock(
        reportable=reportable,
        window_hours=window if reportable or historical_window_hours not in (None, "") else window,
        deadline_utc=deadline if reportable or historical_window_hours not in (None, "") else deadline,
        basis=basis,
        hours_remaining_at_eval=remaining,
    )
