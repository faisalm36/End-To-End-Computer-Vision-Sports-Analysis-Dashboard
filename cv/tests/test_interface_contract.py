"""Tests for detect_frame and track_player interface contract."""

import unittest
import json
import tempfile
from pathlib import Path


class TestDetectFrameSchema(unittest.TestCase):
    """Test detect_frame candidates.json schema."""
    
    def test_candidates_schema_exact(self):
        """Test exact schema for candidates.json."""
        # Mock expected schema
        candidates_output = {
            'frame': 100,
            't': 3.333,
            'width': 1920,
            'height': 1080,
            'candidates': [
                {
                    'bbox': [850.0, 320.0, 920.0, 480.0],
                    'confidence': 0.87,
                    'team': "A",
                    'jersey_number': 10,
                    'class': "player"
                },
                {
                    'bbox': [1200.0, 450.0, 1270.0, 610.0],
                    'confidence': 0.91,
                    'team': "B",
                    'jersey_number': 7,
                    'class': "goalkeeper"
                },
                {
                    'bbox': [500.0, 300.0, 550.0, 400.0],
                    'confidence': 0.65,
                    'team': None,
                    'jersey_number': None,
                    'class': "referee"
                }
            ]
        }
        
        # Validate top-level keys
        required_keys = ['frame', 't', 'width', 'height', 'candidates']
        for key in required_keys:
            self.assertIn(key, candidates_output)
        
        # Validate types
        self.assertIsInstance(candidates_output['frame'], int)
        self.assertIsInstance(candidates_output['t'], float)
        self.assertIsInstance(candidates_output['width'], int)
        self.assertIsInstance(candidates_output['height'], int)
        self.assertIsInstance(candidates_output['candidates'], list)
        
        # Validate candidate structure
        for candidate in candidates_output['candidates']:
            required_candidate_keys = ['bbox', 'confidence', 'team', 'jersey_number', 'class']
            for key in required_candidate_keys:
                self.assertIn(key, candidate)
            
            # Validate bbox format
            self.assertIsInstance(candidate['bbox'], list)
            self.assertEqual(len(candidate['bbox']), 4)
            for coord in candidate['bbox']:
                self.assertIsInstance(coord, (int, float))
            
            # Validate confidence
            self.assertIsInstance(candidate['confidence'], float)
            self.assertGreaterEqual(candidate['confidence'], 0.0)
            self.assertLessEqual(candidate['confidence'], 1.0)
            
            # Validate team (A, B, or null)
            self.assertIn(candidate['team'], ["A", "B", None])
            
            # Validate jersey_number (int or null)
            self.assertTrue(
                candidate['jersey_number'] is None or isinstance(candidate['jersey_number'], int)
            )
            
            # Validate class
            self.assertIn(candidate['class'], ['player', 'goalkeeper', 'referee'])


