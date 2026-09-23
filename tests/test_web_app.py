import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "install web extra for UI tests")
class WebAppTests(unittest.TestCase):
    def test_pvgis_page_shows_editable_inputs(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "web/app.py"), default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        labels = {x.label for x in app.number_input}
        self.assertIn("纬度 °N", labels)
        self.assertIn("倾角 °", labels)
        self.assertIn("PVGIS起始年", labels)
        self.assertEqual(app.radio(key="task").value, "比产额")

    def test_annual_building_form_changes_calculated_result(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "web/app.py"), default_timeout=25).run()
        app.radio(key="task").set_value("逐栋发电量").run()
        app.selectbox(key="source_label").set_value("已有年比产额").run()
        app.checkbox(key="annual_buildings:demo_buildings").set_value(True).run()
        app.number_input(key="annual_buildings:yield_value").set_value(2000.0).run()
        next(x for x in app.button if x.label == "运行并绘图").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertTrue(any("计算完成" in x.value for x in app.success))
        output = Path(app.session_state["last_run"]["path"])
        result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(result["scopes"]["main"]["generation_kwh"], 56000)


if __name__ == "__main__":
    unittest.main()
