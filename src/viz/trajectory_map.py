"""
设备轨迹可视化。

读取 WGS-84 坐标系轨迹 Parquet，清洗去重后渲染到 OSM 底图上。
数据流：只读 lon/lat → 坐标去重 → 全局采样 → GeoJSON 散点渲染。
"""
import numpy as np
import pandas as pd
import folium
from folium.features import GeoJson
from pathlib import Path

# 散点渲染上限
MAX_RENDER_POINTS = 150_000


def _load_and_dedup(parquet_path: Path) -> np.ndarray:
    """只读 lon, lat 两列，按坐标去重，返回 (N, 2) ndarray。"""
    print(f"[traj-map] Loading (lon,lat only)...")
    df = pd.read_parquet(parquet_path, columns=["lon", "lat"])

    raw = len(df)
    print(f"[traj-map] Raw points: {raw:,}")

    df = df.drop_duplicates(subset=["lon", "lat"])
    dedup = len(df)
    print(f"[traj-map] After dedup: {dedup:,} ({raw - dedup:,} removed)")

    return df[["lon", "lat"]].to_numpy()


def _downsample(coords: np.ndarray, max_points: int) -> np.ndarray:
    """均匀采样到 max_points 以内。"""
    n = len(coords)
    if n <= max_points:
        return coords

    step = max(1, n // max_points)
    sampled = coords[::step]
    print(f"[traj-map] Downsampled: {n:,} -> {len(sampled):,} (step={step})")
    return sampled


def render_trajectory_map(
    trajectory_parquet: Path,
    output_path: Path,
    max_render_points: int = MAX_RENDER_POINTS,
) -> None:
    """
    Args:
        trajectory_parquet: WGS-84 轨迹 Parquet (需含 lon, lat 列)
        output_path: 输出 HTML 路径
        max_render_points: 全局渲染点上限，超出则均匀采样
    """
    # ── Step 1: 加载 + 去重 ──
    coords = _load_and_dedup(trajectory_parquet)

    # ── Step 2: 采样 ──
    coords = _downsample(coords, max_render_points)
    lons, lats = coords[:, 0], coords[:, 1]

    print(f"[traj-map] lon [{lons.min():.4f}, {lons.max():.4f}], "
          f"lat [{lats.min():.4f}, {lats.max():.4f}]")

    # ── Step 3: 构建 GeoJSON FeatureCollection ──
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {},
        }
        for lon, lat in zip(lons, lats)
    ]
    geojson_data = {"type": "FeatureCollection", "features": features}

    # ── Step 4: 散点渲染 ──
    m = folium.Map(
        location=[lats.mean(), lons.mean()],
        zoom_start=11,
        tiles="CartoDB positron",
    )

    traj_layer = folium.FeatureGroup(name="Trajectory Points", show=True)

    GeoJson(
        geojson_data,
        marker=folium.CircleMarker(
            radius=2,
            color="#27ae60",
            fill=True,
            fill_opacity=0.4,
            weight=0,
        ),
    ).add_to(traj_layer)

    traj_layer.add_to(m)

    if len(lons) >= 2:
        m.fit_bounds([(lats.min(), lons.min()), (lats.max(), lons.max())],
                     padding=(30, 30))

    print(f"[traj-map] Rendered {len(features):,} scatter points")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    print(f"[traj-map] Saved: {output_path}")
