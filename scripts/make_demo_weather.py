"""Generate deterministic SYNTHETIC weather; never use as a site forecast."""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate(path, year=2025, interval_minutes=60):
    if interval_minutes <= 0 or 60 % interval_minutes:
        raise ValueError("interval_minutes must divide 60")
    start = datetime(year, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    end = datetime(year + 1, 1, 1, tzinfo=start.tzinfo)
    step = timedelta(minutes=interval_minutes)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "ghi", "dni", "dhi", "temp_air", "wind_speed"])
        while start < end:
            center = start + step / 2
            day = center.timetuple().tm_yday
            decl = math.radians(23.45 * math.sin(2 * math.pi * (284 + day) / 365))
            lat = math.radians(23.13)
            solar_hour = center.hour + center.minute / 60 + (113.26 - 120) / 15
            hour_angle = math.radians(15 * (solar_hour - 12))
            sine = max(0, math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle))
            dni = 650.0 if sine > 0 else 0.0
            dhi = 100.0 * sine
            writer.writerow([start.isoformat(), round(dni * sine + dhi, 4), dni, round(dhi, 4), 25.0, 1.5])
            start += step


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--interval-minutes", type=int, default=60)
    args = parser.parse_args()
    generate(args.output, args.year, args.interval_minutes)
    print(f"Synthetic weather written: {args.output}")
