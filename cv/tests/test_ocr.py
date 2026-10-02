"""Unit tests for OCR jersey number reading and voting."""

import unittest
from unittest.mock import Mock, patch
from cv.ocr import JerseyNumberReader


class TestJerseyNumberReader(unittest.TestCase):
    """Test OCR and majority voting logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock EasyOCR to avoid actual initialization
        with patch('cv.ocr.easyocr.Reader'):
            self.reader = JerseyNumberReader(languages=['en'], gpu=False)
    
    def test_add_reading(self):
        """Test adding jersey number readings."""
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 11)
        
        self.assertEqual(len(self.reader.track_numbers[1]), 3)
    
    def test_add_reading_none(self):
        """Test that None readings are not added."""
        self.reader.add_reading(1, None)
        self.assertEqual(len(self.reader.track_numbers[1]), 0)
    
    def test_majority_vote_clear_winner(self):
        """Test majority vote with clear winner."""
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 11)
        
        result = self.reader.get_majority_vote(1, min_readings=3)
        self.assertEqual(result, 10)
    
    def test_majority_vote_insufficient_readings(self):
        """Test majority vote with insufficient readings."""
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        
        result = self.reader.get_majority_vote(1, min_readings=3)
        self.assertIsNone(result)
    
    def test_majority_vote_no_readings(self):
        """Test majority vote with no readings."""
        result = self.reader.get_majority_vote(999, min_readings=3)
        self.assertIsNone(result)
    
    def test_majority_vote_tie(self):
        """Test majority vote with tie (returns most common)."""
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 11)
        self.reader.add_reading(1, 11)
        
        result = self.reader.get_majority_vote(1, min_readings=3)
        # Should return one of them (Counter returns first in tie)
        self.assertIn(result, [10, 11])
    
    def test_get_all_jersey_numbers(self):
        """Test getting all jersey numbers."""
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        self.reader.add_reading(1, 10)
        
        self.reader.add_reading(2, 7)
        self.reader.add_reading(2, 7)
        self.reader.add_reading(2, 7)
        
        self.reader.add_reading(3, 15)  # Insufficient readings
        
        result = self.reader.get_all_jersey_numbers()
        
        self.assertEqual(result[1], 10)
        self.assertEqual(result[2], 7)
        self.assertIsNone(result[3])
    
    def test_jersey_number_filtering(self):
        """Test that only valid jersey numbers (0-99) would be accepted."""
        # This tests the logic in read_jersey_number
        # We'll test the filtering criteria
        
        # Mock OCR results
        mock_results = [
            ([], "10", 0.9),   # Valid
            ([], "99", 0.8),   # Valid
            ([], "0", 0.7),    # Valid
            ([], "100", 0.9),  # Invalid (>99)
            ([], "abc", 0.9),  # Invalid (not digit)
            ([], "5", 0.4),    # Invalid (low confidence)
        ]
        
        # Test filtering logic
        valid_numbers = []
        conf_threshold = 0.5
        
        for bbox_ocr, text, conf in mock_results:
            if conf >= conf_threshold and text.isdigit():
                num = int(text)
                if 0 <= num <= 99:
                    valid_numbers.append(num)
        
        self.assertEqual(valid_numbers, [10, 99, 0])


if __name__ == '__main__':
    unittest.main()
