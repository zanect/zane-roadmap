"""
将 OSM NetworkX 路网转换为 leuvenmapmatching 的 SqliteMap 对象。
"""
import networkx as nx
from typing import Dict, Set
from leuvenmapmatching.map.sqlite import SqliteMap


def build_matching_map(
    G: nx.MultiDiGraph,
    db_path: str = "data/matching_graph.db",
) -> SqliteMap:
    """
    构建 leuvenmapmatching 的 SqliteMap。

    Args:
        G: OSM NetworkX MultiDiGraph
        db_path: 地图数据库路径

    Returns:
        leuvenmapmatching SqliteMap 对象
    """
    mmap = SqliteMap(
        db_path,
        use_latlon=True,
        index_edges=True,
        sync_session=False,
    )

    nodes_added: Set[int] = set()
    for node_id, data in G.nodes(data=True):
        if node_id not in nodes_added:
            mmap.add_node(node_id, (data["y"], data["x"]))
            nodes_added.add(node_id)

    edges_added: Set[tuple] = set()
    for u, v, k, data in G.edges(keys=True, data=True):
        edge_key = (min(u, v), max(u, v))
        if edge_key not in edges_added:
            mmap.add_edge(u, v)
            geom = data.get("geometry")
            if geom is not None:
                _add_intermediate_nodes(mmap, u, v, geom)
            edges_added.add(edge_key)

    return mmap


def _add_intermediate_nodes(mmap: SqliteMap, u: int, v: int,
                            geom) -> None:
    """沿路段几何添加中间节点以提高匹配精度"""
    coords = list(geom.coords)
    if len(coords) <= 2:
        return

    prev_node = u
    for i, coord in enumerate(coords[1:-1], start=0):
        node_id = -(u * 10000 + i)  # 负 ID 避免冲突
        mmap.add_node(node_id, (coord[1], coord[0]))
        mmap.add_edge(prev_node, node_id)
        prev_node = node_id

    mmap.add_edge(prev_node, v)
