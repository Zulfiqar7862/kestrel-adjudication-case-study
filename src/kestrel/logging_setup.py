"""Structured JSON logging helpers."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured stdout logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a LogRecord as a single-line JSON object."""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger with a JSON formatter at the given level."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
