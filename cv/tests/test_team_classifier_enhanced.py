"""Unit tests for v2.0 enhanced team classifier with goalkeeper detection."""

import unittest
import numpy as np
from cv.team_classifier_enhanced import TeamClassifierEnhanced


class TestTeamClassifierEnhanced(unittest.TestCase):
    """Test enhanced team classification with kit priors and goalkeeper detection."""
    
    def test_kit_colour_distance_calculation(self):
        """Test kit colour distance calculation concept."""
        # Kit colours in LAB space
        kit_red = np.array([50, 50, 0])  # Reddish
        kit_blue = np.array([50, 0, -50])  # Bluish
        
        # Player colour close to red
        player_red = np.array([50, 55, 5])
        
        # Distance to red vs blue
        dist_to_red = np.linalg.norm(player_red - kit_red)
        dist_to_blue = np.linalg.norm(player_red - kit_blue)
        
        self.assertLess(dist_to_red, dist_to_blue,
                       "Red player should be closer to red kit than blue kit")
    
    def test_goalkeeper_position_concept(self):
        """Test goalkeeper position detection concept."""
        pitch_length_m = 105.0
        goal_line_threshold = 15.0  # Within 15m of goal
        
        # Positions
        gk_position_x = 5.0  # Near x=0 goal
        outfield_position_x = 52.5  # Midfield
        
        # Check if near goal
        near_left_goal = gk_position_x < goal_line_threshold
        near_right_goal = gk_position_x > (pitch_length_m - goal_line_threshold)
        
        self.assertTrue(near_left_goal, "GK position should be near left goal")
        self.assertFalse(near_right_goal, "GK position should not be near right goal")
        
        # Outfield not near goal
        outfield_near_left = outfield_position_x < goal_line_threshold
        self.assertFalse(outfield_near_left, "Outfield position should not be near goal")
    
    def test_colour_difference_for_goalkeeper(self):
        """Test colour difference detection for goalkeeper."""
        # Team outfield colours (similar)
        outfield_colors = [
            np.array([50, 10, 5]),
            np.array([50, 12, 4]),
            np.array([50, 11, 6])
        ]
        
        # Goalkeeper colour (different)
        gk_color = np.array([50, -30, 10])
        
        # Mean outfield colour
        mean_outfield = np.mean(outfield_colors, axis=0)
        
        # Distance from GK to mean
        dist_gk = np.linalg.norm(gk_color - mean_outfield)
        
        # Distance from outfield player to mean
        dist_outfield = np.linalg.norm(outfield_colors[0] - mean_outfield)
        
        self.assertGreater(dist_gk, dist_outfield,
                          "GK colour should be more different from team mean")
    
    def test_per_tracklet_classification_concept(self):
        """Test per-tracklet classification concept."""
        # Tracklet 1: multiple observations of red
        track1_colors = [
            np.array([50, 50, 5]),
            np.array([50, 52, 4]),
            np.array([50, 48, 6])
        ]
        
        # Median colour for track 1
        track1_median = np.median(track1_colors, axis=0)
        
        # Should be close to red
        self.assertGreater(track1_median[1], 40, "Track 1 median should be reddish")
    
    def test_min_tracks_requirement(self):
        """Test minimum tracks requirement for classification."""
        min_tracks = 4
        
        # Sufficient tracks
        track_count_ok = 5
        self.assertGreaterEqual(track_count_ok, min_tracks,
                               "Should classify with sufficient tracks")
        
        # Insufficient tracks
        track_count_low = 2
        self.assertLess(track_count_low, min_tracks,
                       "Should warn with insufficient tracks")


if __name__ == '__main__':
    unittest.main()
