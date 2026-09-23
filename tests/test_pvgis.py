import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from urban_rooftop_pv.cli import run, run_yield
from urban_rooftop_pv.core import InputError
from urban_rooftop_pv.pvgis import resolve, validate_spec

ROOT = Path(__file__).resolve().parents[1]


class PvgisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.cfg = json.loads((ROOT / "examples/pvgis-tmy.json").read_text())
        self.cfg["buildings_csv"] = str(ROOT / "examples/buildings.csv")
        self.cfg["yields"]["reference"]["pvgis"]["cache_csv"] = "local/pvgis-tmy-weather.csv"
        self.cfg["yields"]["reference"]["pvgis"]["cache_metadata_json"] = "local/pvgis-tmy-metadata.json"
        self.spec = self.cfg["yields"]["reference"]

    def response(self):
        import numpy as np
        import pandas as pd
        dates = pd.date_range("2025-01-01", "2026-01-01", freq="h", inclusive="left", tz="UTC")
        daylight = np.maximum(0, np.sin(np.pi * (dates.hour - 6) / 12))
        weather = pd.DataFrame({"ghi": daylight * 600, "dni": daylight * 500,
                                "dhi": daylight * 100, "temp_air": 25.0,
                                "wind_speed": 1.5}, index=dates)
        meta = {"inputs": {"meteo_data": {"radiation_db": "PVGIS-ERA5"},
                            "location": {"irradiance_time_offset": 0.5}},
                "months_selected": [{"month": 1, "year": 2015}]}
        return weather, meta

    def test_all_request_inputs_forwarded_and_cache_is_reused(self):
        with patch("pvlib.iotools.get_pvgis_tmy", return_value=self.response()) as getter:
            first, _, files = resolve(self.spec, self.base)
            second, _, _ = resolve(self.spec, self.base)
        getter.assert_called_once()
        kwargs = getter.call_args.kwargs
        self.assertEqual(kwargs["url"], self.spec["pvgis"]["api_url"])
        self.assertEqual(kwargs["startyear"], 2010)
        self.assertEqual(kwargs["endyear"], 2020)
        self.assertIs(kwargs["usehorizon"], False)
        self.assertEqual(kwargs["coerce_year"], 2025)
        self.assertEqual(first["kwh_per_kwp"], second["kwh_per_kwp"])
        self.assertTrue(all(x.is_file() for x in files))

    def test_cache_changes_are_rejected(self):
        with patch("pvlib.iotools.get_pvgis_tmy", return_value=self.response()):
            resolve(self.spec, self.base)
        changed = copy.deepcopy(self.spec)
        changed["pvgis"]["use_horizon"] = True
        changed["pvgis"]["cache_policy"] = "cache_only"
        with self.assertRaisesRegex(InputError, "differs"):
            resolve(changed, self.base)

    def test_database_and_time_offset_checked(self):
        for field, value, message in (("radiation_db", "PVGIS-SARAH3", "selected"),
                                       ("irradiance_time_offset", 0.25, "offset")):
            with self.subTest(field=field):
                frame, meta = self.response()
                if field == "radiation_db":
                    meta["inputs"]["meteo_data"][field] = value
                else:
                    meta["inputs"]["location"][field] = value
                with patch("pvlib.iotools.get_pvgis_tmy", return_value=(frame, meta)):
                    with self.assertRaisesRegex(InputError, message):
                        resolve(self.spec, self.base)
                self.assertFalse((self.base / "local/pvgis-tmy-weather.csv").exists())

    def test_cache_only_never_calls_network(self):
        self.spec["pvgis"]["cache_policy"] = "cache_only"
        with patch("pvlib.iotools.get_pvgis_tmy") as getter:
            with self.assertRaisesRegex(InputError, "cache is missing"):
                resolve(self.spec, self.base)
        getter.assert_not_called()

    def test_run_saves_weather_and_response_metadata(self):
        path = self.base / "scenario.json"
        path.write_text(json.dumps(self.cfg))
        with patch("pvlib.iotools.get_pvgis_tmy", return_value=self.response()):
            result = run(path, self.base / "result")
        self.assertGreater(result["scopes"]["main"]["generation_kwh"], 0)
        self.assertEqual(result["resolved_yields"]["reference"]["pvgis"]["radiation_database"], "PVGIS-ERA5")
        self.assertTrue((self.base / "result/pvgis_1_weather.csv").is_file())
        self.assertTrue((self.base / "result/pvgis_1_metadata.json").is_file())

    def test_unsupported_year_and_mismatched_time_rejected(self):
        self.spec["time"]["year"] = 2024
        with self.assertRaisesRegex(InputError, "non-leap"):
            validate_spec(self.spec)
        self.spec["time"]["year"] = 2025
        self.spec["time"]["timezone"] = "Asia/Shanghai"
        with self.assertRaisesRegex(InputError, "UTC"):
            validate_spec(self.spec)

    def test_yield_only_needs_no_building_file(self):
        only = {"schema_version": 1, **self.spec}
        path = self.base / "only.json"
        path.write_text(json.dumps(only))
        with patch("pvlib.iotools.get_pvgis_tmy", return_value=self.response()):
            result = run_yield(path, self.base / "yield-result")
        self.assertGreater(result["kwh_per_kwp"], 0)
        self.assertTrue((self.base / "yield-result/monthly_yield.csv").is_file())
        self.assertTrue((self.base / "yield-result/input_1.csv").is_file())
        self.assertFalse((self.base / "yield-result/buildings.csv").exists())


if __name__ == "__main__":
    unittest.main()
