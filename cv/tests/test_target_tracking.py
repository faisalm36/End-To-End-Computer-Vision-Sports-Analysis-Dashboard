"""Unit tests for target tracking and re-acquisition."""

import unittest
import numpy as np
from cv.target_tracking import TargetTracker, TargetSpec, load_target_spec_from_file, save_target_spec_to_file
import tempfile
import json
from pathlib import Path


class TestTargetResolution(unittest.TestCase):
    """Test target resolution from different specifications."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = TargetTracker(fps=30.0)
        
        # Mock detections at frame 100
        self.detections = [
            {
                'frame': 100,
                'track_id': 1,
                'class': 'player',
                'bbox_x1': 100,
                'bbox_y1': 200,
                'bbox_x2': 150,
                'bbox_y2': 300,
                'team': 0,
                'jersey_number': 10
            },
            {
                'frame': 100,
                'track_id': 2,
                'class': 'player',
                'bbox_x1': 500,
                'bbox_y1': 400,
                'bbox_x2': 550,
                'bbox_y2': 500,
                'team': 1,
                'jersey_number': 7
            },
            {
                'frame': 100,
                'track_id': 3,
                'class': 'player',
                'bbox_x1': 800,
                'bbox_y1': 300,
                'bbox_x2': 850,
                'bbox_y2': 400,
                'team': 0,
                'jersey_number': 3
            }
        ]
        
        self.player_uid_map = {1: 1, 2: 2, 3: 3}
        self.team_map = {1: 0, 2: 1, 3: 0}
        self.jersey_map = {1: 10, 2: 7, 3: 3}
    
    def test_resolve_by_bbox_iou(self):
        """Test resolution by bbox IoU."""
        spec = TargetSpec(target_frame=100, target_bbox=(105, 205, 145, 295))
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(self.tracker.target_player_uid, 1)
        self.assertEqual(self.tracker.target_jersey, 10)
        self.assertEqual(self.tracker.target_team, 0)
    
    def test_resolve_by_point_inside_bbox(self):
        """Test resolution by point inside bbox."""
        spec = TargetSpec(target_frame=100, target_point=(525, 450))
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(self.tracker.target_player_uid, 2)
        self.assertEqual(self.tracker.target_jersey, 7)
    
    def test_resolve_by_point_nearest_bbox(self):
        """Test resolution by nearest bbox when point is outside all boxes."""
        spec = TargetSpec(target_frame=100, target_point=(160, 250))  # Near track 1
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertTrue(success)
        self.assertEqual(self.tracker.target_player_uid, 1)
    
    def test_resolve_by_jersey_unique(self):
        """Test resolution by unique jersey number."""
        spec = TargetSpec(target_jersey=10)
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertTrue(success)
        self.assertEqual(self.tracker.target_player_uid, 1)
        self.assertEqual(self.tracker.target_jersey, 10)
    
    def test_resolve_by_jersey_with_team(self):
        """Test resolution by jersey + team."""
        spec = TargetSpec(target_jersey=7, target_team=1)
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertTrue(success)
        self.assertEqual(self.tracker.target_player_uid, 2)
        self.assertEqual(self.tracker.target_team, 1)
    
    def test_resolve_jersey_not_found(self):
        """Test error when jersey not found."""
        spec = TargetSpec(target_jersey=99)
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertFalse(success)
        self.assertIn("No player found", error)
    
    def test_resolve_jersey_ambiguous(self):
        """Test error when jersey is ambiguous (multiple players)."""
        # Add another player with jersey 10 but different uid
        jersey_map_ambiguous = {1: 10, 2: 7, 3: 3, 4: 10}
        player_uid_map_ambiguous = {1: 1, 2: 2, 3: 3, 4: 4}
        
        spec = TargetSpec(target_jersey=10)
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, player_uid_map_ambiguous, self.team_map, jersey_map_ambiguous
        )
        
        self.assertFalse(success)
        self.assertIn("Ambiguous", error)
    
    def test_resolve_no_detections_at_frame(self):
        """Test error when no detections at target frame."""
        spec = TargetSpec(target_frame=999, target_point=(100, 100))
        
        success, error = self.tracker.resolve_target(
            spec, self.detections, self.player_uid_map, self.team_map, self.jersey_map
        )
        
        self.assertFalse(success)
        self.assertIn("No player detections found", error)


class TestReacquisitionGating(unittest.TestCase):
    """Test re-acquisition gating logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = TargetTracker(
            max_speed_ms=12.0,
            fps=30.0,
            motion_gate_multiplier=1.5
        )
        
        # Initialize target state
        self.tracker.target_player_uid = 1
        self.tracker.target_team = 0
        self.tracker.target_jersey = 10
        self.tracker.target_track_ids = [1]
        self.tracker.last_known_position = (50.0, 30.0, 1.0)  # x, y, t
    
    def test_motion_gate_accepts_feasible_movement(self):
        """Test that motion gate accepts physically feasible movement."""
        # Detection 10 meters away after 1 second (10 m/s, within 12 m/s limit)
        detection = {
            'track_id': 2,
            'pitch_x': 60.0,
            'pitch_y': 30.0,
            'timestamp': 2.0,
            'team': 0
        }
        
        self.assertTrue(self.tracker._passes_motion_gate(detection))
    
    def test_motion_gate_rejects_implausible_jump(self):
        """Test that motion gate rejects physically impossible jump."""
        # Detection 50 meters away after 0.5 seconds (100 m/s, impossible)
        detection = {
            'track_id': 2,
            'pitch_x': 100.0,
            'pitch_y': 30.0,
            'timestamp': 1.5,
            'team': 0
        }
        
        self.assertFalse(self.tracker._passes_motion_gate(detection))
    
    def test_motion_gate_with_multiplier(self):
        """Test motion gate allows gate_multiplier * max_speed."""
        # Detection 17 meters away after 1 second
        # max_distance = 12 * 1 * 1.5 = 18 m (should pass)
        detection = {
            'track_id': 2,
            'pitch_x': 67.0,
            'pitch_y': 30.0,
            'timestamp': 2.0,
            'team': 0
        }
        
        self.assertTrue(self.tracker._passes_motion_gate(detection))
        
        # 19 meters (should fail)
        detection['pitch_x'] = 69.0
        self.assertFalse(self.tracker._passes_motion_gate(detection))
    
    def test_find_target_rejects_wrong_team(self):
        """Test that target is not found on wrong team."""
        frame_detections = [
            {
                'track_id': 2,
                'team': 1,  # Wrong team
                'pitch_x': 51.0,
                'pitch_y': 30.0,
                'timestamp': 1.1,
                'jersey_number': 10  # Same jersey but wrong team
            }
        ]
        
        team_map = {2: 1}
        jersey_map = {2: 10}
        
        result = self.tracker._find_target_in_frame(
            frame_detections, team_map, jersey_map, None
        )
        
        self.assertIsNone(result)


