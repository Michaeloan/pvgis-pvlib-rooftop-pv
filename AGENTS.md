# Development notes

- Keep every input that changes a result explicit in the configuration or web form.
- Use the same calculation functions for the CLI and web app.
- Keep PVGIS response metadata and input hashes with each result; never publish `local/`, `outputs/`, credentials, or a personal dataset as an example.
- Distinguish synthetic building/weather demonstrations from results derived from a real PVGIS request.
- After calculation or UI changes, run `python -m unittest discover -s tests -q` with `.[weather,web]` installed.
