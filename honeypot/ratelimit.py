"""Self-imposed multi-tier rate limiter, so a spam wave cannot make the bot hit global limits."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class _Tier:
    limit: int
    window: float
    count: int = 0
    resets_at: float = 0.0


@dataclass(slots=True)
class TieredLimiter:
    """Allow an action only while every ``(limit, window_seconds)`` tier still has room."""

    tiers: list[tuple[int, float]]
    clock: Callable[[], float] = time.monotonic
    _state: list[_Tier] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Build per-tier counters."""
        now = self.clock()
        self._state = [
            _Tier(limit, window, 0, now + window) for limit, window in self.tiers
        ]

    def try_acquire(self) -> bool:
        """Consume one slot from every tier, or none if any tier is exhausted."""
        now = self.clock()
        for tier in self._state:
            if now >= tier.resets_at:
                tier.count = 0
                tier.resets_at = now + tier.window
        if any(tier.count >= tier.limit for tier in self._state):
            return False
        for tier in self._state:
            tier.count += 1
        return True
