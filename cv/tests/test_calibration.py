"""Unit tests for v2.0 pitch calibration with RANSAC."""

import unittest
import numpy as np
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
    
    def test_ransac_homography_with_outliers(self):
        """Test RANSAC can handle outliers in correspondences."""
        # 4 good points + 2 outliers
        image_pts = np.array([
            [50, 50], [1230, 50], [1230, 670], [50, 670],  # Good
            [500, 500], [1500, 1000]  # Outliers
        ], dtype=np.float32)
        
        pitch_pts = np.array([
            [0, 0], [105, 0], [105, 68], [0, 68],
            [999, 999], [-100, -100]  # Bad correspondences
        ], dtype=np.float32)
        
        calibrator = PitchKeypointCalibrator(
            pitch_width_m=68.0,
            pitch_length_m=105.0,
            ransac_threshold=5.0
        )
        
        H, inliers = calibrator.compute_homography_ransac(image_pts, pitch_pts)
        
        self.assertIsNotNone(H, "Should compute homography despite outliers")
        self.assertIsNotNone(inliers, "Should return inlier mask")
        
        # At least 4 inliers (the good points)
        inlier_count = np.sum(inliers)
        self.assertGreaterEqual(inlier_count, 4, "Should find at least 4 inliers")
    
    def test_reprojection_error_calculation(self):
        """Test reprojection error is calculated correctly."""
        image_pts = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.float32)
        pitch_pts = np.array([[0, 0], [105, 0], [105, 68], [0, 68]], dtype=np.float32)
        
        calibrator = PitchKeypointCalibrator(
            pitch_width_m=68.0,
            pitch_length_m=105.0
        )
        
        H, inliers = calibrator.compute_homography_ransac(image_pts, pitch_pts)
        errors = calibrator.compute_reprojection_errors(H, image_pts, pitch_pts)
        
        self.assertEqual(len(errors), len(image_pts), "Should have error per point")
        self.assertTrue(all(e >= 0 for e in errors), "Errors should be non-negative")
        
        # With perfect correspondence, errors should be very small
        self.assertTrue(np.mean(errors) < 1.0, "Mean error should be small for perfect data")
    
    def test_temporal_smoothing_reduces_jitter(self):
        """Test temporal smoothing reduces homography jitter."""
        calibrator = PitchKeypointCalibrator(
            pitch_width_m=68.0,
            pitch_length_m=105.0,
            temporal_smoothing_alpha=0.8  # Strong smoothing
        )
        
        # First homography
        H1 = np.eye(3, dtype=np.float32)
        H1[0, 2] = 10.0  # Translation
        
        calibrator.update_temporal_filter(H1)
        smoothed1 = calibrator.get_smoothed_homography()
        
        # Should be close to H1 (first frame)
        self.assertIsNotNone(smoothed1)
        np.testing.assert_array_almost_equal(smoothed1, H1, decimal=2)
        
        # Second homography with large jump
        H2 = np.eye(3, dtype=np.float32)
        H2[0, 2] = 50.0  # Large translation jump
        
        calibrator.update_temporal_filter(H2)
        smoothed2 = calibrator.get_smoothed_homography()
        
        # Smoothed should be between H1 and H2 (not at H2)
        self.assertLess(smoothed2[0, 2], H2[0, 2],
                       "Temporal smoothing should reduce jump magnitude")
        self.assertGreater(smoothed2[0, 2], H1[0, 2],
                          "Smoothed value should move toward new measurement")


if __name__ == '__main__':
    unittest.main()
