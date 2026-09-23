import json
import tempfile
import unittest
from pathlib import Path

from urban_rooftop_pv.core import InputError
from web.workspace import execute, prepare_inputs, template


class WebWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_yield_template_does_not_require_buildings(self):
        cfg = template("pvgis_yield")
        self.assertNotIn("buildings_csv", cfg)
        self.assertEqual(cfg["mode"], "pvgis_tmy")
        self.assertIn("system", cfg)

    def test_building_demo_is_explicit_and_runs_existing_core(self):
        cfg = template("annual_buildings")
        with self.assertRaisesRegex(InputError, "建筑CSV"):
            prepare_inputs(cfg, True, run_root=self.base / "runs")
        output, result = execute(cfg, True, use_demo_buildings=True, run_root=self.base / "runs")
        self.assertEqual(result["scopes"]["main"]["generation_kwh"], 28000)
        snap = json.loads((output / "config.snapshot.json").read_text())
        self.assertEqual(snap["roof_profiles"], cfg["roof_profiles"])

    def test_pvgis_cache_filename_tracks_request_inputs(self):
        cfg = template("pvgis_yield")
        prepare_inputs(cfg, False, run_root=self.base / "runs", cache_root=self.base / "cache")
        first = next((self.base / "runs").glob("*/scenario.json"))
        before = json.loads(first.read_text())["pvgis"]["cache_csv"]
        cfg["location"]["latitude"] += 0.5
        prepare_inputs(cfg, False, run_root=self.base / "runs", cache_root=self.base / "cache")
        paths = [json.loads(p.read_text())["pvgis"]["cache_csv"] for p in (self.base / "runs").glob("*/scenario.json")]
        self.assertIn(before, paths)
        self.assertEqual(len(set(paths)), 2)

    def test_synthetic_local_weather_needs_opt_in(self):
        cfg = template("weather_yield")
        with self.assertRaisesRegex(InputError, "合成气象"):
            prepare_inputs(cfg, False, run_root=self.base / "runs")


if __name__ == "__main__":
    unittest.main()
