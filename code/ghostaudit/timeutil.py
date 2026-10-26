"""UTC time parsing and formatting (SPEC T6).

Implements SPEC T6: every time is parsed once into integer UTC epoch seconds.
Parsing uses a regular expression instead of datetime.fromisoformat, whose
accepted forms differ between Python 3.9 and 3.11+, so results are identical on
every supported interpreter (SPEC N5).
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_ISO_PATTERN = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"[T ](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.\d+)?)?"
    r"\s*(?P<zone>Z|[+-]\d{2}:?\d{2})?"
)


@lru_cache(maxsize=None)
def to_epoch(text: str) -> int:
    """Return integer UTC epoch seconds for an ISO-8601 timestamp (SPEC T6).

    Accepts a 'T' or space separator, optional seconds, optional fractional
    seconds (truncated), and a 'Z' or +/-HH[:]MM offset. A missing offset is
    read as UTC, because every SPEC time is UTC. Raises ValueError otherwise.
    """
    match = _ISO_PATTERN.fullmatch(text.strip())
    if match is None:
        raise ValueError("unrecognised timestamp: %r" % text)
    wall = datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second") or 0),
    )
    return calendar.timegm(wall.timetuple()) - _offset_seconds(match.group("zone"))


def iso(epoch: int) -> str:
    """Format integer UTC epoch seconds as YYYY-MM-DDTHH:MM:SSZ (SPEC T6)."""
    return (EPOCH + timedelta(seconds=epoch)).strftime(ISO_FORMAT)


def _offset_seconds(zone: Optional[str]) -> int:
    """Seconds east of UTC for a zone designator; None and 'Z' are UTC."""
    if zone is None or zone == "Z":
        return 0
    sign = -1 if zone[0] == "-" else 1
    digits = zone[1:].replace(":", "")
    offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return sign * int(offset.total_seconds())
