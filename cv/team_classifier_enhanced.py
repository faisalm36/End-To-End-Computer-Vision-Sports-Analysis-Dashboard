"""
Enhanced team classification with:
- Kit colour prior from user input
- Per-tracklet classification (not per-frame)
- Goalkeeper heuristic (colour outlier near goal)
- Optional SigLIP embedding backend (documented but not required)
"""

import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter
from sklearn.cluster import KMeans


class TeamClassifierEnhanced:
    """Enhanced team classifier with kit priors and goalkeeper detection."""
    
    def __init__(
        self,
        n_teams: int = 2,
        early_frames_count: int = 300,
        kit_colours: Optional[Dict[str, Tuple[int, int, int]]] = None,
        use_siglip: bool = False
    ):
        """Initialize enhanced team classifier.
        
        Args:
            n_teams: Number of teams
            early_frames_count: Frames to collect before fitting
            kit_colours: Optional kit colour dict {'team_a': (B, G, R), 'team_b': (B, G, R)}
            use_siglip: Use SigLIP embeddings (requires additional setup)
        """
        self.n_teams = n_teams
        self.early_frames_count = early_frames_count
        self.kit_colours = kit_colours
        self.use_siglip = use_siglip
        
        # Per-tracklet jersey colors (median of observations)
        self.track_colors: Dict[int, List[np.ndarray]] = defaultdict(list)
        self.track_median_colors: Dict[int, np.ndarray] = {}
        
        # Team and role assignments
        self.track_teams: Dict[int, Optional[int]] = {}
        self.track_roles: Dict[int, str] = {}
        
        # KMeans model
        self.kmeans: Optional[KMeans] = None
        self.fitted = False
        self.frame_count = 0
        
        # SigLIP embeddings (placeholder - would require model)
        if use_siglip:
            print("Note: SigLIP embeddings not implemented. Using colour-based classification.")
            self.use_siglip = False
    
    def extract_jersey_color(
        self,
        frame: np.ndarray,
        bbox: List[float],
        use_lab: bool = True
    ) -> Optional[np.ndarray]:
        """Extract dominant jersey color from torso region.
        
        Args:
            frame: Input frame
            bbox: Bounding box [x1, y1, x2, y2]
            use_lab: Use LAB color space
        
        Returns:
            Dominant color vector or None
        """
        x1, y1, x2, y2 = [int(c) for c in bbox]
        
        # Ensure bbox within frame
        h, w = frame.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)
        
        if x2 <= x1 or y2 <= y1:
            return None
        
        # Crop to torso region (middle 60% height, middle 80% width)
        crop_h = y2 - y1
        crop_w = x2 - x1
        
        torso_y1 = y1 + int(crop_h * 0.2)
        torso_y2 = y1 + int(crop_h * 0.8)
        torso_x1 = x1 + int(crop_w * 0.1)
        torso_x2 = x1 + int(crop_w * 0.9)
        
        torso = frame[torso_y1:torso_y2, torso_x1:torso_x2]
        
        if torso.size == 0:
            return None
        
        # Convert to LAB or HSV
        if use_lab:
            color_space = cv2.cvtColor(torso, cv2.COLOR_BGR2LAB)
        else:
            color_space = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        
        # Get median color (robust to outliers)
        median_color = np.median(color_space.reshape(-1, 3), axis=0)
        
        return median_color
    
    def add_observation(
        self,
        track_id: int,
        frame: np.ndarray,
        bbox: List[float]
    ):
        """Add color observation for a track.
        
        Args:
            track_id: Player track ID
            frame: Input frame
            bbox: Bounding box
        """
        color = self.extract_jersey_color(frame, bbox)
        if color is not None:
            self.track_colors[track_id].append(color)
        
        self.frame_count += 1
    
    def fit_teams(self, min_samples: int = 4):
        """Fit team classifier on collected colors (per-tracklet median).
        
        Args:
            min_samples: Minimum number of tracks
        """
        if self.fitted:
            return
        
        # Compute median color per track
        all_colors = []
        track_ids = []
        
        for track_id, colors in self.track_colors.items():
            if len(colors) > 0:
                median_color = np.median(colors, axis=0)
                self.track_median_colors[track_id] = median_color
                all_colors.append(median_color)
                track_ids.append(track_id)
        
        if len(all_colors) < min_samples:
            print(f"Warning: Only {len(all_colors)} tracks, need >= {min_samples} for classification")
            return
        
        # If kit colours provided, use them as priors
        if self.kit_colours:
            self._fit_with_priors(all_colors, track_ids)
        else:
            self._fit_kmeans(all_colors, track_ids)
        
        self.fitted = True
        print(f"Team classification fitted on {len(all_colors)} tracklets from {self.frame_count} frames")
    
    def _fit_kmeans(self, all_colors: List[np.ndarray], track_ids: List[int]):
        """Fit KMeans without priors."""
        X = np.array(all_colors)
        self.kmeans = KMeans(n_clusters=self.n_teams, random_state=42, n_init=10)
        self.kmeans.fit(X)
    
    def _fit_with_priors(self, all_colors: List[np.ndarray], track_ids: List[int]):
        """Fit with kit colour priors."""
        # Convert kit colours to LAB
        team_a_bgr = np.array([[self.kit_colours['team_a']]], dtype=np.uint8)
        team_b_bgr = np.array([[self.kit_colours['team_b']]], dtype=np.uint8)
        
        team_a_lab = cv2.cvtColor(team_a_bgr, cv2.COLOR_BGR2LAB)[0, 0]
        team_b_lab = cv2.cvtColor(team_b_bgr, cv2.COLOR_BGR2LAB)[0, 0]
        
        # Initialize KMeans with prior centers
        initial_centers = np.array([team_a_lab, team_b_lab])
        
        X = np.array(all_colors)
        self.kmeans = KMeans(
            n_clusters=self.n_teams,
            init=initial_centers,
            n_init=1,
            random_state=42
        )
        self.kmeans.fit(X)
    
    def assign_teams(self, outlier_threshold: float = 1.5):
        """Assign teams to all tracks (per-tracklet).
        
        Args:
            outlier_threshold: Distance threshold in std devs for referee detection
        """
        if not self.fitted or self.kmeans is None:
            return
        
        # Assign each track to closest cluster
        for track_id, median_color in self.track_median_colors.items():
            color_reshaped = median_color.reshape(1, -1)
            
            # Predict cluster
            cluster = self.kmeans.predict(color_reshaped)[0]
            distances = self.kmeans.transform(color_reshaped)[0]
            min_distance = distances[cluster]
            
            # Compute outlier threshold
            mean_distance = np.mean(distances)
            std_distance = np.std(distances)
            
            # If far from all clusters, likely a referee
            if min_distance > mean_distance + outlier_threshold * std_distance:
                self.track_teams[track_id] = None  # Referee
                self.track_roles[track_id] = 'referee'
            else:
                self.track_teams[track_id] = int(cluster)
                self.track_roles[track_id] = 'player'  # Default
    
    def detect_goalkeepers(
        self,
        track_positions: Dict[int, List[Tuple[float, float]]],
        pitch_length_m: float = 105.0
    ):
        """Detect goalkeepers based on position (stay near goal).
        
        Args:
            track_positions: Dict mapping track_id to list of (pitch_x, pitch_y)
            pitch_length_m: Pitch length in meters
        """
        if not self.fitted:
            return
        
        for track_id, positions in track_positions.items():
            if len(positions) < 10:
                continue
            
            if track_id not in self.track_teams or self.track_teams[track_id] is None:
                continue  # Skip referees
            
            # Compute average x position
            avg_x = np.mean([x for x, y in positions])
            
            # Check if near goal (< 20m from either end)
            near_left_goal = avg_x < 20.0
            near_right_goal = avg_x > (pitch_length_m - 20.0)
            
            if near_left_goal or near_right_goal:
                # Check if position is consistent (stays in that zone)
                x_positions = [x for x, y in positions]
                x_std = np.std(x_positions)
                
                # If standard deviation is low, likely a goalkeeper
                if x_std < 15.0:
                    # Check if colour is different from team (GK often has different kit)
                    team = self.track_teams[track_id]
                    team_center = self.kmeans.cluster_centers_[team]
                    
                    if track_id in self.track_median_colors:
                        player_color = self.track_median_colors[track_id]
                        distance = np.linalg.norm(player_color - team_center)
                        
                        # If colour is significantly different from team, mark as GK
                        if distance > 20.0:  # Threshold for colour difference
                            self.track_roles[track_id] = 'goalkeeper'
                            print(f"Detected goalkeeper: track {track_id}, avg_x={avg_x:.1f}m, colour_dist={distance:.1f}")
    
    def get_team(self, track_id: int) -> Optional[int]:
        """Get team assignment for a track."""
        return self.track_teams.get(track_id)
    
    def get_role(self, track_id: int) -> str:
        """Get role for a track."""
        return self.track_roles.get(track_id, 'player')
    
    def refine_with_voting(self, min_observations: int = 10):
        """Refine team assignments using majority voting (less relevant for tracklet-based).
        
        For tracklet-based classification, this mainly validates consistency.
        """
        if not self.fitted:
            return
        
        for track_id, colors in self.track_colors.items():
            if len(colors) < min_observations:
                continue
            
            # Predict cluster for each observation
            X = np.array(colors)
            predictions = self.kmeans.predict(X)
            
            # Count votes
            votes = Counter(predictions)
            total_votes = len(predictions)
            
            # If one team has >70% votes, ensure it's assigned
            for team, count in votes.items():
                if count / total_votes > 0.7:
                    self.track_teams[track_id] = int(team)
                    if self.track_roles[track_id] != 'goalkeeper':
                        self.track_roles[track_id] = 'player'
                    break
