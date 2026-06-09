"""
Folium 交互式地图可视化。

生成三层 HTML 地图：
1. 全路网背景（灰白色，80% 透明度）
2. 覆盖路段（深蓝色，深浅对应 pass_count 频次）
3. 图例
"""
import pandas as pd
import folium
from shapely import wkt
from pathlib import Path
import numpy as np


def _blue_intensity(pass_count: int, max_count: int) -> tuple:
    """pass_count → (color, opacity, weight)

    频次越高蓝色越深、线越粗。
    """
    if max_count <= 1:
        return "#1a237e", 0.75, 4

    # 对数映射，避免长尾被极值压扁
    log_p = np.log1p(pass_count)
    log_max = np.log1p(max_count)
    t = log_p / log_max  # 0..1

    # 深蓝渐变: 浅蓝(#64b5f6) → 深蓝(#0d47a1)
    r = int(100 - t * 87)       # 100 → 13
    g = int(181 - t * 111)      # 181 → 70
    b = int(246 - t * 85)       # 246 → 161
    color = f"#{r:02x}{g:02x}{b:02x}"

    opacity = 0.40 + t * 0.55   # 0.40 → 0.95
    weight = 3.0 + t * 5.0      # 3.0 → 8.0
    return color, opacity, weight


def render_map(
    coverage_path: Path,
    output_path: Path,
    center_lat: float = 30.274,
    center_lon: float = 120.155,
) -> None:
    """生成覆盖率可视化地图"""
    df = pd.read_parquet(coverage_path)
    df["geometry"] = df["geometry"].apply(wkt.loads)

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles="CartoDB positron",
    )

    # ── 图层 1: 全路网背景 (灰色细线) ──
    bg_layer = folium.FeatureGroup(name="全路网 (背景)", show=True)
    for _, row in df.iterrows():
        coords = [(lat, lon) for lon, lat in row["geometry"].coords]
        folium.PolyLine(
            coords,
            color="#9e9e9e",
            weight=1.5,
            opacity=0.30,
        ).add_to(bg_layer)
    bg_layer.add_to(m)

    # ── 图层 2: 匹配覆盖路段 (深蓝色，频次深浅) ──
    matched = df[df["pass_count"] > 0]
    cov_layer = folium.FeatureGroup(name="覆盖路段 (频次深浅)", show=True)

    max_count = int(matched["pass_count"].max()) if len(matched) > 0 else 1

    for _, row in matched.iterrows():
        geom = row["geometry"]
        coords = [(lat, lon) for lon, lat in geom.coords]
        color, opacity, weight = _blue_intensity(row["pass_count"], max_count)

        popup_text = (
            f"<b>{row['road_name'] or '未命名道路'}</b><br>"
            f"覆盖频次: {row['pass_count']}<br>"
            f"覆盖率: {row['coverage_ratio']:.1%}<br>"
            f"道路等级: {row['highway_type']}"
        )

        folium.PolyLine(
            coords,
            color=color,
            weight=weight,
            opacity=opacity,
            popup=popup_text,
        ).add_to(cov_layer)

    cov_layer.add_to(m)

    # ── 图例 ──
    legend_html = f"""
    <div style="position:fixed;bottom:50px;left:50px;z-index:1000;
                background:white;padding:10px;border-radius:5px;
                border:1px solid #ccc;font-size:13px;">
      <b>图例 — 覆盖频次</b><br>
      <span style="color:#64b5f6;font-size:16px;">━━</span> 低频 (1次)<br>
      <span style="color:#1565c0;font-size:16px;">━━</span> 中频<br>
      <span style="color:#0d47a1;font-size:16px;">━━</span> 高频 ({max_count}次)<br>
      <hr style="margin:4px 0;">
      <span style="color:#9e9e9e;font-size:16px;">━━</span> 未覆盖路网
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl().add_to(m)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    print(f"地图已保存: {output_path}")
