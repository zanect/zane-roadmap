"""
杭州路网获取：通过 osmnx 下载 OSM 路网，构建 NetworkX 图和相关映射表。
"""
import osmnx as ox
import networkx as nx
from typing import Dict, List, Tuple, Any


def download_hangzhou_network(highway_types: List[str]) -> nx.MultiDiGraph:
    """
    下载杭州行政区划内的道路网络。

    Args:
        highway_types: 要保留的道路类型

    Returns:
        NetworkX MultiDiGraph，节点含 'x' (lon) 和 'y' (lat) 属性
    """
    place_name = "杭州市, China"
    boundary = ox.geocode_to_gdf(place_name)
    polygon = boundary.geometry.union_all()
    G = ox.graph_from_polygon(polygon, network_type="drive")

    filter_func = lambda u, v, k, data: data.get("highway") in highway_types
    G_filtered = ox.utils_graph.graph_from_functions(
        G, filter_edges=filter_func
    )
    return G_filtered


def build_way_mapping(G: nx.MultiDiGraph) -> Dict[str, Dict[str, Any]]:
    """
    构建 way_id → 路段属性映射。

    Returns:
        {way_id: {
            'geometry': LineString,
            'length': float (m),
            'name': str,
            'highway': str,
            'nodes': [(node_id, lat, lon), ...],
        }}
    """
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
            "name": data.get("name", ""),
            "highway": data.get("highway", "unclassified"),
            "nodes": [
                (u, G.nodes[u]["y"], G.nodes[u]["x"]),
                (v, G.nodes[v]["y"], G.nodes[v]["x"]),
            ],
        }

    return way_map


def build_node_to_ways(G: nx.MultiDiGraph) -> Dict[int, set]:
    """
    构建 node_id → {way_id, ...} 的映射。

    用于匹配后将节点映射回 OSM way 进行统计。
    """
    node_ways: Dict[int, set] = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        way_id = str(data.get("osmid", f"{u}-{v}"))
        node_ways.setdefault(u, set()).add(way_id)
        node_ways.setdefault(v, set()).add(way_id)
    return node_ways


def load_road_network(config: dict) -> Tuple[nx.MultiDiGraph, Dict[str, Dict]]:
    """
    完整加载路网的入口函数。

    Returns:
        (graph, way_map)
    """
    highway_types = config["road_network"]["highway_types"]
    G = download_hangzhou_network(highway_types)
    way_map = build_way_mapping(G)
    return G, way_map
