"""Unit tests for v2.0 pitch calibration with RANSAC."""

import unittest
import numpy as np
import cv2
from cv.calibration import PitchKeypointCalibrator, HomographyTransformEnhanced


class TestPitchCalibration(unittest.TestCase):
    """Test RANSAC-based pitch calibration and reprojection error gating."""
    
    def test_calibration_quality_perfect_correspondence(self):
        """Test calibration quality with perfect correspondences."""
        # Perfect square correspondence
        image_pts = np.array([
            [0, 0], [100, 0], [100, 100], [0, 100]
        ], dtype=np.float32)
        
        pitch_pts = np.array([
            [0, 0], [105, 0], [105, 68], [0, 68]
        ], dtype=np.float32)
        
        transform = HomographyTransformEnhanced(
            image_points=image_pts.tolist(),
            pitch_points=pitch_pts.tolist(),
            pitch_width_m=68.0,
            pitch_length_m=105.0
        )
        
        quality = transform.get_calibration_quality()
        
        self.assertIsNotNone(quality, "Should return quality dict")
        self.assertEqual(quality['method'], 'manual')
        self.assertEqual(quality['inliers'], 4)
        self.assertEqual(quality['total_points'], 4)
        self.assertEqual(quality['inlier_ratio'], 1.0)
    
    def test_ransac_parameters(self):
        """Test RANSAC parameters are reasonable."""
        calibrator = PitchKeypointCalibrator(
            pitch_width_m=68.0,
            pitch_length_m=105.0,
            ransac_threshold=5.0
        )
        
        self.assertEqual(calibrator.ransac_threshold, 5.0)
        self.assertEqual(calibrator.pitch_width_m, 68.0)
        self.assertEqual(calibrator.pitch_length_m, 105.0)
    
    def test_homography_computation(self):
        """Test basic homography computation without outliers."""
        # 4 perfect correspondences
        image_pts = np.array([
            [0, 0], [100, 0], [100, 100], [0, 100]
        ], dtype=np.float32)
        
        pitch_pts = np.array([
            [0, 0], [105, 0], [105, 68], [0, 68]
        ], dtype=np.float32)
        
        # Use cv2 directly for testing
        H, status = cv2.findHomography(image_pts, pitch_pts, cv2.RANSAC, 5.0)
        
        self.assertIsNotNone(H, "Should compute homography")
        self.assertEqual(H.shape, (3, 3), "Homography should be 3x3")
        self.assertIsNotNone(status, "Should return inlier status")
    
    def test_reprojection_error_concept(self):
        """Test reprojection error calculation concept."""
        # With perfect homography, error should be zero
        # This tests the mathematical concept
        
        src_pt = np.array([100.0, 100.0])
        dst_pt = np.array([52.5, 34.0])  # Pitch center
        
        # Identity transform means error = distance
        error = np.linalg.norm(src_pt - dst_pt)
        
        self.assertGreater(error, 0, "Error should be positive for different points")
        
        # For same point, error is zero
        error_zero = np.linalg.norm(src_pt - src_pt)
        self.assertEqual(error_zero, 0.0, "Error should be zero for identical points")
    
    def test_temporal_smoothing_alpha(self):
        """Test temporal smoothing parameter."""
        calibrator = PitchKeypointCalibrator(
            pitch_width_m=68.0,
            pitch_length_m=105.0,
            temporal_smoothing_alpha=0.8
        )
        
        self.assertEqual(calibrator.temporal_smoothing_alpha, 0.8)
        self.assertGreater(calibrator.temporal_smoothing_alpha, 0.0)
        self.assertLessEqual(calibrator.temporal_smoothing_alpha, 1.0)


if __name__ == '__main__':
    unittest.main()
