"""
多进程并行地图匹配 + tqdm 进度展示。

大文件优化：按设备批次流式读取，不将全量数据加载到内存。
单设备/小批量场景：详细打印每步耗时。
"""
import time
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
    子进程入口：加载本批设备数据 → 预处理 → HMM 匹配。
    """
    from leuvenmapmatching.map.sqlite import SqliteMap
    from src.preprocess.clean import preprocess_device
    from src.matching.hmm_matcher import match_trip
    import duckdb

    t0 = time.time()
    # 子进程中必须用绝对路径 (SqliteMap 默认 dir 是系统临时目录)
    mmap_db_path = str(Path(mmap_db_path).resolve())
    mmap = SqliteMap(mmap_db_path, use_latlon=True)
    preprocess_cfg = config["preprocess"]
    matching_cfg = config["matching"]
    all_results = []

    ids_str = ", ".join(f"'{d}'" for d in device_ids)
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT * FROM '{parquet_path}'
        WHERE device_id IN ({ids_str})
        ORDER BY device_id, timestamp
    """).df()
    con.close()

    n_devices = len(device_ids)
    n_rows = len(df)

    for di, (device_id, device_df) in enumerate(df.groupby("device_id")):
        t_dev = time.time()
        raw_pts = len(device_df)

        trips = preprocess_device(
            device_df,
            min_speed_ms=preprocess_cfg["min_speed_ms"],
            max_jump_m=preprocess_cfg["max_jump_m"],
            trip_gap_minutes=preprocess_cfg["trip_gap_minutes"],
            dp_epsilon_m=preprocess_cfg["dp_epsilon_m"],
        )

        prep_time = time.time() - t_dev
        n_trips = len(trips)
        total_obs = sum(len(list(t.coords)) for t in trips)

        # 单设备 / 少量设备时打印详情
        verbose = n_devices <= 10
        if verbose:
            print(f"  [{di+1}/{n_devices}] device={device_id}: "
                  f"{raw_pts} 原始点 → {n_trips} trips → ~{total_obs} 观测点 "
                  f"(预处理 {prep_time:.1f}s)")

        for trip_idx, trip in enumerate(trips):
            trip_id = f"{device_id}_{trip_idx}"
            result = match_trip(
                mmap, trip,
                observation_sigma=matching_cfg.get("observation_sigma", 25),
                verbose=verbose,
            )
            if result is not None and result.matched_edges:
                all_results.append({
                    "trip_id": trip_id,
                    "device_id": device_id,
                    "matched_nodes": result.matched_nodes,
                    "matched_edges": result.matched_edges,
                    "match_ratio": result.match_ratio,
                })

    elapsed = time.time() - t0
    if len(device_ids) <= 10:
        print(f"  ← 批次完成: {len(all_results)} trip匹配, {elapsed:.0f}s")
    return all_results


def run_map_matching(
    trips_parquet: Path,
    mmap_db_path: str,
    config: dict,
) -> pd.DataFrame:
    """并行地图匹配入口 — 流式处理大文件"""
    from src.data.trajectory import get_device_ids

    trips_parquet = str(trips_parquet)
    device_ids = get_device_ids(Path(trips_parquet))
    total_devices = len(device_ids)

    chunk_size = config["matching"]["device_chunk_size"]
    max_workers = config["matching"]["max_workers"]

    id_batches = [
        list(device_ids[i:i + chunk_size])
        for i in range(0, total_devices, chunk_size)
    ]

    print(f"[匹配] 设备总数: {total_devices}, 批次: {len(id_batches)}, "
          f"进程: {max_workers}, 每批设备: {chunk_size}")

    all_matched = []
    t0 = time.time()

    # 少量设备时用单进程 (避免多进程开销，方便看日志)
    if total_devices <= 50:
        print("[匹配] 设备数少，使用单进程模式")
        for idx, batch_ids in enumerate(id_batches):
            results = match_device_batch(
                batch_ids, trips_parquet, mmap_db_path, config
            )
            if results:
                all_matched.extend(results)
    else:
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
                    pbar.update(len(id_batches[batch_idx]))
                    pbar.set_postfix({"匹配trip": len(all_matched)})

    elapsed = time.time() - t0
    print(f"[匹配] 完成: {len(all_matched)} trip匹配 ({elapsed:.0f}s)")

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
