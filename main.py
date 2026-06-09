"""
杭州路网覆盖率计算 — 主入口。

Usage:
    python main.py
    python main.py --csv data/trajectory.csv
    python main.py --config my_config.yaml
"""
import argparse
import time
import yaml
import pandas as pd
from pathlib import Path
import pickle

from src.data.road_network import load_road_network, build_node_to_ways
from src.data.trajectory import load_csv_to_parquet, convert_coordinates
from src.data.admin_boundaries import download_boundaries, assign_districts
from src.matching.graph import build_matching_map
from src.matching.parallel import run_map_matching
from src.stats.coverage import compute_coverage, save_results
from src.viz.map import render_map
from src.viz.trajectory_map import render_trajectory_map
from src.utils.logger import setup_logging


def parse_args():
    parser = argparse.ArgumentParser(description="杭州路网覆盖率计算")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--csv", help="CSV 轨迹文件路径")
    parser.add_argument("--force", action="store_true", help="强制重新下载路网")
    parser.add_argument("--coord", default="wgs84", choices=["wgs84", "gcj02"],
                        help="轨迹坐标系 (默认 wgs84)")
    return parser.parse_args()


def step_header(step: int, total: int, desc: str) -> float:
    """打印步骤头，返回开始时间"""
    print(f"\n{'='*60}")
    print(f"[{step}/{total}] {desc}")
    print(f"{'='*60}")
    return time.time()


def step_done(t_start: float, extra: str = "") -> None:
    elapsed = time.time() - t_start
    print(f"  ✓ 完成 ({elapsed:.0f}s){' — ' + extra if extra else ''}")


