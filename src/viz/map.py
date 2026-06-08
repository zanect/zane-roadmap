"""
Folium 交互式地图可视化。

生成双图层 HTML 地图：
1. 覆盖率 Choropleth（红-黄-绿）
2. 覆盖密度（线宽映射）
"""
import pandas as pd
import folium
from shapely import wkt
from pathlib import Path


def _coverage_color(ratio: float) -> str:
    if ratio > 0.8:
        return "#2ecc71"
    elif ratio > 0.4:
        return "#f1c40f"
    else:
        return "#e74c3c"


def _density_weight(pass_count: int, max_count: int) -> float:
    if max_count == 0:
        return 2
    return 2 + (pass_count / max_count) * 8


def render_map(
    coverage_path: Path,
    output_path: Path,
    center_lat: float = 30.274,
    center_lon: float = 120.155,
) -> None:
    """生成可视化地图"""
    df = pd.read_parquet(coverage_path)
    df["geometry"] = df["geometry"].apply(wkt.loads)

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles="OpenStreetMap",
    )

    # 图层 1: 覆盖率
    coverage_layer = folium.FeatureGroup(name="覆盖率 (Coverage Ratio)", show=True)

    for _, row in df.iterrows():
        geom = row["geometry"]
        color = _coverage_color(row["coverage_ratio"])
        coords = [(lat, lon) for lon, lat in geom.coords]

        folium.PolyLine(
            coords, color=color, weight=3, opacity=0.8,
            popup=(
                f"<b>{row['road_name'] or '未命名道路'}</b><br>"
                f"覆盖率: {row['coverage_ratio']:.1%}<br>"
                f"通行次数: {row['pass_count']}<br>"
                f"道路等级: {row['highway_type']}"
            ),
        ).add_to(coverage_layer)

    coverage_layer.add_to(m)

    # 图层 2: 密度 (线宽映射)
    density_layer = folium.FeatureGroup(name="覆盖密度 (Pass Count)", show=False)
    max_count = int(df["pass_count"].max()) if len(df) > 0 else 1

    for _, row in df.iterrows():
        if row["pass_count"] == 0:
            continue

        geom = row["geometry"]
        weight = _density_weight(row["pass_count"], max_count)
        coords = [(lat, lon) for lon, lat in geom.coords]

        folium.PolyLine(
            coords, color="#3498db", weight=weight, opacity=0.7,
            popup=(
                f"<b>{row['road_name'] or '未命名道路'}</b><br>"
                f"通行次数: {row['pass_count']}<br>"
                f"覆盖率: {row['coverage_ratio']:.1%}"
            ),
        ).add_to(density_layer)

    density_layer.add_to(m)

    # 图例
    legend_html = """
    <div style="position:fixed;bottom:50px;left:50px;z-index:1000;
                background:white;padding:10px;border-radius:5px;
                border:1px solid #ccc;font-size:14px;">
      <b>图例 — 覆盖率</b><br>
      <span style="color:#2ecc71;">●</span> &gt;80% 覆盖良好<br>
      <span style="color:#f1c40f;">●</span> 40%–80% 部分覆盖<br>
      <span style="color:#e74c3c;">●</span> &lt;40% 覆盖不足<br>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl().add_to(m)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    print(f"地图已保存: {output_path}")
