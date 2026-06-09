"""
设备轨迹可视化。

读取 WGS-84 坐标系的轨迹 Parquet，渲染到 OSM 底图上。
"""
import pandas as pd
import folium
from pathlib import Path


def render_trajectory_map(
    trajectory_parquet: Path,
    output_path: Path,
) -> None:
    """
    Args:
        trajectory_parquet: WGS-84 坐标系轨迹 Parquet (device_id, lon, lat, timestamp)
        output_path: 输出 HTML 路径
    """
    print("[traj-map] Loading trajectory (WGS-84)...")
    traj_df = pd.read_parquet(trajectory_parquet)

    print(f"[traj-map] lon [{traj_df['lon'].min():.4f}, {traj_df['lon'].max():.4f}], "
          f"lat [{traj_df['lat'].min():.4f}, {traj_df['lat'].max():.4f}]")

    # Center on trajectory
    center_lat = (traj_df["lat"].min() + traj_df["lat"].max()) / 2
    center_lon = (traj_df["lon"].min() + traj_df["lon"].max()) / 2

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=11,
        tiles="CartoDB positron",
    )

    # Render trajectory per device
    print("[traj-map] Rendering trajectory...")
    traj_layer = folium.FeatureGroup(name="Device Trajectory", show=True)

    device_ids = traj_df["device_id"].unique()
    all_coords = []

    for device_id in device_ids:
        dev_df = traj_df[traj_df["device_id"] == device_id].sort_values("timestamp")
        # Downsample if >5000 points
        step = max(1, len(dev_df) // 5000)
        sampled = dev_df.iloc[::step]
        coords = [(lat, lon) for lon, lat in zip(sampled["lon"], sampled["lat"])]
        all_coords.extend(coords)

        folium.PolyLine(
            coords, color="#27ae60", weight=2.5, opacity=0.8,
            popup=f"Device: {device_id}<br>Points: {len(dev_df)}",
        ).add_to(traj_layer)

        if len(coords) >= 1:
            folium.CircleMarker(
                coords[0], radius=6, color="white",
                fill=True, fill_color="#3498db", fill_opacity=1,
                popup=f"Start: {device_id}",
            ).add_to(traj_layer)
        if len(coords) >= 2:
            folium.CircleMarker(
                coords[-1], radius=6, color="white",
                fill=True, fill_color="#e74c3c", fill_opacity=1,
                popup=f"End: {device_id}",
            ).add_to(traj_layer)

    traj_layer.add_to(m)

    if len(all_coords) >= 2:
        m.fit_bounds(all_coords, padding=(30, 30))

    print(f"[traj-map] {len(device_ids)} devices, {len(all_coords):,} points")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    print(f"[traj-map] Saved: {output_path}")
