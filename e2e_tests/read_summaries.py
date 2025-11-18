"""
Script to continuously read summaries from the FastAPI server.
Queries the /summaries endpoint every minute.
"""

import requests
import sys
import time
from datetime import datetime

# Configuration
HOST = "localhost"
PORT = 8000
INTERVAL_SECONDS = 60


def read_summaries(host: str, port: int):
    """Read all summaries from the server."""
    url = f"http://{host}:{port}/summaries"

    # Query from beginning of time (0) to far future to get all summaries
    params = {
        "start_time": 0,
        "end_time": 2147483647,  # Max 32-bit int (year 2038)
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        summaries = data.get("summaries", [])

        current_time = datetime.now()
        print(
            f"\n[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] Retrieved {len(summaries)} summaries"
        )
        print("=" * 100)

        if not summaries:
            print("No summaries found in database.")
            return

        # Group summaries by window size for clearer display
        summaries_60s = [s for s in summaries if s["window_size"] == 60]
        summaries_300s = [s for s in summaries if s["window_size"] == 300]

        if summaries_60s:
            print(f"\n1-MINUTE SUMMARIES ({len(summaries_60s)} total):")
            print("-" * 100)
            display_summaries(summaries_60s, limit=5)

        if summaries_300s:
            print(f"\n5-MINUTE SUMMARIES ({len(summaries_300s)} total):")
            print("-" * 100)
            display_summaries(summaries_300s, limit=5)

        print("=" * 100)

    except requests.exceptions.ConnectionError:
        current_time = datetime.now()
        print(
            f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Could not connect to {host}:{port}"
        )
    except requests.exceptions.Timeout:
        current_time = datetime.now()
        print(
            f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Request timed out"
        )
    except requests.exceptions.HTTPError:
        current_time = datetime.now()
        print(
            f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: HTTP {response.status_code} - {response.text}"
        )
    except Exception as e:
        current_time = datetime.now()
        print(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: {str(e)}")


def display_summaries(summaries: list, limit: int = None):
    """Display summaries in a formatted table."""
    # Show most recent summaries first
    summaries_sorted = sorted(summaries, key=lambda x: x["time"], reverse=True)

    if limit:
        summaries_sorted = summaries_sorted[:limit]
        if len(summaries) > limit:
            print(f"(Showing {limit} most recent out of {len(summaries)} total)")

    for summary in summaries_sorted:
        sensor_id = summary["sensor_id"]
        timestamp = summary["time"]
        window_size = summary["window_size"]
        stats = summary["statistics"]

        # Convert timestamp to readable format
        dt = datetime.fromtimestamp(timestamp)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        print(f"\nSensor {sensor_id} | {time_str} | Window: {window_size}s")

        if stats:
            temp_stats = stats["temperature"]
            cond_stats = stats["conductivity"]
            count = stats["count"]

            print(f"  Count: {count} measurements")
            print(
                f"  Temperature:  mean={temp_stats['mean']:6.2f}, "
                f"median={temp_stats['median']:6.2f}, "
                f"min={temp_stats['min']:6.2f}, "
                f"max={temp_stats['max']:6.2f}"
            )
            print(
                f"  Conductivity: mean={cond_stats['mean']:6.3f}, "
                f"median={cond_stats['median']:6.3f}, "
                f"min={cond_stats['min']:6.3f}, "
                f"max={cond_stats['max']:6.3f}"
            )
        else:
            print("  No statistics available")


def main():
    """Main loop to continuously read summaries."""
    print("Starting summary reader...")
    print(f"Target: http://{HOST}:{PORT}/summaries")
    print(f"Interval: {INTERVAL_SECONDS} seconds")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            read_summaries(HOST, PORT)
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n\nStopping summary reader...")
        sys.exit(0)


if __name__ == "__main__":
    # Allow command-line overrides
    if len(sys.argv) > 1:
        HOST = sys.argv[1]
    if len(sys.argv) > 2:
        PORT = int(sys.argv[2])

    main()
