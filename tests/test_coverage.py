# tests/test_coverage.py
import pytest
import pandas as pd
import numpy as np
from shapely.geometry import LineString

from src.stats.coverage import compute_segment_coverage, compute_coverage


class TestSegmentCoverage:
    """分段覆盖率计算"""

    def test_full_coverage(self):
        road_geom = LineString([(0, 0), (0, 0.001)])
        matched_points = np.array([
            [0, 0.0001], [0, 0.0003], [0, 0.0005],
            [0, 0.0007], [0, 0.0009],
        ])
        ratio = compute_segment_coverage(road_geom, matched_points, segment_length_m=20)
        assert ratio > 0.8

    def test_partial_coverage(self):
        road_geom = LineString([(0, 0), (0, 0.001)])
        matched_points = np.array([[0, 0.0001], [0, 0.0002]])
        ratio = compute_segment_coverage(road_geom, matched_points, segment_length_m=20)
        assert ratio < 0.5

    def test_no_coverage(self):
        road_geom = LineString([(0, 0), (0, 0.001)])
        matched_points = np.array([]).reshape(0, 2)
        ratio = compute_segment_coverage(road_geom, matched_points, segment_length_m=20)
        assert ratio == 0.0


class TestComputeCoverage:
    """端到端覆盖率聚合"""

    def test_aggregates_by_way(self):
        way_map = {
            "w1": {
                "geometry": LineString([(0, 0), (0, 0.001)]),
                "length": 111.0,
                "name": "Test Road",
                "highway": "primary",
            },
            "w2": {
                "geometry": LineString([(0.001, 0), (0.001, 0.001)]),
                "length": 111.0,
                "name": "Empty Road",
                "highway": "secondary",
            },
        }

        matched = pd.DataFrame({
            "trip_id": ["d1_0", "d1_0", "d2_0"],
            "osm_way_id": ["w1", "w1", "w1"],
            "node_u": [1, 2, 1],
            "node_v": [2, 3, 2],
        })

        result = compute_coverage(matched, way_map, segment_length_m=50)

        assert len(result) == 2
        assert result.loc[result["osm_way_id"] == "w1", "pass_count"].values[0] == 2
        assert result.loc[result["osm_way_id"] == "w2", "pass_count"].values[0] == 0
