"""Portable CLI and reproducible output bundle."""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .core import InputError, aggregate, buildings, read_config, resolve_yields, sha256, unique_json


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def csv_writer(path, rows):
    it = iter(rows)
    first = next(it, None)
    if first is None:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(first))
        writer.writeheader()
        writer.writerow(first)
        writer.writerows(it)


def prepare(config):
    config = Path(config).resolve()
    digest = sha256(config)
    cfg = read_config(config)
    if sha256(config) != digest:
        raise InputError("config changed during read")
    y, profiles, inputs = resolve_yields(cfg, config.parent)
    bpath = (config.parent / cfg["buildings_csv"]).resolve()
    inputs.extend([{"path": str(config), "sha256": digest}, {"path": str(bpath), "sha256": sha256(bpath)}])
    return cfg, y, profiles, inputs, bpath


def run_yield(config, output):
    """Model a reference PV system without requiring any building inventory."""
    config, output = Path(config).resolve(), Path(output).resolve()
    if output.exists():
        raise InputError(f"output already exists; choose a new run directory: {output}")
    digest = sha256(config)
    try:
        wrapper = json.loads(config.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_json)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON: {exc}") from exc
    if not isinstance(wrapper, dict) or set(wrapper) - {"schema_version", "mode", "source", "location", "system", "time", "pvgis", "weather_csv"}:
        raise InputError("yield config has unsupported fields")
    if type(wrapper.get("schema_version")) is not int or wrapper["schema_version"] != 1:
        raise InputError("yield schema_version must be integer 1")
    spec = {k: v for k, v in wrapper.items() if k != "schema_version"}
    if spec.get("mode") == "pvgis_tmy":
        from .pvgis import resolve
        values, profile, paths = resolve(spec, config.parent)
    elif spec.get("mode") == "weather":
        from .weather import compute, validate_spec
        validate_spec(spec)
        path = (config.parent / spec["weather_csv"]).resolve()
        before = sha256(path)
        values, profile = compute(spec, path)
        if sha256(path) != before:
            raise InputError(f"weather input changed during read: {path}")
        paths = [path]
    else:
        raise InputError("yield command supports pvgis_tmy or weather")
    inputs = [{"path": str(config), "sha256": digest}] + [{"path": str(p), "sha256": sha256(p)} for p in paths]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pv-yield-", dir=output.parent) as temporary:
        stage = Path(temporary)
        csv_writer(stage / "yield_profile.csv", profile)
        months = {}
        for step in profile:
            key = step["time"][:7]
            months[key] = months.get(key, 0.0) + step["energy_kwh_per_kwp"]
        csv_writer(stage / "monthly_yield.csv", ({"month": k, "kwh_per_kwp": v} for k, v in sorted(months.items())))
        snapshot_files = []
        for index, path in enumerate(paths, 1):
            destination = f"input_{index}{path.suffix}"
            shutil.copy2(path, stage / destination)
            snapshot_files.append(destination)
        dump(stage / "summary.json", {"schema_version": 1, "mode": spec["mode"],
             "annual_yield_kwh_per_kwp": values["kwh_per_kwp"], "resolved_yield": values,
             "input_snapshots": snapshot_files,
             "definition": "annual AC energy per 1 kWp DC reference system; building area and capacity not applied"})
        dump(stage / "config.snapshot.json", wrapper)
        if any(sha256(r["path"]) != r["sha256"] for r in inputs):
            raise InputError("input changed during yield calculation")
        source_root = Path(__file__).parent
        dump(stage / "manifest.json", {"version": __version__, "python": platform.python_version(),
            "created_utc": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
            "implementation_sha256": {p.name: sha256(p) for p in sorted(source_root.glob("*.py"))},
            "outputs_sha256": {p.name: sha256(p) for p in sorted(stage.iterdir()) if p.is_file()}})
        if output.exists():
            raise InputError("output appeared during run; refusing to overwrite")
        os.rename(stage, output)
    return values


