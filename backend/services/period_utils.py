"""Helpers for clamping analytics periods to available portfolio data."""
from datetime import datetime, timezone


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def start_of_utc_day(value: datetime) -> datetime:
    value = _as_utc(value)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def cap_period_start_to_earliest_transaction(
    requested_start: datetime,
    earliest_transaction_at: datetime | None,
) -> datetime:
    """Do not report performance before the portfolio has transaction data."""
    start = _as_utc(requested_start)
    if earliest_transaction_at is None:
        return start

    first_data_day = start_of_utc_day(earliest_transaction_at)
    return first_data_day if first_data_day > start else start
