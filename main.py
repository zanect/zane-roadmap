"""
杭州路网覆盖率计算 — 主入口。

Usage:
    python main.py                          # 使用 config.yaml 默认配置
    python main.py --csv data/trajectory.csv # 指定 CSV 文件
    python main.py --config my_config.yaml  # 指定配置文件
"""
import argparse
import yaml
from pathlib import Path
import pickle

from src.data.road_network import load_road_network, build_node_to_ways
from src.data.trajectory import load_csv_to_parquet, convert_coordinates
from src.matching.graph import build_matching_map
from src.matching.parallel import run_map_matching
from src.stats.coverage import compute_coverage, save_results
from src.viz.map import render_map


def parse_args():
    parser = argparse.ArgumentParser(description="杭州路网覆盖率计算")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--csv", help="CSV 轨迹文件路径 (覆盖配置文件)")
    return parser.parse_args()


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    args = parse_args()
    config = load_config(args.config)

    csv_path = args.csv or config["trajectory"]["csv_path"]

    print(f"=== 杭州路网覆盖率计算 ===")
    print(f"CSV 数据: {csv_path}")

    # Step 1: 获取路网
    print("\n[1/6] 下载杭州路网...")
    G, way_map = load_road_network(config)
    print(f"  节点: {len(G.nodes)}, 路段: {len(way_map)}")

    node_to_ways = build_node_to_ways(G)
    pkl_path = Path("data") / f"node_ways_{config['date']}.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(node_to_ways, f)

    # Step 2: 构建匹配图
    print("\n[2/6] 构建匹配图...")
    mmap_db_path = str(Path("data") / f"matching_graph_{config['date']}.db")
    mmap = build_matching_map(G, mmap_db_path)
    print(f"  匹配图已保存: {mmap_db_path}")

    # Step 3: CSV → Parquet + 坐标转换
    print("\n[3/6] 加载 CSV 并转换坐标系...")
    raw_path = load_csv_to_parquet(Path(csv_path))
    print(f"  Parquet: {raw_path}")
    wgs84_path = convert_coordinates(raw_path)
    print(f"  WGS-84: {wgs84_path}")

    # Step 4: 地图匹配 (内部已包含预处理)
    print("\n[4/6] 并行地图匹配 (降噪 + trip切分 + HMM匹配)...")
    matched_df = run_map_matching(wgs84_path, mmap_db_path, config)
    matched_path = Path("data") / f"matched_trips_{config['date']}.parquet"
    matched_df.to_parquet(matched_path, index=False)
    print(f"  匹配结果: {matched_path} ({len(matched_df)} 条记录)")

    # Step 5: 统计计算
    print("\n[5/6] 计算覆盖率 & 密度...")
    coverage_df = compute_coverage(
        matched_df, way_map,
        segment_length_m=config["stats"]["segment_length_m"],
    )
    output_dir = Path(config["output"]["dir"])
    parquet_path = output_dir / config["output"]["parquet"]
    save_results(coverage_df, parquet_path)

    covered = (coverage_df["coverage_ratio"] > 0).sum()
    total = len(coverage_df)
    print(f"  路段总数: {total}")
    print(f"  有覆盖路段: {covered} ({covered/total*100:.1f}%)")
    print(f"  平均覆盖率: {coverage_df['coverage_ratio'].mean():.1%}")
    print(f"  结果已保存: {parquet_path}")

    # Step 6: 可视化
    print("\n[6/6] 生成可视化地图...")
    map_path = output_dir / config["output"]["map"]
    render_map(parquet_path, map_path)
    print(f"  地图: {map_path}")

    print(f"\n=== 完成 ===")
    print(f"结果: {parquet_path}")
    print(f"地图: {map_path}")


if __name__ == "__main__":
    main()
