"""Tests for geographic clustering."""

from src.modules.prediction.clustering import Point, haversine_km, cluster_points


class TestHaversine:
    def test_same_point(self):
        assert haversine_km(40.7, -74.0, 40.7, -74.0) == 0.0

    def test_nyc_to_la(self):
        assert 3900 < haversine_km(40.7128, -74.006, 34.0522, -118.2437) < 4000

    def test_london_to_paris(self):
        assert 340 < haversine_km(51.5074, -0.1278, 48.8566, 2.3522) < 360


class TestClustering:
    def test_empty(self):
        assert cluster_points([]) == []

    def test_single(self):
        clusters = cluster_points([Point(40.7, -74.0)])
        assert len(clusters) == 1
        assert len(clusters[0].points) == 1
        assert clusters[0].radius_km == 0.0

    def test_close_points_merge(self):
        points = [Point(40.7, -74.0), Point(40.72, -74.01), Point(40.75, -74.02)]
        clusters = cluster_points(points, distance_km=100.0)
        assert len(clusters) == 1
        assert len(clusters[0].points) == 3

    def test_distant_points_separate(self):
        points = [Point(40.7128, -74.006), Point(34.0522, -118.2437)]
        clusters = cluster_points(points, distance_km=25.0)
        assert len(clusters) == 2

    def test_sorted_by_count(self):
        points = [
            Point(40.7, -74.0),
            Point(40.72, -74.01),  # 2 in NYC
            Point(34.05, -118.24),  # 1 in LA
        ]
        clusters = cluster_points(points, distance_km=100.0)
        assert len(clusters[0].points) >= len(clusters[1].points)
