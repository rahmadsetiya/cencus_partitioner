---
name: run-pipeline
description: Run the CLI partition pipeline on a test GeoJSON from data/ to verify backend changes. Use after edits to partitioner.py, adjacency_builder.py, matrix_builder.py, or config.py.
disable-model-invocation: false
---

You are running the CLI pipeline to verify backend changes work correctly.

## Steps

1. List files in `data/` to find an available GeoJSON (e.g., `sls_enrekang.geojson`).
2. If no GeoJSON exists in `data/`, tell the user and stop — ask them to provide a test file.
3. Run the pipeline with a small officer count (use 3 unless $ARGUMENTS specifies otherwise):
   ```
   python main.py data/<geojson_file> 3 --restarts 5 --debug
   ```
   Use `--restarts 5` to keep the run fast for verification purposes.
4. Capture and report:
   - Whether the run completed without errors
   - The final Coefficient of Variation (CV) score (lower = better balance)
   - Number of SLS partitioned and number of officers
   - Whether all partitions are connected (look for "TIDAK" in the output)
   - Any warnings (OSM fallback, zero-load SLS, geometry repairs)
5. If the run fails, show the full traceback and identify which module raised the error.

## Key things to watch

- `partitioner.py` errors often mean graph connectivity broke (disconnected input graph)
- `adjacency_builder.py` errors often mean OSM download failed — check internet or set `TOUCHING_ONLY = True` in config.py
- EPSG mismatch produces huge or near-zero distances — if distances look wrong, check `config.EPSG_METRIC` vs. the region of the test data

## Notes

- Use `$ARGUMENTS` to accept a custom GeoJSON path or officer count (e.g., `/run-pipeline data/custom.geojson 8`).
- For production runs, raise `--restarts` to 20–50 in config.py for better solution quality.
