"""Optional pvlib backend; complete one-year irradiance input."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core import InputError, keys, number, text


def validate_spec(spec):
    keys(spec, {"mode", "source", "weather_csv", "location", "system", "time"},
         {"mode", "source", "weather_csv", "location", "system", "time"}, "weather yield")
    text(spec["weather_csv"], "weather_csv")
    loc, system, time = spec["location"], spec["system"], spec["time"]
    keys(loc, {"latitude", "longitude", "altitude_m", "timezone"}, {"latitude", "longitude", "altitude_m", "timezone"}, "location")
    number(loc["latitude"], "latitude", -90, 90)
    number(loc["longitude"], "longitude", -180, 180)
    number(loc["altitude_m"], "altitude", -500, 10000)
    try:
        ZoneInfo(text(loc["timezone"], "timezone"))
    except ZoneInfoNotFoundError as exc:
        raise InputError("unknown timezone; on Windows install tzdata") from exc
    fields = {"tilt_deg", "azimuth_deg", "dc_ac_ratio", "gamma_pdc", "system_loss_pct", "inverter_efficiency", "transposition", "aoi", "temperature_model", "temperature_parameters", "albedo"}
    keys(system, fields, fields, "system")
    number(system["tilt_deg"], "tilt_deg", 0, 90)
    number(system["azimuth_deg"], "azimuth_deg", 0, 360)
    number(system["dc_ac_ratio"], "dc_ac_ratio", positive=True)
    number(system["gamma_pdc"], "gamma_pdc", -0.02, 0.02)
    number(system["system_loss_pct"], "system_loss_pct", 0, 100)
    number(system["inverter_efficiency"], "inverter_efficiency", 0, 1, positive=True)
    number(system["albedo"], "albedo", 0, 1)
    if system["transposition"] not in {"isotropic", "haydavies", "perez"}:
        raise InputError("transposition supports isotropic, haydavies, perez")
    if system["aoi"] not in {"physical", "no_loss"}:
        raise InputError("aoi supports physical or no_loss")
    params = system["temperature_parameters"]
    if system["temperature_model"] == "faiman":
        keys(params, {"u0", "u1"}, {"u0", "u1"}, "faiman parameters")
        number(params["u0"], "u0", positive=True)
        number(params["u1"], "u1")
    elif system["temperature_model"] == "pvsyst":
        keys(params, {"u_c", "u_v", "module_efficiency", "alpha_absorption"}, {"u_c", "u_v", "module_efficiency", "alpha_absorption"}, "pvsyst parameters")
        number(params["u_c"], "u_c", positive=True)
        number(params["u_v"], "u_v")
        number(params["module_efficiency"], "module_efficiency", 0, 1)
        number(params["alpha_absorption"], "alpha_absorption", 0, 1)
    else:
        raise InputError("temperature_model supports faiman or pvsyst")
    keys(time, {"year", "interval_minutes", "timestamp_position", "timezone"}, {"year", "interval_minutes", "timestamp_position", "timezone"}, "time")
    if type(time["year"]) is not int or not 1900 <= time["year"] <= 2200:
        raise InputError("time.year must be an integer in [1900, 2200]")
    if type(time["interval_minutes"]) is not int or time["interval_minutes"] <= 0 or 60 % time["interval_minutes"]:
        raise InputError("interval_minutes must be a positive integer divisor of 60")
    if time["timestamp_position"] not in {"start", "center", "end"}:
        raise InputError("timestamp_position must be start, center or end")
    try:
        ZoneInfo(text(time["timezone"], "time.timezone"))
    except ZoneInfoNotFoundError as exc:
        raise InputError("unknown time.timezone") from exc


def compute(spec, path):
    validate_spec(spec)
    try:
        import numpy as np
        import pandas as pd
        import pvlib
    except ImportError as exc:
        raise InputError('weather mode requires: pip install ".[weather]"') from exc
    frame = pd.read_csv(path)
    columns = {"time", "ghi", "dni", "dhi", "temp_air", "wind_speed"}
    if not columns <= set(frame):
        raise InputError(f"weather missing columns: {sorted(columns - set(frame))}")
    loc, system, times = spec["location"], spec["system"], spec["time"]
    stamps = []
    for raw in frame["time"]:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputError(f"invalid weather timestamp: {raw}") from exc
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise InputError("weather timestamps require explicit UTC offset; naive timestamps are rejected")
        stamps.append(dt)
    time_zone = times["timezone"]
    index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True)).tz_convert(time_zone)
    duration = pd.Timedelta(minutes=times["interval_minutes"])
    shift = {"start": 0, "center": 0.5, "end": 1}[times["timestamp_position"]]
    starts = index - shift * duration
    year = times["year"]
    expected = pd.date_range(f"{year}-01-01", f"{year+1}-01-01", freq=duration, inclusive="left", tz=time_zone)
    if not starts.equals(expected):
        raise InputError("weather must cover exactly one declared local calendar year, ordered, without duplicates or gaps")
    frame = frame.drop(columns="time").set_axis(starts + duration / 2)
    for col in columns - {"time"}:
        try:
            frame[col] = pd.to_numeric(frame[col], errors="raise")
        except (ValueError, TypeError) as exc:
            raise InputError(f"weather.{col} must be numeric") from exc
        if not np.isfinite(frame[col]).all():
            raise InputError(f"weather.{col} contains missing or nonfinite values")
        if col != "temp_air" and (frame[col] < 0).any():
            raise InputError(f"weather.{col} must be nonnegative")
    if not frame.temp_air.between(-100, 80).all():
        raise InputError("weather.temp_air must be in Celsius [-100,80]")
    loss_slots = dict.fromkeys(["soiling", "shading", "snow", "mismatch", "wiring", "connections", "lid", "nameplate_rating", "age", "availability"], 0.0)
    loss_slots["soiling"] = float(system["system_loss_pct"])
    eta = float(system["inverter_efficiency"])
    # 1 kWp DC reference. Inverter pdc0 is its DC input limit, not array rating.
    inverter_pdc0 = 1000.0 / float(system["dc_ac_ratio"]) / eta
    pv_system = pvlib.pvsystem.PVSystem(
        surface_tilt=float(system["tilt_deg"]), surface_azimuth=float(system["azimuth_deg"]),
        albedo=float(system["albedo"]), module_parameters={"pdc0": 1000.0, "gamma_pdc": float(system["gamma_pdc"])},
        inverter_parameters={"pdc0": inverter_pdc0, "eta_inv_nom": eta},
        temperature_model_parameters={k: float(v) for k, v in system["temperature_parameters"].items()}, losses_parameters=loss_slots)
    location = pvlib.location.Location(float(loc["latitude"]), float(loc["longitude"]), tz=loc["timezone"], altitude=float(loc["altitude_m"]))
    chain = pvlib.modelchain.ModelChain(pv_system, location, transposition_model=system["transposition"],
        aoi_model=system["aoi"], spectral_model="no_loss", temperature_model=system["temperature_model"],
        dc_model="pvwatts", ac_model="pvwatts", losses_model="pvwatts")
    chain.run_model(frame)
    power = chain.results.ac.clip(lower=0)
    if not np.isfinite(power).all():
        raise InputError("pvlib produced nonfinite AC power; inspect inputs and selected model")
    interval_energy = power * (times["interval_minutes"] / 60) / 1000
    profile = [{"time": start.isoformat(), "ac_w_per_kwp": float(p), "energy_kwh_per_kwp": float(e)}
               for start, p, e in zip(starts, power, interval_energy)]
    return {"kwh_per_kwp": float(interval_energy.sum()),
            "included_effects": ["orientation", "temperature", "inverter", "system_losses", "aoi"],
            "source": spec["source"], "pvlib_version": pvlib.__version__, "year": year,
            "interval_minutes": times["interval_minutes"], "intervals": len(profile),
            "time_zone": time_zone}, profile
