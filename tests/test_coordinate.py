# tests/test_coordinate.py
import pytest
from src.data.coordinate import gcj02_to_wgs84, wgs84_to_gcj02


class TestGCJ02ToWGS84:
    """GCJ-02 → WGS-84 转换测试"""

    def test_known_point_beijing(self):
        """北京天安门附近已知转换点"""
        lng, lat = gcj02_to_wgs84(116.397428, 39.909204)
        assert abs(lng - 116.391) < 0.01
        assert abs(lat - 39.907) < 0.01

    def test_roundtrip_preserves(self):
        """WGS84 → GCJ02 → WGS84 应回到原点"""
        original = (120.155, 30.274)
        gcj = wgs84_to_gcj02(*original)
        recovered = gcj02_to_wgs84(*gcj)
        assert abs(recovered[0] - original[0]) < 2e-5
        assert abs(recovered[1] - original[1]) < 2e-5

    def test_china_offset_is_significant(self):
        """中国境内偏移应 > 100m"""
        original = (120.155, 30.274)
        gcj = wgs84_to_gcj02(*original)
        offset = ((gcj[0] - original[0])**2 + (gcj[1] - original[1])**2) ** 0.5
        offset_m = offset * 111000
        assert offset_m > 100

    def test_array_input(self):
        """支持 numpy array 批量转换"""
        import numpy as np
        lngs = np.array([120.155, 120.156])
        lats = np.array([30.274, 30.275])
        result_lng, result_lat = gcj02_to_wgs84(lngs, lats)
        assert len(result_lng) == 2
        assert len(result_lat) == 2


class TestWGS84ToGCJ02:
    """WGS-84 → GCJ-02 转换测试"""

    def test_reversible(self):
        """正向转换后逆向应可恢复"""
        lng, lat = 120.155, 30.274
        gcj = wgs84_to_gcj02(lng, lat)
        wgs = gcj02_to_wgs84(*gcj)
        assert abs(wgs[0] - lng) < 2e-5
        assert abs(wgs[1] - lat) < 2e-5
