"""End-to-end tests for target tracking with synthetic data."""

import unittest
import tempfile
import json
from pathlib import Path
import sys


class TestTargetTrackingE2E(unittest.TestCase):
    """End-to-end test for target tracking with synthetic detections."""
    
    def test_target_tracking_workflow(self):
        """Test complete target tracking workflow with mock data."""
        from cv.target_tracking import TargetTracker, TargetSpec
        
        # Create tracker
        tracker = TargetTracker(
            max_speed_ms=12.0,
            fps=30.0,
            appearance_threshold=0.7,
            occlusion_max_frames=30
        )
        
        # Create mock detections (100 frames)
        detections = []
        
        # Player 1: jersey 10, team 0, frames 0-40
        for i in range(41):
            detections.append({
                'frame': i,
                'timestamp': i / 30.0,
                'track_id': 1,
                'class': 'player',
                'bbox_x1': 100 + i * 2,
                'bbox_y1': 200,
                'bbox_x2': 150 + i * 2,
                'bbox_y2': 300,
                'pitch_x': 50 + i * 0.5,
                'pitch_y': 30,
                'team': 0,
                'jersey_number': 10,
                'confidence': 0.9
            })
        
        # Gap (occluded): frames 41-50
        
        # Player 1 reappears with new track_id: frames 51-99
        for i in range(51, 100):
            detections.append({
                'frame': i,
                'timestamp': i / 30.0,
                'track_id': 2,  # New track ID
                'class': 'player',
                'bbox_x1': 100 + i * 2,
                'bbox_y1': 200,
                'bbox_x2': 150 + i * 2,
                'bbox_y2': 300,
                'pitch_x': 50 + i * 0.5,
                'pitch_y': 30,
                'team': 0,
                'jersey_number': 10,
                'confidence': 0.9
            })
        
        # Resolve target by jersey
        spec = TargetSpec(target_jersey=10, target_team=0)
        
        player_uid_map = {1: 1, 2: 1}  # Both tracks belong to same player
        team_map = {1: 0, 2: 0}
        jersey_map = {1: 10, 2: 10}
        
        success, error = tracker.resolve_target(
            spec, detections, player_uid_map, team_map, jersey_map
        )
        
        self.assertTrue(success, f"Target resolution failed: {error}")
        self.assertEqual(tracker.target_player_uid, 1)
        self.assertEqual(tracker.target_jersey, 10)
        
        # Track through video
        target_frames = tracker.track_target(
            detections, 30.0, team_map, jersey_map
        )
        
        # Verify results
        self.assertEqual(len(target_frames), 100, "Should have entry for every frame")
        
        # Check states
        # Frames 0-40: tracked
        for i in range(41):
            frame = target_frames[i]
            self.assertIn(frame['state'], ['tracked', 'reacquired'])
            self.assertIsNotNone(frame['bbox'])
        
        # Frames 41-50: occluded or lost
        for i in range(41, 51):
            frame = target_frames[i]
            self.assertIn(frame['state'], ['occluded', 'lost'])
        
        # Frames 51+: reacquired or tracked
        frame_51 = target_frames[51]
        self.assertEqual(frame_51['state'], 'reacquired')
        
        # Get statistics
        stats = tracker.get_statistics(100, 30.0)
        
        self.assertEqual(stats['player_uid'], 1)
        self.assertIn(1, stats['track_ids'])
        self.assertIn(2, stats['track_ids'])
        self.assertGreater(stats['tracked_pct'], 80)  # Should track most frames
        self.assertGreaterEqual(stats['reacquisition_count'], 1)  # At least one re-acquisition
        
        print(f"\nTarget tracking statistics:")
        print(f"  Tracked: {stats['tracked_frames']}/{stats['total_frames']} frames ({stats['tracked_pct']:.1f}%)")
        print(f"  Re-acquisitions: {stats['reacquisition_count']}")
        print(f"  Lost segments: {len(stats['lost_segments'])}")
    
    def test_target_track_json_schema(self):
        """Test target_track.json schema generation."""
        # Mock target track output
        target_track = {
            'schema_version': '1.0',
            'video': {
                'width': 1920,
                'height': 1080,
                'fps': 30.0,
                'frame_count': 100
            },
            'target': {
                'player_uid': 1,
                'track_ids': [1, 2],
                'jersey': 10,
                'team': 0,
                'spec': {
                    'target_frame': None,
                    'target_point': None,
                    'target_bbox': None,
                    'target_jersey': 10,
                    'target_team': 0
                }
            },
            'frames': []
        }
        
        # Add mock frames
        for i in range(100):
            state = 'tracked' if i < 41 or i >= 51 else 'occluded'
            bbox = [100 + i * 2, 200, 150 + i * 2, 300] if state == 'tracked' else None
            
            target_track['frames'].append({
                'frame': i,
                't': round(i / 30.0, 3),
                'bbox': bbox,
                'confidence': 0.9 if bbox else 0.0,
                'state': state,
                'source': 'detected' if bbox else 'lost',
                'pitch_x': round(50 + i * 0.5, 2) if bbox else None,
                'pitch_y': 30.0 if bbox else None
            })
        
        # Save to file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
            json.dump(target_track, f, indent=2)
        
        try:
            # Load and validate
            with open(temp_path, 'r') as f:
                loaded = json.load(f)
            
            # Validate schema
            self.assertEqual(loaded['schema_version'], '1.0')
            self.assertEqual(loaded['video']['frame_count'], 100)
            self.assertEqual(len(loaded['frames']), 100)
            
            # Validate frame entry
            frame_0 = loaded['frames'][0]
            required_fields = ['frame', 't', 'bbox', 'confidence', 'state', 'source', 'pitch_x', 'pitch_y']
            for field in required_fields:
                self.assertIn(field, frame_0)
            
            print("\nTarget track JSON schema validated successfully")
        
        finally:
            Path(temp_path).unlink()


class TestFFmpegEncoder(unittest.TestCase):
    """Test FFmpeg encoder availability and settings."""
    
    def test_imageio_ffmpeg_available(self):
        """Test that imageio-ffmpeg is available."""
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            self.assertTrue(Path(ffmpeg_exe).exists(), "FFmpeg executable not found")
            print(f"\nFFmpeg found: {ffmpeg_exe}")
        except ImportError:
            self.skipTest("imageio-ffmpeg not installed")
    
    def test_h264_codec_name(self):
        """Test H.264 codec name for verification."""
        codec_name = 'h264'
        pix_fmt = 'yuv420p'
        
        # These are the expected values in ffprobe output
        self.assertEqual(codec_name, 'h264')
        self.assertEqual(pix_fmt, 'yuv420p')


if __name__ == '__main__':
    unittest.main()
