"""Enhanced tracking with BoT-SORT, GMC, and ReID support."""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from ultralytics import YOLO


class EnhancedTracker:
    """Enhanced detection and tracking with BoT-SORT/ByteTrack support."""
    
    # COCO class IDs
    PERSON_CLASS_ID = 0
    SPORTS_BALL_CLASS_ID = 32
    
    def __init__(
        self,
        model_path: str = "yolov8x.pt",
        person_conf: float = 0.3,
        ball_conf: float = 0.25,
        iou_threshold: float = 0.5,
        device: str = "auto",
        tracker: str = "botsort",  # 'botsort' or 'bytetrack'
        tracker_config: Optional[str] = None,
        reid_model: Optional[str] = None
    ):
        """Initialize enhanced tracker.
        
        Args:
            model_path: Path to YOLO model weights
            person_conf: Confidence threshold for person detection
            ball_conf: Confidence threshold for ball detection
            iou_threshold: IoU threshold for NMS
            device: 'cuda', 'mps', 'cpu', or 'auto'
            tracker: Tracker type - 'botsort' (default) or 'bytetrack'
            tracker_config: Path to custom tracker YAML config (optional)
            reid_model: Path to ReID model for BoT-SORT (optional, uses default if None)
        """
        self.model_path = model_path
        self.person_conf = person_conf
        self.ball_conf = ball_conf
        self.iou_threshold = iou_threshold
        self.tracker = tracker
        self.tracker_config = tracker_config
        self.reid_model = reid_model
        
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
        print(f"Using tracker: {tracker}")
        self.model = YOLO(model_path)
        
        # Prepare tracker config
        if tracker_config:
            self._tracker_yaml = tracker_config
        else:
            # Use default tracker YAML
            if tracker == "botsort":
                self._tracker_yaml = "botsort.yaml"
            else:
                self._tracker_yaml = "bytetrack.yaml"
    
    def detect_and_track(
        self,
        frame: np.ndarray,
        frame_idx: int,
        imgsz: int = 640,
        pitch_mask: Optional[np.ndarray] = None
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """Detect and track players/referees with enhanced tracker.
        
        Args:
            frame: Input video frame
            frame_idx: Frame index
            imgsz: Inference resolution
            pitch_mask: Optional binary mask for pitch ROI
        
        Returns:
            Tuple of (person_detections, ball_detection)
        """
        # Run tracking on people with selected tracker
        person_results = self.model.track(
            frame,
            persist=True,
            tracker=self._tracker_yaml,
            classes=[self.PERSON_CLASS_ID],
            conf=self.person_conf,
            iou=self.iou_threshold,
            imgsz=imgsz,
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
                        'class_name': 'player',
                        'frame_idx': frame_idx
                    })
        
        # Ball detection handled separately
        ball = None
        
        return persons, ball
