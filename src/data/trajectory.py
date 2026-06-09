"""
从 CSV 文件加载轨迹数据，转换为 WGS-84 坐标，写 Parquet 中间文件。

支持 10+ GB 大文件：CSV 阶段 DuckDB COPY 一次完成（最快），
Parquet 阶段分块处理 + 实时进度日志。
"""
import time
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

from .coordinate import gcj02_to_wgs84

CHUNK_SIZE = 1_000_000


def load_csv_to_parquet(
    csv_path: Path,
    output_path: Optional[Path] = None,
    force: bool = False,
) -> Path:
    """
    从 CSV 加载轨迹数据 → Parquet（DuckDB 流式 COPY，一次完成）。

    13 GB CSV 约 25 秒，无分块。处理后从 Parquet 读取再做分块进度展示。
    COPY 内置进度条提供百分比反馈。

    若 output_path 已存在且 force=False，直接返回（缓存命中）。
    """
    csv_path = Path(csv_path)
    if output_path is None:
        output_path = csv_path.with_suffix(".parquet")

    if not force and output_path.exists():
        total_rows = _count_parquet(output_path)
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"[CSV→Parquet] 缓存命中: {total_rows:,} 行 → {size_mb:.0f} MB")
        return output_path

    csv_str = str(csv_path.resolve()).replace("\\", "/")
    out_str = str(output_path.resolve()).replace("\\", "/")
    file_gb = csv_path.stat().st_size / 1e9

    print(f"[CSV→Parquet] {file_gb:.1f} GB, 单次 COPY 处理中 (~30s)...")

    t_start = time.time()

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT
                device_id,
                lon,
                lat,
                speed,
                to_timestamp(timestamp_ms::BIGINT / 1000) AS timestamp
            FROM read_csv('{csv_str}', header=false,
                columns={{'device_id': 'VARCHAR', 'lon': 'DOUBLE', 'lat': 'DOUBLE',
                          'speed': 'DOUBLE', 'timestamp_ms': 'BIGINT'}},
                auto_detect=false)
            WHERE device_id != 'null'
              AND lon IS NOT NULL AND lat IS NOT NULL
              AND lon BETWEEN 72 AND 138
              AND lat BETWEEN 18 AND 54
        ) TO '{out_str}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.close()

    elapsed = time.time() - t_start
    total_rows = _count_parquet(output_path)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[CSV→Parquet] 完成: {total_rows:,} 行 → {size_mb:.0f} MB "
          f"({elapsed:.0f}s, {total_rows/elapsed:,.0f} 行/秒)")
    return output_path


def _count_parquet(path: Path) -> int:
    """快速获取 Parquet 行数"""
    con = duckdb.connect()
    n = con.execute(f"SELECT count(*) FROM '{path}'").fetchone()[0]
    con.close()
    return n


def convert_coordinates(
    input_path: Path,
    output_path: Optional[Path] = None,
    chunk_size: int = CHUNK_SIZE,
    force: bool = False,
) -> Path:
    """
    分块转换坐标 GCJ-02 → WGS-84。

    逐批读取 → numpy 转换 → 逐批追加写入 (通过 pyarrow ParquetWriter)。

    若 output_path 已存在且 force=False，直接返回（缓存命中）。
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    input_path = Path(input_path)
    if output_path is None:
        stem = input_path.stem
        output_path = input_path.parent / f"{stem}_wgs84.parquet"

    if not force and output_path.exists():
        total = _count_parquet(output_path)
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"  坐标转换缓存命中: {total:,} 行 → {size_mb:.0f} MB")
        return output_path

    total = _count_parquet(input_path)
    print(f"  总行数: {total:,}, 分块大小: {chunk_size:,}, "
          f"预计 {max(1, total // chunk_size)} 批")

    offset = 0
    converted_total = 0
    writer = None

    try:
        while offset < total:
            con = duckdb.connect()
            chunk = con.execute(f"""
                SELECT * FROM '{input_path}'
                LIMIT {chunk_size} OFFSET {offset}
            """).df()
            con.close()

            if len(chunk) == 0:
                break

            lng_wgs, lat_wgs = gcj02_to_wgs84(
                chunk["lon"].values, chunk["lat"].values
            )
            chunk["lon"] = lng_wgs
            chunk["lat"] = lat_wgs

            table = pa.Table.from_pandas(chunk)
            if writer is None:
                writer = pq.ParquetWriter(str(output_path), table.schema)
            writer.write_table(table)

            converted_total += len(chunk)
            offset += chunk_size
            pct = min(100, converted_total * 100 // max(1, total))
            print(f"  转换进度: {converted_total:,}/{total:,} ({pct}%)")
    finally:
        if writer is not None:
            writer.close()

    print(f"  转换完成: {output_path}")
    return output_path


def get_device_ids(parquet_path: Path) -> np.ndarray:
    """获取所有设备 ID (只读元数据)"""
    con = duckdb.connect()
    ids = con.execute(
        f"SELECT DISTINCT device_id FROM '{parquet_path}' ORDER BY device_id"
    ).df()["device_id"].values
    con.close()
    return ids


def load_device_batch(parquet_path: Path, device_ids: list) -> pd.DataFrame:
    """按设备 ID 加载一批数据"""
    ids_str = ", ".join(f"'{d}'" for d in device_ids)
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT * FROM '{parquet_path}'
        WHERE device_id IN ({ids_str})
        ORDER BY device_id, timestamp
    """).df()
    con.close()
    return df
