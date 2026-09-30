"""Unit tests for v2.0 enhanced OCR with legibility filtering."""

import unittest
import numpy as np
from cv.ocr_enhanced import LegibilityFilter, EnhancedJerseyReader


class TestLegibilityFilter(unittest.TestCase):
    """Test legibility filter for jersey number OCR."""
    
    def test_sharp_high_contrast_passes(self):
        """Test that sharp, high-contrast images pass legibility."""
        legibility_filter = LegibilityFilter(
            min_sharpness=100.0,
            min_contrast=50.0,
            min_size=20
        )
        
        # Create sharp, high-contrast test image (checkerboard pattern)
        image = np.zeros((100, 100), dtype=np.uint8)
        image[::10, ::10] = 255  # High frequency pattern
        
        bbox = [10, 10, 90, 90]
        
        result = legibility_filter.is_legible(image, bbox)
        
        # High-frequency checkerboard should be sharp
        self.assertTrue(result['is_legible'], "Sharp high-contrast image should pass")
        self.assertGreater(result['sharpness'], 100.0, "Sharpness should be high")
        self.assertGreater(result['contrast'], 50.0, "Contrast should be high")
    
    def test_blurry_low_contrast_fails(self):
        """Test that blurry, low-contrast images fail legibility."""
        legibility_filter = LegibilityFilter(
            min_sharpness=100.0,
            min_contrast=50.0,
            min_size=20
        )
        
        # Create uniform gray image (no detail, no contrast)
        image = np.full((100, 100), 128, dtype=np.uint8)
        
        bbox = [10, 10, 90, 90]
        
        result = legibility_filter.is_legible(image, bbox)
        
        # Uniform image should fail (low sharpness and contrast)
        self.assertFalse(result['is_legible'], "Uniform image should fail legibility")
        self.assertLess(result['sharpness'], 100.0, "Sharpness should be low")
        self.assertLess(result['contrast'], 50.0, "Contrast should be low")
    
    def test_small_bbox_fails_size_check(self):
        """Test that small bounding boxes fail size check."""
        legibility_filter = LegibilityFilter(
            min_sharpness=50.0,
            min_contrast=20.0,
            min_size=30  # Minimum 30 pixels
        )
        
        # Sharp image
        image = np.zeros((100, 100), dtype=np.uint8)
        image[::5, ::5] = 255
        
        # But small bbox
        bbox = [10, 10, 25, 25]  # 15x15 = 225 px² < 900 px² (30²)
        
        result = legibility_filter.is_legible(image, bbox)
        
        # Should fail size check despite sharpness
        self.assertFalse(result['is_legible'], "Small bbox should fail size check")


class TestEnhancedJerseyReader(unittest.TestCase):
    """Test enhanced jersey reader with confidence-weighted voting."""
    
    def test_confidence_weighted_voting(self):
        """Test that higher confidence readings weigh more."""
        # Mock reader without actual EasyOCR
        reader = EnhancedJerseyReader.__new__(EnhancedJerseyReader)
        reader.track_readings = {}
        reader.roster_team_a = None
        reader.roster_team_b = None
        
        # Add readings for track_id=1
        reader.add_reading(1, (10, 0.9, None), team='A')  # High confidence
        reader.add_reading(1, (99, 0.2, None), team='A')  # Low confidence noise
        reader.add_reading(1, (10, 0.8, None), team='A')  # High confidence
        
        jersey_numbers = reader.get_all_jersey_numbers()
        
        # Should pick 10 (weighted by confidence)
        self.assertEqual(jersey_numbers[1], 10, "Should pick high-confidence reading")
    
    def test_roster_constraint_filters_invalid(self):
        """Test that roster constraint filters out invalid numbers."""
        reader = EnhancedJerseyReader.__new__(EnhancedJerseyReader)
        reader.track_readings = {}
        reader.roster_team_a = {1, 2, 3, 10}
        reader.roster_team_b = {5, 6, 7, 20}
        
        # Add readings for track_id=1 (team A)
        reader.add_reading(1, (10, 0.9, None), team='A')  # Valid
        reader.add_reading(1, (99, 0.8, None), team='A')  # Invalid (not in roster)
        
        jersey_numbers = reader.get_all_jersey_numbers()
        
        # Should pick 10 (in roster), not 99 despite similar confidence
        self.assertEqual(jersey_numbers[1], 10, "Should respect roster constraint")
    
    def test_no_readings_returns_none(self):
        """Test that tracks with no readings return None."""
        reader = EnhancedJerseyReader.__new__(EnhancedJerseyReader)
        reader.track_readings = {}
        reader.roster_team_a = None
        reader.roster_team_b = None
        
        jersey_numbers = reader.get_all_jersey_numbers()
        
        self.assertEqual(len(jersey_numbers), 0, "Should return empty dict for no readings")


if __name__ == '__main__':
    unittest.main()
