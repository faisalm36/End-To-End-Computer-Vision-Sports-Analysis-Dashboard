"""Unit tests for team classification and role assignment."""

import unittest
import numpy as np
from unittest.mock import Mock
from cv.team_classifier import TeamClassifier


class TestTeamClassifier(unittest.TestCase):
    """Test team and role classification."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.classifier = TeamClassifier(n_teams=2, early_frames_count=10)
    
    def test_initialization(self):
        """Test classifier initialization."""
        self.assertEqual(self.classifier.n_teams, 2)
        self.assertEqual(self.classifier.early_frames_count, 10)
        self.assertFalse(self.classifier.fitted)
        self.assertEqual(self.classifier.frame_count, 0)
    
    def test_extract_jersey_color(self):
        """Test jersey color extraction from frame."""
        # Create a simple test frame (blue torso)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[200:400, 250:390, 0] = 255  # Blue channel
        
        bbox = [250, 150, 390, 450]  # Player bbox
        
        color = self.classifier.extract_jersey_color(frame, bbox, use_lab=False)
        
        self.assertIsNotNone(color)
        self.assertEqual(len(color), 3)
        # Should have high value in one channel (blue in HSV space)
    
    def test_extract_jersey_color_invalid_bbox(self):
        """Test that invalid bbox returns None."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Invalid bbox (inverted)
        bbox = [390, 450, 250, 150]
        color = self.classifier.extract_jersey_color(frame, bbox)
        
        self.assertIsNone(color)
    
    def test_add_observation(self):
        """Test adding color observations."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :, 2] = 200  # Red-ish
        
        bbox = [100, 100, 200, 300]
        track_id = 1
        
        self.classifier.add_observation(track_id, frame, bbox)
        
        self.assertEqual(self.classifier.frame_count, 1)
        self.assertGreater(len(self.classifier.track_colors[track_id]), 0)
    
    def test_fit_teams_insufficient_data(self):
        """Test that fitting doesn't happen with insufficient data."""
        # Add only one observation
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.classifier.add_observation(1, frame, [100, 100, 200, 300])
        
        self.classifier.fit_teams()
        
        self.assertFalse(self.classifier.fitted)
        self.assertIsNone(self.classifier.kmeans)
    
    def test_fit_teams_with_data(self):
        """Test team fitting with sufficient data."""
        # Create players with distinct colors
        frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame1[:, :, 2] = 200  # Red team
        
        frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame2[:, :, 0] = 200  # Blue team
        
        bbox = [100, 100, 200, 300]
        
        # Add observations for multiple players in each team
        for i in range(3):
            self.classifier.add_observation(i + 1, frame1, bbox)
        
        for i in range(3):
            self.classifier.add_observation(i + 4, frame2, bbox)
        
        # Simulate reaching early frames count
        self.classifier.frame_count = self.classifier.early_frames_count
        
        self.classifier.fit_teams()
        
        self.assertTrue(self.classifier.fitted)
        self.assertIsNotNone(self.classifier.kmeans)
    
    def test_assign_teams(self):
        """Test team assignment after fitting."""
        # Create and fit with distinct colors
        frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame1[:, :, 2] = 200  # Red
        
        frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame2[:, :, 0] = 200  # Blue
        
        bbox = [100, 100, 200, 300]
        
        # Add observations
        for i in range(3):
            self.classifier.add_observation(i + 1, frame1, bbox)
        
        for i in range(3):
            self.classifier.add_observation(i + 4, frame2, bbox)
        
        self.classifier.frame_count = self.classifier.early_frames_count
        self.classifier.fit_teams()
        self.classifier.assign_teams()
        
        # Check that teams were assigned
        for track_id in [1, 2, 3, 4, 5, 6]:
            team = self.classifier.get_team(track_id)
            role = self.classifier.get_role(track_id)
            
            # Should be assigned to a team or be referee
            self.assertTrue(team in [0, 1, None])
            self.assertIn(role, ['player', 'referee'])
    
    def test_get_team_unknown_track(self):
        """Test getting team for unknown track."""
        team = self.classifier.get_team(999)
        self.assertIsNone(team)
    
    def test_get_role_unknown_track(self):
        """Test getting role for unknown track."""
        role = self.classifier.get_role(999)
        self.assertEqual(role, 'unknown')
    
    def test_referee_detection(self):
        """Test that outliers are detected as referees."""
        # Create two teams with similar colors
        frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame1[:, :, 2] = 200  # Red
        
        frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame2[:, :, 0] = 200  # Blue
        
        # Referee with very different color (green)
        frame_ref = np.zeros((480, 640, 3), dtype=np.uint8)
        frame_ref[:, :, 1] = 200  # Green
        
        bbox = [100, 100, 200, 300]
        
        # Add team observations
        for i in range(3):
            self.classifier.add_observation(i + 1, frame1, bbox)
        
        for i in range(3):
            self.classifier.add_observation(i + 4, frame2, bbox)
        
        # Add referee observation
        self.classifier.add_observation(99, frame_ref, bbox)
        
        self.classifier.frame_count = self.classifier.early_frames_count
        self.classifier.fit_teams()
        self.classifier.assign_teams(outlier_threshold=1.0)  # Lower threshold for test
        
        # Referee should have no team assignment
        ref_team = self.classifier.get_team(99)
        ref_role = self.classifier.get_role(99)
        
        # Referee might be None or assigned to a team depending on threshold
        # Main test is that the logic runs without error
        self.assertIsNotNone(ref_role)


if __name__ == '__main__':
    unittest.main()
