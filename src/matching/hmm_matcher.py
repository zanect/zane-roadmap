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
    max_dist_init: float = 500.0,
    max_dist: float = 300.0,
    max_lattice_width: int = 20,
    min_matched_ratio: float = 0.15,
    verbose: bool = False,
) -> Optional[TripMatchResult]:
    """
    对单个 trip 执行 HMM 地图匹配。

    Args:
        mmap: leuvenmapmatching 地图对象
        trip: trip 折线 (WGS-84)
        observation_sigma: 观测噪声标准差 (米), 默认 25m (GPS 精度)
        max_dist_init: 首个观测点的最大搜索半径 (米)，需足够大以容忍初始偏航
        max_dist: 匹配过程中的硬截断距离 (米)
        max_lattice_width: 每观测点最多候选状态数，限制 HMM 格点规模
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
        max_dist_init=max_dist_init,
        max_dist=max_dist,
        obs_noise=observation_sigma,
        max_lattice_width=max_lattice_width,
        non_emitting_states=True,              # 允许跳过无法匹配的点
    )

    try:
        path, _ = matcher.match(observations, unique=False)
    except Exception as e:
        if verbose:
            print(f"异常: {e}")
        return None

    if verbose:
        elapsed = time.time() - t0
        n_edges = len([n for n in path if n is not None])
        n_obs = len(observations)
        print(f"{n_edges}/{n_obs} 匹配 ({elapsed:.1f}s)")

    if not path:
        return None

    matched_edges = [n for n in path if n is not None]  # 每条是 (u, v) 边元组
    match_ratio = len(matched_edges) / len(observations) if observations else 0

    if match_ratio < min_matched_ratio:
        return None

    # 提取途径节点序列
    matched_nodes: List[int] = []
    for i, edge in enumerate(matched_edges):
        u, v = edge
        if i == 0:
            matched_nodes.append(u)
        matched_nodes.append(v)

    return TripMatchResult(
        trip_id="",
        matched_nodes=matched_nodes,
        matched_edges=matched_edges,
        match_ratio=match_ratio,
    )
