"""Explicit PVGIS TMY acquisition with verified reusable local snapshots."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .core import InputError, keys, number, sha256, text, unique_json
from .weather import validate_spec as validate_weather, compute as compute_weather


PVGIS_KEYS = {"api_url", "start_year", "end_year", "use_horizon", "user_horizon_deg",
              "expected_radiation_database", "timeout_seconds", "cache_csv",
              "cache_metadata_json", "cache_policy", "roll_utc_offset_hours", "output_format"}
WEATHER_KEYS = {"mode", "source", "weather_csv", "location", "system", "time"}
WEATHER_FIELDS = ["time", "ghi", "dni", "dhi", "temp_air", "wind_speed"]


def validate_spec(spec):
    keys(spec, {"mode", "source", "location", "system", "time", "pvgis"},
         {"mode", "source", "location", "system", "time", "pvgis"}, "PVGIS TMY yield")
    p = spec["pvgis"]
    keys(p, PVGIS_KEYS, PVGIS_KEYS, "pvgis")
    uri = urlparse(text(p["api_url"], "pvgis.api_url"))
    if uri.scheme != "https" or not uri.netloc or uri.query or uri.fragment or not p["api_url"].endswith("/"):
        raise InputError("pvgis.api_url must be an HTTPS base URL ending in /, without query or fragment")
    for field in ("start_year", "end_year"):
        if type(p[field]) is not int or not 1900 <= p[field] <= 2200:
            raise InputError(f"pvgis.{field} must be an integer year")
    if p["end_year"] - p["start_year"] < 10:
        raise InputError("PVGIS TMY selection needs at least a 10-year span")
    if type(p["use_horizon"]) is not bool:
        raise InputError("pvgis.use_horizon must be boolean")
    if p["user_horizon_deg"] is not None:
        if not p["use_horizon"] or not isinstance(p["user_horizon_deg"], list) or len(p["user_horizon_deg"]) < 2:
            raise InputError("user_horizon_deg requires use_horizon and at least two equally spaced azimuth samples")
        for angle in p["user_horizon_deg"]:
            number(angle, "user_horizon_deg", 0, 90)
    if p["expected_radiation_database"] is not None:
        text(p["expected_radiation_database"], "expected_radiation_database")
    number(p["timeout_seconds"], "timeout_seconds", 1, 300, positive=True)
    if p["cache_policy"] not in {"cache_only", "fetch_if_missing", "refresh"}:
        raise InputError("cache_policy must be cache_only, fetch_if_missing or refresh")
    for field in ("cache_csv", "cache_metadata_json"):
        text(p[field], f"pvgis.{field}")
    if p["cache_csv"] == p["cache_metadata_json"]:
        raise InputError("PVGIS weather and metadata cache paths must differ")
    if type(p["roll_utc_offset_hours"]) is not int or p["roll_utc_offset_hours"] != 0:
        raise InputError("TMY entry currently supports explicit UTC offset 0 only")
    if p["output_format"] != "json":
        raise InputError("TMY entry requires JSON output so PVGIS metadata can be retained")
    t = spec["time"]
    if t.get("timezone") != "UTC" or t.get("interval_minutes") != 60 or t.get("timestamp_position") != "start":
        raise InputError("TMY time must explicitly set UTC, 60 minutes and start timestamp")
    if t.get("year") in range(1900, 2201) and __import__("calendar").isleap(t["year"]):
        raise InputError("PVGIS TMY has 8760 rows; choose a non-leap reference year")
    validate_weather({**{k: spec[k] for k in ("source", "location", "system", "time")},
                      "mode": "weather", "weather_csv": p["cache_csv"]})


def request_parameters(spec):
    p, loc = spec["pvgis"], spec["location"]
    return {"latitude": float(loc["latitude"]), "longitude": float(loc["longitude"]),
            "outputformat": p["output_format"], "usehorizon": p["use_horizon"],
            "userhorizon": p["user_horizon_deg"], "startyear": p["start_year"],
            "endyear": p["end_year"], "map_variables": True,
            "url": p["api_url"], "timeout": float(p["timeout_seconds"]),
            "roll_utc_offset": p["roll_utc_offset_hours"], "coerce_year": spec["time"]["year"]}


def signature(parameters):
    return hashlib.sha256(json.dumps(parameters, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _paths(spec, base):
    p = spec["pvgis"]
    csv_path = (base / p["cache_csv"]).resolve()
    meta_path = (base / p["cache_metadata_json"]).resolve()
    if csv_path == meta_path:
        raise InputError("cache paths resolve to the same file")
    return csv_path, meta_path


def _actual_database(meta):
    inputs = meta.get("inputs", {})
    meteo = inputs.get("meteo_data", {})
    return meteo.get("radiation_db") or meteo.get("radiation_database")


def _check_database(spec, meta):
    actual = _actual_database(meta)
    if not actual:
        raise InputError("PVGIS response does not identify its radiation database")
    expected = spec["pvgis"]["expected_radiation_database"]
    if expected is not None and actual != expected:
        raise InputError(f"PVGIS selected {actual!r}, expected {expected!r}")
    offset = meta.get("inputs", {}).get("location", {}).get("irradiance_time_offset")
    if offset is None or abs(number(offset, "PVGIS irradiance_time_offset", 0, 1) - 0.5) > 1e-6:
        raise InputError("PVGIS irradiance time offset is not 0.5 h; this hourly-mean TMY path cannot safely use it")
    return actual


def _load_cache(spec, base):
    csv_path, meta_path = _paths(spec, base)
    if not csv_path.is_file() or not meta_path.is_file():
        raise InputError("PVGIS cache is missing; choose fetch_if_missing or refresh, or restore both files")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_json)
    except (ValueError, OSError) as exc:
        raise InputError(f"invalid PVGIS metadata cache: {exc}") from exc
    if meta.get("request_signature") != signature(request_parameters(spec)):
        raise InputError("PVGIS cache request differs from current configuration; use refresh")
    if meta.get("weather_sha256") != sha256(csv_path):
        raise InputError("PVGIS weather cache hash differs from metadata")
    _check_database(spec, meta.get("pvgis_metadata", {}))
    return csv_path, meta_path, meta


def _fetch(spec, base):
    try:
        import pandas as pd
        import pvlib
        import requests
    except ImportError as exc:
        raise InputError('PVGIS mode requires: pip install ".[weather]"') from exc
    params = request_parameters(spec)
    try:
        frame, service_meta = pvlib.iotools.get_pvgis_tmy(**params)
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise InputError(f"PVGIS TMY request failed: {exc}") from exc
    actual = _check_database(spec, service_meta)
    if not isinstance(frame, pd.DataFrame) or not set(WEATHER_FIELDS[1:]) <= set(frame):
        raise InputError("PVGIS response is missing mapped GHI, DNI, DHI, temperature or wind fields")
    csv_path, meta_path = _paths(spec, base)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.parent != meta_path.parent:
        raise InputError("PVGIS weather and metadata cache must share one directory")
    temporary = csv_path.with_name(csv_path.name + f".{os.getpid()}.pending")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(WEATHER_FIELDS)
            for stamp, row in frame.iterrows():
                writer.writerow([stamp.isoformat(), *(row[field] for field in WEATHER_FIELDS[1:])])
        weather_spec = {**{k: spec[k] for k in ("source", "location", "system", "time")},
                        "mode": "weather", "weather_csv": str(temporary)}
        compute_weather(weather_spec, temporary)
        meta = {"request_parameters": params, "request_signature": signature(params),
                "weather_sha256": sha256(temporary), "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                "pvgis_metadata": service_meta, "radiation_database": actual, "pvlib_version": pvlib.__version__}
        meta_pending = meta_path.with_name(meta_path.name + f".{os.getpid()}.pending")
        meta_pending.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
        os.replace(temporary, csv_path)
        os.replace(meta_pending, meta_path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve(spec, base):
    validate_spec(spec)
    policy = spec["pvgis"]["cache_policy"]
    csv_path, meta_path = _paths(spec, base)
    if policy == "refresh" or (policy == "fetch_if_missing" and not (csv_path.exists() or meta_path.exists())):
        _fetch(spec, base)
    csv_path, meta_path, meta = _load_cache(spec, base)
    weather_spec = {**{k: spec[k] for k in ("source", "location", "system", "time")},
                    "mode": "weather", "weather_csv": str(csv_path)}
    values, profile = compute_weather(weather_spec, csv_path)
    values["pvgis"] = {"api_url": spec["pvgis"]["api_url"], "radiation_database": meta["radiation_database"],
                       "retrieved_utc": meta["retrieved_utc"], "request_signature": meta["request_signature"],
                       "months_selected": meta["pvgis_metadata"].get("months_selected")}
    if spec["pvgis"]["use_horizon"]:
        values["included_effects"].append("terrain_horizon")
    return values, profile, [csv_path, meta_path]
