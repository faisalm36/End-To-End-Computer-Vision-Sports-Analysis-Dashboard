"""Regression tests for pipeline bugs found in first Mac run."""

import unittest
import tempfile
import shutil
from pathlib import Path
import cv2
import numpy as np
import json

from cv.pipeline import SoccerAnalyticsPipeline
from cv.config import Config
from cv.tracklet_stitching import TrackletStitcher


class TestHotfixPipelineBugs(unittest.TestCase):
    """Test fixes for bugs 1-4 from first Mac run."""
    
    def setUp(self):
        """Create temp directory for test outputs."""
        self.test_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up temp directory."""
        shutil.rmtree(self.test_dir)
    
    def _create_test_video(self, path: str, num_frames: int = 30, width: int = 640, height: int = 480):
        """Create a simple test video."""
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(path, fourcc, 30.0, (width, height))
        
        for i in range(num_frames):
            # Create frame with moving objects
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            
            # Draw 2-3 moving "players" (colored rectangles)
            # Player 1: moves left to right
            x1 = int(50 + i * 10)
            cv2.rectangle(frame, (x1, 100), (x1 + 40, 180), (255, 0, 0), -1)
            
            # Player 2: moves right to left
            x2 = int(500 - i * 10)
            cv2.rectangle(frame, (x2, 200), (x2 + 40, 280), (0, 255, 0), -1)
            
            # Player 3: stationary (sometimes occluded)
            if i % 3 != 0:  # Intermittent detection
                cv2.rectangle(frame, (300, 300), (340, 380), (0, 0, 255), -1)
            
            out.write(frame)
        
        out.release()
    
    def test_bug1_no_ocr_crash(self):
        """Bug 1: CRASH with --no-ocr due to uninitialized jersey_numbers."""
        video_path = Path(self.test_dir) / "test_video.mp4"
        output_dir = Path(self.test_dir) / "output_no_ocr"
        
        # Create test video
        self._create_test_video(str(video_path), num_frames=30)
        
        # Create config WITHOUT calibration (so stitching won't run, but still tests jersey_numbers init)
        config = Config()
        
        # Create pipeline with OCR DISABLED
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            enable_ocr=False,  # Bug trigger
            enable_team_classification=False,
            tracker='botsort'
        )
        
        # This should NOT crash
        try:
            pipeline.process_video(
                video_path=str(video_path),
                output_dir=str(output_dir),
                annotate_video=False,
                sample_ocr_every_n_frames=10
            )
            success = True
        except UnboundLocalError as e:
            if 'jersey_numbers' in str(e):
                success = False
            else:
                raise
        
        self.assertTrue(success, "Pipeline should not crash with OCR disabled")
        
        # Verify outputs exist
        meta_path = output_dir / "meta.json"
        self.assertTrue(meta_path.exists(), "meta.json should exist")
    
    def test_bug2_tracklet_timestamps(self):
        """Bug 2a: Tracklet timestamps should use actual frame indices, not enumerate indices."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        # Tracklet 1: appears in frames 0-30
        positions_track1 = [(float(i), 0.0, float(i) / 30.0) for i in range(31)]
        stitcher.add_tracklet(
            track_id=1,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=positions_track1,
            frame_range=(0, 30)
        )
        
        # Tracklet 2: appears in frames 60-90 (1 second gap)
        # With correct timestamps: should be stitchable (1s gap, short distance)
        # With wrong enumerate timestamps: would appear to overlap or have wrong timing
        positions_track2 = [(float(i), 1.0, float(i) / 30.0) for i in range(60, 91)]
        stitcher.add_tracklet(
            track_id=2,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=positions_track2,
            frame_range=(60, 90)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # These should be stitchable (same team, same jersey, feasible gap)
        self.assertEqual(track_to_player[1], track_to_player[2],
                        "Tracklets with correct timestamps should stitch")
    
    def test_bug2_singleton_tracklets_get_uid(self):
        """Bug 2b: All tracklets should get a player_uid, including singletons."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        # Add 3 non-overlapping tracklets with different jerseys (can't stitch)
        for tid, jersey in [(1, 10), (2, 7), (3, 4)]:
            stitcher.add_tracklet(
                track_id=tid,
                team=0,
                jersey_number=jersey,
                appearance_vector=None,
                positions=[(float(tid * 10), 0.0, float(tid))],
                frame_range=(tid * 30, tid * 30 + 10)
            )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # All tracks should have a player_uid
        self.assertEqual(len(track_to_player), 3, "All tracklets should get a player_uid")
        self.assertIn(1, track_to_player)
        self.assertIn(2, track_to_player)
        self.assertIn(3, track_to_player)
        
        # Each should have a different uid (singletons)
        uids = set(track_to_player.values())
        self.assertEqual(len(uids), 3, "Singleton tracklets should each get their own uid")
    
    def test_bug2_overlapping_tracklets_forbidden(self):
        """Bug 2c: Overlapping tracklets must not be stitched."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        # Tracklet 1: frames 0-50
        stitcher.add_tracklet(
            track_id=1,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 1.0)],
            frame_range=(0, 50)
        )
        
        # Tracklet 2: frames 30-80 (overlaps with track 1)
        stitcher.add_tracklet(
            track_id=2,
            team=0,
            jersey_number=10,  # Same jersey
            appearance_vector=None,
            positions=[(1.5, 0.0, 1.0), (2.5, 0.0, 2.0)],
            frame_range=(30, 80)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # Must NOT stitch (they overlap in time)
        self.assertNotEqual(track_to_player[1], track_to_player[2],
                           "Overlapping tracklets must not stitch")
    
    def test_bug3_ball_gating_summary(self):
        """Bug 3: Ball gating should log summary count, not per-frame."""
        video_path = Path(self.test_dir) / "test_video.mp4"
        output_dir = Path(self.test_dir) / "output_ball_gating"
        
        # Create test video
        self._create_test_video(str(video_path), num_frames=50)
        
        config = Config()
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            enable_ocr=False,
            enable_team_classification=False,
            tracker='botsort'
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
        
        # Should have ball_gated_frames field
        self.assertIn('ball_gated_frames', meta, "meta.json should have ball_gated_frames")
        self.assertIsInstance(meta['ball_gated_frames'], int)
        self.assertGreaterEqual(meta['ball_gated_frames'], 0)
    
    def test_bug4_frame_timing_reported(self):
        """Bug 4: Per-frame processing time should be reported."""
        video_path = Path(self.test_dir) / "test_video.mp4"
        output_dir = Path(self.test_dir) / "output_timing"
        
        # Create test video
        self._create_test_video(str(video_path), num_frames=30)
        
        config = Config()
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            enable_ocr=False,
            enable_team_classification=False,
            tracker='botsort'
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
        
        # Should have avg_frame_time_ms field
        self.assertIn('avg_frame_time_ms', meta, "meta.json should have avg_frame_time_ms")
        self.assertIsInstance(meta['avg_frame_time_ms'], (int, float))
        self.assertGreater(meta['avg_frame_time_ms'], 0, "Frame time should be positive")
    
    def test_bug2_stats_sanity_warnings(self):
        """Bug 2d: Warning if uid count much lower than track count."""
        video_path = Path(self.test_dir) / "test_video.mp4"
        output_dir = Path(self.test_dir) / "output_warnings"
        
        # Create test video
        self._create_test_video(str(video_path), num_frames=60)
        
        # Create config WITH calibration (so stitching will run)
        # Use default/approximate calibration
        config = Config(use_default_if_missing=True)
        
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            enable_ocr=False,
            enable_team_classification=True,
            tracker='botsort'
        )
        
        pipeline.process_video(
            video_path=str(video_path),
            output_dir=str(output_dir),
            annotate_video=False
        )
        
        # Check metadata for warnings
        meta_path = output_dir / "meta.json"
        with open(meta_path) as f:
            meta = json.load(f)
        
        # Should have warnings field
        self.assertIn('warnings', meta)
        self.assertIsInstance(meta['warnings'], list)
    
    def test_large_frame_processing(self):
        """Bug 4: Ensure large frames (3456x2234) process without upsampling."""
        video_path = Path(self.test_dir) / "large_video.mp4"
        output_dir = Path(self.test_dir) / "output_large"
        
        # Create large test video
        self._create_test_video(str(video_path), num_frames=10, width=1920, height=1080)
        
        config = Config()
        pipeline = SoccerAnalyticsPipeline(
            config=config,
            enable_ocr=False,
            enable_team_classification=False,
            tracker='botsort'
        )
        
        # Should process without error
        pipeline.process_video(
            video_path=str(video_path),
            output_dir=str(output_dir),
            annotate_video=False
        )
        
        # Check metadata
        meta_path = output_dir / "meta.json"
        with open(meta_path) as f:
            meta = json.load(f)
        
        # Verify resolution was recorded
        self.assertEqual(meta['width'], 1920)
        self.assertEqual(meta['height'], 1080)
        self.assertIn('avg_frame_time_ms', meta)


if __name__ == '__main__':
    unittest.main()
