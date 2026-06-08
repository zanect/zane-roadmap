"""
杭州路网获取：通过 osmnx 下载 OSM 路网，构建 NetworkX 图和相关映射表。

首次下载后缓存到 data/ 目录，后续运行直接加载（秒级）。
"""
import pickle
import osmnx as ox
import networkx as nx
from pathlib import Path
from typing import Dict, List, Tuple, Any

CACHE_DIR = Path("data")
CACHE_GRAPH = CACHE_DIR / "hangzhou_graph.pkl"
CACHE_WAYMAP = CACHE_DIR / "hangzhou_waymap.pkl"

# 可用的 Overpass API 端点
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def download_hangzhou_network(
    highway_types: List[str],
    overpass_endpoint: str = None,
) -> nx.MultiDiGraph:
    """下载 + 过滤杭州路网"""
    place_name = "杭州市, China"
    print(f"  地理编码: {place_name}...")
    boundary = ox.geocode_to_gdf(place_name)
    polygon = boundary.geometry.union_all()

    endpoints = [overpass_endpoint] if overpass_endpoint else OVERPASS_MIRRORS

    G = None
    for i, endpoint in enumerate(endpoints):
        ox.settings.overpass_endpoint = endpoint
        try:
            print(f"  从 Overpass 下载路网 ({endpoint.split('/')[2]})...")
            G = ox.graph_from_polygon(polygon, network_type="drive")
            print(f"  原始路网: {len(G.nodes):,} 节点, {len(G.edges):,} 边")
            break
        except Exception as e:
            if i >= len(endpoints) - 2:
                print(f"  端点不可用: {e}")
            continue

    if G is None:
        raise RuntimeError("所有 Overpass 端点均不可用")

    # 过滤道路类型
    remove_edges = [
        (u, v, k) for u, v, k, data in G.edges(keys=True, data=True)
        if data.get("highway") not in highway_types
    ]
    G.remove_edges_from(remove_edges)
    print(f"  过滤后: {len(G.nodes):,} 节点, {len(G.edges):,} 边")
    return G


def load_road_network(config: dict, force_download: bool = False) \
        -> Tuple[nx.MultiDiGraph, Dict[str, Dict]]:
    """
    加载路网（带缓存）。

    - 缓存命中 → 直接加载（~2 秒）
    - 缓存未命中 → 下载 + 缓存（~30 秒，首次）
    - force_download=True → 强制重新下载
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not force_download and CACHE_GRAPH.exists() and CACHE_WAYMAP.exists():
        print(f"[路网] 加载缓存: {CACHE_GRAPH}")
        with open(CACHE_GRAPH, "rb") as f:
            G = pickle.load(f)
        with open(CACHE_WAYMAP, "rb") as f:
            way_map = pickle.load(f)
        print(f"  路网: {len(G.nodes):,} 节点, {len(way_map):,} 路段")
        return G, way_map

    print("[路网] 首次下载（后续将使用缓存）...")
    highway_types = config["road_network"]["highway_types"]
    endpoint = config["road_network"].get("overpass_endpoint", None)
    G = download_hangzhou_network(highway_types, overpass_endpoint=endpoint)
    way_map = build_way_mapping(G)

    # 缓存
    with open(CACHE_GRAPH, "wb") as f:
        pickle.dump(G, f)
    with open(CACHE_WAYMAP, "wb") as f:
        pickle.dump(way_map, f)
    print(f"  已缓存: {CACHE_GRAPH}, {CACHE_WAYMAP}")

    return G, way_map


def _safe_name(val) -> str:
    """OSM name 可能是 str / list / None → 统一转 str"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return val[0] if val else ""
    return str(val)


def build_way_mapping(G: nx.MultiDiGraph) -> Dict[str, Dict[str, Any]]:
    """构建 way_id → 路段属性映射"""
    from shapely.geometry import LineString

    way_map = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        way_id = str(data.get("osmid", f"{u}-{v}"))
        if way_id in way_map:
            continue
        geometry = data.get("geometry", None)
        if geometry is None:
            u_data = G.nodes[u]
            v_data = G.nodes[v]
            geometry = LineString([
                (u_data["x"], u_data["y"]),
                (v_data["x"], v_data["y"]),
            ])
        way_map[way_id] = {
            "geometry": geometry,
            "length": data.get("length", geometry.length * 111000),
            "name": _safe_name(data.get("name", "")),
            "highway": data.get("highway", "unclassified"),
            "nodes": [
                (u, G.nodes[u]["y"], G.nodes[u]["x"]),
                (v, G.nodes[v]["y"], G.nodes[v]["x"]),
            ],
        }
    return way_map


def build_node_to_ways(G: nx.MultiDiGraph) -> Dict[int, set]:
    """构建 node_id → {way_id, ...} 映射"""
    node_ways: Dict[int, set] = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        way_id = str(data.get("osmid", f"{u}-{v}"))
        node_ways.setdefault(u, set()).add(way_id)
        node_ways.setdefault(v, set()).add(way_id)
    return node_ways
