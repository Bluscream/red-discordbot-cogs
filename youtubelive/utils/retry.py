import asyncio
import logging

log = logging.getLogger("red.blu.youtubelive.utils.retry")

class StaggeredRetry:
    """
    A reusable staggered backoff utility for polling tasks.
    """
    def __init__(self, start: float = 60.0, multiplier: float = 1.1, max_val: float = 3600.0):
        self.start = start
        self.multiplier = multiplier
        self.max_val = max_val
        self.current = start
        self.failures = 0

    async def sleep(self):
        """Wait for the current staggered interval and then increment it."""
        log.debug(f"Staggered retry: sleeping for {self.current:.1f}s (failures: {self.failures})")
        await asyncio.sleep(self.current)
        self.failures += 1
        self.current = min(self.current * self.multiplier, self.max_val)

    def reset(self):
        """Resets the backoff interval to the starting value."""
        self.current = self.start
        self.failures = 0
