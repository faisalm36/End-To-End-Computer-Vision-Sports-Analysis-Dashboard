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
        speed_preset: str = 'gps_standard',
        zone_walk_kmh: float = 7.0,
        zone_jog_kmh: float = 15.0,
        zone_run_kmh: float = 20.0,
        zone_hsr_kmh: float = 25.0,
        accel_high_ms2: float = 3.0,
        accel_dwell_s: float = 0.7,
        heatmap_grid: Tuple[int, int] = (21, 14),
        pitch_length_m: float = 105.0,
        pitch_width_m: float = 68.0,
        total_video_frames: int = 0
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
            zone_walk_kmh: Walk zone max speed (km/h)
            zone_jog_kmh: Jog zone max speed (km/h)
            zone_run_kmh: Run zone max speed (km/h)
            zone_hsr_kmh: High-speed running zone max speed (km/h)
            accel_high_ms2: High acceleration/deceleration threshold (m/s^2)
            accel_dwell_s: Minimum dwell time for accel/decel events (s)
            heatmap_grid: Grid dimensions (nx, ny) for heatmap
            pitch_length_m: Pitch length in meters
            pitch_width_m: Pitch width in meters
            total_video_frames: Total video frames for coverage calculation
        """
        self.fps = fps
        self.max_plausible_speed_mph = max_plausible_speed_mph
        self.speed_smoothing_window = speed_smoothing_window
        self.sustained_speed_window_s = sustained_speed_window_s
        self.sustained_speed_window_frames = int(sustained_speed_window_s * fps)
        self.high_speed_threshold_mph = high_speed_threshold_mph
        self.sprint_threshold_mph = sprint_threshold_mph
        self.speed_preset = speed_preset
        
        # Speed zones (km/h)
        self.zone_walk_kmh = zone_walk_kmh
        self.zone_jog_kmh = zone_jog_kmh
        self.zone_run_kmh = zone_run_kmh
        self.zone_hsr_kmh = zone_hsr_kmh
        
        # Acceleration thresholds
        self.accel_high_ms2 = accel_high_ms2
        self.accel_dwell_s = accel_dwell_s
        self.accel_dwell_frames = int(accel_dwell_s * fps)
        
        # Heatmap configuration
        self.heatmap_grid = heatmap_grid
        self.pitch_length_m = pitch_length_m
        self.pitch_width_m = pitch_width_m
        
        # Total video frames for coverage
        self.total_video_frames = total_video_frames
        
        # Track positions per player
        self.track_positions: Dict[int, List[Tuple[float, float, float]]] = defaultdict(list)
    
    def add_position(
        self,
        track_id: int,
        pitch_x: float,
        pitch_y: float,
        timestamp: float,
        is_detected: bool = True
    ):
        """Add position for a player track.
        
        Args:
            track_id: Player track ID
            pitch_x: Pitch x coordinate in meters
            pitch_y: Pitch y coordinate in meters
            timestamp: Timestamp in seconds
            is_detected: Whether this is a detected (True) or interpolated (False) position
        """
        self.track_positions[track_id].append((pitch_x, pitch_y, timestamp, is_detected))
    
    def calculate_speed(
        self,
        positions: List[Tuple[float, float, float, bool]]
    ) -> Tuple[List[float], List[bool]]:
        """Calculate instantaneous speeds from positions.
        
        Args:
            positions: List of (x, y, t, is_detected) tuples
        
        Returns:
            (speeds in mph, is_detected flags)
        """
        if len(positions) < 2:
            return [], []
        
        speeds = []
        detected_flags = []
        
        for i in range(1, len(positions)):
            x1, y1, t1, det1 = positions[i - 1]
            x2, y2, t2, det2 = positions[i]
            
            dt = t2 - t1
            if dt <= 0:
                speeds.append(0.0)
                detected_flags.append(det1 and det2)
                continue
            
            # Distance in meters
            distance_m = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
            # Speed in m/s
            speed_ms = distance_m / dt
            
            # Convert to mph
            speed_mph = speed_ms * 2.23694
            
            speeds.append(speed_mph)
            # Speed is "detected" only if both positions are detected
            detected_flags.append(det1 and det2)
        
        return speeds, detected_flags
    
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
    
    def calculate_distance(
        self,
        positions: List[Tuple[float, float, float, bool]]
    ) -> float:
        """Calculate total distance covered in kilometers.
        
        Args:
            positions: List of (x, y, t, is_detected) tuples
        
        Returns:
            Total distance in km
        """
        if len(positions) < 2:
            return 0.0
        
        total_distance_m = 0.0
        for i in range(1, len(positions)):
            x1, y1, _, _ = positions[i - 1]
            x2, y2, _, _ = positions[i]
            
            distance_m = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
            # Cap implausible segment (e.g., detection error causing teleport)
            max_segment_m = (self.max_plausible_speed_mph / 2.23694) / self.fps
            distance_m = min(distance_m, max_segment_m * 2)  # Allow some margin
            
            total_distance_m += distance_m
        
        return total_distance_m / 1000.0  # Convert to km
    
    def calculate_speed_zones(self, speeds_mph: List[float]) -> Dict[str, float]:
        """Calculate distance covered in each speed zone.
        
        Args:
            speeds_mph: List of speeds in mph
        
        Returns:
            Dict with zone distances in km
        """
        if not speeds_mph:
            return {
                'zone_walk_km': 0.0,
                'zone_jog_km': 0.0,
                'zone_run_km': 0.0,
                'zone_hsr_km': 0.0,
                'zone_sprint_km': 0.0
            }
        
        # Convert speeds to km/h
        speeds_kmh = [s * 1.60934 for s in speeds_mph]
        
        # Count frames in each zone
        walk_frames = sum(1 for s in speeds_kmh if s < self.zone_walk_kmh)
        jog_frames = sum(1 for s in speeds_kmh if self.zone_walk_kmh <= s < self.zone_jog_kmh)
        run_frames = sum(1 for s in speeds_kmh if self.zone_jog_kmh <= s < self.zone_run_kmh)
        hsr_frames = sum(1 for s in speeds_kmh if self.zone_run_kmh <= s < self.zone_hsr_kmh)
        sprint_frames = sum(1 for s in speeds_kmh if s >= self.zone_hsr_kmh)
        
        # Estimate distance: average speed in zone * time
        dt = 1.0 / self.fps
        
        def zone_distance_km(frame_count: int, min_kmh: float, max_kmh: float) -> float:
            if frame_count == 0:
                return 0.0
            # Use midpoint of zone as average speed
            avg_speed_kmh = (min_kmh + max_kmh) / 2.0
            avg_speed_ms = avg_speed_kmh / 3.6
            distance_m = avg_speed_ms * dt * frame_count
            return distance_m / 1000.0
        
        return {
            'zone_walk_km': zone_distance_km(walk_frames, 0.0, self.zone_walk_kmh),
            'zone_jog_km': zone_distance_km(jog_frames, self.zone_walk_kmh, self.zone_jog_kmh),
            'zone_run_km': zone_distance_km(run_frames, self.zone_jog_kmh, self.zone_run_kmh),
            'zone_hsr_km': zone_distance_km(hsr_frames, self.zone_run_kmh, self.zone_hsr_kmh),
            'zone_sprint_km': zone_distance_km(sprint_frames, self.zone_hsr_kmh, self.zone_hsr_kmh + 10.0)
        }
    
    def calculate_accelerations(
        self,
        positions: List[Tuple[float, float, float, bool]],
        max_accel_ms2: float = 6.0
    ) -> Tuple[int, int]:
        """Calculate high acceleration and deceleration event counts.
        
        Uses smoothed velocity and requires sustained acceleration >= threshold
        for >= dwell time. Caps acceleration at max_accel_ms2 (~6 m/s²).
        
        Args:
            positions: List of (x, y, t, is_detected) tuples
            max_accel_ms2: Maximum plausible acceleration (caps extreme values)
        
        Returns:
            (accel_count_high, decel_count_high)
        """
        if len(positions) < 3:
            return (0, 0)
        
        # Calculate velocities (m/s)
        velocities = []
        for i in range(1, len(positions)):
            x1, y1, t1, _ = positions[i - 1]
            x2, y2, t2, _ = positions[i]
            dt = t2 - t1
            if dt <= 0:
                velocities.append(0.0)
                continue
            dx = x2 - x1
            dy = y2 - y1
            velocity = np.sqrt(dx**2 + dy**2) / dt
            velocities.append(velocity)
        
        if len(velocities) < 2:
            return (0, 0)
        
        # Smooth velocities
        velocities_array = np.array(velocities)
        if len(velocities_array) >= 5:
            velocities_smoothed = uniform_filter1d(velocities_array, size=5, mode='nearest')
        else:
            velocities_smoothed = velocities_array
        
        # Calculate accelerations (m/s^2)
        accelerations = []
        dt_frame = 1.0 / self.fps
        for i in range(1, len(velocities_smoothed)):
            dv = velocities_smoothed[i] - velocities_smoothed[i - 1]
            accel = dv / dt_frame
            
            # Cap acceleration at max_accel_ms2
            accel = np.clip(accel, -max_accel_ms2, max_accel_ms2)
            
            accelerations.append(accel)
        
        if not accelerations:
            return (0, 0)
        
        # Smooth accelerations
        accel_array = np.array(accelerations)
        if len(accel_array) >= 5:
            accel_smoothed = uniform_filter1d(accel_array, size=5, mode='nearest')
        else:
            accel_smoothed = accel_array
        
        # Count events with dwell threshold
        accel_count = 0
        decel_count = 0
        
        accel_frames = 0
        decel_frames = 0
        
        for accel in accel_smoothed:
            if accel >= self.accel_high_ms2:
                accel_frames += 1
                decel_frames = 0
                if accel_frames >= self.accel_dwell_frames:
                    accel_count += 1
                    accel_frames = 0  # Reset to avoid double counting
            elif accel <= -self.accel_high_ms2:
                decel_frames += 1
                accel_frames = 0
                if decel_frames >= self.accel_dwell_frames:
                    decel_count += 1
                    decel_frames = 0
            else:
                accel_frames = 0
                decel_frames = 0
        
        return (accel_count, decel_count)
    
    def calculate_heatmap(
        self,
        positions: List[Tuple[float, float, float, bool]]
    ) -> List[List[float]]:
        """Calculate spatial heatmap on pitch grid.
        
        Args:
            positions: List of (x, y, t, is_detected) tuples in meters
        
        Returns:
            2D grid (ny x nx) with time spent in each cell (seconds)
        """
        nx, ny = self.heatmap_grid
        grid = np.zeros((ny, nx), dtype=float)
        
        if len(positions) < 2:
            return grid.tolist()
        
        dt = 1.0 / self.fps
        
        for x, y, t, _ in positions:
            # Map to grid coordinates
            # x: 0 to pitch_length_m -> 0 to nx-1
            # y: 0 to pitch_width_m -> 0 to ny-1
            grid_x = int((x / self.pitch_length_m) * nx)
            grid_y = int((y / self.pitch_width_m) * ny)
            
            # Clamp to grid bounds
            grid_x = max(0, min(nx - 1, grid_x))
            grid_y = max(0, min(ny - 1, grid_y))
            
            grid[grid_y, grid_x] += dt
        
        return grid.tolist()
    
    def calculate_workload_metrics(
        self,
        speeds: List[float],
        detected_flags: List[bool],
        positions: List[Tuple[float, float, float, bool]]
    ) -> Dict[str, float]:
        """Calculate workload metrics for injury risk.
        
        Uses sustained speeds and threshold dwells with hysteresis.
        Top speed computed only from detected (non-interpolated) frames.
        
        Args:
            speeds: List of speeds in mph
            detected_flags: List of is_detected flags per speed
            positions: List of (x, y, t, is_detected) tuples
        
        Returns:
            Dict with workload metrics
        """
        if not speeds:
            return {
                'high_speed_distance_km': 0.0,
                'sprint_distance_km': 0.0,
                'sprint_count': 0,
                'hsr_count': 0,
                'max_speed_mph': 0.0,
                'detected_speed_frames': 0,
                'total_speed_frames': 0
            }
        
        # Filter extreme outliers (only drops clearly implausible speeds)
        valid_speeds = [s for s in speeds if s <= self.max_plausible_speed_mph]
        
        if not valid_speeds:
            # All speeds were outliers
            return {
                'high_speed_distance_km': 0.0,
                'sprint_distance_km': 0.0,
                'sprint_count': 0,
                'hsr_count': 0,
                'max_speed_mph': 0.0,
                'detected_speed_frames': 0,
                'total_speed_frames': 0
            }
        
        # Calculate sustained speeds (rolling window median ~1s)
        sustained_speeds = self.calculate_sustained_speeds(valid_speeds)
        
        # Top speed: max of sustained speeds FROM DETECTED FRAMES ONLY
        detected_sustained_speeds = [
            s for s, det in zip(sustained_speeds, detected_flags[:len(sustained_speeds)])
            if det
        ]
        
        if detected_sustained_speeds:
            if len(detected_sustained_speeds) >= 10:
                sorted_sustained = sorted(detected_sustained_speeds, reverse=True)
                percentile_idx = int(len(sorted_sustained) * 0.01)  # Top 1%
                robust_max_speed = sorted_sustained[percentile_idx]
            else:
                robust_max_speed = max(detected_sustained_speeds)
        else:
            # Fall back to all sustained speeds if no detected speeds
            robust_max_speed = max(sustained_speeds) if sustained_speeds else 0.0
        
        detected_count = sum(1 for det in detected_flags if det)
        
        # Distance calculations with ≥1s dwell (use sustained speeds)
        # HSR: High-Speed Running
        high_speed_frames = sum(1 for s in sustained_speeds if s >= self.high_speed_threshold_mph)
        high_speed_distance_m = high_speed_frames * (self.high_speed_threshold_mph / 2.23694) / self.fps
        
        # Sprint distance
        sprint_frames = sum(1 for s in sustained_speeds if s >= self.sprint_threshold_mph)
        sprint_distance_m = sprint_frames * (self.sprint_threshold_mph / 2.23694) / self.fps
        
        # Count HSR bursts with hysteresis
        hsr_count = 0
        in_hsr = False
        hsr_exit_threshold = self.high_speed_threshold_mph * 0.9
        hsr_duration_frames = 0
        min_dwell_frames = int(1.0 * self.fps)  # 1 second minimum
        
        for speed in sustained_speeds:
            if not in_hsr and speed >= self.high_speed_threshold_mph:
                in_hsr = True
                hsr_duration_frames = 1
            elif in_hsr:
                if speed >= hsr_exit_threshold:
                    hsr_duration_frames += 1
                else:
                    # Exit HSR
                    if hsr_duration_frames >= min_dwell_frames:
                        hsr_count += 1
                    in_hsr = False
                    hsr_duration_frames = 0
        
        # Count last HSR if still active
        if in_hsr and hsr_duration_frames >= min_dwell_frames:
            hsr_count += 1
        
        # Count sprint bursts with hysteresis
        sprint_count = 0
        in_sprint = False
        sprint_exit_threshold = self.sprint_threshold_mph * 0.9
        sprint_duration_frames = 0
        
        for speed in sustained_speeds:
            if not in_sprint and speed >= self.sprint_threshold_mph:
                in_sprint = True
                sprint_duration_frames = 1
            elif in_sprint:
                if speed >= sprint_exit_threshold:
                    sprint_duration_frames += 1
                else:
                    # Exit sprint
                    if sprint_duration_frames >= min_dwell_frames:
                        sprint_count += 1
                    in_sprint = False
                    sprint_duration_frames = 0
        
        # Count last sprint if still active
        if in_sprint and sprint_duration_frames >= min_dwell_frames:
            sprint_count += 1
        
        return {
            'high_speed_distance_km': high_speed_distance_m / 1000.0,
            'sprint_distance_km': sprint_distance_m / 1000.0,
            'sprint_count': sprint_count,
            'hsr_count': hsr_count,
            'max_speed_mph': robust_max_speed,
            'detected_speed_frames': detected_count,
            'total_speed_frames': len(speeds)
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
        
        # Calculate speeds with detected flags
        speeds, detected_flags = self.calculate_speed(positions)
        smoothed_speeds = self.smooth_speeds(speeds)
        
        # Calculate distance
        total_distance_km = self.calculate_distance(positions)
        
        # Temporal metrics
        timestamps = [t for _, _, t, _ in positions]
        first_seen = min(timestamps)
        last_seen = max(timestamps)
        minutes_played = (last_seen - first_seen) / 60.0
        visible_minutes = len(positions) / self.fps / 60.0
        
        # Distance per minute
        distance_per_min_m = None
        if visible_minutes > 0:
            distance_per_min_m = (total_distance_km * 1000.0) / visible_minutes
        
        # Average pitch position
        avg_pitch_x = np.mean([x for x, _, _, _ in positions])
        avg_pitch_y = np.mean([y for _, y, _, _ in positions])
        
        # Workload metrics (now with detected flags)
        workload_metrics = self.calculate_workload_metrics(smoothed_speeds, detected_flags, positions)
        
        # Speed zones
        speed_zones = self.calculate_speed_zones(smoothed_speeds)
        
        # Accelerations
        accel_count_high, decel_count_high = self.calculate_accelerations(positions)
        
        # Coverage percentage
        coverage_pct = None
        if self.total_video_frames > 0:
            coverage_pct = (len(positions) / self.total_video_frames) * 100.0
        
        # Injury risk
        injury_risk = self.calculate_injury_risk(total_distance_km, workload_metrics)
        
        return {
            'track_id': track_id,
            'top_speed_mph': round(workload_metrics['max_speed_mph'], 2),
            'top_speed_kmh': round(workload_metrics['max_speed_mph'] * 1.60934, 2),
            'distance_km': round(total_distance_km, 2),
            'minutes_played': round(minutes_played, 2),
            'visible_minutes': round(visible_minutes, 2),
            'distance_per_min_m': round(distance_per_min_m, 2) if distance_per_min_m is not None else None,
            'avg_pitch_x': round(avg_pitch_x, 2),
            'avg_pitch_y': round(avg_pitch_y, 2),
            'high_speed_distance_km': round(workload_metrics['high_speed_distance_km'], 2),
            'sprint_distance_km': round(workload_metrics['sprint_distance_km'], 2),
            'hsr_count': workload_metrics['hsr_count'],
            'sprint_count': workload_metrics['sprint_count'],
            'hi_efforts_count': workload_metrics['hsr_count'] + workload_metrics['sprint_count'],
            'zone_walk_km': round(speed_zones['zone_walk_km'], 3),
            'zone_jog_km': round(speed_zones['zone_jog_km'], 3),
            'zone_run_km': round(speed_zones['zone_run_km'], 3),
            'zone_hsr_km': round(speed_zones['zone_hsr_km'], 3),
            'zone_sprint_km': round(speed_zones['zone_sprint_km'], 3),
            'accel_count_high': accel_count_high,
            'decel_count_high': decel_count_high,
            'coverage_pct': round(coverage_pct, 2) if coverage_pct is not None else None,
            'detected_frames': workload_metrics.get('detected_speed_frames', 0),
            'total_frames': workload_metrics.get('total_speed_frames', 0),
            'injury_risk': injury_risk
        }
    
    def get_all_heatmaps(self) -> Dict[int, List[List[float]]]:
        """Get heatmaps for all tracked players.
        
        Returns:
            Dict mapping track_id to 2D heatmap grid
        """
        heatmaps = {}
        for track_id, positions in self.track_positions.items():
            if len(positions) >= 2:
                heatmaps[track_id] = self.calculate_heatmap(positions)
        return heatmaps
    
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
