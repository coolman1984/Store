"""Record identity and time.

Every record gets a UUIDv7 made on this PC (time-ordered, globally unique), never an auto-increment number:
a later move to several PCs or branches does not rewrite any record (factory constitution 19).
Times are stored as UTC ISO text; the shop's local day uses this PC's time zone.
"""
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

_last = [0, 0]


def uuid7():
    ms = time.time_ns() // 1_000_000
    if ms <= _last[0]:  # same millisecond: keep order with a counter
        ms, seq = _last[0], _last[1] + 1
    else:
        seq = int.from_bytes(os.urandom(2), 'big') & 0x3FF
    _last[0], _last[1] = ms, seq
    rand = int.from_bytes(os.urandom(8), 'big') & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | ((seq & 0xFFF) << 64) | (0b10 << 62) | rand
    h = f'{value:032x}'
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}'


def utcnow():
    return datetime.now(timezone.utc)


_last_now = [None]
_lock = threading.Lock()


def iso(moment=None):
    """UTC ISO text with milliseconds. Without an argument ("now") the result is strictly increasing in this process:
    two records made in the same millisecond still have an order (a sale made just after counting a product must
    sort after the count line, or the count shows a phantom surplus). A clock moved back by more than a second is
    believed, so time never freezes."""
    if moment is None:
        now = utcnow()
        moment = now.replace(microsecond=now.microsecond // 1000 * 1000)
        with _lock:  # the server answers several browsers at once
            last = _last_now[0]
            if last is not None and last - timedelta(seconds=1) < moment <= last:
                moment = last + timedelta(milliseconds=1)
            _last_now[0] = moment
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def parse(text):
    if not text:
        return None
    moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_day(moment=None):
    """The shop's calendar day (YYYY-MM-DD) for a UTC moment, in this PC's own time zone (Windows knows Egypt's summer time)."""
    return (moment or utcnow()).astimezone().date().isoformat()


def day_bounds(day):
    """UTC ISO strings [start, end) of a local calendar day."""
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day).astimezone()
    nxt = d + timedelta(days=1)
    return iso(start), iso(datetime(nxt.year, nxt.month, nxt.day).astimezone())


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def add_months(day, months):
    d = date.fromisoformat(day)
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last)).isoformat()
