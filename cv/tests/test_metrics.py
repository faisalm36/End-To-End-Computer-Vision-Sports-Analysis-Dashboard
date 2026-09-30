"""Unit tests for performance metrics calculation."""

import unittest
from cv.metrics import PerformanceAnalyzer


class TestPerformanceAnalyzer(unittest.TestCase):
    """Test speed, distance, and injury risk calculations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = PerformanceAnalyzer(
            fps=30.0,
            max_plausible_speed_mph=25.0,  # Updated to new default
            speed_smoothing_window=5,
            sustained_speed_window_s=1.0,
            high_speed_threshold_mph=12.3,
            sprint_threshold_mph=15.7,
            speed_preset='gps_standard'
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
        """Test that implausible speeds are filtered, not capped."""
        # Teleport 100 meters in 1 second (impossible)
        positions = [
            (0.0, 0.0, 0.0),
            (100.0, 0.0, 1.0)
        ]
        speeds = self.analyzer.calculate_speed(positions)
        # Should NOT be capped - raw calculation preserved
        self.assertGreater(speeds[0], 22.0)
        
        # But workload metrics should filter it
        metrics = self.analyzer.calculate_workload_metrics(speeds)
        # Max speed should be 0 since all speeds were outliers
        self.assertEqual(metrics['max_speed_mph'], 0.0)
    
    def test_real_top_speed_below_cap(self):
        """Test that real top speed below cap is reported correctly."""
        # Add realistic player movement to analyzer
        track_id = 1
        
        # Move at ~10 mph: 10 mph = 4.47 m/s
        # At 30 FPS, each frame is 1/30 s, so distance per frame = 4.47/30 = 0.149 m
        for i in range(20):
            self.analyzer.add_position(track_id, float(i) * 0.149, 0.0, float(i) / 30.0)
        
        # Add a burst to ~19 mph: 19 mph = 8.49 m/s, so 8.49/30 = 0.283 m per frame
        self.analyzer.add_position(track_id, 19 * 0.149 + 0.283, 0.0, 20 / 30.0)
        
        # Analyze player
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # 95th percentile should give reasonable top speed, not capped at 22
        # With mostly 10mph and one 19mph, 95th percentile will be around 10-15mph
        self.assertLess(result['top_speed_mph'], 20.0)
        self.assertGreater(result['top_speed_mph'], 8.0)  # At least above average
    
    def test_single_frame_spike_filtered(self):
        """Test that single-frame spikes don't set top speed."""
        track_id = 1
        
        # Steady 12 mph movement: 12 mph = 5.36 m/s, so 5.36/30 = 0.179 m per frame
        for i in range(15):
            self.analyzer.add_position(track_id, float(i) * 0.179, 0.0, float(i) / 30.0)
        
        # Add impossible spike (teleport 50m in one frame = 3350 mph!)
        self.analyzer.add_position(track_id, 14 * 0.179 + 50.0, 0.0, 15 / 30.0)
        
        # Back to steady
        self.analyzer.add_position(track_id, 14 * 0.179 + 50.0 + 0.179, 0.0, 16 / 30.0)
        
        # Analyze player
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Should report ~12 mph (95th percentile), spike should be filtered out
        # The spike will be > 22 mph cap, so filtered by valid_speeds
        self.assertLess(result['top_speed_mph'], 15.0)
        self.assertGreater(result['top_speed_mph'], 10.0)
    
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
        # Max will be median of sustained window, which will be close to 5.5-6.0
        self.assertGreater(metrics['max_speed_mph'], 5.0)
        self.assertLess(metrics['max_speed_mph'], 7.0)
    
    def test_workload_metrics_with_sprints(self):
        """Test workload metrics with sprint bursts."""
        # Two sprint bursts with hysteresis
        speeds = [
            10.0, 15.0, 18.0, 19.0, 20.0,  # First sprint burst
            10.0, 12.0, 10.0,              # Recovery (drops below 90% = 14.1 mph)
            18.0, 19.0, 18.5,              # Second sprint burst
            10.0
        ]
        metrics = self.analyzer.calculate_workload_metrics(speeds)
        
        # With hysteresis: stays in sprint until <90% of threshold (14.1 mph)
        # First burst: enters at 18, exits when drops to 10
        # Second burst: enters at 18
        # Sustained window may smooth these, reducing burst count
        self.assertGreater(metrics['sprint_count'], 0)
        self.assertGreater(metrics['high_speed_distance_km'], 0.0)
        self.assertGreater(metrics['sprint_distance_km'], 0.0)
        # Sustained speeds will be lower than peak instantaneous
        self.assertGreater(metrics['max_speed_mph'], 15.0)
    
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
    
    def test_sustained_24mph_sprint_kept(self):
        """Test that a synthetic 24 mph sustained sprint is kept (not filtered)."""
        track_id = 1
        
        # Sustained 24 mph sprint: 24 mph = 10.72 m/s, so 10.72/30 = 0.357 m per frame
        # Run for 2 seconds (60 frames) at 24 mph
        for i in range(60):
            self.analyzer.add_position(track_id, float(i) * 0.357, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # 24 mph is below the 25 mph filter, so should be kept
        # Sustained speed window should preserve this
        self.assertGreater(result['top_speed_mph'], 22.0)
        self.assertLess(result['top_speed_mph'], 25.0)
    
    def test_one_frame_30mph_spike_ignored(self):
        """Test that a one-frame 30 mph spike is ignored."""
        track_id = 1
        
        # Steady 12 mph: 12 mph = 5.36 m/s, so 5.36/30 = 0.179 m per frame
        for i in range(40):
            self.analyzer.add_position(track_id, float(i) * 0.179, 0.0, float(i) / 30.0)
        
        # Add one-frame 30 mph spike: 30 mph = 13.41 m/s, so 13.41/30 = 0.447 m
        # This would be 30 mph if sustained, but it's just one frame
        self.analyzer.add_position(track_id, 39 * 0.179 + 0.447, 0.0, 40 / 30.0)
        
        # Back to steady 12 mph
        for i in range(41, 50):
            self.analyzer.add_position(track_id, 39 * 0.179 + 0.447 + (i - 40) * 0.179, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Sustained speed window should filter the spike
        # Top speed should be around 12 mph, not 30
        self.assertLess(result['top_speed_mph'], 15.0)
        self.assertGreater(result['top_speed_mph'], 10.0)
    
    def test_extreme_outlier_filtered(self):
        """Test that extreme outliers (>25 mph default) are filtered."""
        track_id = 1
        
        # Normal movement at 10 mph
        for i in range(30):
            self.analyzer.add_position(track_id, float(i) * 0.149, 0.0, float(i) / 30.0)
        
        # Add extreme outlier (teleport: 100m in one frame = ~6700 mph!)
        self.analyzer.add_position(track_id, 29 * 0.149 + 100.0, 0.0, 30 / 30.0)
        
        # Back to normal
        for i in range(31, 40):
            self.analyzer.add_position(track_id, 29 * 0.149 + 100.0 + (i - 30) * 0.149, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Extreme outlier should be filtered by max_plausible_speed_mph = 25
        # Top speed should be around 10 mph
        self.assertLess(result['top_speed_mph'], 12.0)
        self.assertGreater(result['top_speed_mph'], 8.0)
    
    def test_sustained_speed_calculation(self):
        """Test sustained speed calculation with rolling window."""
        # Speeds with a spike
        speeds = [10.0, 10.0, 10.0, 30.0, 10.0, 10.0, 10.0]
        
        sustained = self.analyzer.calculate_sustained_speeds(speeds)
        
        # Sustained speeds should smooth out the spike
        self.assertEqual(len(sustained), len(speeds))
        # The spike at index 3 should be reduced by median filter
        self.assertLess(sustained[3], 20.0)  # Much less than the 30 mph spike


if __name__ == '__main__':
    unittest.main()
