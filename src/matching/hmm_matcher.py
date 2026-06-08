"""
单 trip 的 HMM 地图匹配。

使用 leuvenmapmatching 的 DistanceMatcher 将 trip LineString 匹配到路网节点。
"""
import time
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
    coords = list(trip.coords)
    return [(lat, lon) for lon, lat in coords]


def match_trip(
    mmap: BaseMap,
    trip: LineString,
    observation_sigma: float = 25.0,
    min_matched_ratio: float = 0.3,
    verbose: bool = False,
) -> Optional[TripMatchResult]:
    """
    对单个 trip 执行 HMM 地图匹配。

    Args:
        mmap: leuvenmapmatching 地图对象
        trip: trip 折线 (WGS-84)
        observation_sigma: 观测噪声标准差 (米), 默认 25m (GPS 精度)
        min_matched_ratio: 最小匹配比例
        verbose: 是否打印内部耗时
    """
    observations = trip_to_observations(trip)

    if len(observations) < 2:
        return None

    if verbose:
        print(f"    HMM匹配: {len(observations)} 个观测点...", end=" ", flush=True)
        t0 = time.time()

    matcher = DistanceMatcher(
        mmap,
        max_dist_init=observation_sigma * 3,   # 75m 搜索半径
        max_dist=observation_sigma * 3,
        obs_noise=observation_sigma,
        non_emitting_states=True,              # 允许跳过无法匹配的点
        only_edges=False,
    )

    try:
        path, _ = matcher.match(observations, unique=False)
    except Exception as e:
        if verbose:
            print(f"异常: {e}")
        return None

    if verbose:
        elapsed = time.time() - t0
        matched = len([n for n in path if n is not None])
        print(f"{matched}/{len(observations)} 匹配 ({elapsed:.1f}s)")

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
