"""
多进程并行地图匹配 + tqdm 进度展示。

大文件优化：按设备批次流式读取，不将全量数据加载到内存。
"""
import pandas as pd
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from pathlib import Path
import pickle
import traceback


def match_device_batch(
    device_ids: List[str],
    parquet_path: str,
    mmap_db_path: str,
    config: dict,
) -> List[Dict[str, Any]]:
    """
    子进程中执行一批设备的匹配 (独立进程入口)。

    进程内自行读取数据，避免通过 pickle 传递大 DataFrame。
    """
    from leuvenmapmatching.map.sqlite import SqliteMap
    from src.preprocess.clean import preprocess_device
    from src.matching.hmm_matcher import match_trip
    import duckdb

    mmap = SqliteMap(mmap_db_path, use_latlon=True)
    preprocess_cfg = config["preprocess"]
    matching_cfg = config["matching"]
    all_results = []

    # 子进程内按需加载本批次数据
    ids_str = ", ".join(f"'{d}'" for d in device_ids)
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT * FROM '{parquet_path}'
        WHERE device_id IN ({ids_str})
        ORDER BY device_id, timestamp
    """).df()
    con.close()

    for device_id, device_df in df.groupby("device_id"):
        trips = preprocess_device(
            device_df,
            min_speed_ms=preprocess_cfg["min_speed_ms"],
            max_jump_m=preprocess_cfg["max_jump_m"],
            trip_gap_minutes=preprocess_cfg["trip_gap_minutes"],
            dp_epsilon_m=preprocess_cfg["dp_epsilon_m"],
        )

        for trip_idx, trip in enumerate(trips):
            trip_id = f"{device_id}_{trip_idx}"
            result = match_trip(
                mmap, trip,
                observation_sigma=matching_cfg["observation_sigma"],
            )
            if result is not None and result.matched_edges:
                all_results.append({
                    "trip_id": trip_id,
                    "device_id": device_id,
                    "matched_nodes": result.matched_nodes,
                    "matched_edges": result.matched_edges,
                    "match_ratio": result.match_ratio,
                })

    return all_results


def run_map_matching(
    trips_parquet: Path,
    mmap_db_path: str,
    config: dict,
) -> pd.DataFrame:
    """
    并行地图匹配入口 — 流式处理大文件。

    1. 先查询所有设备 ID (极快，只读元数据)
    2. 按 chunk_size 切分设备 ID 列表
    3. 每个子进程自行按需加载数据 → 匹配
    """
    from src.data.trajectory import get_device_ids

    trips_parquet = str(trips_parquet)
    device_ids = get_device_ids(Path(trips_parquet))
    total_devices = len(device_ids)

    chunk_size = config["matching"]["device_chunk_size"]
    max_workers = config["matching"]["max_workers"]

    # 只切分 ID 列表，不加载数据
    id_batches = [
        list(device_ids[i:i + chunk_size])
        for i in range(0, total_devices, chunk_size)
    ]

    print(f"总设备数: {total_devices}, 批次数: {len(id_batches)}, 进程数: {max_workers}")

    all_matched = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                match_device_batch, batch_ids, trips_parquet, mmap_db_path, config
            ): idx
            for idx, batch_ids in enumerate(id_batches)
        }

        with tqdm(total=total_devices, desc="匹配进度", unit="dev") as pbar:
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    results = future.result()
                    if results:
                        all_matched.extend(results)
                except Exception as e:
                    print(f"\n批次 {batch_idx} 出错: {e}")
                    traceback.print_exc()

                batch_size = len(id_batches[batch_idx])
                pbar.update(batch_size)
                pbar.set_postfix({
                    "匹配trip数": len(all_matched),
                    "批": f"{batch_idx + 1}/{len(id_batches)}",
                })

    return _nodes_to_ways(all_matched, config)


def _nodes_to_ways(results: List[Dict], config: dict) -> pd.DataFrame:
    """将匹配结果中的节点序列转换为 way 序列"""
    node_ways_path = Path("data") / f"node_ways_{config['date']}.pkl"

    if node_ways_path.exists():
        with open(node_ways_path, "rb") as f:
            node_to_ways = pickle.load(f)
    else:
        node_to_ways = {}

    rows = []
    for r in results:
        for edge in r["matched_edges"]:
            u, v = edge
            ways_u = node_to_ways.get(u, set())
            ways_v = node_to_ways.get(v, set())
            common_ways = ways_u & ways_v
            if not common_ways:
                common_ways = ways_u | ways_v
            for way_id in common_ways:
                rows.append({
                    "trip_id": r["trip_id"],
                    "device_id": r["device_id"],
                    "osm_way_id": way_id,
                    "node_u": u,
                    "node_v": v,
                })

    return pd.DataFrame(rows)
