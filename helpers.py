import asyncio
import time
import json
import aiosqlite
import polars as pl

from contextlib import asynccontextmanager
from timer import AsyncPeriodicTimer


@asynccontextmanager
async def db_connection(DB_PATH: str):
    conn = await aiosqlite.connect(DB_PATH, timeout=0.05)
    try:
        yield conn
        await conn.commit()  # this should be no-op w/ default autocommit behavior
    finally:
        await conn.close()


async def calculate_period_statistics(window_size_s: int, db_path: str) -> None:
    """
    Coroutine that runs periodically to calculate mean, median, min, max of
    temperature and conductivity, plus count of measurements over the specified window size.
    Results are stored in the 'summaries' table per sensor.
    window_size: in seconds (e.g., 60 for 1 minute, 300 for 5 minutes)

    Strongly recommended that this some integer multiple or divisor of 60 seconds, so
    that that this happens at predictable times.
    """

    # Wait until 1 second past the minute boundary, to help with determinism.
    await asyncio.sleep(61 - (time.time() % 60))

    while True:
        async with AsyncPeriodicTimer(
            period_s=window_size_s
        ):  # Wait until we have a full window of data
            # We can only summarize the previous period, since the current_period's data is still coming in.
            current_time = int(time.time())
            previous_period_end = (current_time // window_size_s) * window_size_s
            previous_period_start = previous_period_end - window_size_s

            # Fetch data in previous period for all sensors
            async with db_connection(db_path) as db_conn:
                try:
                    cursor = await db_conn.execute(
                        """
                        SELECT sensor_id, temperature, conductivity
                        FROM raw_measurements
                        WHERE time >= ? AND time < ?
                        """,
                        (previous_period_start, previous_period_end),
                    )
                    results = await cursor.fetchall()
                except Exception as e:
                    print(
                        f"Error fetching measurements for window_size={window_size_s}: {e}"
                    )
                    await db_conn.rollback()

            if not results:
                print(f"No measurements found for period ending {previous_period_end}")
                continue

            # Convert to df, calculate one row of stats per sensor
            df = pl.DataFrame(
                results,
                schema=["sensor_id", "temperature", "conductivity"],
                orient="row",
            )
            stats_df = df.group_by("sensor_id").agg(
                [
                    pl.len().alias("count"),
                    pl.col("temperature").mean().alias("temp_mean"),
                    pl.col("temperature").median().alias("temp_median"),
                    pl.col("temperature").min().alias("temp_min"),
                    pl.col("temperature").max().alias("temp_max"),
                    pl.col("conductivity").mean().alias("cond_mean"),
                    pl.col("conductivity").median().alias("cond_median"),
                    pl.col("conductivity").min().alias("cond_min"),
                    pl.col("conductivity").max().alias("cond_max"),
                ]
            )

            # Prepare all inserts for batch execution
            insert_data = []
            for row in stats_df.iter_rows(named=True):
                stats = {
                    "count": row["count"],
                    "temperature": {
                        "mean": row["temp_mean"],
                        "median": row["temp_median"],
                        "min": row["temp_min"],
                        "max": row["temp_max"],
                    },
                    "conductivity": {
                        "mean": row["cond_mean"],
                        "median": row["cond_median"],
                        "min": row["cond_min"],
                        "max": row["cond_max"],
                    },
                }
                insert_data.append(
                    (
                        row["sensor_id"],
                        previous_period_end,
                        window_size_s,
                        json.dumps(stats),
                    )
                )

            # Print summary of what will be inserted
            sensor_ids = [row["sensor_id"] for row in stats_df.iter_rows(named=True)]
            print(
                f"Calculated stats for period ending {previous_period_end}: sensors {sensor_ids}"
            )

            async with db_connection(db_path) as db_conn:
                try:
                    await db_conn.executemany(
                        "INSERT INTO summaries (sensor_id, time, window_size, statistics) VALUES (?, ?, ?, ?)",
                        insert_data,
                    )
                except Exception as e:
                    print(
                        f"Error inserting statistics for window_size={window_size_s}: {e}"
                    )
                    await db_conn.rollback()


async def cleanup_old_data(db_path: str) -> None:
    """
    Delete old data from the database:
    1) Individual measurements older than 3 hours
    2) 1-minute summaries (window_size_s=60) older than 90 minutes
    """

    # Wait until 1 second past the minute boundary, to help with determinism.
    await asyncio.sleep(61 - (time.time() % 60))

    while True:
        async with AsyncPeriodicTimer(period_s=600):
            current_time = int(time.time())
            three_hours_ago = current_time - (3 * 60 * 60)  # 3 hours in seconds
            ninety_minutes_ago = current_time - (90 * 60)  # 90 minutes in seconds

            async with db_connection(db_path) as db_conn:
                try:  # Delete raw measurements
                    cursor = await db_conn.execute(
                        "DELETE FROM raw_measurements WHERE time < ?",
                        (three_hours_ago,),
                    )
                    measurements_deleted = cursor.rowcount

                    # Delete 1-minute summaries
                    cursor = await db_conn.execute(
                        "DELETE FROM summaries WHERE window_size = 60 AND time < ?",
                        (ninety_minutes_ago,),
                    )
                    summaries_deleted = cursor.rowcount
                except Exception as e:
                    print(f"Error during cleanup: {e}")
                    await db_conn.rollback()
            print(
                f"Cleanup: Deleted {measurements_deleted} measurements and {summaries_deleted} 1-minute summaries"
            )
