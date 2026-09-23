import copy
import csv
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from urban_rooftop_pv.cli import run
from urban_rooftop_pv.core import InputError, read_config, sha256

ROOT = Path(__file__).resolve().parents[1]


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.cfg = json.loads((ROOT / "examples/annual.json").read_text())
        with (ROOT / "examples/buildings.csv").open(newline="") as stream:
            self.rows = list(csv.DictReader(stream))

    def execute(self, name="result"):
        self.config = self.base / "scenario.json"
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")
        with (self.base / "buildings.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)
        return run(self.config, self.base / name)

    def test_hand_calculation_and_scope_separation(self):
        r = self.execute()
        self.assertEqual(r["scopes"]["main"]["generation_kwh"], 28000)
        self.assertAlmostEqual(r["scopes"]["reserve"]["generation_kwh"], 6336)
        self.assertEqual(r["scopes"]["main"]["capacity_kwp"], 30)
        self.assertEqual(r["scopes"]["main"]["operational_avoided_co2_kg"], 11200)

    def test_linear_capacity_response(self):
        baseline = self.execute("baseline")
        for p in self.cfg["roof_profiles"].values():
            p["capacity_density_kwp_m2"] *= 2
        second = self.execute("double")
        for scope in baseline["scopes"]:
            self.assertAlmostEqual(second["scopes"][scope]["generation_kwh"], 2 * baseline["scopes"][scope]["generation_kwh"])

    def test_zero_shading_gives_zero_energy_but_preserves_capacity(self):
        self.rows[0]["shading_factor"] = "0"
        r = self.execute()
        self.assertEqual(r["scopes"]["main"]["generation_kwh"], 18000)
        self.assertEqual(r["scopes"]["main"]["capacity_kwp"], 30)

    def test_module_area_does_not_apply_uf(self):
        self.cfg["roof_profiles"]["flat"] = {"area_mode":"module_area", "capacity_density_kwp_m2":0.2,"source":"test"}
        r = self.execute()
        self.assertEqual(r["scopes"]["main"]["generation_kwh"], 56000)

    def test_duplicate_effect_rejected(self):
        self.cfg["yields"]["reference"]["included_effects"].append("shading")
        with self.assertRaisesRegex(InputError, "already included"):
            self.execute()

    def test_area_double_count_rejected(self):
        self.cfg["roof_profiles"]["flat"]["packing_fraction"] = 0.8
        with self.assertRaisesRegex(InputError, "forbids"):
            self.execute()

    def test_unknown_parameter_rejected(self):
        self.cfg["roof_profiles"]["flat"]["effectve_uf"] = 0.6
        with self.assertRaisesRegex(InputError, "unknown keys"):
            self.execute()

    def test_duplicate_id_rejected_without_partial_output(self):
        self.rows[1]["building_id"] = self.rows[0]["building_id"]
        with self.assertRaisesRegex(InputError, "duplicate building_id"):
            self.execute()
        self.assertFalse((self.base / "result").exists())

    def test_unknown_scope_never_silently_dropped(self):
        self.rows[0]["scope"] = "typo"
        with self.assertRaisesRegex(InputError, "unknown scope"):
            self.execute()

    def test_nonfinite_and_negative_inputs(self):
        for value in ("nan", "inf", "-1", ""):
            with self.subTest(value=value):
                self.rows[0]["area_m2"] = value
                with self.assertRaises(InputError):
                    self.execute()

    def test_unknown_profile(self):
        self.rows[0]["roof_profile"] = "unknown"
        with self.assertRaisesRegex(InputError, "unknown roof_profile"):
            self.execute()

    def test_existing_output_preserved(self):
        self.execute()
        digest = sha256(self.base / "result/summary.json")
        with self.assertRaisesRegex(InputError, "already exists"):
            self.execute()
        self.assertEqual(digest, sha256(self.base / "result/summary.json"))

    def test_manifest_and_group_closure(self):
        r = self.execute()
        manifest = json.loads((self.base / "result/manifest.json").read_text())
        for file, digest in manifest["outputs_sha256"].items():
            self.assertEqual(digest, sha256(self.base / "result" / file))
        with (self.base / "result/buildings.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertAlmostEqual(sum(float(x["generation_kwh"]) for x in rows), sum(s["generation_kwh"] for s in r["scopes"].values()))

    def test_empty_scope_retained(self):
        self.cfg["scope_labels"]["unused"] = "Unused"
        self.assertEqual(self.execute()["scopes"]["unused"]["building_count"], 0)

    def test_duplicate_json_keys(self):
        path = self.base / "bad.json"
        path.write_text('{"name":"one","name":"two"}')
        with self.assertRaisesRegex(InputError, "duplicate JSON"):
            read_config(path)

    def test_cli_from_another_working_directory(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/pv.py"), "run", "--config", str(ROOT / "examples/annual.json"), "--output", str(self.base / "cli-run")], cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["scopes"]["main"]["generation_kwh"], 28000)

    def test_cli_error_exit_code(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/pv.py"), "validate", "--config", str(self.base / "missing.json")], cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR:", result.stderr)


if __name__ == "__main__":
    unittest.main()
