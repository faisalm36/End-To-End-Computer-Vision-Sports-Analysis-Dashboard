"""Player performance metrics: speed, distance, injury risk."""

import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from scipy.ndimage import uniform_filter1d


class PerformanceAnalyzer:
    """Calculate player speed, distance, and injury risk metrics."""
    
    def __init__(
        self,
        fps: float = 30.0,
        max_plausible_speed_mph: float = 25.0,
        speed_smoothing_window: int = 5,
        sustained_speed_window_s: float = 1.0,
        high_speed_threshold_mph: float = 12.3,
        sprint_threshold_mph: float = 15.7,
        speed_preset: str = 'gps_standard'
    ):
        """Initialize performance analyzer.
        
        Args:
            fps: Video frames per second
            max_plausible_speed_mph: Filter for extreme outliers (not a cap)
            speed_smoothing_window: Window size for speed smoothing
            sustained_speed_window_s: Window for sustained speed (seconds)
            high_speed_threshold_mph: Threshold for high-speed running
            sprint_threshold_mph: Threshold for sprints
            speed_preset: Sprint/HSR preset ('gps_standard', 'gps_round', 'percent_max')
        """
        self.fps = fps
        self.max_plausible_speed_mph = max_plausible_speed_mph
        self.speed_smoothing_window = speed_smoothing_window
        self.sustained_speed_window_s = sustained_speed_window_s
        self.sustained_speed_window_frames = int(sustained_speed_window_s * fps)
        self.high_speed_threshold_mph = high_speed_threshold_mph
        self.sprint_threshold_mph = sprint_threshold_mph
        self.speed_preset = speed_preset
        
        # Track positions per player
        self.track_positions: Dict[int, List[Tuple[float, float, float]]] = defaultdict(list)
    
    def add_position(self, track_id: int, pitch_x: float, pitch_y: float, timestamp: float):
        """Add position for a player track.
        
        Args:
            track_id: Player track ID
            pitch_x: Pitch x coordinate in meters
            pitch_y: Pitch y coordinate in meters
            timestamp: Timestamp in seconds
        """
        self.track_positions[track_id].append((pitch_x, pitch_y, timestamp))
    
    def calculate_speed(self, positions: List[Tuple[float, float, float]]) -> List[float]:
        """Calculate instantaneous speeds from positions.
        
        Args:
            positions: List of (x, y, t) tuples
        
        Returns:
            List of speeds in mph (uncapped for robust statistics)
        """
        if len(positions) < 2:
            return []
        
        speeds = []
        for i in range(1, len(positions)):
            x1, y1, t1 = positions[i - 1]
            x2, y2, t2 = positions[i]
            
            dt = t2 - t1
            if dt <= 0:
                speeds.append(0.0)
                continue
            
            # Distance in meters
            distance_m = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
            # Speed in m/s
            speed_ms = distance_m / dt
            
            # Convert to mph
            speed_mph = speed_ms * 2.23694
            
            # Don't cap here - let outlier detection handle implausible speeds
            speeds.append(speed_mph)
        
        return speeds
    
    def smooth_speeds(self, speeds: List[float]) -> List[float]:
        """Smooth speeds to reduce jitter.
        
        Args:
            speeds: List of instantaneous speeds
        
        Returns:
            Smoothed speeds
        """
        if len(speeds) < self.speed_smoothing_window:
            return speeds
        
        speeds_array = np.array(speeds)
        smoothed = uniform_filter1d(speeds_array, size=self.speed_smoothing_window, mode='nearest')
        return smoothed.tolist()
    
    def calculate_sustained_speeds(self, speeds: List[float]) -> List[float]:
        """Calculate sustained speeds using rolling window median.
        
        Requires speed to be sustained for ~1 second (rolling window).
        This filters single-frame spikes while keeping real sprints.
        
        Args:
            speeds: List of instantaneous speeds
        
        Returns:
            Sustained speeds (median over window)
        """
        if len(speeds) < self.sustained_speed_window_frames:
            # For very short sequences, use median of all
            return [np.median(speeds)] * len(speeds) if speeds else []
        
        sustained = []
        half_window = self.sustained_speed_window_frames // 2
        
        for i in range(len(speeds)):
            # Get window around current position
            start = max(0, i - half_window)
            end = min(len(speeds), i + half_window + 1)
            window = speeds[start:end]
            
            # Use median for robustness
            sustained.append(np.median(window))
        
        return sustained
    
    def calculate_distance(self, positions: List[Tuple[float, float, float]]) -> float:
        """Calculate total distance covered in kilometers.
        
        Args:
            positions: List of (x, y, t) tuples
        
        Returns:
            Total distance in km
        """
        if len(positions) < 2:
            return 0.0
        
        total_distance_m = 0.0
        for i in range(1, len(positions)):
            x1, y1, _ = positions[i - 1]
            x2, y2, _ = positions[i]
            
            distance_m = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
            # Cap implausible segment (e.g., detection error causing teleport)
            max_segment_m = (self.max_plausible_speed_mph / 2.23694) / self.fps
            distance_m = min(distance_m, max_segment_m * 2)  # Allow some margin
            
            total_distance_m += distance_m
        
        return total_distance_m / 1000.0  # Convert to km
    
    def calculate_workload_metrics(
        self,
        speeds: List[float]
    ) -> Dict[str, float]:
        """Calculate workload metrics for injury risk.
        
        Uses sustained speeds and threshold dwells with hysteresis.
        
        Args:
            speeds: List of speeds in mph
        
        Returns:
            Dict with workload metrics
        """
        if not speeds:
            return {
                'high_speed_distance_km': 0.0,
                'sprint_distance_km': 0.0,
                'sprint_count': 0,
                'max_speed_mph': 0.0
            }
        
        # Filter extreme outliers (only drops clearly implausible speeds)
        valid_speeds = [s for s in speeds if s <= self.max_plausible_speed_mph]
        
        if not valid_speeds:
            # All speeds were outliers
            return {
                'high_speed_distance_km': 0.0,
                'sprint_distance_km': 0.0,
                'sprint_count': 0,
                'max_speed_mph': 0.0
            }
        
        # Calculate sustained speeds (rolling window median ~1s)
        sustained_speeds = self.calculate_sustained_speeds(valid_speeds)
        
        # Top speed: max of sustained speeds (99th percentile for extra robustness)
        if len(sustained_speeds) >= 10:
            sorted_sustained = sorted(sustained_speeds, reverse=True)
            percentile_idx = int(len(sorted_sustained) * 0.01)  # Top 1%
            robust_max_speed = sorted_sustained[percentile_idx]
        else:
            # For short sequences, just use max
            robust_max_speed = max(sustained_speeds)
        
        # Distance calculations with ≥1s dwell (use sustained speeds)
        # HSR: High-Speed Running
        high_speed_frames = sum(1 for s in sustained_speeds if s >= self.high_speed_threshold_mph)
        high_speed_distance_m = high_speed_frames * (self.high_speed_threshold_mph / 2.23694) / self.fps
        
        # Sprint distance
        sprint_frames = sum(1 for s in sustained_speeds if s >= self.sprint_threshold_mph)
        sprint_distance_m = sprint_frames * (self.sprint_threshold_mph / 2.23694) / self.fps
        
        # Count sprint bursts with hysteresis (consecutive frames above threshold)
        # Hysteresis: once in sprint, stay until speed drops below 90% of threshold
        sprint_count = 0
        in_sprint = False
        sprint_exit_threshold = self.sprint_threshold_mph * 0.9
        
        for speed in sustained_speeds:
            if not in_sprint and speed >= self.sprint_threshold_mph:
                sprint_count += 1
                in_sprint = True
            elif in_sprint and speed < sprint_exit_threshold:
                in_sprint = False
        
        return {
            'high_speed_distance_km': high_speed_distance_m / 1000.0,
            'sprint_distance_km': sprint_distance_m / 1000.0,
            'sprint_count': sprint_count,
            'max_speed_mph': robust_max_speed
        }
    
    def calculate_injury_risk(
        self,
        total_distance_km: float,
        workload_metrics: Dict[str, float]
    ) -> str:
        """Calculate injury risk category based on workload.
        
        Args:
            total_distance_km: Total distance covered
            workload_metrics: Dict with sprint_count, etc.
        
        Returns:
            'Low', 'Medium', or 'High'
        """
        risk_score = 0
        
        # Factor 1: Total distance
        if total_distance_km > 10.0:
            risk_score += 2
        elif total_distance_km > 7.0:
            risk_score += 1
        
        # Factor 2: Sprint count
        sprint_count = workload_metrics.get('sprint_count', 0)
        if sprint_count > 50:
            risk_score += 2
        elif sprint_count > 30:
            risk_score += 1
        
        # Factor 3: High-speed distance
        high_speed_km = workload_metrics.get('high_speed_distance_km', 0.0)
        if high_speed_km > 1.5:
            risk_score += 2
        elif high_speed_km > 0.8:
            risk_score += 1
        
        # Classify
        if risk_score >= 4:
            return 'High'
        elif risk_score >= 2:
            return 'Medium'
        else:
            return 'Low'
    
    def analyze_player(self, track_id: int) -> Optional[Dict]:
        """Analyze performance for a single player.
        
        Args:
            track_id: Player track ID
        
        Returns:
            Dict with performance metrics or None
        """
        positions = self.track_positions.get(track_id, [])
        
        if len(positions) < 2:
            return None
        
        # Calculate speeds
        speeds = self.calculate_speed(positions)
        smoothed_speeds = self.smooth_speeds(speeds)
        
        # Calculate distance
        total_distance_km = self.calculate_distance(positions)
        
        # Workload metrics
        workload_metrics = self.calculate_workload_metrics(smoothed_speeds)
        
        # Injury risk
        injury_risk = self.calculate_injury_risk(total_distance_km, workload_metrics)
        
        return {
            'track_id': track_id,
            'top_speed_mph': round(workload_metrics['max_speed_mph'], 2),
            'distance_km': round(total_distance_km, 2),
            'injury_risk': injury_risk,
            'high_speed_distance_km': round(workload_metrics['high_speed_distance_km'], 2),
            'sprint_distance_km': round(workload_metrics['sprint_distance_km'], 2),
            'sprint_count': workload_metrics['sprint_count']
        }
    
    def analyze_all_players(self) -> List[Dict]:
        """Analyze performance for all tracked players.
        
        Returns:
            List of player performance dicts
        """
        results = []
        for track_id in self.track_positions.keys():
            analysis = self.analyze_player(track_id)
            if analysis:
                results.append(analysis)
        
        return results
