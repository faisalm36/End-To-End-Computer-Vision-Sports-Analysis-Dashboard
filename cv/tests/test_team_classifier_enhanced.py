"""Unit tests for v2.0 enhanced team classifier with goalkeeper detection."""

import unittest
import numpy as np
from cv.team_classifier_enhanced import TeamClassifierEnhanced


class TestTeamClassifierEnhanced(unittest.TestCase):
    """Test enhanced team classification with kit priors and goalkeeper detection."""
    
    def test_kit_colour_prior_biases_assignment(self):
        """Test that kit colour priors bias team assignment."""
        # Define kit colours: Team A = red, Team B = blue
        kit_colours = {
            'team_a': {'lab': [50, 50, 0]},  # Reddish
            'team_b': {'lab': [50, 0, -50]}  # Bluish
        }
        
        classifier = TeamClassifierEnhanced(
            n_teams=2,
            early_frames_count=10,
            kit_colours=kit_colours
        )
        
        # Mock adding observations
        # Track 1: red colour (should be team A)
        classifier.track_colors[1] = [np.array([50, 55, 5])]  # Close to team A
        classifier.track_median_colors[1] = np.array([50, 55, 5])
        
        # Track 2: blue colour (should be team B)
        classifier.track_colors[2] = [np.array([50, 5, -45])]  # Close to team B
        classifier.track_median_colors[2] = np.array([50, 5, -45])
        
        classifier.frame_count = 10
        classifier.fit_teams()
        
        # With kit priors, assignment should be consistent
        team1 = classifier.get_team(1)
        team2 = classifier.get_team(2)
        
        self.assertIsNotNone(team1, "Team 1 should be assigned")
        self.assertIsNotNone(team2, "Team 2 should be assigned")
        self.assertNotEqual(team1, team2, "Different colours should get different teams")
    
    def test_goalkeeper_detection_by_position(self):
        """Test goalkeeper detection based on position near goal."""
        classifier = TeamClassifierEnhanced(
            n_teams=2,
            early_frames_count=10
        )
        
        # Mock team assignment
        classifier.track_teams = {1: 'A', 2: 'A', 3: 'B', 4: 'B'}
        classifier.track_roles = {1: 'player', 2: 'player', 3: 'player', 4: 'player'}
        classifier.fitted = True
        
        # Tracklet positions (x, y)
        tracklet_positions = {
            1: [(5.0, 34.0)] * 20,   # Team A: near x=0 goal, center y
            2: [(52.0, 34.0)] * 20,  # Team A: midfield
            3: [(100.0, 34.0)] * 20, # Team B: near x=105 goal, center y
            4: [(50.0, 34.0)] * 20   # Team B: midfield
        }
        
        pitch_length_m = 105.0
        
        classifier.detect_goalkeepers(tracklet_positions, pitch_length_m)
        
        # Tracks 1 and 3 should be detected as goalkeepers
        self.assertEqual(classifier.get_role(1), 'goalkeeper', "Track 1 should be GK")
        self.assertEqual(classifier.get_role(2), 'player', "Track 2 should be player")
        self.assertEqual(classifier.get_role(3), 'goalkeeper', "Track 3 should be GK")
        self.assertEqual(classifier.get_role(4), 'player', "Track 4 should be player")
    
    def test_goalkeeper_detection_with_different_colour(self):
        """Test goalkeeper detection enhanced by different kit colour."""
        classifier = TeamClassifierEnhanced(
            n_teams=2,
            early_frames_count=10
        )
        
        # Mock setup
        classifier.track_teams = {1: 'A', 2: 'A'}
        classifier.track_roles = {1: 'player', 2: 'player'}
        classifier.track_median_colors = {
            1: np.array([50, 0, 0]),   # Red
            2: np.array([50, -30, 0])  # Green (different)
        }
        classifier.fitted = True
        
        # Both near goal
        tracklet_positions = {
            1: [(5.0, 34.0)] * 20,
            2: [(5.0, 30.0)] * 20
        }
        
        classifier.detect_goalkeepers(tracklet_positions, 105.0)
        
        # Track 2 (different colour + position) more likely to be GK
        role1 = classifier.get_role(1)
        role2 = classifier.get_role(2)
        
        # At least one should be goalkeeper
        self.assertTrue(role1 == 'goalkeeper' or role2 == 'goalkeeper',
                       "At least one near-goal player should be GK")
    
    def test_no_goalkeeper_detection_without_fit(self):
        """Test that goalkeeper detection requires fitted classifier."""
        classifier = TeamClassifierEnhanced(
            n_teams=2,
            early_frames_count=10
        )
        
        # Not fitted
        self.assertFalse(classifier.fitted)
        
        tracklet_positions = {
            1: [(5.0, 34.0)] * 20
        }
        
        # Should not crash, but also not detect
        classifier.detect_goalkeepers(tracklet_positions, 105.0)
        
        # No team assigned, so no role update
        self.assertEqual(classifier.get_role(1), 'unknown')


if __name__ == '__main__':
    unittest.main()
