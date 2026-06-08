# src/data/coordinate.py
"""
GCJ-02 (火星坐标系) ↔ WGS-84 坐标转换

误差 < 10m (中国境内)。
来源: https://github.com/wandergis/coordTransform_py (MIT License)
"""
import math
from typing import Tuple, Union
import numpy as np

PI = math.pi
ELLIPSOID_A = 6378245.0
ELLIPSOID_EE = 0.00669342162296594323


def _is_out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def _delta(lng: float, lat: float) -> Tuple[float, float]:
    if _is_out_of_china(lng, lat):
        return 0.0, 0.0
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - ELLIPSOID_EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((ELLIPSOID_A * (1 - ELLIPSOID_EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (ELLIPSOID_A / sqrtmagic * math.cos(radlat) * PI)
    return dlng, dlat


def gcj02_to_wgs84(lng: Union[float, np.ndarray], lat: Union[float, np.ndarray]) \
        -> Union[Tuple[float, float], Tuple[np.ndarray, np.ndarray]]:
    """
    火星坐标系 (GCJ-02) 转 WGS-84 (迭代逼近)

    原理: _delta() 的输入是 WGS-84 坐标，但 GCJ→WGS 时我们只有 GCJ 坐标。
    因此需要迭代: 用 GCJ 坐标作为初始猜测 → 算偏移 → 修正 → 重复直到收敛。
    精度: < 1m (通常 2-3 次迭代即收敛)
    """
    scalar = isinstance(lng, (int, float))
    lng = np.atleast_1d(np.asarray(lng, dtype=float))
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    result_lng = np.empty_like(lng)
    result_lat = np.empty_like(lat)

    for i in range(len(lng)):
        gcj_lng, gcj_lat = lng[i], lat[i]
        # 初始猜测: GCJ 坐标就是 WGS (偏移量 ~300-500m)
        wgs_lng, wgs_lat = gcj_lng, gcj_lat
        for _ in range(5):  # 通常 2-3 次收敛, 5 次保底
            dlng, dlat = _delta(wgs_lng, wgs_lat)
            new_lng = gcj_lng - dlng
            new_lat = gcj_lat - dlat
            # 收敛判断: 变化 < 1e-7 度 (~0.01m)
            if abs(new_lng - wgs_lng) < 1e-7 and abs(new_lat - wgs_lat) < 1e-7:
                wgs_lng, wgs_lat = new_lng, new_lat
                break
            wgs_lng, wgs_lat = new_lng, new_lat
        result_lng[i] = wgs_lng
        result_lat[i] = wgs_lat

    if scalar:
        return float(result_lng[0]), float(result_lat[0])
    return result_lng, result_lat


def wgs84_to_gcj02(lng: Union[float, np.ndarray], lat: Union[float, np.ndarray]) \
        -> Union[Tuple[float, float], Tuple[np.ndarray, np.ndarray]]:
    """WGS-84 转火星坐标系 (GCJ-02)"""
    scalar = isinstance(lng, (int, float))
    lng = np.atleast_1d(np.asarray(lng, dtype=float))
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    result_lng = np.empty_like(lng)
    result_lat = np.empty_like(lat)
    for i in range(len(lng)):
        dlng, dlat = _delta(lng[i], lat[i])
        result_lng[i] = lng[i] + dlng
        result_lat[i] = lat[i] + dlat
    if scalar:
        return float(result_lng[0]), float(result_lat[0])
    return result_lng, result_lat
    