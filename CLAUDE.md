# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Sistem Partisi Wilayah Petugas Sensus** — a geospatial tool for BPS Indonesia that partitions SLS (Satuan Lingkungan Setempat) census areas among officers with balanced workloads and geographic connectivity. All UI labels, tooltips, and error messages are in Indonesian.

## How to Run

```bash
# Streamlit web UI
streamlit run app.py

# CLI pipeline
python main.py data/<file>.geojson <n_officers>
python main.py data/sls.geojson 8 --override koreksi.xlsx --output-excel hasil.xlsx --output-map peta.html --epsg 32750 --restarts 20
python main.py data/sls.geojson 1 --generate-template   # generate override template
```

## Install

```bash
pip install -r requirements.txt
```

## Key Configuration (config.py)

All algorithm tunables live in `config.py`. Critical parameters:

| Parameter | Default | Notes |
|---|---|---|
| `EPSG_METRIC` | 32750 | UTM zone — must match region (see below) |
| `N_RESTARTS` | 15 | More restarts = better CV, slower |
| `ROAD_DISTANCE_THRESHOLD_M` | 8000 | Max road distance for an edge |
| `TOUCHING_ONLY` | False | Set True to skip OSM, use polygon-touch only |

## EPSG by Region

Wrong EPSG produces incorrect distance calculations — always verify before running:

| EPSG | Region |
|---|---|
| 32750 | Sulawesi, Kalimantan, Maluku, Papua |
| 32749 | Jawa Tengah/Timur, Bali, NTB, NTT |
| 32748 | Sumatera, Jawa Barat |

## OSM Dependency

`osmnx` downloads road networks at runtime and requires internet access. The system gracefully falls back to polygon-touching-only adjacency if OSM is unavailable or `TOUCHING_ONLY = True`.

## Algorithm (partitioner.py)

Multi-start region-growing with local search and connectivity guarantees:
1. k-means++ seed dispersal across the graph
2. Min-heap region growing (smallest group expands first)
3. Boundary node swaps with connectivity check
4. N_RESTARTS runs — best Coefficient of Variation (CV = std/mean of loads) wins

**Hard constraints**: Every partition must be connected; all SLS assigned to exactly one officer.

## Edge Weights (adjacency_builder.py)

```
weight = WEIGHT_DISTANCE * (road_dist_m / 1000) + WEIGHT_TOUCHING * (0 if touching else 1)
```

Smaller weight = easier access. Drives which swaps local search accepts.

## Input Formats

- **GeoJSON**: polygon features with `kode_sls` and `muatan` properties
- **Excel override**: sheets `force_connect` and `force_disconnect` (columns: `kode_sls_a`, `kode_sls_b`, `catatan`)
- **Streamlit Excel**: sheet `TOTAL MUATAN PER SLS`, columns `idsubsls`, `Perkiraan_Jumlah_Muatan`, `kode_sls`

## Geometry Validation

Invalid polygons are auto-repaired via `shapely.validation.make_valid`. SLS with `muatan = 0` are kept but logged as warnings. Large datasets (>1000 SLS) may slow OSM downloads — tune `OSM_BUFFER_DEG` in config.

## Workflow Preferences

- **Propose a plan before implementing** — outline the approach before touching any file.
- **Keep responses concise** — no lengthy explanations; be direct.
- **Verify after UI changes** — run `streamlit run app.py` to confirm the UI works after edits.
- **Algorithm changes require tradeoff notes** — when modifying `partitioner.py`, `matrix_builder.py`, or `adjacency_builder.py`, explain the tradeoff (e.g., speed vs. solution quality, connectivity guarantees).

## Linting & Formatting (ruff)

```bash
pip install ruff          # one-time install
ruff check .              # lint
ruff check . --fix        # auto-fix lint issues
ruff format .             # format all files
```

Config: `ruff.toml` (100-char lines, Python 3.11+, E/F/W/I/UP rules).

## No Tests

No test suite exists. Validate correctness by running the app or CLI pipeline on a real dataset (`/verify` or `/run-pipeline`).