def main():
    t0 = time.time()
    args = parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # ── 初始化日志系统：所有输出重定向到文件 ──
    log_cfg = config.get("logging", {})
    log_path = setup_logging(
        log_dir=log_cfg.get("log_dir", "logs"),
        verbose=log_cfg.get("verbose", False),
    )

    csv_path = args.csv or config["trajectory"]["csv_path"]

    print(f"=== 杭州路网覆盖率计算 ===")
    print(f"数据: {csv_path}")

    # ── Step 1: 路网 ──
    t = step_header(1, 6, "下载杭州 OSM 路网 (osmnx)")
    print("  正在从 OpenStreetMap 下载...")
    G, way_map = load_road_network(config, force_download=args.force)
    step_done(t, f"{len(G.nodes):,} 节点, {len(way_map):,} 路段")

    node_to_ways = build_node_to_ways(G)
    pkl_path = Path("data") / "node_ways.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(node_to_ways, f)

    # ── 标注道路所属区县 ──
    print("  标注道路区县归属...")
    boundaries = download_boundaries("data/hangzhou_districts.pkl")
    way_map = assign_districts(way_map, boundaries)
    # 回写更新后的 way_map 到缓存
    waymap_pkl = Path("data") / "hangzhou_waymap.pkl"
    with open(waymap_pkl, "wb") as f:
        pickle.dump(way_map, f)

    # ── Step 2: 匹配图 ──
    t = step_header(2, 6, "构建 HMM 匹配图")
    print("  将 OSM 路网转换为 leuvenmapmatching 地图...")
    mmap_db_path = str(Path("data") / "matching_graph.db")
    mmap = build_matching_map(G, mmap_db_path, force_rebuild=args.force)
    step_done(t, f"db: {mmap_db_path}")

    # ── Step 3: CSV → Parquet + 坐标转换 ──
    t = step_header(3, 6, "CSV 加载 + 坐标转换")
    raw_path = load_csv_to_parquet(Path(csv_path), force=args.force)

    # # 输出原始坐标用于调试
    # _raw_df = pd.read_parquet(raw_path)
    # _raw_df[["lon", "lat"]].to_csv(
    #     Path("data/csv/test/origin_pos.csv"), index=False, header=False
    # )
    # print(f"  原始坐标已输出: data/csv/test/origin_pos.csv ({len(_raw_df)} 行)")

    coord_system = config.get("trajectory", {}).get("coord_system", args.coord)
    if coord_system == "gcj02":
        wgs84_path = convert_coordinates(raw_path, force=args.force)
    else:
        wgs84_path = raw_path  # 已是 WGS-84, 无需转换

    # # 输出转换后坐标用于调试
    # _wgs_df = pd.read_parquet(wgs84_path)
    # _wgs_df[["lon", "lat"]].to_csv(
    #     Path("data/csv/test/transform_pos.csv"), index=False, header=False
    # )
    # print(f"  转换后坐标已输出: data/csv/test/transform_pos.csv ({len(_wgs_df)} 行)")
    # if coord_system == "gcj02":
    #     _delta_lon = (_wgs_df["lon"] - _raw_df["lon"]).mean()
    #     _delta_lat = (_wgs_df["lat"] - _raw_df["lat"]).mean()
    #     print(f"  GCJ-02 → WGS-84 平均偏移: dlon={_delta_lon:.6f}°, dlat={_delta_lat:.6f}°")

    step_done(t, f"coord_system={coord_system}")

    # ── Step 4: 地图匹配 ──
    t = step_header(4, 6, "轨迹预处理 + 并行地图匹配")
    print("  降噪 → trip切分 → DP抽稀 → HMM匹配 → way映射")
    matched_df = run_map_matching(wgs84_path, mmap_db_path, config)
    matched_path = Path("data") / f"matched_trips_{config['date']}.parquet"
    matched_df.to_parquet(matched_path, index=False)
    step_done(t, f"{len(matched_df)} 条匹配记录")

    # ── Step 4.5: 设备-道路归属映射 ──
    print("  生成设备→道路→区县映射...")
    dev_road_df = _build_device_road_map(matched_df, way_map)
    dev_road_path = Path(config["output"]["dir"]) / "device_road_map.parquet"
    dev_road_df.to_parquet(dev_road_path, index=False)
    # 设备汇总
    dev_summary = (
        dev_road_df.groupby("device_id")
        .agg(
            road_count=("osm_way_id", "nunique"),
            district_count=("district", "nunique"),
            districts=("district", lambda x: ", ".join(sorted(set(x)))),
        )
        .reset_index()
    )
    dev_summary_path = Path(config["output"]["dir"]) / "device_summary.parquet"
    dev_summary.to_parquet(dev_summary_path, index=False)
    for _, row in dev_summary.iterrows():
        print(f"    {row['device_id']}: {row['road_count']} 条路, "
              f"{row['district_count']} 个区 ({row['districts']})")

    # ── Step 5: 统计 ──
    t = step_header(5, 6, "计算覆盖率 & 密度")
    print(f"  分段长度: {config['stats']['segment_length_m']}m")
    coverage_df = compute_coverage(
        matched_df, way_map,
        segment_length_m=config['stats']['segment_length_m'],
    )
    output_dir = Path(config["output"]["dir"])
    parquet_path = output_dir / config["output"]["parquet"]
    save_results(coverage_df, parquet_path)

    covered = (coverage_df["coverage_ratio"] > 0).sum()
    total_roads = len(coverage_df)
    step_done(t,
              f"{covered}/{total_roads} 路段有覆盖 "
              f"({covered/max(1,total_roads)*100:.1f}%), "
              f"平均覆盖率 {coverage_df['coverage_ratio'].mean():.1%}")

    # # ── Step 6: 覆盖率地图 ──
    t = step_header(6, 6, "生成覆盖率可视化")
    map_path = output_dir / config["output"]["map"]
    render_map(parquet_path, map_path)
    step_done(t, str(map_path))

    # ── Step 7: 轨迹地图 ──
    #t = step_header(7, 7, "生成设备轨迹可视化")
    #traj_map_path = output_dir / "trajectory_map.html"
    ## wgs84_path 数据已经是 WGS-84 坐标系（Step 3 已按 args.coord 处理）
    #render_trajectory_map(wgs84_path, traj_map_path)
    #step_done(t, str(traj_map_path))

    # ── 总结 ──
    total_time = time.time() - t0
    print(f"\n{'='*60}")
    print(f"全部完成 ({total_time:.0f}s)")
    print(f"日志文件: {log_path}")
    print(f"覆盖率结果: {parquet_path}")
    print(f"覆盖率地图: {map_path}")
    #print(f"轨迹地图: {traj_map_path}")


def _build_device_road_map(matched_df: pd.DataFrame, way_map: dict) -> pd.DataFrame:
    """
    构建设备→道路→区县映射表。

    从匹配结果中提取每台设备走过的每条道路，
    附带道路名称、等级、长度和所属区县。

    Returns:
        DataFrame with columns:
        device_id, osm_way_id, road_name, highway_type, road_length, district, pass_count
    """
    # 构建 way_id → (name, highway, length, district) 查找表
    way_info = {}
    for wid, info in way_map.items():
        key = str(wid)
        way_info[key] = (
            info.get("name", ""),
            info.get("highway", ""),
            info.get("length", 0),
            info.get("district", ""),
        )

    rows = []
    for (device_id, way_id), grp in matched_df.groupby(["device_id", "osm_way_id"]):
        way_id_str = str(way_id)
        info = way_info.get(way_id_str, ("", "", 0, ""))
        rows.append({
            "device_id": device_id,
            "osm_way_id": way_id_str,
            "road_name": info[0],
            "highway_type": info[1],
            "road_length": info[2],
            "district": info[3],
            "pass_count": len(grp),
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
