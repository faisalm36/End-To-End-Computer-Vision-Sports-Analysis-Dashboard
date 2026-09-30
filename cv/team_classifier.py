"""Team and role classification from jersey colors."""

import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter
from sklearn.cluster import KMeans


class TeamClassifier:
    """Classify players into teams based on jersey colors."""
    
    def __init__(self, n_teams: int = 2, early_frames_count: int = 300):
        """Initialize team classifier.
        
        Args:
            n_teams: Number of teams to cluster (default: 2)
            early_frames_count: Number of early frames to fit initial model
        """
        self.n_teams = n_teams
        self.early_frames_count = early_frames_count
        
        # Track jersey colors per player
        self.track_colors: Dict[int, List[np.ndarray]] = defaultdict(list)
        
        # Team assignments per track_id
        self.track_teams: Dict[int, Optional[int]] = {}
        self.track_roles: Dict[int, str] = {}
        
        # KMeans model (fitted once on early frames)
        self.kmeans: Optional[KMeans] = None
        self.fitted = False
        self.frame_count = 0
    
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
            use_lab: Use LAB color space (better for perceptual distance)
        
        Returns:
            Dominant color as [L, A, B] or [H, S, V] vector, or None
        """
        x1, y1, x2, y2 = [int(c) for c in bbox]
        
        # Ensure bbox is within frame
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
        
        # Get median color (more robust than mean)
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
    
    def fit_teams(self):
        """Fit KMeans on collected color observations from early frames."""
        if self.fitted or self.frame_count < self.early_frames_count:
            return
        
        # Collect all colors
        all_colors = []
        track_ids = []
        
        for track_id, colors in self.track_colors.items():
            if len(colors) > 0:
                # Use median color per track for fitting
                median_color = np.median(colors, axis=0)
                all_colors.append(median_color)
                track_ids.append(track_id)
        
        if len(all_colors) < self.n_teams + 1:  # Need at least n_teams + referee
            return
        
        # Fit KMeans
        X = np.array(all_colors)
        self.kmeans = KMeans(n_clusters=self.n_teams, random_state=42, n_init=10)
        self.kmeans.fit(X)
        
        self.fitted = True
        print(f"Team clustering fitted on {len(all_colors)} players from first {self.frame_count} frames")
    
    def assign_teams(self, outlier_threshold: float = 1.5):
        """Assign teams to all tracks based on fitted KMeans.
        
        Args:
            outlier_threshold: Distance threshold (in std devs) for referee detection
        """
        if not self.fitted or self.kmeans is None:
            return
        
        # Assign each track to closest cluster
        for track_id, colors in self.track_colors.items():
            if len(colors) == 0:
                continue
            
            # Use median color
            median_color = np.median(colors, axis=0).reshape(1, -1)
            
            # Predict cluster
            cluster = self.kmeans.predict(median_color)[0]
            distance = np.min(self.kmeans.transform(median_color))
            
            # Compute distances to all cluster centers
            all_distances = self.kmeans.transform(median_color)[0]
            mean_distance = np.mean(all_distances)
            std_distance = np.std(all_distances)
            
            # If far from all clusters, likely a referee
            if distance > mean_distance + outlier_threshold * std_distance:
                self.track_teams[track_id] = None  # Referee
                self.track_roles[track_id] = 'referee'
            else:
                self.track_teams[track_id] = int(cluster)
                self.track_roles[track_id] = 'player'  # Default, refined later
    
    def detect_goalkeepers(self):
        """Detect goalkeepers based on position (stay near goal)."""
        # TODO: Implement goalkeeper detection based on pitch position
        # For now, this is a placeholder - would need position tracking over time
        pass
    
    def get_team(self, track_id: int) -> Optional[int]:
        """Get team assignment for a track.
        
        Args:
            track_id: Player track ID
        
        Returns:
            Team number (0 or 1) or None for referee
        """
        return self.track_teams.get(track_id)
    
    def get_role(self, track_id: int) -> str:
        """Get role for a track.
        
        Args:
            track_id: Player track ID
        
        Returns:
            'player', 'referee', 'goalkeeper', or 'unknown'
        """
        return self.track_roles.get(track_id, 'unknown')
    
    def refine_with_voting(self, min_observations: int = 10):
        """Refine team assignments using majority voting across frames.
        
        Args:
            min_observations: Minimum observations before voting
        """
        if not self.fitted:
            return
        
        # For tracks with many observations, use voting
        for track_id, colors in self.track_colors.items():
            if len(colors) < min_observations:
                continue
            
            # Predict cluster for each observation
            X = np.array(colors)
            predictions = self.kmeans.predict(X)
            
            # Count votes for each team
            votes = Counter(predictions)
            
            # If one team has >70% votes, assign it
            total_votes = len(predictions)
            for team, count in votes.items():
                if count / total_votes > 0.7:
                    self.track_teams[track_id] = int(team)
                    self.track_roles[track_id] = 'player'
                    break
