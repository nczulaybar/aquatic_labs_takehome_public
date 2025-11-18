import asyncio
import time


class AsyncPeriodicTimer:
    """
    RAII-style async context manager that ensures a block of code
    runs at a fixed periodic interval.

    Better than just using sleep() because it accounts for the time
    taken by the code block itself.

    Usage:
    async with AsyncPeriodicTimer(period=5):
        # code block
    """

    def __init__(self, period_s: float):
        self.period = period_s

    async def __aenter__(self):
        self.start = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        elapsed = time.perf_counter() - self.start
        sleep_time = self.period - elapsed
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        else:
            print(
                f"WARN: Loop took ({elapsed:.2f}s) exceeding period ({self.period:.2f}s)"
            )
