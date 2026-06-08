"""
从 CSV 文件加载轨迹数据，转换为 WGS-84 坐标，写 Parquet 中间文件。

CSV 格式 (ClickHouse 导出):
    device_id, lon, lat, speed, height, angle, timestamp
    列分隔符: , (逗号)
    坐标系: GCJ-02
"""
import duckdb
import pandas as pd
from pathlib import Path
from typing import Optional

from .coordinate import gcj02_to_wgs84


def load_csv_to_parquet(
    csv_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """
    从 CSV 文件加载轨迹数据，写入 Parquet (DuckDB 高效读取)。

    Args:
        csv_path: CSV 文件路径
        output_path: 输出 Parquet 路径，默认同名 .parquet

    Returns:
        Parquet 文件路径
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
    return output_path


def convert_coordinates(
    input_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """
    将 Parquet 中的轨迹数据 GCJ-02 → WGS-84。

    Args:
        input_path: 原始轨迹 Parquet (GCJ-02)
        output_path: 输出路径，默认在文件名后加 _wgs84

    Returns:
        转换后的 Parquet 路径
    """
    input_path = Path(input_path)
    if output_path is None:
        stem = input_path.stem
        output_path = input_path.parent / f"{stem}_wgs84.parquet"

    df = pd.read_parquet(input_path)
    print(f"  加载 {len(df):,} 行，开始坐标转换...")

    lng_wgs, lat_wgs = gcj02_to_wgs84(df["lon"].values, df["lat"].values)
    df["lon"] = lng_wgs
    df["lat"] = lat_wgs

    df.to_parquet(output_path, index=False)
    print(f"  转换完成: {output_path}")
    return output_path


def load_trajectory_parquet(path: Path) -> pd.DataFrame:
    """加载轨迹 Parquet 为 DataFrame"""
    return pd.read_parquet(path)
