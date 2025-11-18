import pytest
import asyncio
import time
from timer import AsyncPeriodicTimer


@pytest.mark.asyncio
async def test_timer_with_fast_operation():
    """
    Test timer with 3 second period and operation that takes 1.5 seconds.
    The timer should wait an additional 1.5 seconds to maintain the 3 second period.
    """
    period = 3.0
    operation_duration = 1.5

    start_time = time.perf_counter()

    async with AsyncPeriodicTimer(period_s=period):
        await asyncio.sleep(operation_duration)

    total_elapsed = time.perf_counter() - start_time

    # Allow 5% error.
    assert abs(total_elapsed - period) / period < 0.05, (
        f"Expected total time ~{period}s, got {total_elapsed:.2f}s"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
