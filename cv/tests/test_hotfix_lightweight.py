"""Lightweight unit tests for hotfix bugs (no pipeline dependencies)."""

import unittest
from cv.tracklet_stitching import TrackletStitcher


class TestHotfixTrackletBugs(unittest.TestCase):
    """Unit tests for tracklet stitching bugs fixed in hotfix."""
    
    def test_singleton_tracklets_get_uid(self):
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
    
    def test_correct_timestamps_enable_stitching(self):
        """Bug 2a: Tracklets with correct timestamps should stitch when feasible."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        # Tracklet 1: appears in frames 0-30 (0-1 second)
        positions_track1 = [(float(i * 0.1), 0.0, float(i) / 30.0) for i in range(31)]
        stitcher.add_tracklet(
            track_id=1,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=positions_track1,
            frame_range=(0, 30)
        )
        
        # Tracklet 2: appears in frames 60-90 (2-3 seconds, 1 second gap)
        # Position moves ~1m in 1 second gap (feasible at 12 m/s max)
        positions_track2 = [(3.0 + float(i * 0.1), 0.0, 2.0 + float(i) / 30.0) for i in range(31)]
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
    
    def test_overlapping_tracklets_forbidden(self):
        """Bug 2c: Overlapping tracklets must not be stitched."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        # Tracklet 1: frames 0-50 (0-1.67 seconds)
        stitcher.add_tracklet(
            track_id=1,
            team=0,
            jersey_number=10,
            appearance_vector=None,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 1.67)],
            frame_range=(0, 50)
        )
        
        # Tracklet 2: frames 30-80 (1.0-2.67 seconds, overlaps with track 1)
        stitcher.add_tracklet(
            track_id=2,
            team=0,
            jersey_number=10,  # Same jersey
            appearance_vector=None,
            positions=[(1.5, 0.0, 1.0), (2.5, 0.0, 2.67)],
            frame_range=(30, 80)
        )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # Must NOT stitch (they overlap in time)
        self.assertNotEqual(track_to_player[1], track_to_player[2],
                           "Overlapping tracklets must not stitch")
    
    def test_many_non_overlapping_tracklets(self):
        """Regression: N non-overlapping tracklets should give N player_uids."""
        stitcher = TrackletStitcher(max_speed_ms=12.0, fps=30.0)
        
        # Add 10 non-overlapping tracklets (different teams, separated in time)
        for tid in range(1, 11):
            stitcher.add_tracklet(
                track_id=tid,
                team=tid % 2,  # Alternate teams
                jersey_number=tid,
                appearance_vector=None,
                positions=[(float(tid), 0.0, float(tid) * 2.0)],
                frame_range=(tid * 100, tid * 100 + 20)
            )
        
        track_to_player = stitcher.stitch_tracklets()
        
        # All 10 tracks should have uids
        self.assertEqual(len(track_to_player), 10)
        
        # All should be different (can't stitch across teams)
        uids = set(track_to_player.values())
        self.assertEqual(len(uids), 10)


if __name__ == '__main__':
    unittest.main()
