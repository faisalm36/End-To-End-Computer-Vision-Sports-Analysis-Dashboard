"""
Offline tracklet stitching to create stable player_uid across the match.

Stitches tracklets based on:
- Team assignment agreement
- Jersey number agreement
- Appearance similarity (colour histogram or embedding)
- Physically feasible gap (distance <= v_max * dt)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
import networkx as nx


class TrackletStitcher:
    """Stitch short-term tracklets into long-term player identities."""
    
    def __init__(
        self,
        max_speed_ms: float = 12.0,  # ~43 km/h, max plausible running speed
        fps: float = 30.0,
        appearance_threshold: float = 0.5,  # Similarity threshold (0-1)
        use_appearance: bool = True
    ):
        """Initialize tracklet stitcher.
        
        Args:
            max_speed_ms: Maximum plausible player speed (m/s)
            fps: Video FPS (for time gap calculation)
            appearance_threshold: Appearance similarity threshold
            use_appearance: Use appearance similarity in stitching
        """
        self.max_speed_ms = max_speed_ms
        self.fps = fps
        self.appearance_threshold = appearance_threshold
        self.use_appearance = use_appearance
        
        # Tracklet data
        self.tracklets: Dict[int, Dict] = {}  # track_id -> tracklet info
        
        # Stitching results
        self.track_to_player_uid: Dict[int, int] = {}  # track_id -> player_uid
        self.player_uid_to_tracks: Dict[int, List[int]] = defaultdict(list)  # player_uid -> [track_ids]
    
    def add_tracklet(
        self,
        track_id: int,
        team: Optional[int],
        jersey_number: Optional[int],
        appearance_vector: Optional[np.ndarray],
        positions: List[Tuple[float, float, float]],  # [(x, y, t), ...]
        frame_range: Tuple[int, int]  # (first_frame, last_frame)
    ):
        """Add a tracklet for stitching.
        
        Args:
            track_id: Track ID
            team: Team assignment (0, 1, or None for referee)
            jersey_number: Jersey number (or None)
            appearance_vector: Appearance feature (colour histogram or embedding)
            positions: List of (x, y, t) positions in meters
            frame_range: (first_frame, last_frame)
        """
        self.tracklets[track_id] = {
            'team': team,
            'jersey_number': jersey_number,
            'appearance': appearance_vector,
            'positions': positions,
            'frame_range': frame_range,
            'first_position': positions[0] if positions else None,
            'last_position': positions[-1] if positions else None
        }
    
    def compute_appearance_similarity(
        self,
        appearance1: Optional[np.ndarray],
        appearance2: Optional[np.ndarray]
    ) -> float:
        """Compute appearance similarity between two vectors.
        
        Args:
            appearance1: First appearance vector
            appearance2: Second appearance vector
        
        Returns:
            Similarity score (0-1, higher is more similar)
        """
        if appearance1 is None or appearance2 is None:
            return 0.0
        
        # Cosine similarity
        dot_product = np.dot(appearance1, appearance2)
        norm1 = np.linalg.norm(appearance1)
        norm2 = np.linalg.norm(appearance2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        
        # Normalize to [0, 1]
        similarity = (similarity + 1.0) / 2.0
        
        return float(similarity)
    
    def is_physically_feasible(
        self,
        tracklet1: Dict,
        tracklet2: Dict
    ) -> bool:
        """Check if two tracklets can be the same player (motion constraint).
        
        Args:
            tracklet1: First tracklet
            tracklet2: Second tracklet (should start after tracklet1 ends)
        
        Returns:
            True if physically feasible
        """
        # Get last position of tracklet1 and first position of tracklet2
        last_pos1 = tracklet1['last_position']
        first_pos2 = tracklet2['first_position']
        
        if last_pos1 is None or first_pos2 is None:
            return False
        
        x1, y1, t1 = last_pos1
        x2, y2, t2 = first_pos2
        
        # Time gap
        dt = t2 - t1
        
        if dt <= 0:
            return False  # tracklet2 doesn't start after tracklet1
        
        # Distance
        distance_m = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        
        # Maximum distance player could have traveled
        max_distance_m = self.max_speed_ms * dt
        
        return distance_m <= max_distance_m
    
    def compute_stitching_cost(
        self,
        track_id1: int,
        track_id2: int
    ) -> float:
        """Compute stitching cost between two tracklets (lower is better).
        
        Args:
            track_id1: First track ID
            track_id2: Second track ID
        
        Returns:
            Cost (0 = perfect match, inf = impossible)
        """
        tracklet1 = self.tracklets[track_id1]
        tracklet2 = self.tracklets[track_id2]
        
        # Check temporal order (tracklet2 should start after tracklet1 ends)
        if tracklet2['frame_range'][0] <= tracklet1['frame_range'][1]:
            return float('inf')  # Overlapping or wrong order
        
        # Team agreement
        team1 = tracklet1['team']
        team2 = tracklet2['team']
        
        if team1 is not None and team2 is not None and team1 != team2:
            return float('inf')  # Different teams
        
        # Jersey number agreement
        jersey1 = tracklet1['jersey_number']
        jersey2 = tracklet2['jersey_number']
        
        if jersey1 is not None and jersey2 is not None and jersey1 != jersey2:
            return float('inf')  # Different jersey numbers
        
        # Physical feasibility
        if not self.is_physically_feasible(tracklet1, tracklet2):
            return float('inf')  # Too far apart
        
        # Compute cost (lower is better)
        cost = 0.0
        
        # Jersey number match bonus (if both available)
        if jersey1 is not None and jersey2 is not None and jersey1 == jersey2:
            cost -= 10.0  # Strong bonus
        
        # Team match bonus
        if team1 is not None and team2 is not None and team1 == team2:
            cost -= 5.0
        
        # Appearance similarity
        if self.use_appearance:
            appearance_sim = self.compute_appearance_similarity(
                tracklet1['appearance'],
                tracklet2['appearance']
            )
            cost -= appearance_sim * 5.0  # Higher similarity = lower cost
        
        # Time gap penalty (prefer shorter gaps)
        last_pos1 = tracklet1['last_position']
        first_pos2 = tracklet2['first_position']
        
        if last_pos1 and first_pos2:
            dt = first_pos2[2] - last_pos1[2]
            cost += dt / 10.0  # Small penalty for longer gaps
        
        return cost
    
    def stitch_tracklets(self) -> Dict[int, int]:
        """Stitch tracklets into player UIDs using graph matching.
        
        Returns:
            Dict mapping track_id to player_uid
        """
        if len(self.tracklets) == 0:
            return {}
        
        # Build graph: nodes are tracklets, edges are potential stitches
        G = nx.DiGraph()
        
        # Add nodes
        for track_id in self.tracklets.keys():
            G.add_node(track_id)
        
        # Add edges with costs
        track_ids = list(self.tracklets.keys())
        
        for i, track_id1 in enumerate(track_ids):
            for track_id2 in track_ids[i+1:]:
                # Compute cost in both directions
                cost_12 = self.compute_stitching_cost(track_id1, track_id2)
                cost_21 = self.compute_stitching_cost(track_id2, track_id1)
                
                # Add edge if feasible
                if cost_12 < float('inf'):
                    G.add_edge(track_id1, track_id2, cost=cost_12)
                
                if cost_21 < float('inf'):
                    G.add_edge(track_id2, track_id1, cost=cost_21)
        
        # Find connected components (chains of tracklets)
        # Use greedy approach: for each tracklet, find best continuation
        visited = set()
        player_uid_counter = 0
        
        self.track_to_player_uid = {}
        self.player_uid_to_tracks = defaultdict(list)
        
        # Sort tracklets by first frame
        sorted_tracks = sorted(
            self.tracklets.keys(),
            key=lambda tid: self.tracklets[tid]['frame_range'][0]
        )
        
        for track_id in sorted_tracks:
            if track_id in visited:
                continue
            
            # Start a new player UID
            player_uid = player_uid_counter
            player_uid_counter += 1
            
            # Build chain from this tracklet
            chain = [track_id]
            visited.add(track_id)
            
            current_track = track_id
            
            while True:
                # Find best next tracklet
                successors = list(G.successors(current_track))
                
                if not successors:
                    break
                
                # Find successor with lowest cost that hasn't been visited
                best_next = None
                best_cost = float('inf')
                
                for next_track in successors:
                    if next_track not in visited:
                        cost = G[current_track][next_track]['cost']
                        if cost < best_cost:
                            best_cost = cost
                            best_next = next_track
                
                if best_next is None or best_cost > 10.0:  # Cost threshold
                    break
                
                # Add to chain
                chain.append(best_next)
                visited.add(best_next)
                current_track = best_next
            
            # Assign player UID to all tracks in chain
            for tid in chain:
                self.track_to_player_uid[tid] = player_uid
                self.player_uid_to_tracks[player_uid].append(tid)
        
        print(f"Stitched {len(self.tracklets)} tracklets into {player_uid_counter} player UIDs")
        
        return self.track_to_player_uid
    
    def get_player_uid(self, track_id: int) -> Optional[int]:
        """Get player UID for a track ID."""
        return self.track_to_player_uid.get(track_id)
    
    def get_contributing_tracks(self, player_uid: int) -> List[int]:
        """Get all track IDs that contribute to a player UID."""
        return self.player_uid_to_tracks.get(player_uid, [])
