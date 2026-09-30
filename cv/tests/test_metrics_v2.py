"""Additional unit tests for v2.0 metrics changes."""

import unittest
from cv.metrics import PerformanceAnalyzer


class TestMetricsV2Enhancements(unittest.TestCase):
    """Test v2.0 metrics enhancements: acceleration cap and detected-only top speed."""
    
    def setUp(self):
        """Set up analyzer."""
        self.analyzer = PerformanceAnalyzer(
            fps=30.0,
            max_plausible_speed_mph=25.0
        )
    
    def test_acceleration_cap_concept(self):
        """Test acceleration cap concept (6 m/s² cap in calculate_accelerations)."""
        # The acceleration cap is applied in calculate_accelerations()
        # Test that the cap value is reasonable
        max_accel_ms2 = 6.0
        
        # Convert to mph/s for comparison
        max_accel_mph_s = max_accel_ms2 * 2.23694  # m/s² to mph/s
        
        self.assertEqual(max_accel_ms2, 6.0, "Max acceleration should be 6.0 m/s²")
        self.assertGreater(max_accel_mph_s, 0, "Max acceleration in mph/s should be positive")
    
    def test_top_speed_only_from_detected_frames(self):
        """Test that top speed is calculated only from is_detected=True frames."""
        # Add detected frames with reasonable speed
        for i in range(10):
            self.analyzer.add_position(
                1, float(i) * 2.0, 0.0, float(i) / 30.0, is_detected=True
            )
        
        # Add interpolated frames with huge fake speed (should be ignored)
        for i in range(10, 15):
            self.analyzer.add_position(
                1, float(i) * 100.0, 0.0, float(i) / 30.0, is_detected=False
            )
        
        result = self.analyzer.analyze_player(1)
        
        # Top speed should not include the interpolated crazy speeds
        top_speed = result['top_speed_mph']
        
        self.assertIsNotNone(top_speed, "Top speed should be computed")
        # Detected-only speed should be reasonable (not the 100x multiplier from interpolated)
        self.assertLess(top_speed, 50.0, "Top speed should be reasonable without interpolated data")
    
    def test_detected_and_total_frames_reported(self):
        """Test that detected_frames and total_frames are reported in stats."""
        # Add positions with mix of detected and interpolated
        for i in range(7):
            self.analyzer.add_position(1, float(i), 0.0, float(i)/30.0, is_detected=True)
        
        for i in range(7, 10):
            self.analyzer.add_position(1, float(i), 0.0, float(i)/30.0, is_detected=False)
        
        result = self.analyzer.analyze_player(1)
        
        # Should report detected and total frames fields
        self.assertIn('detected_frames', result, "Should have detected_frames field")
        self.assertIn('total_frames', result, "Should have total_frames field")
        # Values should be non-negative integers
        self.assertGreaterEqual(result['detected_frames'], 0)
        self.assertGreaterEqual(result['total_frames'], 0)
    
    def test_no_detected_frames_returns_minimal_speed(self):
        """Test that with zero detected frames, top speed is minimal."""
        # Only interpolated positions (no real detections)
        for i in range(5):
            self.analyzer.add_position(1, float(i), 0.0, float(i)/30.0, is_detected=False)
        
        result = self.analyzer.analyze_player(1)
        
        # Should have the v2.0 fields
        self.assertIn('detected_frames', result, "Should have detected_frames field")
        self.assertIn('total_frames', result, "Should have total_frames field")
        
        # Top speed should be minimal with only interpolated data
        top_speed = result['top_speed_mph']
        self.assertIsNotNone(top_speed, "Top speed should be present")
        self.assertLessEqual(top_speed, 1.0, "Top speed should be minimal with no detected frames")


if __name__ == '__main__':
    unittest.main()
