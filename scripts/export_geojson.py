"""
将 data/hangzhou_graph.pkl 导出为 QGIS 可读的 GeoJSON 文件。
Output: data/hangzhou_network.geojson
"""
import pickle
import json
from pathlib import Path

GRAPH_PATH = Path("data/hangzhou_graph.pkl")
OUTPUT_PATH = Path("data/hangzhou_network.geojson")


def export():
    print(f"加载 {GRAPH_PATH}...")
    with open(GRAPH_PATH, "rb") as f:
        G = pickle.load(f)

    print(f"  节点: {len(G.nodes):,}, 边: {len(G.edges):,}")

    features = []
    seen = set()

    for u, v, k, data in G.edges(keys=True, data=True):
        osmid = data.get("osmid")
        if isinstance(osmid, list):
            osmid = osmid[0] if osmid else None
        dedup_key = str(osmid) if osmid is not None else f"{u}-{v}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        geom = data.get("geometry")
        if geom is None:
            # 没有几何属性，用首尾节点坐标构建直线
            from shapely.geometry import LineString
            u_data = G.nodes[u]
            v_data = G.nodes[v]
            geom = LineString([
                (u_data["x"], u_data["y"]),
                (v_data["x"], v_data["y"]),
            ])

        coords = [(lng, lat) for lng, lat in geom.coords]
        if len(coords) < 2:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "osmid": str(osmid) if osmid is not None else f"{u}-{v}",
                "highway": data.get("highway", ""),
                "name": data.get("name", ""),
                "length": data.get("length", 0),
                "oneway": data.get("oneway", False),
                "maxspeed": data.get("maxspeed", ""),
                "lanes": data.get("lanes", ""),
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"导出完成: {OUTPUT_PATH}")
    print(f"  {len(features)} 条路段 → GeoJSON FeatureCollection")


if __name__ == "__main__":
    export()
