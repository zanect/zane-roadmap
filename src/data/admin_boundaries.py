"""
Hangzhou district boundary download and road attribution.

Downloads district boundary polygons via Nominatim, caches as pickle,
spatially assigns each road to a district using midpoint containment.
"""
import time
import pickle
from pathlib import Path
from typing import Dict, List, Optional
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.prepared import prep


# 杭州市 13 个区县 (行政区划代码 3301)
HANGZHOU_DISTRICTS = [
    "上城区", "拱墅区", "西湖区", "滨江区", "萧山区",
    "余杭区", "富阳区", "临安区", "钱塘区", "临平区",
    "桐庐县", "淳安县", "建德市",
]


def download_boundaries(
    cache_path: str = "data/hangzhou_districts.pkl",
    force: bool = False,
) -> Dict[str, Polygon]:
    """
    下载杭州市各区县行政边界，缓存到本地。

    Returns:
        {区县名: Polygon}
    """
    cache_path = Path(cache_path)
    if not force and cache_path.exists():
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    import osmnx as ox

    boundaries = {}
    for name in HANGZHOU_DISTRICTS:
        place = f"{name}, 杭州市, China"
        try:
            gdf = ox.geocode_to_gdf(place)
            geom = gdf.geometry.iloc[0]
            if isinstance(geom, MultiPolygon):
                # 取面积最大的子多边形 (主城区)
                geom = max(geom.geoms, key=lambda g: g.area)
            boundaries[name] = geom
            print(f"  {name}: OK (area {geom.area*111000**2/1e6:.0f} km^2)")
        except Exception as e:
            print(f"  {name}: FAIL ({e})")
        time.sleep(1.2)  # Nominatim 限速

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(boundaries, f)

    print(f"  Cached {len(boundaries)} district boundaries -> {cache_path}")
    return boundaries


def assign_districts(
    way_map: dict,
    boundaries: Optional[Dict[str, Polygon]] = None,
) -> dict:
    """
    为每条道路标注所属区县。

    取道路 LineString 的中点做空间归属判断。
    如果中点不在任何区县多边形内（边界溢出），则找最近的多边形。

    Returns:
        增强后的 way_map，每条道路新增 'district' 字段
    """
    if boundaries is None:
        boundaries = download_boundaries()

    # 预编译多边形以加速 contains 查询
    prepared = {name: prep(poly) for name, poly in boundaries.items()}

    assigned = 0
    unassigned = 0

    for way_id, info in way_map.items():
        geom = info["geometry"]
        # 取中点
        mid = geom.interpolate(0.5, normalized=True)
        pt = Point(mid.x, mid.y)

        district = _find_containing(pt, prepared)
        if district is None:
            # 回退：找最近的多边形
            district = _find_nearest(pt, boundaries)
            unassigned += 1
        else:
            assigned += 1

        info["district"] = district

    total = len(way_map)
    print(f"  District assign: {assigned}/{total} direct hit, "
          f"{unassigned}/{total} nearest match")

    return way_map


def _find_containing(pt: Point, prepared: dict) -> Optional[str]:
    """查找包含该点的区县名。"""
    for name, poly in prepared.items():
        if poly.contains(pt):
            return name
    return None


def _find_nearest(pt: Point, boundaries: dict) -> str:
    """查找最近的区县名。"""
    best_name = ""
    best_dist = float("inf")
    for name, poly in boundaries.items():
        d = poly.distance(pt)
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name
