"""Unit tests for homography transformation."""

import unittest
import numpy as np
from cv.homography import HomographyTransform


class TestHomographyTransform(unittest.TestCase):
    """Test homography coordinate transformation."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Simple test case: corners of a rectangle
        # Image: 1000x1000 with corners at (100,100), (900,100), (900,900), (100,900)
        # Pitch: 105x68 meters with corners at (0,0), (105,0), (105,68), (0,68)
        self.image_points = [
            [100, 100],
            [900, 100],
            [900, 900],
            [100, 900]
        ]
        
        self.pitch_points = [
            [0, 0],
            [105, 0],
            [105, 68],
            [0, 68]
        ]
        
        self.transform = HomographyTransform(
            self.image_points,
            self.pitch_points,
            pitch_width_m=68.0,
            pitch_length_m=105.0
        )
    
    def test_initialization(self):
        """Test homography initialization."""
        self.assertIsNotNone(self.transform.H)
        self.assertEqual(self.transform.pitch_width_m, 68.0)
        self.assertEqual(self.transform.pitch_length_m, 105.0)
    
    def test_initialization_insufficient_points(self):
        """Test that initialization fails with <4 points."""
        with self.assertRaises(ValueError):
            HomographyTransform(
                [[0, 0], [1, 0]],
                [[0, 0], [1, 0]]
            )
    
    def test_initialization_mismatched_points(self):
        """Test that initialization fails with mismatched point counts."""
        with self.assertRaises(ValueError):
            HomographyTransform(
                [[0, 0], [1, 0], [1, 1]],
                [[0, 0], [1, 0]]
            )
    
    def test_corner_transformation(self):
        """Test transformation of corner points."""
        # Transform should map image corners to pitch corners (with small tolerance)
        result = self.transform.transform_point(100, 100)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.0, delta=1.0)
        self.assertAlmostEqual(result[1], 0.0, delta=1.0)
        
        result = self.transform.transform_point(900, 900)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 105.0, delta=1.0)
        self.assertAlmostEqual(result[1], 68.0, delta=1.0)
    
    def test_center_transformation(self):
        """Test transformation of center point."""
        # Center of image should map roughly to center of pitch
        result = self.transform.transform_point(500, 500)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 52.5, delta=5.0)
        self.assertAlmostEqual(result[1], 34.0, delta=5.0)
    
    def test_bbox_center_transformation(self):
        """Test bbox center transformation."""
        bbox = [400, 400, 600, 600]  # Center at (500, 500)
        result = self.transform.transform_bbox_center(bbox)
        self.assertIsNotNone(result)
        # Should be near pitch center
        self.assertAlmostEqual(result[0], 52.5, delta=5.0)
        self.assertAlmostEqual(result[1], 34.0, delta=5.0)
    
    def test_foot_position_transformation(self):
        """Test foot position (bottom center) transformation."""
        bbox = [400, 300, 600, 600]  # Bottom center at (500, 600)
        result = self.transform.transform_foot_position(bbox)
        self.assertIsNotNone(result)
        # Y should be closer to bottom of pitch
        self.assertGreater(result[1], 30.0)
    
    def test_out_of_bounds_rejection(self):
        """Test that points far outside pitch are rejected."""
        # Point way outside the pitch
        result = self.transform.transform_point(2000, 2000)
        # Should either be None or far from valid range
        if result is not None:
            # If not filtered, values should be outside reasonable bounds
            self.assertTrue(
                result[0] < -10 or result[0] > 115 or
                result[1] < -10 or result[1] > 78
            )


if __name__ == '__main__':
    unittest.main()
