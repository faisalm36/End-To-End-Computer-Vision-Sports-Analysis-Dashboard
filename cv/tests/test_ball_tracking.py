"""Unit tests for v2.0 ball tracking with Kalman filter."""

import unittest
import numpy as np
from cv.ball_tracking import BallTracker


class TestBallTracker(unittest.TestCase):
    """Test dedicated ball tracking with Kalman filter and speed gating."""
    
    def setUp(self):
        """Set up test tracker (without actual YOLO model for unit tests)."""
        # We'll mock the model in actual tests
        self.fps = 30.0
        self.max_gap_frames = 10
    
    def test_speed_gating_accepts_reasonable_speed(self):
        """Test that reasonable ball speeds are accepted."""
        tracker = BallTracker(
            model_path="yolov8n.pt",
            ball_conf=0.3,
            device="cpu",
            fps=self.fps,
            max_gap_frames=self.max_gap_frames
        )
        
        # Simulate reasonable ball movement: 10 pixels/frame at 30fps
        # If 1 meter = 50 pixels (example), this is 0.2 m/frame = 6 m/s - reasonable
        prev_center = np.array([100.0, 100.0])
        curr_center = np.array([110.0, 100.0])
        
        # This should be accepted (10 px at 30fps, well below 35 m/s limit)
        result = tracker._check_speed_plausibility(prev_center, curr_center)
        self.assertTrue(result, "Reasonable ball speed should be accepted")
    
    def test_speed_gating_rejects_implausible_jump(self):
        """Test that implausible ball jumps are rejected."""
        tracker = BallTracker(
            model_path="yolov8n.pt",
            ball_conf=0.3,
            device="cpu",
            fps=self.fps,
            max_gap_frames=self.max_gap_frames
        )
        
        # Simulate impossible ball teleportation: 1000 pixels in one frame
        prev_center = np.array([100.0, 100.0])
        curr_center = np.array([1100.0, 100.0])
        
        # This should be rejected
        result = tracker._check_speed_plausibility(prev_center, curr_center)
        self.assertFalse(result, "Implausible ball jump should be rejected")
    
    def test_interpolation_fills_short_gaps(self):
        """Test that short gaps are filled with interpolation."""
        tracker = BallTracker(
            model_path="yolov8n.pt",
            ball_conf=0.3,
            device="cpu",
            fps=self.fps,
            max_gap_frames=5  # Allow 5-frame gaps
        )
        
        # Manually set up state
        tracker.last_valid_center = np.array([100.0, 100.0])
        tracker.last_valid_frame = 0
        tracker.gap_frames = 3
        
        # Try to interpolate at frame 3 (gap of 3 frames)
        interpolated = tracker._try_interpolate(3)
        
        self.assertIsNotNone(interpolated, "Should interpolate within max gap")
        self.assertTrue(interpolated['is_interpolated'], "Should be flagged as interpolated")
        self.assertFalse(interpolated['is_detected'], "Should not be flagged as detected")
    
    def test_no_interpolation_beyond_max_gap(self):
        """Test that gaps beyond max are not interpolated."""
        tracker = BallTracker(
            model_path="yolov8n.pt",
            ball_conf=0.3,
            device="cpu",
            fps=self.fps,
            max_gap_frames=5
        )
        
        tracker.last_valid_center = np.array([100.0, 100.0])
        tracker.last_valid_frame = 0
        tracker.gap_frames = 10  # Gap too large
        
        # Try to interpolate at frame 10 (gap of 10 frames > max 5)
        interpolated = tracker._try_interpolate(10)
        
        self.assertIsNone(interpolated, "Should not interpolate beyond max gap")
    
    def test_kalman_update_maintains_state(self):
        """Test that Kalman filter updates state correctly."""
        tracker = BallTracker(
            model_path="yolov8n.pt",
            ball_conf=0.3,
            device="cpu",
            fps=self.fps,
            max_gap_frames=self.max_gap_frames
        )
        
        # Initialize Kalman filter
        tracker._init_kalman_filter(np.array([100.0, 100.0]))
        
        initial_state = tracker.kf.x.copy()
        
        # Update with a new measurement
        tracker._update_kalman(np.array([110.0, 100.0]))
        
        updated_state = tracker.kf.x.copy()
        
        # State should have changed
        self.assertFalse(np.array_equal(initial_state, updated_state),
                        "Kalman state should update with new measurement")
        
        # Position should be close to measurement (but smoothed)
        self.assertAlmostEqual(updated_state[0], 110.0, delta=10.0,
                              msg="Updated x position should be close to measurement")


if __name__ == '__main__':
    unittest.main()
