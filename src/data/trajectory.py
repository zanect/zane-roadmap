"""
从 CSV 文件加载轨迹数据，转换为 WGS-84 坐标，写 Parquet 中间文件。

CSV 格式 (ClickHouse 导出):
    device_id, lon, lat, speed, height, angle, timestamp
    列分隔符: , (逗号)
    坐标系: GCJ-02

支持 10+ GB 大文件：分块流式处理，内存可控。
"""
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

from .coordinate import gcj02_to_wgs84

# 每批处理行数 (约 100MB 内存)
CHUNK_SIZE = 1_000_000


def load_csv_to_parquet(
    csv_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """
    从 CSV 文件加载轨迹数据，写入 Parquet (DuckDB 流式读取)。

    10+ GB CSV 无压力 — DuckDB 自动分块读取，不占内存。
    """
    csv_path = Path(csv_path)
    if output_path is None:
        output_path = csv_path.with_suffix(".parquet")

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT * FROM read_csv('{csv_path}', auto_detect=true, header=true)
        ) TO '{output_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.close()

    # 显示文件大小
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  CSV → Parquet: {size_mb:.0f} MB")
    return output_path


def convert_coordinates(
    input_path: Path,
    output_path: Optional[Path] = None,
    chunk_size: int = CHUNK_SIZE,
) -> Path:
    """
    分块转换坐标 GCJ-02 → WGS-84。

    逐批读取 → numpy 转换 → 逐批追加写入。
    无论文件多大，内存始终控制在 chunk_size * 行大小 (~150MB/chunk)。
    """
    input_path = Path(input_path)
    if output_path is None:
        stem = input_path.stem
        output_path = input_path.parent / f"{stem}_wgs84.parquet"

    # 获取总行数
    con = duckdb.connect()
    total = con.execute(
        f"SELECT count(*) FROM '{input_path}'"
    ).fetchone()[0]
    con.close()

    print(f"  总行数: {total:,}, 分块大小: {chunk_size:,}, "
          f"预计 {max(1, total // chunk_size)} 批")

    first_batch = True
    offset = 0
    converted_total = 0

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

        if first_batch:
            chunk.to_parquet(output_path, index=False)
            first_batch = False
        else:
            # 追加写入 (PyArrow 引擎支持)
            chunk.to_parquet(output_path, index=False, append=True)

        converted_total += len(chunk)
        offset += chunk_size
        pct = min(100, converted_total * 100 // max(1, total))
        print(f"  转换进度: {converted_total:,}/{total:,} ({pct}%)")

    print(f"  转换完成: {output_path}")
    return output_path


def get_device_ids(parquet_path: Path) -> np.ndarray:
    """获取所有设备 ID (只读元数据，不加载全表)"""
    con = duckdb.connect()
    ids = con.execute(
        f"SELECT DISTINCT device_id FROM '{parquet_path}' ORDER BY device_id"
    ).df()["device_id"].values
    con.close()
    return ids


def load_device_batch(parquet_path: Path, device_ids: list) -> pd.DataFrame:
    """按设备 ID 列表分批加载轨迹数据"""
    ids_str = ", ".join(f"'{d}'" for d in device_ids)
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT * FROM '{parquet_path}'
        WHERE device_id IN ({ids_str})
        ORDER BY device_id, timestamp
    """).df()
    con.close()
    return df
