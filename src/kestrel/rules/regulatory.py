"""Explicit scoped calendar arithmetic; workbook clocks are historical references."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class NotificationRule:
    """Controlled-rule input contract, not a built-in legal-policy registry.

    Approval/source references must come from an authorized policy-control process.
    No such adapter or approved production rules are supplied with this prototype.
    """

    rule_id: str
    tenant_code: str
    product_ref: str
    market: str
    kind: str
    amount: float
    source_hash: str
    approval_ref: str
    timezone: Optional[str] = None
    cutoff: Optional[str] = None
    weekends: Optional[tuple[int, ...]] = None
    holidays: Optional[tuple[date, ...]] = None
    calendar_start: Optional[date] = None
    calendar_end: Optional[date] = None

    def deadline(self, alert: datetime) -> datetime:
        """UTC input/output; reject incomplete control scope and calendar coverage."""
        if not all((self.rule_id.strip(), self.approval_ref.strip(), self.tenant_code, self.product_ref, self.market)):
            raise ValueError("controlled rule identity/scope missing")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", self.source_hash):
            raise ValueError("controlled source hash missing")
        if isinstance(self.amount, bool) or not isfinite(self.amount) or self.amount <= 0:
            raise ValueError("positive finite calendar amount required")
        utc = alert.replace(tzinfo=timezone.utc) if alert.tzinfo is None else alert.astimezone(timezone.utc)
        if (
            not self.calendar_start
            or not self.calendar_end
            or not self.calendar_start <= utc.date() <= self.calendar_end
        ):
            raise ValueError("rule validity/calendar coverage unresolved")
        if self.kind == "elapsed_hours":
            due = utc + timedelta(hours=self.amount)
        else:
            if not self.timezone or not self.cutoff or int(self.amount) != self.amount:
                raise ValueError("calendar zone, cutoff and integer days required")
            zone = ZoneInfo(self.timezone)
            local_day = utc.astimezone(zone).date()
            if not self.calendar_start <= local_day <= self.calendar_end:
                raise ValueError("local holiday calendar coverage unavailable")
            if not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", self.cutoff):
                raise ValueError("explicit local wall-clock cutoff required")
            if self.kind == "calendar_days":
                local_day += timedelta(days=int(self.amount))
            elif self.kind == "next_business_day":
                if (
                    self.holidays is None
                    or self.weekends is None
                    or not self.weekends
                    or any(d not in range(7) for d in self.weekends)
                    or len(set(self.weekends)) == 7
                ):
                    raise ValueError("explicit weekend calendar required")
                remaining = int(self.amount)
                while remaining:
                    local_day += timedelta(days=1)
                    if local_day > self.calendar_end:
                        raise ValueError("holiday calendar coverage exhausted")
                    if local_day.weekday() not in self.weekends and local_day not in self.holidays:
                        remaining -= 1
            else:
                raise ValueError("unsupported controlled calendar kind")
            if not self.calendar_start <= local_day <= self.calendar_end:
                raise ValueError("local due date exceeds controlled calendar coverage")
            due = datetime.combine(local_day, time.fromisoformat(self.cutoff), tzinfo=zone)
            # Ambiguous/nonexistent local cutoffs need an explicit policy, not a guess.
            if (
                due.utcoffset() != due.replace(fold=1).utcoffset()
                or due.astimezone(timezone.utc).astimezone(zone) != due
            ):
                raise ValueError("ambiguous/nonexistent local cutoff")
        if due.astimezone(timezone.utc).date() > self.calendar_end:
            raise ValueError("rule/calendar coverage exhausted")
        return due.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class RegulatoryClock:
    """Unknown authority is explicit; no country, region or 24h fallback."""

    reportable: Optional[bool]
    window_hours: Optional[float]
    deadline_utc: Optional[datetime]
    basis: str
    hours_remaining_at_eval: Optional[float] = None
    reportability_status: str = "UNKNOWN"
    deadline_status: str = "UNKNOWN"
    historical_window_reference: Any = None


def regulatory_clock(
    tenant_code: str,
    alert_ts: Optional[datetime],
    tenant_row: Optional[dict[str, Any]] = None,
    historically_reportable: Any = None,
    historical_window_hours: Any = None,
    eval_ts: Optional[datetime] = None,
    *,
    rule: Optional[NotificationRule] = None,
    product_ref: Optional[str] = None,
    market: Optional[str] = None,
) -> RegulatoryClock:
    """Track historical Y conservatively; N/blank cannot establish inapplicability.

    No controlled policy is installed by default. The arithmetic contract accepts
    explicit fixtures/controlled registry input, never guessed country applicability.
    """
    reportable = True if str(historically_reportable or "").upper() == "Y" else None
    clock = RegulatoryClock(
        reportable,
        None,
        None,
        "Unresolved applicability/calendar authority; historical reportability/window are reference only",
        reportability_status="REPORTABLE" if reportable else "UNKNOWN",
        historical_window_reference=historical_window_hours,
    )
    if rule is None or alert_ts is None:
        return clock
    if (tenant_code, product_ref, market) != (rule.tenant_code, rule.product_ref, rule.market):
        clock.basis = "Unresolved: controlled tenant/product/market scope mismatch"
        return clock
    try:
        deadline = rule.deadline(alert_ts)
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError) as exc:
        clock.basis = "Unresolved controlled calendar: " + str(exc)
        return clock
    clock.deadline_utc = deadline
    clock.deadline_status = "CONTROLLED_RULE_INPUT"
    clock.basis = f"{rule.rule_id}; source sha256:{rule.source_hash}; approval {rule.approval_ref}"
    eval_ts = eval_ts or alert_ts
    if eval_ts.tzinfo is not None:
        eval_ts = eval_ts.astimezone(timezone.utc).replace(tzinfo=None)
    clock.hours_remaining_at_eval = (deadline - eval_ts).total_seconds() / 3600
    if rule.kind == "elapsed_hours":
        clock.window_hours = float(rule.amount)
    return clock
