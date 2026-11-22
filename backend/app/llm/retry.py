import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(error, "headers", None)
    if headers is None:
        return None

    try:
        value = headers.get("retry-after")
    except (AttributeError, TypeError):
        return None
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()

    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds
