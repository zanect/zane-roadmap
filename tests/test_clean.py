# tests/test_clean.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from shapely.geometry import LineString

from src.preprocess.clean import (
    denoise_trajectory,
    split_trips,
    douglas_peucker,
    preprocess_device,
)


class TestDenoise:
    """降噪测试"""

    def make_point(self, device_id="d1", lon=120.0, lat=30.0, speed=10.0,
                   timestamp=None):
        if timestamp is None:
            timestamp = datetime(2026, 6, 7, 8, 0, 0)
        return {
            "device_id": device_id, "lon": lon, "lat": lat,
            "speed": speed, "timestamp": timestamp,
        }

    def test_removes_stationary_points(self):
        """剔除静止点：speed < 0.5 m/s 且间距 < 5m"""
        points = [
            self.make_point(lon=120.0, lat=30.0, speed=10.0,
                           timestamp=datetime(2026, 6, 7, 8, 0, 0)),
            self.make_point(lon=120.00001, lat=30.00001, speed=0.3,
                           timestamp=datetime(2026, 6, 7, 8, 0, 10)),
            self.make_point(lon=120.001, lat=30.001, speed=15.0,
                           timestamp=datetime(2026, 6, 7, 8, 0, 20)),
        ]
        df = pd.DataFrame(points)
        result = denoise_trajectory(df)
        assert len(result) == 2
        assert result.iloc[0]["speed"] == 10.0
        assert result.iloc[1]["speed"] == 15.0

    def test_removes_outlier_jumps(self):
        """剔除孤立漂移点：与前后点距离均 > 500m"""
        points = [
            self.make_point(lon=120.0, lat=30.0,
                           timestamp=datetime(2026, 6, 7, 8, 0, 0)),
            self.make_point(lon=120.01, lat=30.01,
                           timestamp=datetime(2026, 6, 7, 8, 0, 10)),
            self.make_point(lon=120.0001, lat=30.0001,
                           timestamp=datetime(2026, 6, 7, 8, 0, 20)),
        ]
        df = pd.DataFrame(points)
        result = denoise_trajectory(df)
        assert len(result) == 2

    def test_preserves_valid_high_speed(self):
        """高速移动的点不应被误删"""
        points = [
            self.make_point(lon=120.0, lat=30.0, speed=30.0,
                           timestamp=datetime(2026, 6, 7, 8, 0, 0)),
            self.make_point(lon=120.005, lat=30.005, speed=35.0,
                           timestamp=datetime(2026, 6, 7, 8, 0, 30)),
        ]
        df = pd.DataFrame(points)
        result = denoise_trajectory(df)
        assert len(result) == 2


class TestSplitTrips:
    """Trip 切分测试"""

    def test_split_by_time_gap(self):
        """间隔 > 5 分钟 → 新 trip"""
        t0 = datetime(2026, 6, 7, 8, 0, 0)
        points = [
            {"device_id": "d1", "lon": 120.0, "lat": 30.0,
             "speed": 10.0, "timestamp": t0},
            {"device_id": "d1", "lon": 120.001, "lat": 30.001,
             "speed": 10.0, "timestamp": t0 + timedelta(seconds=30)},
            {"device_id": "d1", "lon": 120.002, "lat": 30.002,
             "speed": 10.0, "timestamp": t0 + timedelta(minutes=8)},
            {"device_id": "d1", "lon": 120.003, "lat": 30.003,
             "speed": 10.0, "timestamp": t0 + timedelta(minutes=8, seconds=30)},
        ]
        df = pd.DataFrame(points)
        trips = split_trips(df, gap_minutes=5)
        assert len(trips) == 2
        assert len(trips[0]) == 2
        assert len(trips[1]) == 2

    def test_single_point_no_trip(self):
        """单点不能构成 trip"""
        points = [
            {"device_id": "d1", "lon": 120.0, "lat": 30.0,
             "speed": 10.0, "timestamp": datetime(2026, 6, 7, 8, 0, 0)},
        ]
        df = pd.DataFrame(points)
        trips = split_trips(df, gap_minutes=5)
        assert len(trips) == 0


class TestDouglasPeucker:
    """DP 抽稀测试"""

    def test_straight_line_simplifies_to_endpoints(self):
        points = [
            (120.0, 30.0), (120.001, 30.001), (120.002, 30.002),
            (120.003, 30.003), (120.004, 30.004),
        ]
        # 大 epsilon → 只保留首尾
        result = douglas_peucker(points, epsilon=1.0)
        assert len(result) == 2
        assert result[0] == (120.0, 30.0)
        assert result[-1] == (120.004, 30.004)

    def test_preserves_corner(self):
        """转角点应保留 — 使用更明显的直角转弯"""
        points = [
            (120.0, 30.0),
            (120.0, 30.01),
            (120.005, 30.005),  # 明显转弯
            (120.01, 30.005),
            (120.01, 30.0),
        ]
        result = douglas_peucker(points, epsilon=0.0001)
        assert len(result) >= 3


class TestPreprocessDevice:
    """端到端单设备预处理测试"""

    def test_integration_pipeline(self):
        t0 = datetime(2026, 6, 7, 8, 0, 0)
        records = []
        for i in range(10):
            records.append({
                "device_id": "d1",
                "lon": 120.0 + i * 0.001,
                "lat": 30.0 + i * 0.001,
                "speed": 15.0,
                "timestamp": t0 + timedelta(seconds=i * 30),
            })
        df = pd.DataFrame(records)
        trips = preprocess_device(
            df, min_speed_ms=0.5, max_jump_m=500,
            trip_gap_minutes=5, dp_epsilon_m=10,
        )
        assert len(trips) >= 1
        for trip in trips:
            assert isinstance(trip, LineString)
            assert len(trip.coords) >= 2
