"""
Script to continuously post measurements to the FastAPI server.
Posts 2 measurements every 30 seconds from different sensors.
"""

import time
import requests
from datetime import datetime, timezone
import sys

# Configuration
HOST = "localhost"
PORT = 8000
INTERVAL_SECONDS = 30


def post_measurements(host: str, port: int):
    """Post measurements from 2 different sensors to the server."""
    url = f"http://{host}:{port}/measurements"

    current_time = datetime.now(timezone.utc)

    # Sensor 1: temperature = current minute
    # Sensor 2: temperature = current minute + 100 (clearly different)
    base_temp = float(current_time.minute)
    conductivity = float(current_time.second) / 100.0

    measurements = [
        {
            "sensor_id": 1,
            "timestamp": current_time.isoformat().replace("+00:00", "Z"),
            "temperature": base_temp,
            "conductivity": conductivity,
        },
        {
            "sensor_id": 2,
            "timestamp": current_time.isoformat().replace("+00:00", "Z"),
            "temperature": base_temp + 100.0,
            "conductivity": conductivity,
        },
    ]

    for measurement in measurements:
        try:
            response = requests.post(url, json=measurement, timeout=5)
            response.raise_for_status()

            print(
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] Posted: "
                f"sensor_id={measurement['sensor_id']}, "
                f"temp={measurement['temperature']:.1f}, "
                f"cond={measurement['conductivity']:.3f} - "
                f"Status: {response.status_code}"
            )

        except requests.exceptions.ConnectionError:
            print(
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Could not connect to {host}:{port}"
            )
        except requests.exceptions.Timeout:
            print(
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Request timed out"
            )
        except requests.exceptions.HTTPError:
            print(
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: HTTP {response.status_code} - {response.text}"
            )
        except Exception as e:
            print(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: {str(e)}")


def main():
    """Main loop to continuously post measurements."""
    print("Starting measurement poster...")
    print(f"Target: http://{HOST}:{PORT}/measurements")
    print("Posting from 2 sensors (sensor_id=1 and sensor_id=2)")
    print("Sensor 1: temp = current_minute")
    print("Sensor 2: temp = current_minute + 100")
    print(f"Interval: {INTERVAL_SECONDS} seconds")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            post_measurements(HOST, PORT)
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n\nStopping measurement poster...")
        sys.exit(0)


if __name__ == "__main__":
    # Allow command-line overrides
    if len(sys.argv) > 1:
        HOST = sys.argv[1]
    if len(sys.argv) > 2:
        PORT = int(sys.argv[2])

    main()
