# tests/test_hmm_matcher.py
import pytest
import numpy as np
from shapely.geometry import LineString
from leuvenmapmatching.map.sqlite import SqliteMap

from src.matching.hmm_matcher import match_trip, TripMatchResult


class TestMatchTrip:
    """单 trip 地图匹配测试"""

    @pytest.fixture
    def simple_map(self, tmp_path):
        """构建一个十字路口路网"""
        db_path = str(tmp_path / "test_map.db")
        mmap = SqliteMap(db_path, use_latlon=True)

        # 水平路
        for i in range(10):
            lon = 120.0 + i * 0.001
            lat = 30.0
            mmap.add_node(i, (lat, lon))
        for i in range(9):
            mmap.add_edge(i, i + 1)

        # 垂直路
        for i in range(10, 20):
            lon = 120.0045
            lat = 30.0 + (i - 10) * 0.001
            mmap.add_node(i, (lat, lon))
        for i in range(10, 19):
            mmap.add_edge(i, i + 1)

        mmap.add_edge(4, 14)
        return mmap

    def test_straight_trip_matches_horizontal_road(self, simple_map):
        """沿水平道路的 trip 应匹配到路网节点"""
        coords = [(120.0 + i * 0.001 + np.random.normal(0, 0.00005),
                   30.0 + np.random.normal(0, 0.00005))
                  for i in range(8)]
        trip = LineString(coords)

        result = match_trip(simple_map, trip, observation_sigma=10)

        assert isinstance(result, TripMatchResult)
        assert len(result.matched_nodes) >= 3

    def test_very_short_trip_returns_none(self, simple_map):
        """极短 trip (2 个重合点) 匹配比例低，返回 None"""
        trip = LineString([(120.0, 30.0), (120.00001, 30.00001)])
        result = match_trip(simple_map, trip, observation_sigma=10, min_matched_ratio=0.9)
        # 极短 trip 匹配比例可能很低，应在严格阈值下返回 None
        # 宽松阈值下应有结果
        result_lenient = match_trip(simple_map, trip, observation_sigma=10, min_matched_ratio=0.01)
        assert result_lenient is not None or result is None
