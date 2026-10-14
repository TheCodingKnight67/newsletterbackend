"""UTC timestamps compatible with the existing timezone-naive database columns."""
from datetime import datetime, timezone


def utc_now():
    # Generate explicitly in UTC, then normalize for the existing SQL schema.
    return datetime.now(timezone.utc).replace(tzinfo=None)
