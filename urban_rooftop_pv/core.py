"""Standard-library annual accounting; no thesis-specific constants."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path


class InputError(ValueError):
    """An input is incomplete, ambiguous or physically invalid."""


def number(value, label, low=0.0, high=None, positive=False):
    if isinstance(value, bool):
        raise InputError(f"{label}: expected a number, not boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{label}: expected a number, got {value!r}") from exc
    if not math.isfinite(result) or result < low or (high is not None and result > high):
        raise InputError(f"{label}: must be finite and within [{low}, {high or 'infinity'}]")
    if positive and result <= 0:
        raise InputError(f"{label}: must be positive")
    return result


def keys(obj, allowed, required, label):
    if not isinstance(obj, dict):
        raise InputError(f"{label}: expected an object")
    extra, missing = set(obj) - set(allowed), set(required) - set(obj)
    if extra or missing:
        raise InputError(f"{label}: unknown keys={sorted(extra)}, missing keys={sorted(missing)}")


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label}: expected nonempty text")
    return value.strip()


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_config(path):
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_json)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON: {exc}") from exc
    required = {"schema_version", "name", "buildings_csv", "columns", "roof_profiles", "yields", "corrections", "scope_labels"}
    keys(cfg, required | {"carbon", "notes"}, required, "config")
    if type(cfg["schema_version"]) is not int or cfg["schema_version"] != 1:
        raise InputError("schema_version must be integer 1")
    text(cfg["name"], "name")
    text(cfg["buildings_csv"], "buildings_csv")
    cols = {"building_id", "area_m2", "roof_profile", "yield_id", "scope", "district", "category"}
    keys(cfg["columns"], cols, cols, "columns")
    for key, value in cfg["columns"].items():
        text(value, f"columns.{key}")
    if len(set(cfg["columns"].values())) != len(cols):
        raise InputError("columns must map to distinct CSV fields")
    for name in ("roof_profiles", "yields", "scope_labels"):
        if not isinstance(cfg[name], dict) or not cfg[name]:
            raise InputError(f"{name}: expected a nonempty object")
        for key in cfg[name]:
            text(key, name)
    for key, value in cfg["scope_labels"].items():
        text(value, f"scope_labels.{key}")
    for name, p in cfg["roof_profiles"].items():
        keys(p, {"area_mode", "capacity_density_kwp_m2", "effective_uf", "usable_fraction", "packing_fraction", "surface_multiplier", "source"},
             {"area_mode", "capacity_density_kwp_m2", "source"}, f"roof_profiles.{name}")
        number(p["capacity_density_kwp_m2"], "capacity density", positive=True)
        text(p["source"], "roof source")
        mode = p["area_mode"]
        factors = {"usable_fraction", "packing_fraction", "surface_multiplier"}
        if mode == "effective_uf":
            if "effective_uf" not in p or set(p) & factors:
                raise InputError("effective_uf mode requires effective_uf and forbids component factors")
            number(p["effective_uf"], "effective_uf")
        elif mode == "components":
            if "effective_uf" in p or not factors <= set(p):
                raise InputError("components mode requires all three factors and forbids effective_uf")
            number(p["usable_fraction"], "usable_fraction", high=1)
            number(p["packing_fraction"], "packing_fraction", high=1)
            number(p["surface_multiplier"], "surface_multiplier", positive=True)
        elif mode == "module_area":
            if (factors | {"effective_uf"}) & set(p):
                raise InputError("module_area must not apply area conversion factors again")
        else:
            raise InputError(f"unknown area_mode: {mode}")
    for name, y in cfg["yields"].items():
        keys(y, {"mode", "kwh_per_kwp", "included_effects", "source", "weather_csv", "location", "system", "time", "pvgis"},
             {"mode", "source"}, f"yields.{name}")
        text(y["source"], "yield source")
        if y["mode"] == "annual":
            keys(y, {"mode", "kwh_per_kwp", "included_effects", "source"},
                 {"mode", "kwh_per_kwp", "included_effects", "source"}, f"yields.{name}")
            number(y["kwh_per_kwp"], "kwh_per_kwp")
            effects = y["included_effects"]
            if not isinstance(effects, list) or any(not isinstance(x, str) or not x.strip() for x in effects) or len(set(effects)) != len(effects):
                raise InputError("included_effects must be a list of distinct nonempty effect IDs")
        elif y["mode"] == "weather":
            from .weather import validate_spec
            validate_spec(y)
        elif y["mode"] == "pvgis_tmy":
            from .pvgis import validate_spec
            validate_spec(y)
        else:
            raise InputError(f"unknown yield mode: {y['mode']}")
    if not isinstance(cfg["corrections"], list):
        raise InputError("corrections must be a list")
    seen = set()
    for c in cfg["corrections"]:
        keys(c, {"effect", "column", "value", "source"}, {"effect", "source"}, "correction")
        name = text(c["effect"], "effect")
        text(c["source"], "correction source")
        if name in seen:
            raise InputError(f"duplicate correction effect: {name}")
        seen.add(name)
        if ("value" in c) == ("column" in c):
            raise InputError("correction requires exactly one of value or column")
        if "value" in c:
            number(c["value"], name, high=1)
        else:
            text(c["column"], "correction column")
    if "carbon" in cfg:
        c = cfg["carbon"]
        keys(c, {"kg_co2_per_kwh", "factor_year", "source"}, {"kg_co2_per_kwh", "factor_year", "source"}, "carbon")
        number(c["kg_co2_per_kwh"], "carbon factor")
        if type(c["factor_year"]) is not int or c["factor_year"] < 1900:
            raise InputError("carbon.factor_year must be an explicit year")
        text(c["source"], "carbon source")
    return cfg


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolve_yields(cfg, base):
    values, profiles, inputs = {}, {}, []
    for name, y in cfg["yields"].items():
        if y["mode"] == "annual":
            values[name] = {"kwh_per_kwp": float(y["kwh_per_kwp"]), "included_effects": y["included_effects"], "source": y["source"]}
        elif y["mode"] == "weather":
            from .weather import compute
            path = (base / y["weather_csv"]).resolve()
            before = sha256(path)
            values[name], profiles[name] = compute(y, path)
            if sha256(path) != before:
                raise InputError(f"weather input changed during read: {path}")
            inputs.append({"path": str(path), "sha256": before})
        else:
            from .pvgis import resolve
            values[name], profiles[name], files = resolve(y, base)
            inputs.extend({"path": str(path), "sha256": sha256(path)} for path in files)
    for name, y in values.items():
        duplicate = set(y["included_effects"]) & {c["effect"] for c in cfg["corrections"]}
        if duplicate:
            raise InputError(f"yield {name}: corrections already included: {sorted(duplicate)}")
    return values, profiles, inputs


def buildings(cfg, path, yields):
    """Yield validated rows; unknown scopes/categories are never silently dropped."""
    cols, ids = cfg["columns"], set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        if len(set(header)) != len(header):
            raise InputError("duplicate CSV header")
        required = set(cols.values()) | {c["column"] for c in cfg["corrections"] if "column" in c}
        if not required <= set(header):
            raise InputError(f"missing CSV columns: {sorted(required - set(header))}")
        count = 0
        for line, raw in enumerate(reader, 2):
            try:
                if None in raw:
                    raise InputError("too many CSV fields")
                row = {k: text(raw.get(v), v) for k, v in cols.items()}
                bid = row["building_id"]
                if bid in ids:
                    raise InputError(f"duplicate building_id: {bid}")
                ids.add(bid)
                if row["scope"] not in cfg["scope_labels"]:
                    raise InputError(f"unknown scope: {row['scope']}")
                if row["roof_profile"] not in cfg["roof_profiles"] or row["yield_id"] not in yields:
                    raise InputError("unknown roof_profile or yield_id")
                p = cfg["roof_profiles"][row["roof_profile"]]
                y = yields[row["yield_id"]]
                area = number(row.pop("area_m2"), "area_m2")
                mode = p["area_mode"]
                ratio = (float(p["effective_uf"]) if mode == "effective_uf" else
                         float(p["usable_fraction"]) * float(p["packing_fraction"]) * float(p["surface_multiplier"]) if mode == "components" else 1.0)
                module_area = area * ratio
                capacity = module_area * float(p["capacity_density_kwp_m2"])
                factor = 1.0
                for c in cfg["corrections"]:
                    factor *= number(c["value"] if "value" in c else raw.get(c["column"]), c["effect"], high=1)
                generation = capacity * float(y["kwh_per_kwp"]) * factor
                for label, value in (("module_area_m2", module_area), ("capacity_kwp", capacity), ("generation_kwh", generation)):
                    number(value, label)
                row.update(input_area_m2=area, area_mode=mode, module_area_ratio=ratio,
                           module_area_m2=module_area, capacity_kwp=capacity,
                           base_yield_kwh_per_kwp=y["kwh_per_kwp"], external_correction_factor=factor,
                           generation_kwh=generation)
                if "carbon" in cfg:
                    row["operational_avoided_co2_kg"] = number(generation * float(cfg["carbon"]["kg_co2_per_kwh"]), "avoided carbon")
                count += 1
                yield row
            except InputError as exc:
                raise InputError(f"CSV line {line}: {exc}") from exc
        if count == 0:
            raise InputError("buildings CSV contains no data rows")


def aggregate(rows):
    result = {}
    for row in rows:
        key = (row["scope"], row["district"], row["category"])
        out = result.setdefault(key, dict(scope=key[0], district=key[1], category=key[2], building_count=0,
                                          module_area_m2=0.0, capacity_kwp=0.0, generation_kwh=0.0))
        out["building_count"] += 1
        for field in ("module_area_m2", "capacity_kwp", "generation_kwh", "operational_avoided_co2_kg"):
            if field in row:
                out[field] = out.get(field, 0.0) + row[field]
    return [result[k] for k in sorted(result)]
