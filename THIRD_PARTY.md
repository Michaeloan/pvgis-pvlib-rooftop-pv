# Third-party components and data

This repository's Python code, web interface, examples, and skill instructions are distributed under the repository's MIT license. Dependencies retain their own licenses.

- [pvlib-python](https://github.com/pvlib/pvlib-python) (BSD-3-Clause) supplies solar geometry and PV performance models; its source code is not vendored here. Suggested citation: Anderson et al. (2023), *Journal of Open Source Software* 8(92), 5994, [DOI:10.21105/joss.05994](https://doi.org/10.21105/joss.05994).
- [Streamlit](https://github.com/streamlit/streamlit) supplies the local web interface; its source code is not vendored here.
- Real TMY data can be requested from the European Commission Joint Research Centre's [PVGIS API](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en). The selected radiation database and months are recorded in each run. Cached PVGIS responses are excluded from the repository.

The sample building footprints, roof factors, shading factors, carbon factor and generated `examples/weather.csv` are synthetic. They are not thesis data or measurements from Guangzhou. The screenshots show a real PVGIS weather response modeled with pvlib alongside the example parameter values.

`docs/thesis-aggregate-results.md` contains only selected aggregate findings from a thesis draft supplied by the author for this repository. The private manuscript and underlying building-level dataset are not distributed.
