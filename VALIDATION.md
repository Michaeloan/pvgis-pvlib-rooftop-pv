# Validation

Release candidate: 0.3.0.

- `python -m unittest discover -s tests -q`: 38 tests passed locally with Python 3.13, pvlib 0.15.2 and Streamlit 1.64.0 on Windows. Tests include building-level hand calculations, scope separation, parameter and cache validation, leap-year/subhourly integration, offline PVGIS response handling, and Streamlit form interaction.
- A real PVGIS 5.3 TMY request for the public example coordinate (23.13°N, 113.26°E), years 2010–2020, returned PVGIS-ERA5, 12 selected months and 8760 hours. The configured reference system yielded 1242.2647956534645 kWh/kWp of annual AC electricity.
- The live local Streamlit app was opened in a browser. Its form produced the same result and rendered monthly, diurnal and daily charts; `assets/web-inputs.png` and `assets/web-results.png` are screenshots of that page.
- The skill frontmatter and folder layout passed `quick_validate.py`.

The PVGIS weather is real service data. The example building inputs are synthetic. The program has not been calibrated against a measured PV installation and has not reproduced the author's full thesis results.

The thesis values summarized in `docs/thesis-aggregate-results.md` were checked against the latest manuscript provided by the author on 2026-09-23. This is a source transcription check, not an independent rerun of the full thesis model.
