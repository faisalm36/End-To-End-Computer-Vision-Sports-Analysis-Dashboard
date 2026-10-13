"""Player, ball, and referee detection using YOLOv8."""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from ultralytics import YOLO


class DetectionTracker:
    """Handles object detection and tracking for soccer analytics."""
    
    # COCO class IDs
    PERSON_CLASS_ID = 0
    SPORTS_BALL_CLASS_ID = 32
    
    def __init__(
        self,
        model_path: str = "yolov8x.pt",
        person_conf: float = 0.3,
        ball_conf: float = 0.25,
        iou_threshold: float = 0.5,
        device: str = "auto"
    ):
        """Initialize detector with YOLOv8.
        
        Args:
            model_path: Path to YOLO model weights (default: pretrained COCO)
            person_conf: Confidence threshold for person detection
            ball_conf: Confidence threshold for ball detection
            iou_threshold: IoU threshold for NMS
            device: 'cuda', 'mps', 'cpu', or 'auto'
        """
        self.model_path = model_path
        self.person_conf = person_conf
        self.ball_conf = ball_conf
        self.iou_threshold = iou_threshold
        
        # Auto-detect device
        if device == "auto":
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
            elif torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        else:
            self.device = device
        
        print(f"Loading YOLO model from {model_path} on device: {self.device}")
        self.model = YOLO(model_path)
        
        # Ball tracking history for interpolation
        self.ball_history: List[Optional[Dict]] = []
        self.max_ball_gap_frames = 10
    
    def detect_and_track(
        self,
        frame: np.ndarray,
        frame_idx: int,
        imgsz: int = 640,
        pitch_mask: Optional[np.ndarray] = None
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """Detect and track players/referees and ball.
        
        Args:
            frame: Input video frame
            frame_idx: Frame index
            imgsz: Inference resolution
            pitch_mask: Optional binary mask for pitch ROI (filters out non-pitch people)
        
        Returns:
            Tuple of (person_detections, ball_detection)
            Person detections: list of dicts with keys: track_id, bbox, confidence, class_name
            Ball detection: dict or None
        """
        # Run tracking on people
        person_results = self.model.track(
            frame,
            persist=True,
            tracker='bytetrack.yaml',
            classes=[self.PERSON_CLASS_ID],
            conf=self.person_conf,
            iou=self.iou_threshold,
            imgsz=imgsz,
            device=self.device,
            verbose=False
        )
        
        # Run detection on ball (higher resolution, separate inference)
        ball_results = self.model(
            frame,
            classes=[self.SPORTS_BALL_CLASS_ID],
            conf=self.ball_conf,
            iou=self.iou_threshold,
            imgsz=1280,  # Higher res for small ball
            device=self.device,
            verbose=False
        )
        
        # Parse person detections
        persons = []
        if person_results and person_results[0].boxes is not None:
            boxes = person_results[0].boxes
            if boxes.id is not None:
                for i in range(len(boxes)):
                    x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                    track_id = int(boxes.id[i].cpu().numpy())
                    conf = float(boxes.conf[i].cpu().numpy())
                    
                    # Filter by pitch mask if provided
                    if pitch_mask is not None:
                        center_x = int((x1 + x2) / 2)
                        center_y = int((y1 + y2) / 2)
                        if (center_y < pitch_mask.shape[0] and 
                            center_x < pitch_mask.shape[1] and
                            pitch_mask[center_y, center_x] == 0):
                            continue
                    
                    persons.append({
                        'track_id': track_id,
                        'bbox': [float(x1), float(y1), float(x2), float(y2)],
                        'confidence': conf,
                        'class_name': 'player'  # Distinguish player/referee later via jersey color/OCR
                    })
        
        # Parse ball detection (take highest confidence)
        ball = None
        if ball_results and ball_results[0].boxes is not None:
            boxes = ball_results[0].boxes
            if len(boxes) > 0:
                best_idx = boxes.conf.argmax()
                x1, y1, x2, y2 = boxes.xyxy[best_idx].cpu().numpy()
                conf = float(boxes.conf[best_idx].cpu().numpy())
                
                ball = {
                    'bbox': [float(x1), float(y1), float(x2), float(y2)],
                    'confidence': conf,
                    'frame_idx': frame_idx
                }
        
        # Track ball with interpolation for short gaps
        self.ball_history.append(ball)
        if len(self.ball_history) > 100:
            self.ball_history.pop(0)
        
        # If ball not detected, try interpolation
        if ball is None:
            ball = self._interpolate_ball(frame_idx)
        
        return persons, ball
    
    def _interpolate_ball(self, frame_idx: int) -> Optional[Dict]:
        """Interpolate ball position for short gaps."""
        if len(self.ball_history) < 2:
            return None
        
        # Find last valid detection
        last_valid_idx = None
        for i in range(len(self.ball_history) - 2, -1, -1):
            if self.ball_history[i] is not None:
                last_valid_idx = i
                break
        
        if last_valid_idx is None:
            return None
        
        gap_size = len(self.ball_history) - 1 - last_valid_idx
        if gap_size > self.max_ball_gap_frames:
            return None
        
        # Simple linear interpolation (could be improved with motion model)
        if last_valid_idx > 0:
            prev_valid_idx = None
            for i in range(last_valid_idx - 1, -1, -1):
                if self.ball_history[i] is not None:
                    prev_valid_idx = i
                    break
            
            if prev_valid_idx is not None:
                prev_ball = self.ball_history[prev_valid_idx]
                last_ball = self.ball_history[last_valid_idx]
                
                # Interpolate center
                prev_center = [
                    (prev_ball['bbox'][0] + prev_ball['bbox'][2]) / 2,
                    (prev_ball['bbox'][1] + prev_ball['bbox'][3]) / 2
                ]
                last_center = [
                    (last_ball['bbox'][0] + last_ball['bbox'][2]) / 2,
                    (last_ball['bbox'][1] + last_ball['bbox'][3]) / 2
                ]
                
                dx = (last_center[0] - prev_center[0]) / (last_valid_idx - prev_valid_idx)
                dy = (last_center[1] - prev_center[1]) / (last_valid_idx - prev_valid_idx)
                
                new_center = [
                    last_center[0] + dx * gap_size,
                    last_center[1] + dy * gap_size
                ]
                
                # Use last bbox size
                w = last_ball['bbox'][2] - last_ball['bbox'][0]
                h = last_ball['bbox'][3] - last_ball['bbox'][1]
                
                return {
                    'bbox': [
                        new_center[0] - w/2,
                        new_center[1] - h/2,
                        new_center[0] + w/2,
                        new_center[1] + h/2
                    ],
                    'confidence': 0.0,  # Mark as interpolated
                    'frame_idx': frame_idx,
                    'interpolated': True
                }
        
        return None
