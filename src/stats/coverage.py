"""
覆盖率 & 密度统计。

输入匹配结果，输出每条道路的覆盖率 (0-1) 和通行次数。
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from pathlib import Path
from shapely.geometry import LineString, Point


def compute_segment_coverage(
    geometry: LineString,
    matched_points: np.ndarray,
    segment_length_m: float = 50.0,
) -> float:
    """
    计算单条道路的分段覆盖率。

    Args:
        geometry: 道路 LineString (WGS-84)
        matched_points: shape (N, 2) 的匹配点 [(lon, lat), ...]
        segment_length_m: 分段长度 (米)

    Returns:
        覆盖率 0.0 ~ 1.0
    """
    total_length_m = geometry.length * 111000
    if total_length_m < segment_length_m:
        return 1.0 if len(matched_points) > 0 else 0.0

    num_segments = max(1, int(total_length_m / segment_length_m))
    covered = np.zeros(num_segments, dtype=bool)

    if len(matched_points) == 0:
        return 0.0

    for i in range(len(matched_points)):
        lon, lat = matched_points[i]
        pt = Point(lon, lat)
        projected_dist = geometry.project(pt, normalized=True)
        if projected_dist < 0 or projected_dist > 1:
            continue
        seg_idx = min(int(projected_dist * num_segments), num_segments - 1)
        covered[seg_idx] = True

    return float(covered.sum() / num_segments)


def compute_coverage(
    matched_df: pd.DataFrame,
    way_map: Dict[str, Dict[str, Any]],
    segment_length_m: float = 50.0,
) -> pd.DataFrame:
    """计算所有道路的覆盖率和密度"""
    if len(matched_df) > 0:
        density = (
            matched_df.groupby("osm_way_id")["trip_id"]
            .nunique()
            .reset_index(name="pass_count")
        )
    else:
        density = pd.DataFrame(columns=["osm_way_id", "pass_count"])

    rows = []
    for way_id, way_info in way_map.items():
        geometry = way_info["geometry"]
        way_matches = matched_df[matched_df["osm_way_id"] == way_id] if len(matched_df) > 0 else pd.DataFrame()

        if len(way_matches) > 0:
            points = _extract_sample_points(geometry)
            coverage_ratio = compute_segment_coverage(geometry, points, segment_length_m)
        else:
            coverage_ratio = 0.0

        pass_count = 0
        if len(density) > 0:
            dens_row = density[density["osm_way_id"] == way_id]
            if len(dens_row) > 0:
                pass_count = int(dens_row["pass_count"].values[0])

        rows.append({
            "osm_way_id": way_id,
            "road_name": way_info.get("name", ""),
            "road_length": way_info.get("length", 0),
            "coverage_ratio": round(coverage_ratio, 4),
            "pass_count": pass_count,
            "highway_type": way_info.get("highway", ""),
            "geometry": geometry.wkt,
        })

    return pd.DataFrame(rows)


def _extract_sample_points(geometry: LineString) -> np.ndarray:
    """从 geometry 采样点用于覆盖率计算"""
    num_samples = int(geometry.length * 111000 / 10)
    num_samples = max(2, min(num_samples, 1000))
    distances = np.linspace(0, geometry.length, num_samples)
    points = [geometry.interpolate(d) for d in distances]
    return np.array([[p.x, p.y] for p in points])


def save_results(df: pd.DataFrame, output_path: Path) -> None:
    """保存结果为 Parquet"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
