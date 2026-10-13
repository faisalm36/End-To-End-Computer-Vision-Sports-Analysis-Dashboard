"""Unit tests for v2.0 tracklet stitching."""

import unittest
import numpy as np
from cv.tracklet_stitching import TrackletStitcher


class TestTrackletStitching(unittest.TestCase):
    """Test offline tracklet stitching for stable player_uid."""
    
    def test_stitch_by_jersey_number(self):
        """Test stitching based on jersey number agreement."""
        stitcher = TrackletStitcher(
            max_speed_ms=12.0,
            fps=30.0,
            appearance_threshold=0.5,
            use_appearance=False  # Only jersey + team
        )
        
        # Two tracklets with same team and jersey, separated in time
        stitcher.add_tracklet(
            track_id=1,
            team='A',
            jersey_number=10,
            appearance_vector=None,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 1.0)],
            frame_range=(0, 30)
        )
        
        stitcher.add_tracklet(
            track_id=2,
            team='A',
            jersey_number=10,
            appearance_vector=None,
            positions=[(2.0, 0.0, 2.0), (3.0, 0.0, 3.0)],
            frame_range=(60, 90)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # Should be stitched into same player_uid
        self.assertEqual(track_to_player[1], track_to_player[2],
                        "Tracklets with same jersey+team should stitch")
    
    def test_no_stitch_different_teams(self):
        """Test that different teams are not stitched."""
        stitcher = TrackletStitcher(
            max_speed_ms=12.0,
            fps=30.0,
            use_appearance=False
        )
        
        stitcher.add_tracklet(
            track_id=1,
            team='A',
            jersey_number=10,
            appearance_vector=None,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 1.0)],
            frame_range=(0, 30)
        )
        
        stitcher.add_tracklet(
            track_id=2,
            team='B',
            jersey_number=10,  # Same jersey, different team
            appearance_vector=None,
            positions=[(2.0, 0.0, 2.0), (3.0, 0.0, 3.0)],
            frame_range=(60, 90)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # Should NOT be stitched (different teams)
        self.assertNotEqual(track_to_player[1], track_to_player[2],
                           "Different teams should not stitch")
    
    def test_physical_feasibility_blocks_impossible_stitch(self):
        """Test that physically impossible stitching is blocked."""
        stitcher = TrackletStitcher(
            max_speed_ms=12.0,  # 12 m/s max speed
            fps=30.0,
            use_appearance=False
        )
        
        # Tracklet 1 ends at (0, 0) at t=1s
        stitcher.add_tracklet(
            track_id=1,
            team='A',
            jersey_number=10,
            appearance_vector=None,
            positions=[(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
            frame_range=(0, 30)
        )
        
        # Tracklet 2 starts at (100, 0) at t=1.1s (0.1s gap)
        # Distance: 100m, time: 0.1s → speed = 1000 m/s (impossible!)
        stitcher.add_tracklet(
            track_id=2,
            team='A',
            jersey_number=10,
            appearance_vector=None,
            positions=[(100.0, 0.0, 1.1), (101.0, 0.0, 2.0)],
            frame_range=(33, 60)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # Should NOT be stitched (physically impossible)
        self.assertNotEqual(track_to_player[1], track_to_player[2],
                           "Physically impossible movement should block stitching")
    
    def test_appearance_similarity_helps_stitch(self):
        """Test that appearance similarity helps stitching."""
        stitcher = TrackletStitcher(
            max_speed_ms=12.0,
            fps=30.0,
            appearance_threshold=0.5,
            use_appearance=True
        )
        
        # Similar appearance vectors (cosine similarity ~0.95)
        vec1 = np.array([1.0, 0.5, 0.3])
        vec2 = np.array([0.98, 0.52, 0.31])
        
        stitcher.add_tracklet(
            track_id=1,
            team='A',
            jersey_number=None,  # No jersey
            appearance_vector=vec1,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 1.0)],
            frame_range=(0, 30)
        )
        
        stitcher.add_tracklet(
            track_id=2,
            team='A',
            jersey_number=None,
            appearance_vector=vec2,
            positions=[(2.0, 0.0, 2.0), (3.0, 0.0, 3.0)],
            frame_range=(60, 90)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # Should be stitched (same team + high appearance similarity)
        self.assertEqual(track_to_player[1], track_to_player[2],
                        "Similar appearance should help stitch")
    
    def test_get_player_uid(self):
        """Test retrieving player_uid for a track_id."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        stitcher.add_tracklet(
            track_id=1,
            team='A',
            jersey_number=10,
            appearance_vector=None,
            positions=[(0.0, 0.0, 0.0)],
            frame_range=(0, 10)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        player_uid = stitcher.get_player_uid(1)
        
        self.assertIsNotNone(player_uid, "Should return player_uid for valid track")
        self.assertEqual(player_uid, track_to_player[1])
        
        # Non-existent track
        self.assertIsNone(stitcher.get_player_uid(999), "Should return None for unknown track")


if __name__ == '__main__':
    unittest.main()