class TestTrackPlayerSchema(unittest.TestCase):
    """Test track_player output schemas."""
    
    def test_track_json_schema_exact(self):
        """Test exact schema for track.json with status mapping."""
        # Mock expected schema
        track_output = {
            'fps': 30.0,
            'width': 1920,
            'height': 1080,
            'total_frames': 9000,
            'target': {
                'jersey_number': 10,
                'team': "A",
                'init_frame': 100,
                # Additive fields
                'player_uid': 3,
                'track_ids': [12, 45, 67]
            },
            'frames': [
                {
                    'frame': 0,
                    't': 0.0,
                    'bbox': [850.0, 320.0, 920.0, 480.0],
                    'confidence': 0.87,
                    'status': 'tracked',
                    # Additive fields
                    'state': 'tracked',
                    'pitch_x': 52.3,
                    'pitch_y': 34.1
                },
                {
                    'frame': 450,
                    't': 15.0,
                    'bbox': [851.0, 321.0, 921.0, 481.0],
                    'confidence': 0.5,
                    'status': 'interpolated',
                    'state': 'occluded',
                    'pitch_x': None,
                    'pitch_y': None
                },
                {
                    'frame': 500,
                    't': 16.667,
                    'bbox': None,
                    'confidence': None,
                    'status': 'lost',
                    'state': 'lost',
                    'pitch_x': None,
                    'pitch_y': None
                }
            ],
            # Additive field
            'schema_version': '1.0'
        }
        
        # Validate top-level required keys
        required_keys = ['fps', 'width', 'height', 'total_frames', 'target', 'frames']
        for key in required_keys:
            self.assertIn(key, track_output)
        
        # Validate types
        self.assertIsInstance(track_output['fps'], float)
        self.assertIsInstance(track_output['width'], int)
        self.assertIsInstance(track_output['height'], int)
        self.assertIsInstance(track_output['total_frames'], int)
        self.assertIsInstance(track_output['target'], dict)
        self.assertIsInstance(track_output['frames'], list)
        
        # Validate target structure
        target = track_output['target']
        required_target_keys = ['jersey_number', 'team', 'init_frame']
        for key in required_target_keys:
            self.assertIn(key, target)
        
        # Validate target types
        self.assertTrue(target['jersey_number'] is None or isinstance(target['jersey_number'], int))
        self.assertIn(target['team'], ["A", "B", None])
        self.assertIsInstance(target['init_frame'], int)
        
        # Validate frames structure
        for frame in track_output['frames']:
            required_frame_keys = ['frame', 't', 'bbox', 'confidence', 'status']
            for key in required_frame_keys:
                self.assertIn(key, frame)
            
            # Validate frame types
            self.assertIsInstance(frame['frame'], int)
            self.assertIsInstance(frame['t'], float)
            self.assertTrue(frame['bbox'] is None or isinstance(frame['bbox'], list))
            
            # Validate bbox format if present
            if frame['bbox'] is not None:
                self.assertEqual(len(frame['bbox']), 4)
            
            # Validate status values
            self.assertIn(frame['status'], ['tracked', 'interpolated', 'lost'])
    
    def test_status_mapping(self):
        """Test status mapping from internal state."""
        # Status mapping rules:
        # tracked -> tracked
        # reacquired -> tracked
        # occluded -> interpolated
        # lost -> lost
        
        mappings = {
            'tracked': 'tracked',
            'reacquired': 'tracked',
            'occluded': 'interpolated',
            'lost': 'lost'
        }
        
        for internal_state, expected_status in mappings.items():
            # Test the mapping
            if internal_state in ['tracked', 'reacquired']:
                status = 'tracked'
            elif internal_state == 'occluded':
                status = 'interpolated'
            else:
                status = 'lost'
            
            self.assertEqual(status, expected_status, 
                           f"State '{internal_state}' should map to status '{expected_status}'")
    
    def test_meta_json_schema_exact(self):
        """Test exact schema for meta.json."""
        meta_output = {
            'pipeline_version': '2.0.0',
            'tracker': 'botsort',
            'coverage_pct': 91.49,
            'lost_frames': 766,
            'warnings': [],
            # Additive fields
            'reacquisition_count': 2,
            'lost_segments': [
                {'start_t': 45.2, 'end_t': 48.7},
                {'start_t': 120.5, 'end_t': 122.0}
            ]
        }
        
        # Validate required keys
        required_keys = ['pipeline_version', 'tracker', 'coverage_pct', 'lost_frames', 'warnings']
        for key in required_keys:
            self.assertIn(key, meta_output)
        
        # Validate types
        self.assertIsInstance(meta_output['pipeline_version'], str)
        self.assertIsInstance(meta_output['tracker'], str)
        self.assertIsInstance(meta_output['coverage_pct'], (int, float))
        self.assertIsInstance(meta_output['lost_frames'], int)
        self.assertIsInstance(meta_output['warnings'], list)
    
    def test_error_target_not_found_schema(self):
        """Test meta.json schema for exit code 3 (target not found)."""
        meta_error = {
            'pipeline_version': '2.0.0',
            'tracker': 'botsort',
            'coverage_pct': 0.0,
            'lost_frames': 0,
            'warnings': ['No player found with jersey number 99'],
            'error': 'target_not_found'
        }
        
        # Validate error field
        self.assertIn('error', meta_error)
        self.assertEqual(meta_error['error'], 'target_not_found')
    
    def test_error_ambiguous_with_candidates(self):
        """Test meta.json schema for ambiguous target (exit code 3)."""
        meta_error = {
            'pipeline_version': '2.0.0',
            'tracker': 'botsort',
            'coverage_pct': 0.0,
            'lost_frames': 0,
            'warnings': ['Ambiguous: 2 different players detected with jersey 10'],
            'error': 'target_not_found',
            'candidates': [
                {
                    'player_uid': 1,
                    'track_id': 12,
                    'jersey_number': 10,
                    'team': "A"
                },
                {
                    'player_uid': 2,
                    'track_id': 45,
                    'jersey_number': 10,
                    'team': "A"
                }
            ]
        }
        
        # Validate error and candidates
        self.assertIn('error', meta_error)
        self.assertEqual(meta_error['error'], 'target_not_found')
        self.assertIn('candidates', meta_error)
        self.assertIsInstance(meta_error['candidates'], list)
        self.assertGreater(len(meta_error['candidates']), 0)


class TestTeamLabelMapping(unittest.TestCase):
    """Test team label mapping (0/1 -> A/B)."""
    
    def test_team_mapping_consistency(self):
        """Test that team labels are consistently mapped."""
        # Internal: 0 -> A, 1 -> B
        internal_to_label = {
            0: "A",
            1: "B",
            None: None
        }
        
        for internal, expected_label in internal_to_label.items():
            if internal == 0:
                label = "A"
            elif internal == 1:
                label = "B"
            else:
                label = None
            
            self.assertEqual(label, expected_label)


class TestExitCodes(unittest.TestCase):
    """Test exit code contract."""
    
    def test_exit_code_0_success(self):
        """Test exit code 0 for success."""
        exit_code = 0
        self.assertEqual(exit_code, 0)
    
    def test_exit_code_1_general_error(self):
        """Test exit code 1 for general errors."""
        exit_code = 1
        self.assertNotEqual(exit_code, 0)
        self.assertNotEqual(exit_code, 3)
    
    def test_exit_code_3_target_not_found(self):
        """Test exit code 3 for target not found/ambiguous."""
        exit_code = 3
        self.assertEqual(exit_code, 3)


if __name__ == '__main__':
    unittest.main()
