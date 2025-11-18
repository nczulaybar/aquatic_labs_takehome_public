import pytest
import time
import sqlite3
import os
import json
from datetime import datetime, timezone
from fastapi.testclient import TestClient

import math

# Import the app factory
from server import create_app
from data_models import RawMeasurementsResponse, SummariesResponse


@pytest.fixture(scope="function")
def client(tmp_path):
    """Create a test client with a fresh database for each test"""
    db_path = str(tmp_path / "test_aquatic_data.db")
    app = create_app(DB_PATH=db_path)
    app.state.full_db_path = (
        db_path  # Store path for potential use by tests that need db access
    )

    with TestClient(app) as client:
        yield client

    # Teardown: remove the test database file
    if os.path.exists(db_path):
        os.remove(db_path)


def test_write_and_read_raw_measurements(client):
    """
    Write measurements via POST /measurements and read them back via GET /raw_measurements
    """

    base_time = int(time.time())
    sensor_id = 1

    # Construct measurements
    time_offsets = [0, 10, 20]
    temperatures = [25.5, 26.0, 24.5]
    conductivities = [1.2, 1.3, 1.1]

    measurements_to_write = [
        {
            "sensor_id": sensor_id,
            "timestamp": datetime.fromtimestamp(base_time + offset, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "temperature": temp,
            "conductivity": cond,
        }
        for offset, temp, cond in zip(time_offsets, temperatures, conductivities)
    ]

    # Post measurements
    for measurement in measurements_to_write:
        post_response = client.post("/measurements", json=measurement)
        assert post_response.status_code == 200

    # Read data back
    get_response = client.get(
        f"/raw_measurements?start_time={base_time - 10}&end_time={base_time + 100}"
    )
    assert get_response.status_code == 200

    # Verify respponse
    response_data = RawMeasurementsResponse(**get_response.json())
    expected_times = [base_time + offset for offset in time_offsets]
    assert response_data.sensor_id == [sensor_id] * len(time_offsets)
    assert response_data.time == expected_times
    assert response_data.temperature == temperatures
    assert response_data.conductivity == conductivities


def test_read_raw_measurements_empty_range(client):
    """Test GET /raw_measurements returns empty data when no measurements in range"""
    far_future = int(time.time()) + 86400 * 365  # 1 year in future

    response = client.get(
        f"/raw_measurements?start_time={far_future}&end_time={far_future + 3600}"
    )
    assert response.status_code == 200


def test_write_duplicate_timestamp(client):
    """Test that writing duplicate timestamps for the same sensor returns 409 error"""
    current_time = int(time.time())
    sensor_id = 1
    timestamp_str = (
        datetime.fromtimestamp(current_time, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    # First write
    client.post(
        "/measurements",
        json={
            "sensor_id": sensor_id,
            "timestamp": timestamp_str,
            "temperature": 25.0,
            "conductivity": 1.0,
        },
    )

    # Try to write same timestamp for same sensor again
    response = client.post(
        "/measurements",
        json={
            "sensor_id": sensor_id,
            "timestamp": timestamp_str,
            "temperature": 26.0,
            "conductivity": 1.1,
        },
    )
    assert response.status_code == 409

    # But different sensor with same timestamp should succeed
    response2 = client.post(
        "/measurements",
        json={
            "sensor_id": 2,
            "timestamp": timestamp_str,
            "temperature": 26.0,
            "conductivity": 1.1,
        },
    )
    assert response2.status_code == 200


def test_summaries_endpoint_time_based_windows(client):
    """
    Test that /summaries endpoint returns:
    - 60-second window summaries for data less than 1 hour old (55-59 minutes)
    - 300-second window summaries for data more than 1 hour old (60-70 minutes)
    """
    current_time = int(time.time())
    sensor_id = 1

    # Directly access using the path stored in app.state
    # Manually write summaries for between 55 and 70 minutes ago.
    db_path = client.app.state.full_db_path
    db_conn = sqlite3.connect(db_path)
    cursor = db_conn.cursor()

    # Create summaries for every minute from 58 to 70 minutes ago
    for minutes_ago in range(58, 71):
        timestamp = current_time - (minutes_ago * 60)

        temp_mean = 10
        cond_mean = 12

        stats = json.dumps(
            {
                "count": 10,
                "temperature": {
                    "mean": temp_mean,
                    "median": temp_mean,
                    "min": temp_mean,
                    "max": temp_mean,
                },
                "conductivity": {
                    "mean": cond_mean,
                    "median": cond_mean,
                    "min": cond_mean,
                    "max": cond_mean,
                },
            }
        )

        # Insert both 60s and 300s window summaries.
        cursor.execute(
            "INSERT INTO summaries (sensor_id, time, window_size, statistics) VALUES (?, ?, ?, ?)",
            (sensor_id, timestamp, 60, stats),
        )
        if minutes_ago % 5 == 0:
            cursor.execute(
                "INSERT INTO summaries (sensor_id, time, window_size, statistics) VALUES (?, ?, ?, ?)",
                (sensor_id, timestamp, 300, stats),
            )

    db_conn.commit()
    db_conn.close()

    # Query the summaries endpoint for the range covering all our test data
    oldest_time = current_time - (70 * 60) - 60  # Start before our oldest data
    end_time = current_time  # End at current time

    response = client.get(f"/summaries?start_time={oldest_time}&end_time={end_time}")

    assert response.status_code == 200

    response_data = SummariesResponse(**response.json())
    summaries = response_data.summaries

    # We should get exactly 5 summaries (58 to 70 minutes is 58, 59, 60, 65, 70)
    assert len(summaries) == 5, (
        f"Expected 5 summaries (55-70 min), got {len(summaries)}"
    )

    # Verify window sizes based on age
    one_hour_ago = current_time - 3600
    for summary in summaries:
        timestamp = summary.time
        window_size = summary.window_size

        # Calculate how many minutes ago this summary is
        seconds_ago = current_time - timestamp
        minutes_ago = seconds_ago // 60

        if timestamp >= one_hour_ago:
            # Less than 1 hour old: should use 60s window
            assert window_size == 60, (
                f"Summary at {minutes_ago} min ago (timestamp {timestamp}) should use 60s window, got {window_size}s"
            )
        else:
            # More than 1 hour old: should use 300s window
            assert window_size == 300, (
                f"Summary at {minutes_ago} min ago (timestamp {timestamp}) should use 300s window, got {window_size}s"
            )

    # Count how many of each window size we got
    window_60_count = sum(1 for s in summaries if s.window_size == 60)
    window_300_count = sum(1 for s in summaries if s.window_size == 300)
    assert window_60_count == 3, (
        f"Expected 3 summaries with 60s window (55-59 min), got {window_60_count}"
    )
    assert window_300_count == 2, (
        f"Expected 2 summaries with 300s window (60-70 min), got {window_300_count}"
    )


@pytest.fixture(scope="function")
def fast_aiosleep(monkeypatch):
    """
    We can use time-machine to change time, but this seems to create UB for
    asyncio.sleep()s that are already in flight, likely because we 'jumped over'
    their scheduled wakeup time in the event loop.
    We'll monkeypatch asyncio.sleep so that it frequently wakes up and polls
    time.time(). This appears to resolve the issue.

    With this change, asynchronous events in the server are polling the time
    to decide when to run, so after changing the time with time machine, one
    needs to briefly sleep to allow them to poll. The 'brief' sleep here must
    be longer than the fast_sleep polling interval.

    tick=True is necessary for time-machine.travel(), as the event loop seems to
    get stuck/ deadlocked without it.
    """

    import asyncio

    _original_aiosleep = asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        wakeup_time = time.time() + delay
        polling_interval = 0.1
        while time.time() < wakeup_time:
            await _original_aiosleep(polling_interval)
        return

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    return _original_aiosleep


@pytest.mark.asyncio
async def test_time_based_summarization(client, fast_aiosleep):
    """
    Test that:
    1. Freeze time to 12:00 PM
    2. In a loop (5 times):
       - Send 2 measurements
       - Advance time by 1 minute (to let server-side summarization run)
    3. Read back 1-minute summaries
    4. Advance time an hour.
    5. Read back a 5-minute summary.
    """
    import time_machine
    from datetime import datetime, timezone, timedelta
    import asyncio

    num_summaries = 5
    messages_per_minute = 2
    sensor_id = 1

    # Start at 12:00 PM
    start_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    with time_machine.travel(start_time, tick=True) as traveller:
        for i in range(num_summaries):
            current_timestamp = int(time.time())

            # Send 2 measurements
            for j in range(messages_per_minute):
                timestamp_str = (
                    datetime.fromtimestamp(current_timestamp + j, tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )

                response = client.post(
                    "/measurements",
                    json={
                        "sensor_id": sensor_id,
                        "timestamp": timestamp_str,
                        "temperature": 25.0 + i + (j * 0.1),
                        "conductivity": 1.0 + i + (j * 0.01),
                    },
                )
                assert response.status_code == 200, (
                    f"Failed to post measurement {i}.{j}"
                )

            # Advance time, and then let the sever-side sleeps trigger
            traveller.shift(timedelta(minutes=1))
            await asyncio.sleep(0.2)

        # Now read back 1-minute summaries
        query_start = int(start_time.timestamp())
        query_end = int(time.time())
        response = client.get(
            f"/summaries?start_time={query_start}&end_time={query_end}"
        )
        assert response.status_code == 200

        response_data = SummariesResponse(**response.json())
        summaries = response_data.summaries

        # Check initial summaries, should have num_summaries, each with 2 measurements
        assert len(summaries) == num_summaries, "Expected to find 1-minute summaries"
        for summary in summaries:
            assert summary.window_size == 60, (
                f"Expected 60s window, got {summary.window_size}s"
            )
            assert summary.statistics.count == 2, (
                f"Expected 2 measurements per window, got {summary.statistics.count}"
            )

        # Advance time by 2 hours to trigger 5-minute summarization
        traveller.shift(timedelta(hours=2))
        await asyncio.sleep(0.2)

        # Read back 5 minute summary
        query_start_2 = 0
        query_end_2 = int(time.time())
        response_2 = client.get(
            f"/summaries?start_time={query_start_2}&end_time={query_end_2}"
        )
        assert response_2.status_code == 200

        response_data_2 = SummariesResponse(**response_2.json())
        summaries_after_2_hours = response_data_2.summaries

        # We had 6 minutes of data, which should aggregate into 2 5-minute summary
        assert len(summaries_after_2_hours) == math.ceil(float(num_summaries) / 5.0), (
            "Expected to find at least 2 summary after 2 hours"
        )

        # All summaries should now be 5-minute windows (data is > 1 hour old)
        for summary in summaries_after_2_hours:
            print(summary)
            assert summary.window_size == 300, "Expected 300s window after 2 hours"

            assert summary.statistics.count == num_summaries * messages_per_minute, (
                f"Expected {num_summaries * messages_per_minute} measurements in 5-min window, got {summary.statistics.count}"
            )


@pytest.mark.asyncio
async def test_data_cleanup(client, fast_aiosleep):
    """
    Test that measurements are no longer queryable after 4 hours:
    1. Post 2 measurements
    2. Verify they can be queried
    3. Advance time by 4 hours
    4. Verify they can no longer be queried
    """
    import time_machine
    from datetime import datetime, timezone, timedelta
    import asyncio

    sensor_id = 1

    # Start at a fixed time
    start_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    with time_machine.travel(start_time, tick=True) as traveller:
        current_timestamp = int(time.time())

        # Post 2 measurements
        measurement_1 = {
            "sensor_id": sensor_id,
            "timestamp": datetime.fromtimestamp(current_timestamp, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "temperature": 25.0,
            "conductivity": 1.2,
        }
        measurement_2 = {
            "sensor_id": sensor_id,
            "timestamp": datetime.fromtimestamp(current_timestamp + 10, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "temperature": 26.0,
            "conductivity": 1.3,
        }

        response_1 = client.post("/measurements", json=measurement_1)
        assert response_1.status_code == 200, "Failed to post first measurement"

        response_2 = client.post("/measurements", json=measurement_2)
        assert response_2.status_code == 200, "Failed to post second measurement"

        # Verify measurements can be queried immediately
        query_start = current_timestamp - 10
        query_end = current_timestamp + 100
        response = client.get(
            f"/raw_measurements?start_time={query_start}&end_time={query_end}"
        )
        assert response.status_code == 200
        response_data = RawMeasurementsResponse(**response.json())

        # Should have 2 measurements
        assert len(response_data.time) == 2, (
            f"Expected 2 measurements, got {len(response_data.time)}"
        )

        # Advance time past deletion threshold
        traveller.shift(timedelta(hours=3.5))
        await asyncio.sleep(0.2)

        # Try to query the same measurements - they should no longer be available
        response_after = client.get(
            f"/raw_measurements?start_time={query_start}&end_time={query_end}"
        )
        assert response_after.status_code == 200
        response_data_after = RawMeasurementsResponse(**response_after.json())

        # Should have 0 measurements now
        assert len(response_data_after.time) == 0, (
            f"Expected 0 measurements after 4 hours, got {len(response_data_after.time)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
