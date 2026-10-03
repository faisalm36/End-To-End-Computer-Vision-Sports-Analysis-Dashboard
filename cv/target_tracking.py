"""
Target tracking: Re-acquire a specific player across tracklets, occlusions, and exits.

Single-player tracking mode that:
- Resolves a target specification (frame+bbox/point, jersey+team, or target.json)
- Re-acquires the target through track switches using appearance, team, jersey, and motion gates
- Marks frames as tracked/occluded/lost/reacquired
- Never silently jumps to the wrong player
"""

import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass


@dataclass
class TargetSpec:
    """Target specification for player tracking."""
    # Resolution method
    target_frame: Optional[int] = None
    target_bbox: Optional[Tuple[float, float, float, float]] = None  # x1, y1, x2, y2
    target_point: Optional[Tuple[float, float]] = None  # x, y
    target_jersey: Optional[int] = None
    target_team: Optional[int] = None  # 0 or 1
    
    def to_dict(self) -> Dict:
        """Serialize to dict for JSON output."""
        return {
            'target_frame': self.target_frame,
            'target_bbox': list(self.target_bbox) if self.target_bbox else None,
            'target_point': list(self.target_point) if self.target_point else None,
            'target_jersey': self.target_jersey,
            'target_team': self.target_team
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'TargetSpec':
        """Deserialize from dict."""
        return TargetSpec(
            target_frame=data.get('target_frame'),
            target_bbox=tuple(data['target_bbox']) if data.get('target_bbox') else None,
            target_point=tuple(data['target_point']) if data.get('target_point') else None,
            target_jersey=data.get('target_jersey'),
            target_team=data.get('target_team')
        )


class TargetTracker:
    """Single-player target tracker with re-acquisition."""
    
    def __init__(
        self,
        max_speed_ms: float = 12.0,  # ~43 km/h
        fps: float = 30.0,
        appearance_threshold: float = 0.7,  # Stricter than stitching
        color_similarity_threshold: float = 0.6,
        motion_gate_multiplier: float = 1.5,  # Allow 1.5x max speed for occlusion gaps
        occlusion_max_frames: int = 30,  # Max frames to mark as occluded before lost
    ):
        """Initialize target tracker.
        
        Args:
            max_speed_ms: Maximum plausible player speed (m/s)
            fps: Video FPS
            appearance_threshold: Appearance similarity threshold for re-acquisition
            color_similarity_threshold: Color similarity threshold (simpler metric)
            motion_gate_multiplier: Motion gate multiplier for gaps
            occlusion_max_frames: Max frames in occlusion before marking lost
        """
        self.max_speed_ms = max_speed_ms
        self.fps = fps
        self.appearance_threshold = appearance_threshold
        self.color_similarity_threshold = color_similarity_threshold
        self.motion_gate_multiplier = motion_gate_multiplier
        self.occlusion_max_frames = occlusion_max_frames
        
        # Target state
        self.target_player_uid: Optional[int] = None
        self.target_track_ids: List[int] = []  # All track_ids associated with target
        self.target_team: Optional[int] = None
        self.target_jersey: Optional[int] = None
        self.target_appearance: Optional[np.ndarray] = None  # Median appearance
        self.target_spec: Optional[TargetSpec] = None
        
        # Tracking state
        self.last_known_position: Optional[Tuple[float, float, float]] = None  # (x, y, t)
        self.last_known_bbox: Optional[Tuple[float, float, float, float]] = None
        self.frames_since_detection: int = 0
        self.current_state: str = 'lost'  # 'tracked', 'occluded', 'lost', 'reacquired'
        
        # Statistics
        self.total_frames_tracked: int = 0
        self.lost_segments: List[Tuple[float, float]] = []  # [(start_t, end_t), ...]
        self.reacquisition_count: int = 0
        self.warnings: List[str] = []
    
    def resolve_target(
        self,
        spec: TargetSpec,
        detections: List[Dict],
        player_uid_map: Optional[Dict[int, int]] = None,  # track_id -> player_uid
        team_map: Optional[Dict[int, int]] = None,  # track_id -> team
        jersey_map: Optional[Dict[int, int]] = None,  # track_id -> jersey
        appearance_map: Optional[Dict[int, np.ndarray]] = None,  # track_id -> appearance
    ) -> Tuple[bool, Optional[str]]:
        """Resolve target specification to a player_uid.
        
        Args:
            spec: Target specification
            detections: List of all detections
            player_uid_map: Mapping from track_id to player_uid
            team_map: Mapping from track_id to team
            jersey_map: Mapping from track_id to jersey number
            appearance_map: Mapping from track_id to appearance vector
        
        Returns:
            Tuple of (success, error_message)
        """
        self.target_spec = spec
        
        # Method 1: Frame + bbox/point
        if spec.target_frame is not None and (spec.target_bbox or spec.target_point):
            return self._resolve_by_frame_location(
                spec, detections, player_uid_map, team_map, jersey_map, appearance_map
            )
        
        # Method 2: Jersey number (+ optional team)
        if spec.target_jersey is not None:
            return self._resolve_by_jersey(
                spec, player_uid_map, jersey_map, team_map, appearance_map
            )
        
        return False, "No valid target specification provided"
    
    def _resolve_by_frame_location(
        self,
        spec: TargetSpec,
        detections: List[Dict],
        player_uid_map: Optional[Dict[int, int]],
        team_map: Optional[Dict[int, int]],
        jersey_map: Optional[Dict[int, int]],
        appearance_map: Optional[Dict[int, np.ndarray]],
    ) -> Tuple[bool, Optional[str]]:
        """Resolve target by frame and bbox/point."""
        # Find detections at target frame
        frame_detections = [d for d in detections if d['frame'] == spec.target_frame and d['class'] == 'player']
        
        if not frame_detections:
            return False, f"No player detections found at frame {spec.target_frame}"
        
        # Find matching detection
        if spec.target_bbox:
            # IoU matching
            target_bbox = spec.target_bbox
            best_match = None
            best_iou = 0.0
            
            for det in frame_detections:
                det_bbox = (det['bbox_x1'], det['bbox_y1'], det['bbox_x2'], det['bbox_y2'])
                iou = self._compute_iou(target_bbox, det_bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_match = det
            
            if best_iou < 0.3:
                return False, f"No player detection at frame {spec.target_frame} matches the target bbox (best IoU: {best_iou:.2f})"
            
            matched_det = best_match
        
        elif spec.target_point:
            # Point-in-box matching
            px, py = spec.target_point
            matched_det = None
            min_distance = float('inf')
            
            for det in frame_detections:
                x1, y1, x2, y2 = det['bbox_x1'], det['bbox_y1'], det['bbox_x2'], det['bbox_y2']
                
                # Check if point is inside bbox
                if x1 <= px <= x2 and y1 <= py <= y2:
                    # Point inside, use this detection
                    matched_det = det
                    break
                
                # Otherwise, compute distance to bbox center
                center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
                dist = np.sqrt((px - center_x)**2 + (py - center_y)**2)
                if dist < min_distance:
                    min_distance = dist
                    matched_det = det
            
            if not matched_det:
                return False, f"No player detection found near point ({px}, {py}) at frame {spec.target_frame}"
        
        else:
            return False, "Invalid target specification: need bbox or point with frame"
        
        # Extract target info
        track_id = matched_det['track_id']
        self.target_player_uid = player_uid_map.get(track_id, track_id) if player_uid_map else track_id
        self.target_track_ids = [track_id]
        self.target_team = team_map.get(track_id) if team_map else matched_det.get('team')
        self.target_jersey = jersey_map.get(track_id) if jersey_map else matched_det.get('jersey_number')
        self.target_appearance = appearance_map.get(track_id) if appearance_map else None
        
        return True, None
    
    def _resolve_by_jersey(
        self,
        spec: TargetSpec,
        player_uid_map: Optional[Dict[int, int]],
        jersey_map: Optional[Dict[int, int]],
        team_map: Optional[Dict[int, int]],
        appearance_map: Optional[Dict[int, np.ndarray]],
    ) -> Tuple[bool, Optional[str]]:
        """Resolve target by jersey number."""
        if not jersey_map:
            return False, "No jersey number information available"
        
        # Find all track_ids with matching jersey
        matching_tracks = [tid for tid, jersey in jersey_map.items() if jersey == spec.target_jersey]
        
        if not matching_tracks:
            return False, f"No player found with jersey number {spec.target_jersey}"
        
        # Filter by team if specified
        if spec.target_team is not None and team_map:
            matching_tracks = [tid for tid in matching_tracks if team_map.get(tid) == spec.target_team]
            
            if not matching_tracks:
                return False, f"No player found with jersey {spec.target_jersey} on team {spec.target_team}"
        
        # Check for ambiguity
        if len(matching_tracks) > 1:
            # Multiple tracks with same jersey - check if they're the same player_uid
            if player_uid_map:
                player_uids = set(player_uid_map.get(tid, tid) for tid in matching_tracks)
                if len(player_uids) > 1:
                    return False, f"Ambiguous: {len(player_uids)} different players detected with jersey {spec.target_jersey}"
                
                # Same player_uid - OK
                self.target_player_uid = player_uids.pop()
                self.target_track_ids = matching_tracks
            else:
                return False, f"Ambiguous: {len(matching_tracks)} tracks found with jersey {spec.target_jersey}"
        else:
            # Single match
            track_id = matching_tracks[0]
            self.target_player_uid = player_uid_map.get(track_id, track_id) if player_uid_map else track_id
            self.target_track_ids = [track_id]
        
        # Extract target info
        track_id = self.target_track_ids[0]
        self.target_team = team_map.get(track_id) if team_map else None
        self.target_jersey = spec.target_jersey
        self.target_appearance = appearance_map.get(track_id) if appearance_map else None
        
        return True, None
    
    def track_target(
        self,
        detections: List[Dict],
        fps: float,
        team_map: Optional[Dict[int, int]] = None,
        jersey_map: Optional[Dict[int, int]] = None,
        appearance_map: Optional[Dict[int, np.ndarray]] = None,
    ) -> List[Dict]:
        """Track target through all frames with re-acquisition.
        
        Args:
            detections: List of all detections
            fps: Video FPS
            team_map: track_id -> team
            jersey_map: track_id -> jersey
            appearance_map: track_id -> appearance vector
        
        Returns:
            List of frame-by-frame target tracking results
        """
        if self.target_player_uid is None:
            raise ValueError("Target not resolved. Call resolve_target() first.")
        
        # Group detections by frame
        frame_to_detections = {}
        max_frame = 0
        for det in detections:
            frame_idx = det['frame']
            if frame_idx not in frame_to_detections:
                frame_to_detections[frame_idx] = []
            if det['class'] == 'player':
                frame_to_detections[frame_idx].append(det)
            max_frame = max(max_frame, frame_idx)
        
        # Track through all frames
        target_frames = []
        current_lost_start = None
        
        for frame_idx in range(max_frame + 1):
            timestamp = frame_idx / fps
            
            # Check if target is detected in this frame
            frame_dets = frame_to_detections.get(frame_idx, [])
            
            # Look for target in current detections
            target_det = self._find_target_in_frame(
                frame_dets, team_map, jersey_map, appearance_map
            )
            
            if target_det:
                # Target found
                track_id = target_det['track_id']
                bbox = (target_det['bbox_x1'], target_det['bbox_y1'], 
                       target_det['bbox_x2'], target_det['bbox_y2'])
                pitch_x = target_det.get('pitch_x')
                pitch_y = target_det.get('pitch_y')
                confidence = target_det['confidence']
                
                # Update state
                was_lost = self.current_state in ['lost', 'occluded']
                if was_lost and self.frames_since_detection > 5:
                    self.current_state = 'reacquired'
                    self.reacquisition_count += 1
                    if current_lost_start is not None:
                        self.lost_segments.append((current_lost_start, timestamp))
                        current_lost_start = None
                else:
                    self.current_state = 'tracked'
                
                self.last_known_position = (pitch_x, pitch_y, timestamp) if pitch_x else None
                self.last_known_bbox = bbox
                self.frames_since_detection = 0
                self.total_frames_tracked += 1
                
                # Add track_id to target if new
                if track_id not in self.target_track_ids:
                    self.target_track_ids.append(track_id)
                
                target_frames.append({
                    'frame': frame_idx,
                    't': round(timestamp, 3),
                    'bbox': [round(c, 2) for c in bbox],
                    'confidence': round(confidence, 3),
                    'state': self.current_state,
                    'source': 'detected',
                    'pitch_x': round(pitch_x, 2) if pitch_x is not None else None,
                    'pitch_y': round(pitch_y, 2) if pitch_y is not None else None,
                })
            
            else:
                # Target not found
                self.frames_since_detection += 1
                
                # Determine state
                if self.frames_since_detection <= self.occlusion_max_frames:
                    state = 'occluded'
                else:
                    state = 'lost'
                    if self.current_state != 'lost' and current_lost_start is None:
                        current_lost_start = timestamp
                
                self.current_state = state
                
                # Try to predict position (simple linear extrapolation)
                predicted_bbox = None
                if self.last_known_bbox and self.frames_since_detection < 10:
                    # Keep last known bbox (could add velocity-based prediction)
                    predicted_bbox = self.last_known_bbox
                
                target_frames.append({
                    'frame': frame_idx,
                    't': round(timestamp, 3),
                    'bbox': [round(c, 2) for c in predicted_bbox] if predicted_bbox else None,
                    'confidence': 0.0,
                    'state': state,
                    'source': 'interpolated' if predicted_bbox else 'lost',
                    'pitch_x': None,
                    'pitch_y': None,
                })
        
        # Close any open lost segment
        if current_lost_start is not None:
            self.lost_segments.append((current_lost_start, (max_frame + 1) / fps))
        
        return target_frames
    
    def _find_target_in_frame(
        self,
        frame_detections: List[Dict],
        team_map: Optional[Dict[int, int]],
        jersey_map: Optional[Dict[int, int]],
        appearance_map: Optional[Dict[int, np.ndarray]],
    ) -> Optional[Dict]:
        """Find target player in frame detections.
        
        Uses multiple gates in priority order:
        1. Track ID match (already part of target)
        2. Jersey + team match
        3. Appearance similarity + team + motion gate
        
        Returns:
            Matched detection or None
        """
        if not frame_detections:
            return None
        
        # Gate 1: Track ID match
        for det in frame_detections:
            if det['track_id'] in self.target_track_ids:
                return det
        
        # Gate 2: Jersey + team match
        if self.target_jersey is not None and jersey_map:
            for det in frame_detections:
                track_id = det['track_id']
                jersey = jersey_map.get(track_id)
                team = team_map.get(track_id) if team_map else det.get('team')
                
                if jersey == self.target_jersey:
                    # Jersey matches
                    if self.target_team is None or team == self.target_team:
                        # Team matches or no team constraint
                        # Check motion gate
                        if self._passes_motion_gate(det):
                            return det
        
        # Gate 3: Appearance + team + motion
        if self.target_appearance is not None and appearance_map:
            candidates = []
            
            for det in frame_detections:
                track_id = det['track_id']
                team = team_map.get(track_id) if team_map else det.get('team')
                
                # Team must match
                if self.target_team is not None and team != self.target_team:
                    continue
                
                # Motion gate
                if not self._passes_motion_gate(det):
                    continue
                
                # Appearance similarity
                appearance = appearance_map.get(track_id)
                if appearance is not None:
                    similarity = self._compute_appearance_similarity(appearance)
                    if similarity >= self.appearance_threshold:
                        candidates.append((det, similarity))
            
            # Return best candidate
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                return candidates[0][0]
        
        return None
    
    def _passes_motion_gate(self, detection: Dict) -> bool:
        """Check if detection passes motion gate (plausible distance from last position)."""
        if self.last_known_position is None:
            return True  # No previous position, accept
        
        pitch_x = detection.get('pitch_x')
        pitch_y = detection.get('pitch_y')
        
        if pitch_x is None or pitch_y is None:
            return True  # No calibration, can't check
        
        last_x, last_y, last_t = self.last_known_position
        current_t = detection['timestamp']
        
        dt = current_t - last_t
        if dt <= 0:
            return True
        
        distance = np.sqrt((pitch_x - last_x)**2 + (pitch_y - last_y)**2)
        max_distance = self.max_speed_ms * dt * self.motion_gate_multiplier
        
        return distance <= max_distance
    
    def _compute_appearance_similarity(self, appearance: np.ndarray) -> float:
        """Compute appearance similarity to target."""
        if self.target_appearance is None:
            return 0.0
        
        # Cosine similarity
        dot = np.dot(self.target_appearance, appearance)
        norm1 = np.linalg.norm(self.target_appearance)
        norm2 = np.linalg.norm(appearance)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot / (norm1 * norm2)
        return (similarity + 1.0) / 2.0  # Normalize to [0, 1]
    
    def _compute_iou(
        self,
        bbox1: Tuple[float, float, float, float],
        bbox2: Tuple[float, float, float, float]
    ) -> float:
        """Compute IoU between two bboxes."""
        x1_1, y1_1, x2_1, y2_1 = bbox1
        x1_2, y1_2, x2_2, y2_2 = bbox2
        
        # Intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i < x1_i or y2_i < y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        
        # Union
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        if union <= 0:
            return 0.0
        
        return intersection / union
    
    def get_statistics(self, total_frames: int, fps: float) -> Dict:
        """Get target tracking statistics.
        
        Args:
            total_frames: Total frames in video
            fps: Video FPS
        
        Returns:
            Statistics dict
        """
        tracked_pct = (self.total_frames_tracked / total_frames * 100) if total_frames > 0 else 0
        
        return {
            'player_uid': self.target_player_uid,
            'track_ids': self.target_track_ids,
            'jersey': self.target_jersey,
            'team': self.target_team,
            'tracked_frames': self.total_frames_tracked,
            'total_frames': total_frames,
            'tracked_pct': round(tracked_pct, 2),
            'lost_segments': [{'start_t': round(s, 2), 'end_t': round(e, 2)} 
                             for s, e in self.lost_segments],
            'reacquisition_count': self.reacquisition_count,
        }


def load_target_spec_from_file(path: str) -> TargetSpec:
    """Load target specification from JSON file.
    
    Expected format:
    {
        "target_frame": 100,
        "target_bbox": [x1, y1, x2, y2],  // or "target_point": [x, y]
        // OR
        "target_jersey": 10,
        "target_team": 0  // optional
    }
    """
    with open(path, 'r') as f:
        data = json.load(f)
    
    return TargetSpec.from_dict(data)


def save_target_spec_to_file(spec: TargetSpec, path: str):
    """Save target specification to JSON file."""
    with open(path, 'w') as f:
        json.dump(spec.to_dict(), f, indent=2)
