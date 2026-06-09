"""
单 trip 的 HMM 地图匹配。

使用 leuvenmapmatching 的 DistanceMatcher 将 trip LineString 匹配到路网节点。
"""
import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
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


def _find_first_matchable(
    observations: List[tuple],
    mmap: BaseMap,
    search_dist: float,
    max_skip_ratio: float = 0.5,
) -> Tuple[List[tuple], int]:
    """
    从观测序列头部跳过不在路网范围内的点，返回裁剪后的序列和跳过的点数。

    处理场景：设备从路网外（如外市）出发，前段 GPS 点无对应道路。
    对高频采样数据，每隔 5 个点检查一次，找到路网内点后再精确回退定位。

    search_dist 应使用与 matcher 验证距离一致的半径 (即 max_dist，不是 max_dist_init)。
    """
    n = len(observations)
    max_skip = int(n * max_skip_ratio)
    if max_skip < 1:
        return observations, 0

    # Step 1: 大步长跳跃扫描
    step = 5
    found_idx = -1
    for i in range(0, min(max_skip, n - 1), step):
        edges = mmap.edges_closeto(observations[i], max_dist=search_dist)
        if len(edges) > 0:
            found_idx = i
            break

    if found_idx < 0:
        for i in range(min(max_skip, n - 1)):
            edges = mmap.edges_closeto(observations[i], max_dist=search_dist)
            if len(edges) > 0:
                found_idx = i
                break

    if found_idx <= 0:
        return observations, 0
    if found_idx >= n - 2:
        return observations[found_idx:], found_idx

    # Step 2: 向前精确定位
    for i in range(max(0, found_idx - step), found_idx):
        edges = mmap.edges_closeto(observations[i], max_dist=search_dist)
        if len(edges) > 0:
            return observations[i:], i

    return observations[found_idx:], found_idx


def match_trip(
    mmap: BaseMap,
    trip: LineString,
    observation_sigma: float = 30.0,
    dist_noise: float = 50.0,
    max_dist_init: float = 900.0,
    max_dist: float = 300.0,
    max_lattice_width: int = 40,
    min_matched_ratio: float = 0.05,
    non_emitting_states_maxnb: int = 40,
    ne_length_factor: float = 0.75,
    goback_on_edge_factor: float = 0.7,
    goback_to_edge_factor: float = 0.7,
    not_connected_edges_factor: float = 0.6,
    verbose: bool = False,
) -> Tuple[Optional[TripMatchResult], str]:
    """
    对单个 trip 执行 HMM 地图匹配。

    Args:
        mmap: leuvenmapmatching 地图对象
        trip: trip 折线 (WGS-84)
        observation_sigma: 观测噪声标准差 (米)，默认 30m
        dist_noise: 转移概率中的距离差噪声 (米)，默认 50m
        max_dist_init: 首个观测点的最大搜索半径 (米)，默认 700m
        max_dist: 匹配过程中的硬截断距离 (米)，默认 150m
        max_lattice_width: 每观测点最多候选状态数
        min_matched_ratio: 最小匹配比例
        non_emitting_states_maxnb: 最大连续非发射步数
        ne_length_factor: 非发射状态长度惩罚因子 (0-1, 越小惩罚越重)
        goback_on_edge_factor: 同路段回头惩罚因子 (0-1)
        goback_to_edge_factor: 返回已访问路段惩罚因子 (0-1)
        not_connected_edges_factor: 非连通路段跳转惩罚因子 (0-1)
        verbose: 是否打印内部耗时

    Returns:
        (TripMatchResult, "") 匹配成功
        (None, reason) 匹配失败及原因
    """
    observations = trip_to_observations(trip)

    if len(observations) < 2:
        return None, "too_few_observations"

    # ── 自适应起点裁剪：跳过不在路网范围内的前导观测点 ──
    # 注意：使用 max_dist (不是 max_dist_init) 作为验证半径，
    # 因为 leuvenmapmatching 的 do_stop() 使用 max_dist 校验所有候选 (含起始点)。
    observations, skipped = _find_first_matchable(observations, mmap, max_dist)

    if len(observations) < 2:
        return None, f"all_points_outside_network(skipped={skipped})"

    if verbose:
        t0 = time.time()
        skip_msg = f"(跳过前{skipped}点) " if skipped > 0 else ""
        print(f"    HMM匹配: {len(observations)} 个观测点... {skip_msg}", end=" ", flush=True)

    matcher = DistanceMatcher(
        mmap,
        max_dist_init=max_dist_init,
        max_dist=max_dist,
        obs_noise=observation_sigma,
        obs_noise_ne=observation_sigma * 2,
        dist_noise=dist_noise,
        dist_noise_ne=dist_noise,
        max_lattice_width=max_lattice_width,
        non_emitting_states=True,
    )

    # ── 非发射状态控制 ──
    matcher.non_emitting_states_maxnb = non_emitting_states_maxnb
    matcher.ne_length_factor_log = math.log(ne_length_factor)

    # ── 转移惩罚因子 (调宽松以减少 GPS 漂移/路网断连导致的误判) ──
    matcher.gobackonedge_factor_log = math.log(goback_on_edge_factor)
    matcher.gobacktoedge_factor_log = math.log(goback_to_edge_factor)
    matcher.notconnectededges_factor_log = math.log(not_connected_edges_factor)

    try:
        path, last_idx = matcher.match(observations, unique=False)
    except Exception as e:
        if verbose:
            print(f"异常: {e}")
        return None, f"exception:{e}"

    if verbose:
        elapsed = time.time() - t0
        n_edges = len([n for n in path if n is not None])
        n_obs = len(observations)
        if last_idx < len(observations) - 1:
            print(f"提前终止@obs[{last_idx}], {n_edges}/{n_obs} 匹配 ({elapsed:.1f}s)")
        else:
            print(f"{n_edges}/{n_obs} 匹配 ({elapsed:.1f}s)")

    if not path:
        if last_idx == 0:
            return None, "no_start_edge"
        return None, "early_stop"

    matched_edges = [n for n in path if n is not None]
    match_ratio = len(matched_edges) / len(observations) if observations else 0

    if match_ratio < min_matched_ratio:
        return None, f"low_match_ratio:{match_ratio:.2f}"

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
    ), ""
