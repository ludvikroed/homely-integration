"""Logging helpers for the Homely integration."""

from __future__ import annotations

import json
import logging
from typing import Any

_LOG_REDACT_KEYS = {
    "deviceid",
    "gatewayid",
    "gatewayserial",
    "id",
    "location",
    "locationid",
    "modelid",
    "name",
    "networklinkaddress",
    "rootlocationid",
    "serialnumber",
    "userid",
}


def _log_identifier(value: Any) -> str | None:
    """Return a shortened identifier suitable for logs."""
    if value is None:
        return None

    text = str(value)
    if len(text) <= 8:
        return text
    return f"{text[:8]}..."


def _ctx(
    entry_id: str,
    location_id: str | int | None = None,
    device_id: str | int | None = None,
) -> str:
    """Build consistent structured logging context."""
    context = f"entry_id={entry_id}"
    if location_id is not None:
        context += f" location_id={_log_identifier(location_id)}"
    if device_id is not None:
        context += f" device_id={_log_identifier(device_id)}"
    return context


def _json_debug(value: Any) -> str:
    """Return JSON string for debug logging without raising."""
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return repr(value)


def _redact_for_debug_logging(value: Any) -> Any:
    """Return a version of nested payloads suitable for debug logging."""
    if isinstance(value, dict):
        return {
            key: (
                "**REDACTED**"
                if isinstance(key, str) and key.casefold() in _LOG_REDACT_KEYS
                else _redact_for_debug_logging(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_for_debug_logging(item) for item in value]
    return value


def _log_startup_device_payloads(
    logger: logging.Logger,
    data: dict[str, Any],
    entry_id: str,
    location_id: str | int,
) -> None:
    """Log full payload per device once during startup when debug logging is enabled."""
    if not logger.isEnabledFor(logging.DEBUG):
        return

    location_id_str = str(location_id)
    devices = data.get("devices")
    if not isinstance(devices, list):
        logger.debug(
            "Startup API device dump skipped; devices list missing %s",
            _ctx(entry_id, location_id_str),
        )
        return

    logger.debug(
        "Startup API device dump begin %s device_count=%s",
        _ctx(entry_id, location_id_str),
        len(devices),
    )

    for index, device in enumerate(devices, start=1):
        if not isinstance(device, dict):
            logger.debug(
                "Startup API device payload #%s is not an object %s payload=%r",
                index,
                _ctx(entry_id, location_id_str),
                device,
            )
            continue

        device_dump = json.dumps(
            _redact_for_debug_logging(device),
            indent=2,
            ensure_ascii=True,
            sort_keys=True,
        )

        logger.debug(
            "Startup API payload #%s %s\n%s",
            index,
            _ctx(entry_id, location_id_str),
            device_dump,
        )

    logger.debug(
        "Startup API device dump complete %s", _ctx(entry_id, location_id_str)
    )
