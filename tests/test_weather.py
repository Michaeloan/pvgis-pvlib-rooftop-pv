import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from scripts.make_demo_weather import generate
from urban_rooftop_pv.core import InputError
from urban_rooftop_pv.cli import run
from urban_rooftop_pv.weather import compute, validate_spec

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = all(importlib.util.find_spec(x) for x in ("pvlib", "numpy", "pandas"))


@unittest.skipUnless(AVAILABLE, "install weather extras to test pvlib backend")
class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "weather.csv"
        self.spec = json.loads((ROOT / "examples/weather.json").read_text())["yields"]["reference"]

    def test_full_year_output_and_inverter_limit(self):
        generate(self.path)
        y, p = compute(self.spec, self.path)
        self.assertGreater(y["kwh_per_kwp"], 0)
        self.assertEqual(len(p), 8760)
        self.assertAlmostEqual(y["kwh_per_kwp"], sum(x["energy_kwh_per_kwp"] for x in p), places=8)
        self.assertLessEqual(max(x["ac_w_per_kwp"] for x in p), 1000 / 1.2 + 1e-8)
        self.assertEqual(p[0]["energy_kwh_per_kwp"], 0)

    def test_half_hour_leap_year_integrates_duration(self):
        generate(self.path, 2024, 30)
        self.spec["time"].update(year=2024, interval_minutes=30)
        y, p = compute(self.spec, self.path)
        self.assertEqual(len(p), 366 * 48)
        self.assertAlmostEqual(y["kwh_per_kwp"], sum(x["ac_w_per_kwp"] for x in p) / 2000, places=7)

    def test_missing_hour_is_not_annualized(self):
        generate(self.path)
        lines = self.path.read_text().splitlines()
        self.path.write_text("\n".join(lines[:-1]) + "\n")
        with self.assertRaisesRegex(InputError, "exactly one"):
            compute(self.spec, self.path)

    def test_naive_timestamp_rejected(self):
        generate(self.path)
        self.path.write_text(self.path.read_text().replace("+08:00", ""))
        with self.assertRaisesRegex(InputError, "explicit UTC offset"):
            compute(self.spec, self.path)

    def test_pvsyst_temperature_backend(self):
        generate(self.path)
        self.spec["system"].update(temperature_model="pvsyst", temperature_parameters={"u_c":29,"u_v":0,"module_efficiency":0.2,"alpha_absorption":0.9})
        y, _ = compute(self.spec, self.path)
        self.assertGreater(y["kwh_per_kwp"], 0)

    def test_all_system_losses_remove_energy(self):
        generate(self.path)
        self.spec["system"]["system_loss_pct"] = 100
        y, _ = compute(self.spec, self.path)
        self.assertEqual(y["kwh_per_kwp"], 0)

    def test_weather_export_monthly_closure(self):
        import csv
        generate(self.path)
        config = json.loads((ROOT / "examples/weather.json").read_text())
        config["buildings_csv"] = str(ROOT / "examples/buildings.csv")
        path = Path(self.tmp.name) / "scenario.json"
        path.write_text(json.dumps(config))
        output = Path(self.tmp.name) / "result"
        summary = run(path, output)
        with (output / "monthly_yields.csv").open(encoding="utf-8-sig", newline="") as stream:
            monthly = list(csv.DictReader(stream))
        self.assertEqual(len(monthly), 12)
        self.assertAlmostEqual(sum(float(x["energy_kwh_per_kwp"]) for x in monthly), summary["resolved_yields"]["reference"]["kwh_per_kwp"], places=8)


class WeatherSpecTests(unittest.TestCase):
    def test_unsupported_model_rejected(self):
        spec = json.loads((ROOT / "examples/weather.json").read_text())["yields"]["reference"]
        spec["system"]["temperature_model"] = "arbitrary"
        with self.assertRaisesRegex(InputError, "temperature_model"):
            validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
