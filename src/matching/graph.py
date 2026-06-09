"""
将 OSM NetworkX 路网转换为 leuvenmapmatching 的 SqliteMap 对象。

使用 bulk API (add_nodes/add_edges) 批量写入，代替逐条 add_node/add_edge，
避免每次 SQLite COMMIT 触发 fsync。82k 节点 + 138k 边从 ~10 分钟降至 ~10 秒。
"""
import networkx as nx
from typing import List, Tuple, Set
from pathlib import Path
from leuvenmapmatching.map.sqlite import SqliteMap


def build_matching_map(
    G: nx.MultiDiGraph,
    db_path: str = "data/matching_graph.db",
    force_rebuild: bool = False,
) -> SqliteMap:
    """构建 leuvenmapmatching SqliteMap (bulk 写入 + 缓存)"""
    db_path = str(Path(db_path).resolve())
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # 缓存命中 → 直接加载 (避免重建)
    if not force_rebuild and Path(db_path).exists():
        from leuvenmapmatching.map.sqlite import SqliteMap as SM
        print(f"  加载缓存: {db_path}")
        p = Path(db_path)
        mmap = SM(p.name, dir=str(p.parent), use_latlon=True, deserializing=True)
        if mmap.size() > 0:
            return mmap
        # 缓存损坏 (空库) → 删除并重建
        print(f"  缓存为空，删除并重建: {db_path}")
        mmap.db.close()
        Path(db_path).unlink()

    # 删除旧文件 (避免 SqliteMap 构造函数覆盖写入时的潜在问题)
    if Path(db_path).exists():
        Path(db_path).unlink()

    mmap = SqliteMap(db_path, use_latlon=True)

    total_nodes = len(G.nodes)
    total_edges = len(G.edges)
    print(f"  路网: {total_nodes:,} 节点, {total_edges:,} 边")

    # ── Phase 1: 收集所有 OSM 节点 ──
    print(f"  收集节点...", end=" ", flush=True)
    osm_nodes: List[Tuple[int, Tuple[float, float]]] = [
        (node_id, (data["y"], data["x"]))
        for node_id, data in G.nodes(data=True)
    ]
    print(f"{len(osm_nodes):,} 个")

    # ── Phase 2: 收集边 + 曲线中间节点 ──
    print(f"  收集边 + 中间节点...", end=" ", flush=True)
    edges_added: Set[tuple] = set()
    osm_edges: List[Tuple[int, int]] = []
    extra_nodes: List[Tuple[int, Tuple[float, float]]] = []
    extra_edges: List[Tuple[int, int]] = []
    next_id = -1  # 递减计数器，避免与正 ID 冲突

    for u, v, k, data in G.edges(keys=True, data=True):
        edge_key = (min(u, v), max(u, v))
        if edge_key in edges_added:
            continue
        edges_added.add(edge_key)
        osm_edges.append((u, v))

        geom = data.get("geometry")
        if geom is not None:
            coords = list(geom.coords)
            if len(coords) > 2:
                # 曲线段：拆分中间节点 + 边
                prev = u
                for coord in coords[1:-1]:
                    mid = next_id
                    next_id -= 1
                    extra_nodes.append((mid, (coord[1], coord[0])))
                    extra_edges.append((prev, mid))
                    prev = mid
                extra_edges.append((prev, v))
    print(f"{len(osm_edges):,} OSM 边 + {len(extra_nodes):,} 中间节点 + {len(extra_edges):,} 中间边")

    # ── Phase 3: 批量写入 ──
    all_nodes = osm_nodes + extra_nodes
    all_edges = osm_edges + extra_edges

    print(f"  批量写入 {len(all_nodes):,} 节点...", end=" ", flush=True)
    mmap.add_nodes(all_nodes)       # 1 次 COMMIT
    print("完成")

    print(f"  批量写入 {len(all_edges):,} 边...", end=" ", flush=True)
    mmap.add_edges(all_edges)       # 1 次 COMMIT
    print("完成")

    # ── Phase 4: 索引 ──
    print(f"  构建空间索引...", end=" ", flush=True)
    mmap.reindex_edges()
    print("完成")

    return mmap
