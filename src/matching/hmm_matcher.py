"""
单 trip 的 HMM 地图匹配。

使用 leuvenmapmatching 的 DistanceMatcher 将 trip LineString 匹配到路网节点。
"""
from dataclasses import dataclass, field
from typing import List, Optional
from shapely.geometry import LineString
from leuvenmapmatching.map.base import BaseMap
from leuvenmapmatching.matcher.distance import DistanceMatcher


@dataclass
class TripMatchResult:
    """单 trip 匹配结果"""
    trip_id: str = ""
    matched_nodes: List[int] = field(default_factory=list)
    matched_edges: List[tuple] = field(default_factory=list)
    match_ratio: float = 0.0


def trip_to_observations(trip: LineString) -> List[tuple]:
    """
    将 trip LineString 转换为观测序列 (lat, lon) 格式。
    leuvenmapmatching 使用 (lat, lon) 顺序。
    """
    coords = list(trip.coords)
    return [(lat, lon) for lon, lat in coords]


def match_trip(
    mmap: BaseMap,
    trip: LineString,
    observation_sigma: float = 10.0,
    min_matched_ratio: float = 0.3,
) -> Optional[TripMatchResult]:
    """
    对单个 trip 执行 HMM 地图匹配。

    Args:
        mmap: leuvenmapmatching 地图对象
        trip: trip 折线 (WGS-84)
        observation_sigma: 观测噪声标准差 (米)
        min_matched_ratio: 最小匹配比例

    Returns:
        匹配结果，或 None（匹配失败）
    """
    observations = trip_to_observations(trip)

    if len(observations) < 2:
        return None

    matcher = DistanceMatcher(
        mmap,
        max_dist_init=observation_sigma * 3,
        max_dist=observation_sigma * 2,
        obs_noise=observation_sigma,
        non_emitting_states=False,
        only_edges=False,
    )

    try:
        path, _ = matcher.match(observations, unique=False)
    except Exception:
        return None

    if not path:
        return None

    matched_count = len([n for n in path if n is not None])
    match_ratio = matched_count / len(observations) if observations else 0

    if match_ratio < min_matched_ratio:
        return None

    matched_nodes = [n for n in path if n is not None]
    matched_edges = [
        (matched_nodes[i], matched_nodes[i + 1])
        for i in range(len(matched_nodes) - 1)
    ]

    return TripMatchResult(
        trip_id="",
        matched_nodes=matched_nodes,
        matched_edges=matched_edges,
        match_ratio=match_ratio,
    )
