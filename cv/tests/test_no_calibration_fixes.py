"""Regression tests for no-calibration scenario and 3-tuple fixes."""

import unittest
import tempfile
import shutil
from pathlib import Path
import numpy as np
from collections import defaultdict

from cv.team_classifier_enhanced import TeamClassifierEnhanced


class TestNoCalibrationAndTupleFixes(unittest.TestCase):
    """Test fixes for no-calibration stitching and 3-tuple handling."""
    
    def test_detect_goalkeepers_with_3tuples(self):
        """Test that detect_goalkeepers handles (x, y, frame) tuples."""
        classifier = TeamClassifierEnhanced(n_teams=2, early_frames_count=10)
        
        # Simulate fitted classifier with teams
        classifier.fitted = True
        classifier.track_teams = {1: 0, 2: 1}
        
        # Mock kmeans
        classifier.kmeans = type('obj', (object,), {
            'cluster_centers_': np.array([[100, 100, 100], [200, 200, 200]])
        })()
        
        # Track 1: goalkeeper position (near left goal, x < 20m)
        # Positions as 3-tuples: (x, y, frame)
        track_positions = {
            1: [(10.0 + i * 0.1, 50.0, i) for i in range(20)],
            2: [(50.0 + i * 0.1, 50.0, i) for i in range(20)]
        }
        
        # Should not crash
        try:
            classifier.detect_goalkeepers(track_positions, pitch_length_m=105.0)
            success = True
        except ValueError as e:
            if 'too many values to unpack' in str(e):
                success = False
            else:
                raise
        
        self.assertTrue(success, "detect_goalkeepers should handle 3-tuples")
    
    def test_aggregation_with_no_calibration_creates_stats_rows(self):
        """Test that all tracks get stats rows even without calibration."""
        # This is an integration-style test but without full pipeline
        # We'll simulate the scenario where tracks exist but have no pitch coords
        
        from cv.tracklet_stitching import TrackletStitcher
        
        stitcher = TrackletStitcher(max_speed_ms=5.0, fps=30.0)  # Use pixel-scale speeds
        
        # Add 10 tracklets with normalized image-space positions (0-1 range)
        for tid in range(1, 11):
            # Each track appears for 30 frames with slight movement
            positions = [
                (0.1 * tid + i * 0.001, 0.5 + i * 0.001, i) 
                for i in range(30)
            ]
            stitcher.add_tracklet(
                track_id=tid,
                team=tid % 2,
                jersey_number=tid,
                appearance_vector=None,
                positions=positions,
                frame_range=(tid * 100, tid * 100 + 29)
            )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # All 10 tracks should get a player_uid
        self.assertEqual(len(track_to_player), 10, "All tracks should get a player_uid")
        
        # Each should get its own uid (different teams/jerseys)
        uids = set(track_to_player.values())
        self.assertEqual(len(uids), 10, "Should have 10 unique player_uids")
    
    def test_normalized_positions_enable_stitching(self):
        """Test that normalized image-space positions work for stitching."""
        from cv.tracklet_stitching import TrackletStitcher
        
        # Use pixel-scale max speed (e.g., 0.1 screen widths per second)
        stitcher = TrackletStitcher(max_speed_ms=0.1, fps=30.0)
        
        # Track 1: normalized position (0.3, 0.5) for 1 second
        positions_1 = [(0.3 + i * 0.0001, 0.5, i / 30.0) for i in range(31)]
        stitcher.add_tracklet(
            track_id=1,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=positions_1,
            frame_range=(0, 30)
        )
        
        # Track 2: normalized position (0.32, 0.51) starting at t=2s
        # Gap: 1s, distance: ~0.022 screen units, speed: 0.022/s < 0.1/s (feasible)
        positions_2 = [(0.32 + i * 0.0001, 0.51, 2.0 + i / 30.0) for i in range(31)]
        stitcher.add_tracklet(
            track_id=2,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=positions_2,
            frame_range=(60, 90)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # These should stitch (same team, same jersey, feasible gap)
        self.assertEqual(track_to_player[1], track_to_player[2],
                        "Normalized positions should enable stitching")
    
    def test_metadata_contains_imgsz_fields(self):
        """Test that meta.json contains detection_imgsz and related fields."""
        import tempfile
        import cv2
        import json
        from cv.pipeline import SoccerAnalyticsPipeline
        from cv.config import Config
        
        test_dir = tempfile.mkdtemp()
        try:
            video_path = Path(test_dir) / "test.mp4"
            output_dir = Path(test_dir) / "output"
            
            # Create minimal test video
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(video_path), fourcc, 30.0, (640, 480))
            for _ in range(10):
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                out.write(frame)
            out.release()
            
            # Run pipeline
            config = Config()
            pipeline = SoccerAnalyticsPipeline(
                config=config,
                enable_ocr=False,
                enable_team_classification=False
            )
            
            pipeline.process_video(
                video_path=str(video_path),
                output_dir=str(output_dir),
                annotate_video=False
            )
            
            # Check metadata
            meta_path = output_dir / "meta.json"
            with open(meta_path) as f:
                meta = json.load(f)
            
            # Should have imgsz fields
            self.assertIn('detection_imgsz', meta, "meta should have detection_imgsz")
            self.assertIn('ball_detection_imgsz', meta, "meta should have ball_detection_imgsz")
            self.assertIn('avg_frame_time_ms', meta, "meta should have avg_frame_time_ms")
            
            # Values should be reasonable
            self.assertEqual(meta['detection_imgsz'], 1280, "detection_imgsz should be 1280")
            self.assertGreater(meta['avg_frame_time_ms'], 0, "avg_frame_time_ms should be positive")
            
        finally:
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()
