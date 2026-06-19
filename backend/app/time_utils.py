from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
INTRADAY_ENTRY_CUTOFF = time(15, 10)
INTRADAY_SQUARE_OFF = time(15, 20)
MARKET_CLOSE = time(15, 30)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return now_utc().astimezone(IST)


def current_trading_day() -> str:
    return now_ist().date().isoformat()


def next_session_expiry() -> datetime:
    now = now_ist()
    next_midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=IST)
    return min(now + timedelta(hours=24), next_midnight).astimezone(timezone.utc)


def is_market_open(moment: datetime | None = None) -> bool:
    local = (moment or now_utc()).astimezone(IST)
    if local.weekday() >= 5:
        return False
    return MARKET_OPEN <= local.time() <= MARKET_CLOSE


def is_intraday_square_off_time(moment: datetime | None = None) -> bool:
    local = (moment or now_utc()).astimezone(IST)
    if local.weekday() >= 5:
        return False
    return INTRADAY_SQUARE_OFF <= local.time() <= MARKET_CLOSE


def is_intraday_entry_cutoff_time(moment: datetime | None = None) -> bool:
    local = (moment or now_utc()).astimezone(IST)
    if local.weekday() >= 5:
        return False
    return INTRADAY_ENTRY_CUTOFF <= local.time() <= MARKET_CLOSE


def build_intraday_market_clock(moment: datetime | None = None) -> dict[str, object]:
    local = (moment or now_utc()).astimezone(IST)
    entry_cutoff = datetime.combine(local.date(), INTRADAY_ENTRY_CUTOFF, tzinfo=IST)
    square_off = datetime.combine(local.date(), INTRADAY_SQUARE_OFF, tzinfo=IST)
    local_time = local.time()

    if local.weekday() >= 5 or local_time < MARKET_OPEN or local_time > MARKET_CLOSE:
        phase = "exit-only"
    elif local_time < time(10, 0):
        phase = "opening"
    elif local_time < time(14, 45):
        phase = "normal"
    elif local_time < INTRADAY_ENTRY_CUTOFF:
        phase = "late-session"
    else:
        phase = "exit-only"

    return {
        "currentTimeIst": local.isoformat(),
        "marketPhase": phase,
        "entryCutoffIst": "15:10",
        "squareOffIst": "15:20",
        "minutesUntilEntryCutoff": _minutes_until(local, entry_cutoff),
        "minutesUntilSquareOff": _minutes_until(local, square_off),
        "newEntriesAllowed": (
            local.weekday() < 5
            and MARKET_OPEN <= local_time < INTRADAY_ENTRY_CUTOFF
        ),
    }


def _minutes_until(current: datetime, target: datetime) -> int:
    return max(math.ceil((target - current).total_seconds() / 60), 0)


def utc_iso(moment: datetime | None = None) -> str:
    return (moment or now_utc()).astimezone(timezone.utc).isoformat()