def run(config, output):
    output = Path(output).resolve()
    if output.exists():
        raise InputError(f"output already exists; choose a new run directory: {output}")
    cfg, yields, profiles, inputs, bpath = prepare(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pv-run-", dir=output.parent) as temporary:
        stage = Path(temporary)
        # Stream building rows into CSV and aggregation; do not retain city-wide rows.
        def captured_rows():
            with (stage / "buildings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = None
                for row in buildings(cfg, bpath, yields):
                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    yield row
        groups = aggregate(captured_rows())
        for record in inputs:
            if sha256(record["path"]) != record["sha256"]:
                raise InputError(f"input changed during run: {record['path']}")
        csv_writer(stage / "groups.csv", groups)
        scopes = {}
        for key, label in cfg["scope_labels"].items():
            selected = [g for g in groups if g["scope"] == key]
            sums = {field: sum(g.get(field, 0) for g in selected) for field in
                    ("building_count", "module_area_m2", "capacity_kwp", "generation_kwh")}
            if "carbon" in cfg:
                sums["operational_avoided_co2_kg"] = sum(g["operational_avoided_co2_kg"] for g in selected)
            scopes[key] = {"label": label, **sums}
        profile_files = {}
        monthly = []
        for index, (name, profile) in enumerate(profiles.items(), 1):
            filename = f"yield_profile_{index}.csv"
            csv_writer(stage / filename, profile)
            profile_files[name] = filename
            months = {}
            for step in profile:
                key = step["time"][:7]
                months[key] = months.get(key, 0.0) + step["energy_kwh_per_kwp"]
            monthly.extend({"yield_id": name, "month": key, "energy_kwh_per_kwp": value} for key, value in sorted(months.items()))
        if monthly:
            csv_writer(stage / "monthly_yields.csv", monthly)
        pvgis_snapshots = {}
        for index, (name, source) in enumerate(cfg["yields"].items(), 1):
            if source["mode"] != "pvgis_tmy":
                continue
            item = {}
            for key, suffix in (("cache_csv", "weather.csv"), ("cache_metadata_json", "metadata.json")):
                origin = (Path(config).resolve().parent / source["pvgis"][key]).resolve()
                destination = f"pvgis_{index}_{suffix}"
                shutil.copy2(origin, stage / destination)
                item[key] = destination
            pvgis_snapshots[name] = item
        summary = {"schema_version": 1, "name": cfg["name"], "period": "annual", "scopes": scopes,
                   "resolved_yields": yields, "yield_profile_files": profile_files,
                   "pvgis_snapshots": pvgis_snapshots,
                   "carbon": cfg.get("carbon"),
                   "definitions": {"module_area_m2": "effective module surface area, not automatically footprint area",
                                   "capacity_kwp": "DC nameplate capacity", "generation_kwh": "annual AC energy after configured external corrections"}}
        dump(stage / "summary.json", summary)
        dump(stage / "config.snapshot.json", cfg)
        lines = [f"# {cfg['name']}", "", "Annual rooftop PV accounting. Scopes are reported separately.", "",
                 "| Scope | Buildings | Module area (m2) | DC capacity (kWp) | AC energy (kWh/year) |", "|---|---:|---:|---:|---:|"]
        for key, s in scopes.items():
            lines.append(f"| {key} | {s['building_count']} | {s['module_area_m2']:.3f} | {s['capacity_kwp']:.3f} | {s['generation_kwh']:.3f} |")
        lines.extend(["", "Configuration: config.snapshot.json. Definitions and resolved yields: summary.json.",
                      "Weather profiles are per-kWp reference systems; external annual corrections do not establish hourly building shading.",
                      "This run does not establish installation feasibility, grid capacity or investment profitability."])
        (stage / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        source_root = Path(__file__).parent
        dump(stage / "manifest.json", {"version": __version__, "python": platform.python_version(),
            "created_utc": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
            "implementation_sha256": {p.name: sha256(p) for p in sorted(source_root.glob("*.py"))},
            "outputs_sha256": {p.name: sha256(p) for p in sorted(stage.iterdir()) if p.is_file()}})
        # Rename within the destination filesystem. Never replace an existing run.
        if output.exists():
            raise InputError("output appeared during run; refusing to overwrite")
        os.rename(stage, output)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Urban rooftop photovoltaic annual accounting")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "validate", "yield"):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
        if name in ("run", "yield"):
            command.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            summary = run(args.config, args.output)
            print(json.dumps({"output": str(args.output.resolve()), "scopes": summary["scopes"]}, ensure_ascii=False, indent=2))
        elif args.command == "yield":
            result = run_yield(args.config, args.output)
            print(json.dumps({"output": str(args.output.resolve()), "annual_yield_kwh_per_kwp": result["kwh_per_kwp"],
                              "source": result["source"]}, ensure_ascii=False, indent=2))
        else:
            cfg, y, _, inputs, path = prepare(args.config)
            count = sum(1 for _ in buildings(cfg, path, y))
            if any(sha256(r["path"]) != r["sha256"] for r in inputs):
                raise InputError("input changed during validation")
            print(f"VALID: {count} buildings; {len(y)} yield profiles")
    except (InputError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0
