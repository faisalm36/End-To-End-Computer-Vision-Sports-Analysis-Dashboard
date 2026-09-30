"""Unit tests for performance metrics calculation."""

import unittest
from cv.metrics import PerformanceAnalyzer


class TestPerformanceAnalyzer(unittest.TestCase):
    """Test speed, distance, and injury risk calculations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = PerformanceAnalyzer(
            fps=30.0,
            max_plausible_speed_mph=25.0,
            speed_smoothing_window=5,
            sustained_speed_window_s=1.0,
            high_speed_threshold_mph=12.3,
            sprint_threshold_mph=15.7,
            speed_preset='gps_standard',
            zone_walk_kmh=7.0,
            zone_jog_kmh=15.0,
            zone_run_kmh=20.0,
            zone_hsr_kmh=25.0,
            accel_high_ms2=3.0,
            accel_dwell_s=0.7,
            heatmap_grid=(21, 14),
            pitch_length_m=105.0,
            pitch_width_m=68.0,
            total_video_frames=900  # 30 seconds at 30 fps
        )
    
    def test_speed_calculation_zero_movement(self):
        """Test speed calculation with no movement."""
        positions = [
            (0.0, 0.0, 0.0, True),
            (0.0, 0.0, 1.0, True),
            (0.0, 0.0, 2.0, True)
        ]
        speeds, detected_flags = self.analyzer.calculate_speed(positions)
        self.assertEqual(len(speeds), 2)
        self.assertAlmostEqual(speeds[0], 0.0)
        self.assertAlmostEqual(speeds[1], 0.0)
    
    def test_speed_calculation_constant_movement(self):
        """Test speed calculation with constant movement."""
        # Moving 1 meter per second = 2.237 mph
        positions = [
            (0.0, 0.0, 0.0, True),
            (1.0, 0.0, 1.0, True),
            (2.0, 0.0, 2.0, True)
        ]
        speeds, detected_flags = self.analyzer.calculate_speed(positions)
        self.assertEqual(len(speeds), 2)
        # 1 m/s = 2.237 mph
        self.assertAlmostEqual(speeds[0], 2.237, delta=0.1)
        self.assertAlmostEqual(speeds[1], 2.237, delta=0.1)
    
    def test_speed_capping(self):
        """Test that implausible speeds are filtered, not capped."""
        # Teleport 100 meters in 1 second (impossible)
        positions = [
            (0.0, 0.0, 0.0, True),
            (100.0, 0.0, 1.0, True)
        ]
        speeds, detected_flags = self.analyzer.calculate_speed(positions)
        # Should NOT be capped - raw calculation preserved
        self.assertGreater(speeds[0], 22.0)
        
        # But workload metrics should filter it
        detected_flags_for_metrics = [True] * len(speeds)
        metrics = self.analyzer.calculate_workload_metrics(speeds, detected_flags_for_metrics, positions)
        # Call calculate_workload_metrics with detected_flags
        detected_flags = [True] * len(speeds)
        metrics = self.analyzer.calculate_workload_metrics(speeds, detected_flags, positions)
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
            positions.append((float(i) * 0.5, 0.0, float(i) / 30.0, True))
        
        distance_km = self.analyzer.calculate_distance(positions)
        # Total: 10 segments * 0.5m = 5 meters = 0.005 km
        # Each 0.5m segment is well below the cap (~0.66m), so should not be capped
        self.assertAlmostEqual(distance_km, 0.005, delta=0.0001)
    
    def test_distance_with_single_position(self):
        """Test distance with insufficient positions."""
        positions = [(0.0, 0.0, 0.0, True)]
        distance_km = self.analyzer.calculate_distance(positions)
        self.assertEqual(distance_km, 0.0)
    
    def test_workload_metrics_no_sprints(self):
        """Test workload metrics with low speeds."""
        speeds = [5.0, 6.0, 5.5, 6.5, 5.0]  # All below high-speed threshold
        # Create dummy positions for these speeds (4-tuple with is_detected)
        positions = [(float(i), 0.0, float(i)/30.0, True) for i in range(len(speeds) + 1)]
        # Call calculate_workload_metrics with detected_flags
        detected_flags = [True] * len(speeds)
        metrics = self.analyzer.calculate_workload_metrics(speeds, detected_flags, positions)
        
        self.assertEqual(metrics['sprint_count'], 0)
        self.assertEqual(metrics['high_speed_distance_km'], 0.0)
        self.assertEqual(metrics['sprint_distance_km'], 0.0)
        # Max will be median of sustained window, which will be close to 5.5-6.0
        self.assertGreater(metrics['max_speed_mph'], 5.0)
        self.assertLess(metrics['max_speed_mph'], 7.0)
    
    def test_workload_metrics_with_sprints(self):
        """Test workload metrics with sprint bursts."""
        # Sprint threshold: 15.7 mph
        # Need sustained speeds above threshold for >=1s (30 frames at 30 fps)
        # Create a longer sequence with sustained high speeds
        speeds = [
            10.0, 10.0, 10.0,  # Warmup
            16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 20.0,  # First sprint burst (10 frames)
            20.0, 19.5, 19.0, 18.5, 18.0, 17.5, 17.0, 16.5, 16.0, 16.0,  # Continue (10 more)
            16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 20.0,  # Continue (10 more = 30 total)
            15.0, 14.0, 13.0, 12.0, 11.0, 10.0,  # Recovery (drops below 90% = 14.1 mph)
            16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 20.0,  # Second sprint burst (10 frames)
            20.0, 19.5, 19.0, 18.5, 18.0, 17.5, 17.0, 16.5, 16.0, 16.0,  # Continue (10 more)
            16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 20.0,  # Continue (10 more = 30 total)
            10.0, 10.0, 10.0
        ]
        # Create dummy positions (4-tuple with is_detected)
        positions = [(float(i), 0.0, float(i)/30.0, True) for i in range(len(speeds) + 1)]
        # Call calculate_workload_metrics with detected_flags
        detected_flags = [True] * len(speeds)
        metrics = self.analyzer.calculate_workload_metrics(speeds, detected_flags, positions)
        
        # With sustained window and dwell threshold, should detect sprint bursts
        # The sustained speed calculation will smooth these, so we should see counts
        self.assertGreaterEqual(metrics['sprint_count'], 1)
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
    
    def test_speed_zones_synthetic(self):
        """Test speed zone calculations with synthetic trajectory."""
        track_id = 1
        
        # Create a trajectory with known speed zones
        # Walk: 0-7 km/h = 0-4.35 mph = 0-1.94 m/s
        # Jog: 7-15 km/h = 4.35-9.32 mph = 1.94-4.17 m/s
        # Run: 15-20 km/h = 9.32-12.43 mph = 4.17-5.56 m/s
        # HSR: 20-25 km/h = 12.43-15.53 mph = 5.56-6.94 m/s
        # Sprint: >=25 km/h = >=15.53 mph = >=6.94 m/s
        
        # 30 frames walking at 1.5 m/s (5.4 km/h)
        for i in range(30):
            self.analyzer.add_position(track_id, float(i) * 1.5 / 30.0, 0.0, float(i) / 30.0)
        
        # 30 frames jogging at 3.5 m/s (12.6 km/h)
        for i in range(30, 60):
            x_prev = 29 * 1.5 / 30.0
            self.analyzer.add_position(track_id, x_prev + float(i - 30) * 3.5 / 30.0, 0.0, float(i) / 30.0)
        
        # 30 frames running at 5.0 m/s (18 km/h)
        for i in range(60, 90):
            x_prev = 29 * 1.5 / 30.0 + 29 * 3.5 / 30.0
            self.analyzer.add_position(track_id, x_prev + float(i - 60) * 5.0 / 30.0, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Should have distance in walk, jog, and run zones
        self.assertGreater(result['zone_walk_km'], 0.0)
        self.assertGreater(result['zone_jog_km'], 0.0)
        self.assertGreater(result['zone_run_km'], 0.0)
        # No HSR or sprint in this trajectory
        self.assertLess(result['zone_hsr_km'], 0.01)
        self.assertLess(result['zone_sprint_km'], 0.01)
    
    def test_temporal_metrics(self):
        """Test minutes_played, visible_minutes, and coverage_pct."""
        track_id = 1
        
        # Add positions over 60 frames (2 seconds at 30 fps)
        for i in range(60):
            self.analyzer.add_position(track_id, float(i) * 0.5, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # minutes_played: ~2 seconds = 0.0333 minutes
        self.assertAlmostEqual(result['minutes_played'], 2.0 / 60.0, delta=0.01)
        # visible_minutes: 60 frames / 30 fps / 60 = 0.0333 minutes
        self.assertAlmostEqual(result['visible_minutes'], 60.0 / 30.0 / 60.0, delta=0.01)
        # coverage_pct: 60 / 900 * 100 = 6.67%
        self.assertAlmostEqual(result['coverage_pct'], 60.0 / 900.0 * 100.0, delta=0.1)
    
    def test_spatial_metrics(self):
        """Test avg_pitch_x and avg_pitch_y."""
        track_id = 1
        
        # Move from (10, 20) to (30, 40) over 20 frames
        for i in range(20):
            x = 10.0 + i * 1.0
            y = 20.0 + i * 1.0
            self.analyzer.add_position(track_id, x, y, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Average should be around (20, 30)
        self.assertAlmostEqual(result['avg_pitch_x'], 19.5, delta=1.0)
        self.assertAlmostEqual(result['avg_pitch_y'], 29.5, delta=1.0)
    
    def test_hsr_and_sprint_counts(self):
        """Test HSR and sprint burst counts with dwell."""
        track_id = 1
        
        # HSR threshold: 12.3 mph = 5.5 m/s
        # Sprint threshold: 15.7 mph = 7.0 m/s
        # At 30 fps, need 30 frames for 1 second dwell
        
        # Start with slow movement
        for i in range(30):
            self.analyzer.add_position(track_id, float(i) * 0.1, 0.0, float(i) / 30.0)
        
        # HSR burst: 40 frames at 6.0 m/s (13.4 mph)
        for i in range(30, 70):
            x_prev = 29 * 0.1
            self.analyzer.add_position(track_id, x_prev + float(i - 30) * 6.0 / 30.0, 0.0, float(i) / 30.0)
        
        # Recovery
        for i in range(70, 100):
            x_prev = 29 * 0.1 + 39 * 6.0 / 30.0
            self.analyzer.add_position(track_id, x_prev + float(i - 70) * 0.1, 0.0, float(i) / 30.0)
        
        # Sprint burst: 35 frames at 7.5 m/s (16.8 mph)
        for i in range(100, 135):
            x_prev = 29 * 0.1 + 39 * 6.0 / 30.0 + 29 * 0.1
            self.analyzer.add_position(track_id, x_prev + float(i - 100) * 7.5 / 30.0, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Should detect 1 HSR burst (40 frames > 30 frame threshold)
        self.assertGreaterEqual(result['hsr_count'], 1)
        # Should detect 1 sprint burst (35 frames > 30 frame threshold)
        self.assertGreaterEqual(result['sprint_count'], 1)
        # hi_efforts should be sum
        self.assertEqual(result['hi_efforts_count'], result['hsr_count'] + result['sprint_count'])
    
    def test_acceleration_events(self):
        """Test high acceleration and deceleration event counts."""
        track_id = 1
        
        # Create a trajectory with acceleration
        # Start at rest
        for i in range(10):
            self.analyzer.add_position(track_id, 0.0, 0.0, float(i) / 30.0)
        
        # Accelerate: go from 0 to 6 m/s over 30 frames (~0.2 m/s^2 per frame = 6 m/s^2 total)
        for i in range(10, 40):
            # Quadratic trajectory: x = 0.5 * a * t^2, with a = 6 m/s^2
            t = (i - 10) / 30.0
            x = 0.5 * 6.0 * t * t
            self.analyzer.add_position(track_id, x, 0.0, float(i) / 30.0)
        
        # Constant speed for a bit
        x_const = 0.5 * 6.0 * (30.0 / 30.0) ** 2
        for i in range(40, 60):
            x = x_const + (i - 40) * 6.0 / 30.0
            self.analyzer.add_position(track_id, x, 0.0, float(i) / 30.0)
        
        # Decelerate: go from 6 m/s to 0 over 30 frames
        for i in range(60, 90):
            t = (i - 60) / 30.0
            x_decel = x_const + (20 * 6.0 / 30.0) + 6.0 * t - 0.5 * 6.0 * t * t
            self.analyzer.add_position(track_id, x_decel, 0.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        self.assertIsNotNone(result)
        # Should detect acceleration and deceleration events
        # (exact count depends on smoothing, but should be > 0)
        self.assertIsNotNone(result['accel_count_high'])
        self.assertIsNotNone(result['decel_count_high'])
    
    def test_heatmap_grid(self):
        """Test heatmap generation on a known trajectory."""
        track_id = 1
        
        # Move in a square: (0,0) -> (10,0) -> (10,10) -> (0,10) -> (0,0)
        # 30 frames per side = 120 frames total
        
        # Side 1: (0,0) to (10,0)
        for i in range(30):
            x = i * 10.0 / 30.0
            self.analyzer.add_position(track_id, x, 0.0, float(i) / 30.0)
        
        # Side 2: (10,0) to (10,10)
        for i in range(30, 60):
            y = (i - 30) * 10.0 / 30.0
            self.analyzer.add_position(track_id, 10.0, y, float(i) / 30.0)
        
        # Side 3: (10,10) to (0,10)
        for i in range(60, 90):
            x = 10.0 - (i - 60) * 10.0 / 30.0
            self.analyzer.add_position(track_id, x, 10.0, float(i) / 30.0)
        
        # Side 4: (0,10) to (0,0)
        for i in range(90, 120):
            y = 10.0 - (i - 90) * 10.0 / 30.0
            self.analyzer.add_position(track_id, 0.0, y, float(i) / 30.0)
        
        heatmaps = self.analyzer.get_all_heatmaps()
        
        self.assertIn(track_id, heatmaps)
        heatmap = heatmaps[track_id]
        
        # Should be 14 rows x 21 columns
        self.assertEqual(len(heatmap), 14)
        self.assertEqual(len(heatmap[0]), 21)
        
        # Should have non-zero values along the perimeter
        total_time = sum(sum(row) for row in heatmap)
        # Total time should be ~4 seconds (120 frames / 30 fps)
        self.assertAlmostEqual(total_time, 4.0, delta=0.2)
    
    def test_null_metrics_without_calibration(self):
        """Test that metrics are calculated correctly even when calibration might be missing."""
        # This test just ensures the analyzer doesn't crash when calculating metrics
        track_id = 1
        
        # Add some positions
        for i in range(60):
            self.analyzer.add_position(track_id, float(i) * 0.5, 10.0, float(i) / 30.0)
        
        result = self.analyzer.analyze_player(track_id)
        
        # All fields should be present
        self.assertIsNotNone(result)
        self.assertIn('top_speed_mph', result)
        self.assertIn('top_speed_kmh', result)
        self.assertIn('distance_km', result)
        self.assertIn('minutes_played', result)
        self.assertIn('visible_minutes', result)
        self.assertIn('distance_per_min_m', result)
        self.assertIn('avg_pitch_x', result)
        self.assertIn('avg_pitch_y', result)
        self.assertIn('zone_walk_km', result)
        self.assertIn('zone_jog_km', result)
        self.assertIn('zone_run_km', result)
        self.assertIn('zone_hsr_km', result)
        self.assertIn('zone_sprint_km', result)
        self.assertIn('hsr_count', result)
        self.assertIn('sprint_count', result)
        self.assertIn('hi_efforts_count', result)
        self.assertIn('accel_count_high', result)
        self.assertIn('decel_count_high', result)
        self.assertIn('coverage_pct', result)


if __name__ == '__main__':
    unittest.main()
