"""
轨迹预处理：降噪 → Trip 切分 → Douglas-Peucker 抽稀。

对单台设备的 GPS 点序列进行处理，输出压缩后的 trip LineString 列表。
"""
import pandas as pd
import numpy as np
from typing import List, Tuple
from shapely.geometry import LineString
from math import radians, sin, cos, sqrt, atan2


def _haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """计算两点间的球面距离 (米)"""
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def denoise_trajectory(df: pd.DataFrame, min_speed_ms: float = 0.5,
                       max_jump_m: float = 500) -> pd.DataFrame:
    """
    剔除静止点和漂移点。
    """
    if len(df) < 3:
        return df

    mask = np.ones(len(df), dtype=bool)
    lons = df["lon"].values
    lats = df["lat"].values
    speeds = df["speed"].values

    for i in range(1, len(df) - 1):
        dist_to_prev = _haversine_distance(lons[i], lats[i], lons[i - 1], lats[i - 1])
        if speeds[i] < min_speed_ms and dist_to_prev < 5:
            mask[i] = False
            continue

        dist_to_next = _haversine_distance(lons[i], lats[i], lons[i + 1], lats[i + 1])
        if dist_to_prev > max_jump_m and dist_to_next > max_jump_m:
            mask[i] = False

    return df.loc[mask].copy()


def split_trips(df: pd.DataFrame, gap_minutes: int = 5) -> List[pd.DataFrame]:
    """按时间间隔切分为 trips"""
    if len(df) < 2:
        return []

    timestamps = df["timestamp"].values
    gaps = np.diff(timestamps).astype("timedelta64[m]").astype(int)
    split_indices = np.where(gaps > gap_minutes)[0] + 1

    segments = []
    start = 0
    for idx in split_indices:
        if idx - start >= 2:
            segments.append(df.iloc[start:idx].copy())
        start = idx
    if len(df) - start >= 2:
        segments.append(df.iloc[start:].copy())

    return segments


def _perpendicular_distance(point: Tuple[float, float],
                            line_start: Tuple[float, float],
                            line_end: Tuple[float, float]) -> float:
    """点到线段的垂直距离"""
    x0, y0 = point
    x1, y1 = line_start
    x2, y2 = line_end
    numerator = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denominator = sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)
    if denominator < 1e-12:
        return sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2)
    return numerator / denominator


def douglas_peucker(points: List[Tuple[float, float]], epsilon: float) \
        -> List[Tuple[float, float]]:
    """
    Douglas-Peucker 轨迹抽稀算法。

    Args:
        points: [(lon, lat), ...] 点序列
        epsilon: 距离阈值 (约 0.00009 = 10m)

    Returns:
        抽稀后的关键点列表
    """
    if len(points) <= 2:
        return points

    dmax = 0
    index = 0
    end = len(points) - 1
    for i in range(1, end):
        d = _perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        left = douglas_peucker(points[:index + 1], epsilon)
        right = douglas_peucker(points[index:], epsilon)
        return left[:-1] + right

    return [points[0], points[end]]


def preprocess_device(df: pd.DataFrame, min_speed_ms: float = 0.5,
                      max_jump_m: float = 500, trip_gap_minutes: int = 5,
                      dp_epsilon_m: float = 10) -> List[LineString]:
    """
    单台设备的完整预处理流水线。

    Returns:
        trip LineString 列表 (WGS-84)
    """
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = denoise_trajectory(df, min_speed_ms, max_jump_m)

    trip_dfs = split_trips(df, trip_gap_minutes)

    trips = []
    dp_epsilon_deg = dp_epsilon_m / 111000.0

    for trip_df in trip_dfs:
        points = list(zip(trip_df["lon"], trip_df["lat"]))
        simplified = douglas_peucker(points, dp_epsilon_deg)
        if len(simplified) >= 2:
            trips.append(LineString(simplified))

    return trips
