"""Validate CV pipeline against known measured sprint events in real clips.

Measures tracking accuracy by comparing detected sprint speeds/distances against
known ground-truth measurements (e.g., player A sprinted 40m in 5.0s).
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np


class RealClipValidator:
    """Validate CV pipeline output against known real-world measurements."""
    
    def __init__(self, ground_truth_file: Optional[str] = None):
        """Initialize validator.
        
        Args:
            ground_truth_file: JSON file with ground truth measurements
        """
        self.ground_truth = {}
        if ground_truth_file:
            self.load_ground_truth(ground_truth_file)
    
    def load_ground_truth(self, filepath: str):
        """Load ground truth measurements from JSON file.
        
        Expected format:
        {
            "clip_name": {
                "events": [
                    {
                        "type": "sprint",
                        "player_jersey": 10,
                        "start_time_s": 12.5,
                        "end_time_s": 17.5,
                        "distance_m": 40.0,
                        "notes": "Measured from video analysis"
                    }
                ]
            }
        }
        """
        with open(filepath, 'r') as f:
            self.ground_truth = json.load(f)
    
    def validate_sprint(
        self,
        cv_output_path: str,
        clip_name: str,
        player_jersey: int,
        expected_distance_m: float,
        start_time_s: float,
        end_time_s: float,
        tolerance_pct: float = 10.0
    ) -> Dict:
        """Validate a sprint event against CV pipeline output.
        
        Args:
            cv_output_path: Path to CV pipeline output directory
            clip_name: Name of the clip (for reference)
            player_jersey: Jersey number of player
            expected_distance_m: Expected sprint distance (ground truth)
            start_time_s: Sprint start time
            end_time_s: Sprint end time
            tolerance_pct: Acceptable error percentage
        
        Returns:
            Dictionary with validation results
        """
        # Load CV detections
        detections_path = Path(cv_output_path) / "tracking_detections.json"
        if not detections_path.exists():
            return {'error': f'CV output not found: {detections_path}'}
        
        with open(detections_path, 'r') as f:
            detections = json.load(f)
        
        # Filter detections for this player and time window
        player_detections = [
            d for d in detections
            if d.get('jersey_number') == player_jersey
            and start_time_s <= d['timestamp'] <= end_time_s
            and d.get('pitch_x') is not None
            and d.get('pitch_y') is not None
        ]
        
        if not player_detections:
            return {
                'error': 'No detections found for player in time window',
                'player_jersey': player_jersey,
                'time_window': (start_time_s, end_time_s)
            }
        
        # Calculate distance from CV pipeline
        positions = [(d['pitch_x'], d['pitch_y']) for d in player_detections]
        cv_distance_m = self._calculate_distance(positions)
        
        # Compare to ground truth
        error_m = abs(cv_distance_m - expected_distance_m)
        error_pct = (error_m / expected_distance_m) * 100.0
        
        passed = error_pct <= tolerance_pct
        
        result = {
            'clip_name': clip_name,
            'player_jersey': player_jersey,
            'time_window': (start_time_s, end_time_s),
            'expected_distance_m': expected_distance_m,
            'cv_distance_m': round(cv_distance_m, 2),
            'error_m': round(error_m, 2),
            'error_pct': round(error_pct, 2),
            'tolerance_pct': tolerance_pct,
            'passed': passed,
            'frames_analyzed': len(player_detections)
        }
        
        return result
    
    def _calculate_distance(self, positions: List[tuple]) -> float:
        """Calculate total distance traveled from sequence of (x, y) positions.
        
        Args:
            positions: List of (x, y) tuples in meters
        
        Returns:
            Total distance in meters
        """
        if len(positions) < 2:
            return 0.0
        
        total_distance = 0.0
        for i in range(1, len(positions)):
            x1, y1 = positions[i - 1]
            x2, y2 = positions[i]
            segment_distance = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            total_distance += segment_distance
        
        return total_distance
    
    def validate_top_speed(
        self,
        cv_output_path: str,
        player_jersey: int,
        expected_top_speed_kmh: float,
        tolerance_pct: float = 15.0
    ) -> Dict:
        """Validate top speed measurement.
        
        Args:
            cv_output_path: Path to CV pipeline output directory
            player_jersey: Jersey number of player
            expected_top_speed_kmh: Expected top speed in km/h
            tolerance_pct: Acceptable error percentage
        
        Returns:
            Validation results
        """
        # Load player stats
        stats_path = Path(cv_output_path) / "player_match_stats.json"
        if not stats_path.exists():
            return {'error': f'Stats not found: {stats_path}'}
        
        with open(stats_path, 'r') as f:
            stats = json.load(f)
        
        # Find player by jersey number
        player_stat = None
        for stat in stats:
            if stat.get('jersey_number') == player_jersey:
                player_stat = stat
                break
        
        if not player_stat:
            return {
                'error': 'Player not found in stats',
                'player_jersey': player_jersey
            }
        
        cv_top_speed_kmh = player_stat.get('top_speed_kmh')
        if cv_top_speed_kmh is None:
            return {
                'error': 'Top speed not available (no calibration?)',
                'player_jersey': player_jersey
            }
        
        error_kmh = abs(cv_top_speed_kmh - expected_top_speed_kmh)
        error_pct = (error_kmh / expected_top_speed_kmh) * 100.0
        
        passed = error_pct <= tolerance_pct
        
        return {
            'player_jersey': player_jersey,
            'expected_top_speed_kmh': expected_top_speed_kmh,
            'cv_top_speed_kmh': cv_top_speed_kmh,
            'error_kmh': round(error_kmh, 2),
            'error_pct': round(error_pct, 2),
            'tolerance_pct': tolerance_pct,
            'passed': passed
        }
    
    def run_all_validations(self, cv_output_path: str, clip_name: str) -> Dict:
        """Run all validations for a clip against loaded ground truth.
        
        Args:
            cv_output_path: Path to CV pipeline output directory
            clip_name: Name of clip in ground truth data
        
        Returns:
            Dictionary with all validation results
        """
        if clip_name not in self.ground_truth:
            return {'error': f'No ground truth for clip: {clip_name}'}
        
        clip_gt = self.ground_truth[clip_name]
        results = {
            'clip_name': clip_name,
            'validations': [],
            'summary': {}
        }
        
        for event in clip_gt.get('events', []):
            if event['type'] == 'sprint':
                result = self.validate_sprint(
                    cv_output_path=cv_output_path,
                    clip_name=clip_name,
                    player_jersey=event['player_jersey'],
                    expected_distance_m=event['distance_m'],
                    start_time_s=event['start_time_s'],
                    end_time_s=event['end_time_s'],
                    tolerance_pct=event.get('tolerance_pct', 10.0)
                )
                results['validations'].append(result)
        
        # Summary
        passed = sum(1 for r in results['validations'] if r.get('passed', False))
        total = len(results['validations'])
        
        results['summary'] = {
            'total_validations': total,
            'passed': passed,
            'failed': total - passed,
            'pass_rate_pct': round((passed / total * 100.0) if total > 0 else 0.0, 2)
        }
        
        return results


def main():
    """Run real-clip validation."""
    print("=" * 60)
    print("Real-Clip Sprint Validation")
    print("=" * 60)
    
    if len(sys.argv) < 2:
        print("\nUsage: python validate_real_clip.py <cv_output_path> [ground_truth.json]")
        print("\nExample ground_truth.json format:")
        print(json.dumps({
            "match_clip_1": {
                "events": [
                    {
                        "type": "sprint",
                        "player_jersey": 10,
                        "start_time_s": 12.5,
                        "end_time_s": 17.5,
                        "distance_m": 40.0,
                        "notes": "Measured sprint"
                    }
                ]
            }
        }, indent=2))
        return
    
    cv_output_path = sys.argv[1]
    ground_truth_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    validator = RealClipValidator(ground_truth_file)
    
    if not ground_truth_file:
        print("\nNo ground truth file provided. Example validation:")
        print("Validating hypothetical sprint: Player #10, 40m, 12.5s-17.5s")
        
        result = validator.validate_sprint(
            cv_output_path=cv_output_path,
            clip_name="example",
            player_jersey=10,
            expected_distance_m=40.0,
            start_time_s=12.5,
            end_time_s=17.5,
            tolerance_pct=10.0
        )
        
        print("\nValidation Result:")
        print(json.dumps(result, indent=2))
    else:
        print(f"\nRunning validations from: {ground_truth_file}")
        clip_name = Path(cv_output_path).stem
        results = validator.run_all_validations(cv_output_path, clip_name)
        
        print("\nValidation Results:")
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
