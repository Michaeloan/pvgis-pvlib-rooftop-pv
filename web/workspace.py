"""Prepare isolated inputs and call the same verified computation as the CLI."""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

from urban_rooftop_pv.cli import run, run_yield
from urban_rooftop_pv.core import InputError
from urban_rooftop_pv.pvgis import request_parameters, signature

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def template(kind: str) -> dict:
    names = {
        "pvgis_yield": "pvgis-yield.json",
        "pvgis_buildings": "pvgis-tmy.json",
        "weather_yield": "weather.json",
        "weather_buildings": "weather.json",
        "annual_buildings": "annual.json",
    }
    if kind not in names:
        raise InputError(f"unknown scenario template: {kind}")
    value = json.loads((EXAMPLES / names[kind]).read_text(encoding="utf-8"))
    if kind == "weather_yield":
        value = {"schema_version": 1, **value["yields"]["reference"]}
    return value


def _yield_spec(config: dict, building_mode: bool) -> dict:
    return config["yields"]["reference"] if building_mode else config


def prepare_inputs(config: dict, building_mode: bool, uploaded_buildings=None,
                   buildings_path: str = "", uploaded_weather=None,
                   weather_path: str = "", use_demo_buildings: bool = False,
                   use_demo_weather: bool = False,
                   run_root: Path | None = None, cache_root: Path | None = None) -> tuple[Path, Path]:
    """Write a new scenario directory and return (config_path, output_path)."""
    cfg = copy.deepcopy(config)
    run_root = Path(run_root or ROOT / "local" / "web_runs").resolve()
    cache_root = Path(cache_root or ROOT / "local" / "web_cache").resolve()
    mode = _yield_spec(cfg, building_mode)["mode"]
    if mode == "weather" and uploaded_weather is None and not weather_path.strip() and not use_demo_weather:
        raise InputError("请上传气象CSV或提供本地路径；合成气象示例需明确勾选。")
    if building_mode and uploaded_buildings is None and not buildings_path.strip() and not use_demo_buildings:
        raise InputError("请上传建筑CSV或提供本地路径；合成示例需明确勾选。")
    work = run_root / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    source = _yield_spec(cfg, building_mode)
    if mode == "pvgis_tmy":
        params = request_parameters(source)
        token = signature(params)
        source["pvgis"]["cache_csv"] = str(cache_root / f"{token}.csv")
        source["pvgis"]["cache_metadata_json"] = str(cache_root / f"{token}.json")
    elif mode == "weather":
        destination = work / "weather.csv"
        if uploaded_weather is not None:
            uploaded_weather.seek(0)
            with destination.open("xb") as stream:
                shutil.copyfileobj(uploaded_weather, stream)
        elif weather_path.strip():
            shutil.copyfile(Path(weather_path).expanduser(), destination)
        elif use_demo_weather:
            sample = EXAMPLES / "weather.csv"
            if not sample.is_file():
                raise InputError("请上传气象CSV、提供本地路径，或先生成examples/weather.csv。")
            shutil.copyfile(sample, destination)
        else:
            raise InputError("请上传气象CSV或提供本地路径；合成气象示例需明确勾选。")
        source["weather_csv"] = destination.name
    if building_mode:
        destination = work / "buildings.csv"
        if uploaded_buildings is not None:
            uploaded_buildings.seek(0)
            with destination.open("xb") as stream:
                shutil.copyfileobj(uploaded_buildings, stream)
        elif buildings_path.strip():
            shutil.copyfile(Path(buildings_path).expanduser(), destination)
        elif use_demo_buildings:
            shutil.copyfile(EXAMPLES / "buildings.csv", destination)
        else:
            raise InputError("请上传建筑CSV或提供本地路径；合成示例需明确勾选。")
        cfg["buildings_csv"] = destination.name
    config_path = work / "scenario.json"
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return config_path, work / "result"


def execute(config: dict, building_mode: bool, **inputs) -> tuple[Path, dict]:
    config_path, output = prepare_inputs(config, building_mode, **inputs)
    result = run(config_path, output) if building_mode else run_yield(config_path, output)
    return output, result
