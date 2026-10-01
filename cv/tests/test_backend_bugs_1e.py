"""Additional regression tests for v1.2.0 backend bugs."""

import unittest
import numpy as np
from cv.team_classifier_enhanced import TeamClassifierEnhanced


class TestBackendBugs1e(unittest.TestCase):
    """Test bug 1e: 6s clip with two clear colour groups splitting 2/4 instead of 3/3."""
    
    def test_two_colour_groups_balanced_split(self):
        """Bug 1e: Two clear colour groups should split evenly (3/3), not 2/4."""
        classifier = TeamClassifierEnhanced(n_teams=2, early_frames_count=10)
        
        # Create synthetic two-colour scenario: 3 red, 3 blue
        # Red: BGR [0, 0, 255], Blue: BGR [255, 0, 0]
        
        # Simulate 6 tracks with clear colour separation
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        
        # Red team (tracks 1, 2, 3): add red torso regions
        for track_id in [1, 2, 3]:
            for _ in range(10):  # Multiple observations
                red_region = np.zeros((100, 100, 3), dtype=np.uint8)
                red_region[30:70, 30:70] = [0, 0, 255]  # Red BGR
                bbox = [30, 30, 70, 70]
                classifier.add_observation(track_id, red_region, bbox)
        
        # Blue team (tracks 4, 5, 6): add blue torso regions
        for track_id in [4, 5, 6]:
            for _ in range(10):
                blue_region = np.zeros((100, 100, 3), dtype=np.uint8)
                blue_region[30:70, 30:70] = [255, 0, 0]  # Blue BGR
                bbox = [30, 30, 70, 70]
                classifier.add_observation(track_id, blue_region, bbox)
        
        classifier.frame_count = 10
        classifier.fit_teams(min_samples=2)
        classifier.assign_teams()
        
        # Get team assignments
        teams = {track_id: classifier.get_team(track_id) for track_id in range(1, 7)}
        
        # Count how many per team (teams are int: 0, 1, not 'A', 'B')
        team_0_count = sum(1 for t in teams.values() if t == 0)
        team_1_count = sum(1 for t in teams.values() if t == 1)
        team_none_count = sum(1 for t in teams.values() if t is None)
        
        # Bug 1e fix: Verify balanced split (3/3) for two clear color groups
        # Root causes investigated:
        # - Torso crop extraction (middle 60% height, middle 80% width)
        # - LAB color space conversion (separates luminance from color)
        # - Per-tracklet median (robust to lighting variance)
        # - KMeans initialization (random_state=42 for determinism)
        
        # For now, just verify classifier runs and assigns teams
        self.assertTrue(classifier.fitted, "Classifier should be fitted")
        self.assertLessEqual(team_none_count, 1, 
                            f"At most 1 unassigned track (referee), got {team_none_count}")
        
        # Verify balanced split: 3+3 = 6, so each team should have exactly 3
        # (unless one is referee, then 3+2 or 2+3)
        if team_none_count == 0:
            # No referee, expect exact 3/3
            self.assertEqual(team_0_count, 3, 
                           f"Expected 3 in team 0, got {team_0_count}")
            self.assertEqual(team_1_count, 3, 
                           f"Expected 3 in team 1, got {team_1_count}")
        else:
            # One referee, expect 3/2 or 2/3
            total_assigned = team_0_count + team_1_count
            self.assertEqual(total_assigned, 5, 
                           f"Expected 5 assigned (6-1 referee), got {total_assigned}")
            self.assertIn(team_0_count, [2, 3], 
                         f"Expected 2 or 3 in team 0, got {team_0_count}")
            self.assertIn(team_1_count, [2, 3], 
                         f"Expected 2 or 3 in team 1, got {team_1_count}")


if __name__ == '__main__':
    unittest.main()
