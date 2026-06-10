# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

The development environment is **Windows**. All commands and file operations must be Windows-compatible (path separators, shell compatibility, etc.). Do not use Linux-only commands or path styles.

## Commands

```bash
# Run the full pipeline
python main.py
python main.py --csv data/csv/pos/pos.csv --coord gcj02
python main.py --config custom_config.yaml --force

# Run tests
pytest tests/ -v                          # all tests
pytest tests/test_coordinate.py -v        # single test file
pytest tests/test_coordinate.py::TestGCJ02ToWGS84::test_roundtrip_preserves -v  # single test
```

## Architecture

This is a **road network coverage calculator for Hangzhou, China**. It computes per-road coverage ratios and pass counts by matching GPS trajectory data to OSM road network segments via HMM (Hidden Markov Model) map matching.

**Pipeline (7 steps):**
1. Download Hangzhou OSM road network via osmnx → `NetworkX MultiDiGraph` + `way_map` dict; assign each road to a district via Nominatim boundary polygons
2. Convert road network to a `leuvenmapmatching.SqliteMap` for HMM matching (spatial-indexed SQLite)
3. Load trajectory CSV via DuckDB `COPY` → Parquet, optionally convert GCJ-02 → WGS-84
4. Preprocess per-device (dedup → denoise → trip split → Douglas-Peucker simplification → adaptive start trimming) then parallel HMM matching; build device→road→district mapping
5. Compute segment-based coverage ratio per road (with district attribution) and aggregate pass counts
6. Generate folium coverage map (color-coded + density layers)
7. Generate trajectory scatter map (dedup → downsample to 150k → GeoJSON CircleMarker rendering)

**Key modules:**

| Module | Role |
|--------|------|
| `src/data/road_network.py` | OSM download via osmnx + pickle caching; builds `way_map` (way_id → geometry/name/highway/nodes) |
| `src/data/admin_boundaries.py` | Downloads Hangzhou 13 district boundary polygons via Nominatim; spatial-joins roads to districts via midpoint containment |
| `src/data/trajectory.py` | DuckDB CSV→Parquet (handles 10+ GB files); chunked coordinate conversion; device batch loading |
| `src/data/coordinate.py` | GCJ-02 ↔ WGS-84 conversion (iterative approximation, <1m error) |
| `src/preprocess/clean.py` | Per-device: coordinate dedup (dist <0.1m) → denoise (speed/jump filter) → trip split (time gap) → DP simplification |
| `src/matching/graph.py` | OSM graph → leuvenmapmatching `SqliteMap` via bulk insert API (add_nodes/add_edges) |
| `src/matching/hmm_matcher.py` | Single-trip HMM matching via `DistanceMatcher`; adaptive start-point trimming via `_find_first_matchable`; configurable goback/not-connected penalties; returns `(TripMatchResult, failure_reason)` tuple |
| `src/matching/parallel.py` | Orchestrates parallel matching: chunks devices, spawns `ProcessPoolExecutor`, maps edges → OSM ways; collects per-batch failure reason statistics |
| `src/stats/coverage.py` | Segment-based coverage ratio: projects matched points onto road geometry, bins into segments; outputs `district` field |
| `src/viz/map.py` | Folium coverage map: green (>80%) / yellow (40-80%) / red (<40%) |
| `src/viz/trajectory_map.py` | Folium trajectory scatter map: loads lon/lat only, coordinate dedup, uniform downsample to 150k, GeoJSON+CircleMarker rendering |
| `src/utils/logger.py` | `setup_logging()` redirects all stdout/stderr to timestamped log file via `_TeeWriter`; supports verbose (terminal+file) or silent (file-only) mode |

**HMM matching details:**

- Uses `DistanceMatcher` (Newson & Krumm algorithm) with edge-based states
- Adaptive start trimming: before matching, scans from trip head to skip GPS points outside road network coverage, then trims to first matchable point
- Failure tracking: each unmatched trip returns a reason string (`no_start_edge`, `early_stop`, `low_match_ratio`, `all_points_outside_network`, `exception`)
- Penalty factors are configurable via config.yaml:
  - `goback_on_edge_factor` / `goback_to_edge_factor`: relaxed from 0.5→0.7 to tolerate GPS multipath
  - `not_connected_edges_factor`: relaxed from 0.5→0.6 for OSM connectivity gaps
  - `non_emitting_states_maxnb`: reduced from 100→40 for high-frequency GPS
  - `ne_length_factor`: tightened from 0.9→0.75

**Caching strategy** — intermediate results are cached to disk to avoid recomputation:
- `data/hangzhou_graph.pkl` / `data/hangzhou_waymap.pkl` — OSM road network (pickle, way_map includes `district` field after first run)
- `data/hangzhou_districts.pkl` — district boundary polygons (pickle, 13 districts)
- `data/matching_graph_<date>.db` — leuvenmapmatching SQLite DB
- `data/node_ways_<date>.pkl` — node→way lookup table
- `*.parquet` (next to CSV) — CSV→Parquet conversion cache
- `*_wgs84.parquet` — coordinate conversion cache
- `logs/pipeline_YYYYMMDD_HHMMSS.log` — full run log

Use `--force` to rebuild all caches.

**Coordinate systems:** Chinese GPS data is typically in GCJ-02 (Mars coordinates, offset ~300-500m from WGS-84). The pipeline auto-detects via config or `--coord gcj02` flag and runs iterative conversion before matching.

**Parallel matching:** For >50 devices, `ProcessPoolExecutor` spawns worker processes. Each worker loads its device batch from Parquet via DuckDB, preprocesses, and runs HMM matching against a shared `SqliteMap` (read-only per process, each opens its own connection). Device chunk size is configurable (default 200). A `Counter` aggregates failure reasons across batches.

**Output files:**

| File | Content |
|------|---------|
| `output/roads_coverage.parquet` | Per-road coverage ratio, pass count, district |
| `output/device_road_map.parquet` | device→road→district mapping with pass counts |
| `output/device_summary.parquet` | Per-device road count and district coverage |
| `output/coverage_map.html` | Folium color-coded coverage map |
| `output/trajectory_map.html` | Folium trajectory scatter map (deduped, 150k points) |
| `logs/pipeline_*.log` | Full run log with failure reason distribution |

**Dependencies:** osmnx, leuvenmapmatching, duckdb, shapely, folium, numpy, scipy, tqdm, pyyaml, pandas, pytest, pyarrow.

**Known library patch:** leuvenmapmatching `sqlite.py:490` had a debug `print(f"edges_closeto({loc})")` that was removed to prevent log spam during parallel matching.