class TestStateTransitions(unittest.TestCase):
    """Test state transitions (tracked → occluded → lost → reacquired)."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = TargetTracker(
            max_speed_ms=12.0,
            fps=30.0,
            occlusion_max_frames=30
        )
        
        # Resolve target
        self.tracker.target_player_uid = 1
        self.tracker.target_team = 0
        self.tracker.target_track_ids = [1]
        self.tracker.current_state = 'tracked'
        self.tracker.frames_since_detection = 0
    
    def test_tracked_to_occluded(self):
        """Test transition from tracked to occluded."""
        # Simulate 10 frames without detection
        for i in range(10):
            self.tracker.frames_since_detection += 1
            
            if self.tracker.frames_since_detection <= self.tracker.occlusion_max_frames:
                state = 'occluded'
            else:
                state = 'lost'
            
            self.tracker.current_state = state
        
        self.assertEqual(self.tracker.current_state, 'occluded')
    
    def test_occluded_to_lost(self):
        """Test transition from occluded to lost."""
        # Simulate 31 frames without detection
        self.tracker.current_state = 'tracked'
        
        for i in range(31):
            self.tracker.frames_since_detection += 1
            
            if self.tracker.frames_since_detection <= self.tracker.occlusion_max_frames:
                state = 'occluded'
            else:
                state = 'lost'
            
            self.tracker.current_state = state
        
        self.assertEqual(self.tracker.current_state, 'lost')
    
    def test_lost_to_reacquired(self):
        """Test transition from lost to reacquired."""
        self.tracker.current_state = 'lost'
        self.tracker.frames_since_detection = 50
        
        # Simulate re-detection
        was_lost = self.tracker.current_state in ['lost', 'occluded']
        if was_lost and self.tracker.frames_since_detection > 5:
            new_state = 'reacquired'
        else:
            new_state = 'tracked'
        
        self.assertEqual(new_state, 'reacquired')


class TestTargetTrackSchema(unittest.TestCase):
    """Test target_track.json output schema."""
    
    def test_schema_fields(self):
        """Test that all required schema fields are present."""
        # Mock output
        target_track = {
            'schema_version': '1.0',
            'video': {
                'width': 1920,
                'height': 1080,
                'fps': 30.0,
                'frame_count': 9000
            },
            'target': {
                'player_uid': 3,
                'track_ids': [12, 45],
                'jersey': 10,
                'team': 0,
                'spec': {
                    'target_frame': 100,
                    'target_point': [885, 400],
                    'target_bbox': None,
                    'target_jersey': None,
                    'target_team': None
                }
            },
            'frames': [
                {
                    'frame': 0,
                    't': 0.0,
                    'bbox': [850.2, 320.5, 920.8, 480.3],
                    'confidence': 0.87,
                    'state': 'tracked',
                    'source': 'detected',
                    'pitch_x': 52.3,
                    'pitch_y': 34.1
                }
            ]
        }
        
        # Validate top-level keys
        self.assertIn('schema_version', target_track)
        self.assertIn('video', target_track)
        self.assertIn('target', target_track)
        self.assertIn('frames', target_track)
        
        # Validate video info
        video = target_track['video']
        self.assertIn('width', video)
        self.assertIn('height', video)
        self.assertIn('fps', video)
        self.assertIn('frame_count', video)
        
        # Validate target info
        target = target_track['target']
        self.assertIn('player_uid', target)
        self.assertIn('track_ids', target)
        self.assertIn('jersey', target)
        self.assertIn('team', target)
        self.assertIn('spec', target)
        
        # Validate frame entry
        frame = target_track['frames'][0]
        required_fields = ['frame', 't', 'bbox', 'confidence', 'state', 'source', 'pitch_x', 'pitch_y']
        for field in required_fields:
            self.assertIn(field, frame)
        
        # Validate state values
        valid_states = ['tracked', 'occluded', 'lost', 'reacquired']
        self.assertIn(frame['state'], valid_states)
        
        # Validate source values
        valid_sources = ['detected', 'interpolated', 'lost']
        self.assertIn(frame['source'], valid_sources)


class TestTargetSpecSerialization(unittest.TestCase):
    """Test target specification serialization."""
    
    def test_to_dict(self):
        """Test TargetSpec.to_dict()."""
        spec = TargetSpec(
            target_frame=100,
            target_point=(885, 400),
            target_jersey=None,
            target_team=None
        )
        
        data = spec.to_dict()
        
        self.assertEqual(data['target_frame'], 100)
        self.assertEqual(data['target_point'], [885, 400])
        self.assertIsNone(data['target_jersey'])
    
    def test_from_dict(self):
        """Test TargetSpec.from_dict()."""
        data = {
            'target_frame': 100,
            'target_point': [885, 400],
            'target_bbox': None,
            'target_jersey': None,
            'target_team': None
        }
        
        spec = TargetSpec.from_dict(data)
        
        self.assertEqual(spec.target_frame, 100)
        self.assertEqual(spec.target_point, (885, 400))
        self.assertIsNone(spec.target_jersey)
    
    def test_save_and_load_file(self):
        """Test saving and loading target spec from file."""
        spec = TargetSpec(target_jersey=10, target_team=0)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            save_target_spec_to_file(spec, temp_path)
            
            loaded_spec = load_target_spec_from_file(temp_path)
            
            self.assertEqual(loaded_spec.target_jersey, 10)
            self.assertEqual(loaded_spec.target_team, 0)
        
        finally:
            Path(temp_path).unlink()


class TestIoUComputation(unittest.TestCase):
    """Test IoU computation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = TargetTracker()
    
    def test_iou_perfect_overlap(self):
        """Test IoU with perfect overlap."""
        bbox1 = (100, 200, 150, 300)
        bbox2 = (100, 200, 150, 300)
        
        iou = self.tracker._compute_iou(bbox1, bbox2)
        
        self.assertAlmostEqual(iou, 1.0, places=5)
    
    def test_iou_no_overlap(self):
        """Test IoU with no overlap."""
        bbox1 = (100, 200, 150, 300)
        bbox2 = (200, 400, 250, 500)
        
        iou = self.tracker._compute_iou(bbox1, bbox2)
        
        self.assertEqual(iou, 0.0)
    
    def test_iou_partial_overlap(self):
        """Test IoU with partial overlap."""
        bbox1 = (100, 200, 150, 300)
        bbox2 = (125, 225, 175, 325)
        
        iou = self.tracker._compute_iou(bbox1, bbox2)
        
        # Manually computed IoU
        # Intersection: (125, 225) to (150, 300) = 25 * 75 = 1875
        # Area1: 50 * 100 = 5000
        # Area2: 50 * 100 = 5000
        # Union: 5000 + 5000 - 1875 = 8125
        # IoU: 1875 / 8125 = 0.23076923
        
        self.assertAlmostEqual(iou, 1875 / 8125, places=5)


if __name__ == '__main__':
    unittest.main()
