"""Unit tests for performance metrics calculation."""

import unittest
from cv.metrics import PerformanceAnalyzer


class TestPerformanceAnalyzer(unittest.TestCase):
    """Test speed, distance, and injury risk calculations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = PerformanceAnalyzer(
            fps=30.0,
            max_plausible_speed_mph=22.0,
            speed_smoothing_window=5,
            high_speed_threshold_mph=15.0,
            sprint_threshold_mph=18.0
        )
    
    def test_speed_calculation_zero_movement(self):
        """Test speed calculation with no movement."""
        positions = [
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 2.0)
        ]
        speeds = self.analyzer.calculate_speed(positions)
        self.assertEqual(len(speeds), 2)
        self.assertAlmostEqual(speeds[0], 0.0)
        self.assertAlmostEqual(speeds[1], 0.0)
    
    def test_speed_calculation_constant_movement(self):
        """Test speed calculation with constant movement."""
        # Moving 1 meter per second = 2.237 mph
        positions = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 1.0),
            (2.0, 0.0, 2.0)
        ]
        speeds = self.analyzer.calculate_speed(positions)
        self.assertEqual(len(speeds), 2)
        # 1 m/s = 2.237 mph
        self.assertAlmostEqual(speeds[0], 2.237, delta=0.1)
        self.assertAlmostEqual(speeds[1], 2.237, delta=0.1)
    
    def test_speed_capping(self):
        """Test that implausible speeds are capped."""
        # Teleport 100 meters in 1 second (impossible)
        positions = [
            (0.0, 0.0, 0.0),
            (100.0, 0.0, 1.0)
        ]
        speeds = self.analyzer.calculate_speed(positions)
        # Should be capped at max_plausible_speed_mph
        self.assertLessEqual(speeds[0], 22.0)
    
    def test_distance_calculation(self):
        """Test total distance calculation."""
        # Move in a straight line with small increments (simulating frame-by-frame tracking)
        # At 30 fps, time delta is 1/30 seconds per position
        positions = []
        for i in range(11):
            positions.append((float(i) * 0.5, 0.0, float(i) / 30.0))
        
        distance_km = self.analyzer.calculate_distance(positions)
        # Total: 10 segments * 0.5m = 5 meters = 0.005 km
        # Each 0.5m segment is well below the cap (~0.66m), so should not be capped
        self.assertAlmostEqual(distance_km, 0.005, delta=0.0001)
    
    def test_distance_with_single_position(self):
        """Test distance with insufficient positions."""
        positions = [(0.0, 0.0, 0.0)]
        distance_km = self.analyzer.calculate_distance(positions)
        self.assertEqual(distance_km, 0.0)
    
    def test_workload_metrics_no_sprints(self):
        """Test workload metrics with low speeds."""
        speeds = [5.0, 6.0, 5.5, 6.5, 5.0]  # All below high-speed threshold
        metrics = self.analyzer.calculate_workload_metrics(speeds)
        
        self.assertEqual(metrics['sprint_count'], 0)
        self.assertEqual(metrics['high_speed_distance_km'], 0.0)
        self.assertEqual(metrics['sprint_distance_km'], 0.0)
        self.assertEqual(metrics['max_speed_mph'], 6.5)
    
    def test_workload_metrics_with_sprints(self):
        """Test workload metrics with sprint bursts."""
        # Two sprint bursts
        speeds = [
            10.0, 15.0, 18.0, 19.0, 20.0,  # First sprint burst
            10.0, 12.0, 10.0,              # Recovery
            18.0, 19.0, 18.5,              # Second sprint burst
            10.0
        ]
        metrics = self.analyzer.calculate_workload_metrics(speeds)
        
        self.assertEqual(metrics['sprint_count'], 2)
        self.assertGreater(metrics['high_speed_distance_km'], 0.0)
        self.assertGreater(metrics['sprint_distance_km'], 0.0)
        self.assertEqual(metrics['max_speed_mph'], 20.0)
    
    def test_injury_risk_low(self):
        """Test low injury risk classification."""
        workload_metrics = {
            'high_speed_distance_km': 0.5,
            'sprint_distance_km': 0.2,
            'sprint_count': 10,
            'max_speed_mph': 18.0
        }
        risk = self.analyzer.calculate_injury_risk(5.0, workload_metrics)
        self.assertEqual(risk, 'Low')
    
    def test_injury_risk_medium(self):
        """Test medium injury risk classification."""
        workload_metrics = {
            'high_speed_distance_km': 1.0,
            'sprint_distance_km': 0.5,
            'sprint_count': 35,
            'max_speed_mph': 19.0
        }
        risk = self.analyzer.calculate_injury_risk(8.0, workload_metrics)
        self.assertEqual(risk, 'Medium')
    
    def test_injury_risk_high(self):
        """Test high injury risk classification."""
        workload_metrics = {
            'high_speed_distance_km': 2.0,
            'sprint_distance_km': 1.0,
            'sprint_count': 60,
            'max_speed_mph': 21.0
        }
        risk = self.analyzer.calculate_injury_risk(11.0, workload_metrics)
        self.assertEqual(risk, 'High')
    
    def test_analyze_player_integration(self):
        """Test full player analysis integration."""
        track_id = 1
        
        # Add some positions (player running across pitch)
        for i in range(10):
            self.analyzer.add_position(
                track_id,
                pitch_x=float(i * 10),
                pitch_y=34.0,
                timestamp=float(i / 30.0)
            )
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['track_id'], track_id)
        self.assertGreater(result['distance_km'], 0.0)
        self.assertGreaterEqual(result['top_speed_mph'], 0.0)
        self.assertIn(result['injury_risk'], ['Low', 'Medium', 'High'])
    
    def test_analyze_player_insufficient_data(self):
        """Test player analysis with insufficient data."""
        result = self.analyzer.analyze_player(999)
        self.assertIsNone(result)
    
    def test_speed_smoothing(self):
        """Test speed smoothing reduces jitter."""
        # Noisy speeds
        speeds = [10.0, 15.0, 9.0, 16.0, 11.0, 14.0, 10.0]
        smoothed = self.analyzer.smooth_speeds(speeds)
        
        self.assertEqual(len(smoothed), len(speeds))
        
        # Smoothed values should have less variation
        import numpy as np
        original_std = np.std(speeds)
        smoothed_std = np.std(smoothed)
        self.assertLess(smoothed_std, original_std)


if __name__ == '__main__':
    unittest.main()
