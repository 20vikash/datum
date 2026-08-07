from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from threading import Lock
from time import monotonic


@dataclass
class RateLimitWindow:
    """One caller's requests to one route, since the window opened.

    `first_request_at` is not touched again once the window is open. Refreshing
    it per request would push the window out under sustained traffic, and a
    caller at the limit would never get back in.
    """

    first_request_at: float
    count: int


@dataclass(frozen=True)
class RateLimitKey:
    """Who is calling what path. Frozen, because it keys the window dict."""

    caller: str
    route: str


@dataclass
class RateLimiter:
    """A fixed window per caller and route, counted in this process."""

    ratelimit_windows: dict[RateLimitKey, RateLimitWindow] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def get_retry_after(self, caller: str, route: str, limit: int, period: float) -> int:
        """Seconds to wait, or 0 when the request may go ahead and has been counted.

        A refused request is not counted. Counting it would push the window out,
        and a caller at the limit would never get back in.
        """
        now = monotonic()
        with self.lock:
            key = RateLimitKey(caller, route)
            window = self.ratelimit_windows.get(key)
            if window is None or (now - window.first_request_at) >= period:
                self.ratelimit_windows[key] = RateLimitWindow(first_request_at=now, count=1)
                return 0
            if window.count >= limit:
                # Wait for this long before retrying.
                return max(1, ceil(period - (now - window.first_request_at)))
            window.count += 1
            return 0
