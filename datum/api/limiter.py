from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from math import ceil
from threading import Lock
from time import monotonic


@dataclass
class RateLimitWindow:
    """One caller's requests to one route, since the window opened."""

    first_request_at: float
    count: int
    period: float

    def is_expired(self, now: float) -> bool:
        return (now - self.first_request_at) >= self.period


@dataclass(frozen=True)
class RateLimitKey:
    """Who is calling what path. Frozen, because it keys the window dict."""

    caller: str
    route: str


@dataclass
class RateLimiter:
    """A fixed window per caller and route, counted in this process."""

    ratelimit_windows: OrderedDict[RateLimitKey, RateLimitWindow] = field(
        default_factory=OrderedDict
    )
    lock: Lock = field(default_factory=Lock)
    clock: Callable[[], float] = monotonic

    def get_retry_after(self, caller: str, route: str, limit: int, period: float) -> int:
        """Seconds to wait, or 0 when the request may go ahead and has been counted.

        A refused request is not counted. Counting it would push the window out,
        and a caller at the limit would never get back in.
        """
        now = self.clock()
        with self.lock:
            key = RateLimitKey(caller, route)
            window = self.ratelimit_windows.get(key)
            if window is None or window.is_expired(now):
                self.open_window(key, now, period)
                return 0
            if window.count >= limit:
                # Wait for this long before retrying.
                return max(1, ceil(period - (now - window.first_request_at)))
            window.count += 1
            return 0

    def open_window(self, key: RateLimitKey, now: float, period: float) -> None:
        """Start counting again, newest last, retiring one dead window as we go."""
        self.retire_oldest(now)
        self.ratelimit_windows[key] = RateLimitWindow(now, count=1, period=period)
        self.ratelimit_windows.move_to_end(key)

    def retire_oldest(self, now: float) -> None:
        """Drop the oldest window if it has expired, to keep the dict from growing."""
        oldest = next(iter(self.ratelimit_windows.items()), None)
        if oldest is not None and oldest[1].is_expired(now):
            del self.ratelimit_windows[oldest[0]]
