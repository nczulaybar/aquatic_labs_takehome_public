from fastapi import FastAPI, Query, HTTPException, Depends
from contextlib import asynccontextmanager
from datetime import datetime
import aiosqlite
import json
import asyncio
import time

from data_models import Measurement, SummariesResponse, RawMeasurementsResponse
from helpers import calculate_period_statistics, cleanup_old_data


def create_app(DB_PATH="aquatic_data.db") -> FastAPI:
    """
    FastAPI model is to create an app and register functions to it.

    Since registered methods aren't actually app members, some server state
    (running side-tasks) weirdly lives in a yielded setup-teardown function.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: Create database connection and verify tables
        db_conn = await aiosqlite.connect(DB_PATH)

        # Create raw_measurements table if it doesn't exist
        await db_conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_measurements (
                sensor_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                temperature REAL,
                conductivity REAL,
                PRIMARY KEY (sensor_id, time)
            )
        """)

        # Create summaries table if it doesn't exist
        await db_conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                sensor_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                window_size INTEGER NOT NULL,
                statistics JSON,
                PRIMARY KEY (sensor_id, time, window_size)
            )
        """)

        await db_conn.commit()
        print(f"Database initialized at {DB_PATH}")
        print("Tables verified: raw_measurements, summaries")

        await db_conn.close()

        # Start summary statistics coroutine
        summarise_every_minute = asyncio.create_task(
            calculate_period_statistics(window_size_s=60, db_path=DB_PATH)
        )
        summarise_every_five_minutes = asyncio.create_task(
            calculate_period_statistics(window_size_s=300, db_path=DB_PATH)
        )
        cleanup_data = asyncio.create_task(cleanup_old_data(db_path=DB_PATH))
        print("Started background stats coroutines")

        yield  # In fastapi, everything below is shutdown code.

        # Clean up active coroutines
        tasks = [
            summarise_every_minute,
            summarise_every_five_minutes,
            cleanup_data,
        ]
        for t in tasks:
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    app = FastAPI(lifespan=lifespan)

    async def get_db():
        db_conn = await aiosqlite.connect(DB_PATH)
        try:
            yield db_conn  # give to the endpoint
        finally:
            await db_conn.close()  # teardown (always runs)

    @app.get("/raw_measurements", response_model=RawMeasurementsResponse)
    async def get_raw_measurements(
        start_time: int = Query(..., description="Start time (unix timestamp)"),
        end_time: int = Query(..., description="End time (unix timestamp)"),
        sensor_id: int = Query(None, description="Optional sensor ID filter"),
        db_conn: aiosqlite.Connection = Depends(get_db),
    ):
        """
        Retrieves raw sensor measurements between start_time and end_time.

        This normally returns data for all sensors, but a single sensor can optionally be
        specified to filter results.
        """

        # Build query based on whether sensor_id filter is provided
        query = """
            SELECT sensor_id, time, temperature, conductivity
            FROM raw_measurements
            WHERE time >= ? AND time <= ?
        """
        params = [start_time, end_time]

        if sensor_id is not None:
            query += " AND sensor_id = ?"
            params.append(sensor_id)

        query += " ORDER BY time LIMIT 10000"

        cursor = await db_conn.execute(query, params)
        results = await cursor.fetchall()

        # Transform to struct of arrays, to make this easier to work with downstream.
        if not results:
            sensor_ids = times = temps = conductivities = []
        else:
            sensor_ids, times, temps, conductivities = zip(*results)

        measurements = {
            "sensor_id": list(sensor_ids),
            "time": list(times),
            "temperature": list(temps),
            "conductivity": list(conductivities),
        }

        return measurements

    @app.get("/summaries", response_model=SummariesResponse)
    async def get_summaries(
        start_time: int = Query(..., description="Start time (unix timestamp)"),
        end_time: int = Query(..., description="End time (unix timestamp)"),
        sensor_id: int = Query(None, description="Optional sensor ID filter"),
        db_conn: aiosqlite.Connection = Depends(get_db),
    ):
        """
        Gets mean, median, min, max of temperature and conductivity for the windows between
        start and end time.

        A window's time is the time when a window ends (i.e., after the last measurement),
        not the time the window opens.

        This normally returns data for all sensors, but a single sensor can optionally be
        specified to filter results.
        """

        current_time = int(time.time())
        one_hour_ago = current_time - 3600

        # Single query: 1-minute summaries for recent data, 5-minute for data older than an hour
        query = """
            SELECT sensor_id, time, window_size, statistics
            FROM summaries
            WHERE time >= ? AND time <= ?
            AND (
                (window_size = 60 AND time >= ?) OR
                (window_size = 300 AND time < ?)
            )
        """
        params = [start_time, end_time, one_hour_ago, one_hour_ago]

        if sensor_id is not None:
            query += " AND sensor_id = ?"
            params.append(sensor_id)

        query += " ORDER BY time"

        cursor = await db_conn.execute(query, params)
        results = await cursor.fetchall()

        summaries = [
            {
                "sensor_id": row[0],
                "time": row[1],
                "window_size": row[2],
                "statistics": json.loads(row[3]) if row[3] else None,
            }
            for row in results
        ]

        return {"summaries": summaries}

    @app.post("/measurements")
    async def set_measurements(
        measurement: Measurement, db_conn: aiosqlite.Connection = Depends(get_db)
    ):
        """
        Writes a single measurement to the database. Bulk writing of multiple
        measurements in a single REST call is not supported.
        """

        # Parse ISO timestamp to Unix timestamp
        try:
            timestamp_str = measurement.timestamp
            dt = datetime.fromisoformat(timestamp_str)
            unix_time = int(dt.timestamp())
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timestamp format. Expected ISO format: {str(e)}",
            )

        try:
            # Insert single measurement
            await db_conn.execute(
                "INSERT INTO raw_measurements (sensor_id, time, temperature, conductivity) VALUES (?, ?, ?, ?)",
                (
                    measurement.sensor_id,
                    unix_time,
                    measurement.temperature,
                    measurement.conductivity,
                ),
            )
            await db_conn.commit()
        except aiosqlite.IntegrityError as e:
            await db_conn.rollback()
            # Check if it's a primary key conflict. Sqlite seems to call it a UNIQUE conflict.
            if "PRIMARY KEY constraint failed" in str(
                e
            ) or "UNIQUE constraint failed" in str(e):
                raise HTTPException(
                    status_code=409,
                    detail=f"Conflict: Measurement for sensor {measurement.sensor_id} at timestamp {measurement.timestamp} already exists",
                )
            raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")

        return {"message": f"Inserted measurement for sensor {measurement.sensor_id}"}

    return app


if __name__ == "__main__":
    app = create_app("aquatic_data.db")
