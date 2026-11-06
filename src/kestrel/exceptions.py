"""Domain and API exception hierarchy."""

from __future__ import annotations


class KestrelError(Exception):
    """Base class for recoverable Kestrel domain/API errors."""


class NotFoundError(KestrelError):
    """Requested entity (event, bundle, SOP) was not found."""


class TenantIsolationError(KestrelError, PermissionError):
    """Cross-tenant access denied (Meridian Cl.22 / evidence isolation)."""


class ValidationAppError(KestrelError):
    """Caller supplied invalid input for an API or service operation."""


class DependencyMissingError(KestrelError):
    """Optional framework dependency (FastAPI/Pydantic/uvicorn) is not installed."""


class StaleEvidenceError(Exception):
    """Raised when a signature is submitted against evidence that has since changed."""
