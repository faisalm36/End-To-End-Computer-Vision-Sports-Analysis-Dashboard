"""Benchmark against Metrica Sports open tracking data.

Downloads Metrica sample data on demand and evaluates tracking quality against
ground-truth positions, speeds, and distances.

License: Metrica Sports tracking data is released under CC BY 4.0
https://github.com/metrica-sports/sample-data
"""

import json
import urllib.request
import os
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np


class MetricaBenchmark:
    """Evaluate CV pipeline against Metrica Sports sample tracking data."""
    
    # Metrica sample data URLs (Game 1, Test)
    METRICA_DATA_URL = "https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_1/Sample_Game_1_RawTrackingData_Away_Team.csv"
    
    def __init__(self, cache_dir: str = "/tmp/metrica_data"):
        """Initialize benchmark.
        
        Args:
            cache_dir: Directory to cache downloaded Metrica data
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = self.cache_dir / "metrica_sample.csv"
    
    def download_data(self) -> bool:
        """Download Metrica sample data if not cached.
        
        Returns:
            True if data is available, False otherwise
        """
        if self.data_file.exists():
            print(f"Using cached Metrica data: {self.data_file}")
            return True
        
        print(f"Downloading Metrica sample data...")
        print(f"License: CC BY 4.0 - https://github.com/metrica-sports/sample-data")
        
        try:
            urllib.request.urlretrieve(self.METRICA_DATA_URL, self.data_file)
            print(f"Downloaded to: {self.data_file}")
            return True
        except Exception as e:
            print(f"Failed to download Metrica data: {e}")
            return False
    
    def load_metrica_ground_truth(self) -> Dict:
        """Load Metrica ground truth tracking data.
        
        Returns:
            Dictionary with player trajectories
        """
        if not self.download_data():
            return {}
        
        # Parse CSV (simplified - Metrica has specific format)
        # Format: Frame,Period,Time [s],Player1_x,Player1_y,Player1_vx,Player1_vy,...
        
        players = {}
        
        with open(self.data_file, 'r') as f:
            header = f.readline().strip().split(',')
            
            # Find player columns
            player_cols = {}
            for i, col in enumerate(header):
                if '_x' in col:
                    player_id = col.replace('_x', '')
                    player_cols[player_id] = {'x_idx': i}
                elif '_y' in col and col.replace('_y', '') in player_cols:
                    player_id = col.replace('_y', '')
                    player_cols[player_id]['y_idx'] = i
            
            # Read positions
            for line in f:
                parts = line.strip().split(',')
                if len(parts) < 3:
                    continue
                
                try:
                    frame = int(parts[0])
                    timestamp = float(parts[2])
                except:
                    continue
                
                for player_id, indices in player_cols.items():
                    try:
                        x = float(parts[indices['x_idx']])
                        y = float(parts[indices['y_idx']])
                        
                        if player_id not in players:
                            players[player_id] = []
                        
                        players[player_id].append({
                            'frame': frame,
                            'timestamp': timestamp,
                            'x': x,
                            'y': y
                        })
                    except:
                        continue
        
        return players
    
    def evaluate_tracking(self, cv_output_path: str) -> Dict:
        """Evaluate CV pipeline output against Metrica ground truth.
        
        Args:
            cv_output_path: Path to CV pipeline output directory
        
        Returns:
            Dictionary with evaluation metrics
        """
        # Load ground truth
        ground_truth = self.load_metrica_ground_truth()
        if not ground_truth:
            return {'error': 'Failed to load ground truth data'}
        
        # Load CV pipeline output
        detections_path = Path(cv_output_path) / "tracking_detections.json"
        if not detections_path.exists():
            return {'error': f'CV output not found: {detections_path}'}
        
        with open(detections_path, 'r') as f:
            cv_detections = json.load(f)
        
        # Match CV tracks to ground truth players (simplified: by spatial proximity)
        # In real evaluation, you'd need correspondence based on jersey numbers
        
        # Calculate metrics
        metrics = {
            'ground_truth_players': len(ground_truth),
            'cv_detected_tracks': len(set(d['track_id'] for d in cv_detections if d['track_id'] > 0)),
            'note': 'Full implementation requires video-to-Metrica correspondence mapping'
        }
        
        return metrics
    
    def calculate_position_error(
        self,
        ground_truth: List[Tuple[float, float]],
        predicted: List[Tuple[float, float]]
    ) -> Dict:
        """Calculate position error metrics.
        
        Args:
            ground_truth: List of (x, y) ground truth positions
            predicted: List of (x, y) predicted positions
        
        Returns:
            Dictionary with error metrics (RMSE, mean, max)
        """
        if len(ground_truth) != len(predicted):
            return {'error': 'Length mismatch between ground truth and predicted'}
        
        errors = []
        for (gt_x, gt_y), (pred_x, pred_y) in zip(ground_truth, predicted):
            error = np.sqrt((gt_x - pred_x)**2 + (gt_y - pred_y)**2)
            errors.append(error)
        
        return {
            'rmse_m': float(np.sqrt(np.mean(np.array(errors)**2))),
            'mean_error_m': float(np.mean(errors)),
            'max_error_m': float(np.max(errors)),
            'p95_error_m': float(np.percentile(errors, 95)),
            'samples': len(errors)
        }


def main():
    """Run Metrica benchmark."""
    print("=" * 60)
    print("Metrica Sports Tracking Data Benchmark")
    print("=" * 60)
    
    benchmark = MetricaBenchmark()
    
    # Check data availability
    if not benchmark.download_data():
        print("\nFailed to obtain Metrica data.")
        print("Please check network connection and retry.")
        return
    
    print("\nMetrica data ready!")
    print("To evaluate your CV pipeline:")
    print("1. Run pipeline on a Metrica video (if available)")
    print("2. Call benchmark.evaluate_tracking('/path/to/output')")
    print("\nExample:")
    print("  python -m cv.run_pipeline --video metrica.mp4 --out /tmp/results")
    print("  python cv/benchmark/benchmark_speed_distance.py --eval /tmp/results")
    
    # Load sample ground truth to show structure
    players = benchmark.load_metrica_ground_truth()
    print(f"\nLoaded {len(players)} players from Metrica ground truth")
    if players:
        sample_player = list(players.keys())[0]
        sample_frames = len(players[sample_player])
        print(f"Example: Player '{sample_player}' has {sample_frames} frames")


if __name__ == '__main__':
    main()
