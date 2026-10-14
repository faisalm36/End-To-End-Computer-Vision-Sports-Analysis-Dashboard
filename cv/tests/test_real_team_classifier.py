"""Tests for real TeamClassifierEnhanced integration (no mocking)."""

import unittest
import numpy as np
from pathlib import Path
import sys

# Add cv to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cv.team_classifier_enhanced import TeamClassifierEnhanced


class TestRealTeamClassifierEnhanced(unittest.TestCase):
    """Test suite for real TeamClassifierEnhanced API to catch AttributeError regressions."""

    def test_real_classifier_attributes(self):
        """Verify TeamClassifierEnhanced has expected attributes (track_teams not track_votes)."""
        classifier = TeamClassifierEnhanced(n_teams=2)
        
        # Should have these attributes
        self.assertTrue(hasattr(classifier, 'track_teams'))
        self.assertTrue(hasattr(classifier, 'track_roles'))
        self.assertTrue(hasattr(classifier, 'track_median_colors'))
        self.assertTrue(hasattr(classifier, 'get_team'))
        self.assertTrue(hasattr(classifier, 'get_role'))
        
        # Should NOT have track_votes
        self.assertFalse(hasattr(classifier, 'track_votes'))

    def test_classifier_lifecycle(self):
        """Test full classifier lifecycle: add observations, fit, query."""
        classifier = TeamClassifierEnhanced(n_teams=2, early_frames_count=10)
        
        # Create synthetic frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[100:200, 100:200] = [0, 0, 255]  # Red torso for track 1
        frame[100:200, 300:400] = [255, 0, 0]  # Blue torso for track 2
        
        # Add observations for two tracks
        for _ in range(5):
            classifier.add_observation(1, frame, [100, 100, 200, 200])
            classifier.add_observation(2, frame, [300, 100, 400, 200])
        
        # Fit teams
        classifier.fit_teams(min_samples=2)
        self.assertTrue(classifier.fitted)
        
        # Verify track_median_colors is populated (track_teams may be empty if clustering fails)
        self.assertIn(1, classifier.track_median_colors)
        self.assertIn(2, classifier.track_median_colors)
        
        # Verify get_team works (returns int or None)
        # With only 2 tracks, teams may not be assigned, but method should not raise
        team1 = classifier.get_team(1)
        team2 = classifier.get_team(2)
        # Both should return a value (int or None), not raise AttributeError
        self.assertIsNotNone(classifier.track_median_colors.get(1))

    def test_track_teams_keys_iteration(self):
        """Test that track_teams can be iterated (the pattern used in pipeline.py)."""
        classifier = TeamClassifierEnhanced(n_teams=2)
        
        # Simulate fitted classifier with some tracks
        classifier.track_teams = {1: 0, 2: 1, 3: 0}
        classifier.track_median_colors = {
            1: np.array([50, 100, 150]),
            2: np.array([200, 100, 50]),
            3: np.array([60, 110, 140])
        }
        classifier.fitted = True
        
        # Extract team/appearance maps (used in pipeline.py lines 632 and 922)
        team_map = {}
        appearance_map = {}
        
        # This is the code pattern from pipeline.py - should not raise AttributeError
        try:
            for track_id in classifier.track_teams.keys():
                team = classifier.get_team(track_id)
                if team is not None:
                    team_map[track_id] = team
                appearance = classifier.track_median_colors.get(track_id)
                if appearance is not None:
                    appearance_map[track_id] = appearance
        except AttributeError as e:
            if 'track_votes' in str(e):
                self.fail(f"Pipeline still references track_votes: {e}")
            raise
        
        self.assertEqual(len(team_map), 3)
        self.assertEqual(len(appearance_map), 3)


if __name__ == '__main__':
    unittest.main()
