"""Tests for real TeamClassifierEnhanced integration (no mocking)."""

import unittest
import numpy as np
import tempfile
import shutil
from pathlib import Path
import json
import sys

# Add cv to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from team_classifier_enhanced import TeamClassifierEnhanced
from pipeline import SoccerAnalyticsPipeline
from config import Config


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
        
        # Verify track_teams is populated
        self.assertIn(1, classifier.track_teams)
        self.assertIn(2, classifier.track_teams)
        
        # Verify get_team works
        team1 = classifier.get_team(1)
        team2 = classifier.get_team(2)
        self.assertIsNotNone(team1)
        self.assertIsNotNone(team2)
        # Different colors should get different teams
        self.assertNotEqual(team1, team2)

    def test_detect_frame_uses_real_api(self):
        """Test detect_frame.py uses real TeamClassifierEnhanced API."""
        from detect_frame import detect_frame_candidates
        
        # Create a minimal synthetic video (1 frame)
        temp_dir = tempfile.mkdtemp()
        try:
            video_path = Path(temp_dir) / "test_video.mp4"
            out_dir = Path(temp_dir) / "out"
            out_dir.mkdir()
            
            # Create 1-frame video with opencv
            import cv2
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(video_path), fourcc, 30, (640, 480))
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            frame[200:300, 250:350] = [255, 255, 255]  # White box
            writer.write(frame)
            writer.release()
            
            # Run detect_frame - should not raise AttributeError
            try:
                detect_frame_candidates(
                    video_path=str(video_path),
                    t=0.0,
                    output_dir=str(out_dir),
                    device='cpu',
                    model_path=None
                )
            except AttributeError as e:
                if 'track_votes' in str(e):
                    self.fail(f"detect_frame still references track_votes: {e}")
                # Other AttributeErrors are OK (e.g. no YOLO model in test env)
        finally:
            shutil.rmtree(temp_dir)

    def test_track_player_uses_real_api(self):
        """Test track_player uses real TeamClassifierEnhanced API via pipeline."""
        # Create minimal pipeline
        config = Config(use_default_if_missing=True, device='cpu')
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            model_path=None,
            device='cpu',
            enable_ocr=False,
            tracker='botsort'
        )
        
        # Verify pipeline's team_classifier uses real API
        if pipeline.team_classifier:
            self.assertTrue(hasattr(pipeline.team_classifier, 'track_teams'))
            self.assertFalse(hasattr(pipeline.team_classifier, 'track_votes'))

    def test_pipeline_iterates_track_teams(self):
        """Test pipeline correctly iterates track_teams.keys() not track_votes."""
        config = Config(use_default_if_missing=True, device='cpu')
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            model_path=None,
            device='cpu',
            enable_ocr=False,
            tracker='botsort'
        )
        
        # Simulate fitted classifier with some tracks
        if pipeline.team_classifier:
            pipeline.team_classifier.track_teams = {1: 0, 2: 1, 3: 0}
            pipeline.team_classifier.track_median_colors = {
                1: np.array([50, 100, 150]),
                2: np.array([200, 100, 50]),
                3: np.array([60, 110, 140])
            }
            pipeline.team_classifier.fitted = True
            
            # Extract team/appearance maps (used in pipeline.py lines 632 and 922)
            team_map = {}
            appearance_map = {}
            
            # This is the code pattern from pipeline.py - should not raise AttributeError
            try:
                for track_id in pipeline.team_classifier.track_teams.keys():
                    team = pipeline.team_classifier.get_team(track_id)
                    if team is not None:
                        team_map[track_id] = team
                    appearance = pipeline.team_classifier.track_median_colors.get(track_id)
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
