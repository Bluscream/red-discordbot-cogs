import asyncio

class StaggeredRetry:
    """
    A simple utility for staggered/exponential backoff retry intervals.
    Automatically handles sleeping and compounding the interval.
    """
    def __init__(self, start: float = 60.0, multiplier: float = 1.1, max_val: float = 3600.0):
        self.start = start
        self.multiplier = multiplier
        self.max_val = max_val
        self.current = start

    def reset(self):
        """Resets the interval to the starting value."""
        self.current = self.start

    async def sleep(self):
        """Asynchronously sleeps for the current interval, then scales it up for the next call."""
        await asyncio.sleep(self.current)
        self.current *= self.multiplier
        if self.max_val is not None:
            self.current = min(self.current, self.max_val)
