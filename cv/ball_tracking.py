"""Dedicated ball tracking with tiled inference, Kalman filtering, and interpolation."""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from ultralytics import YOLO
from filterpy.kalman import KalmanFilter


class BallTracker:
    """
    Advanced ball tracking with:
    - Tiled/sliced high-res inference for small ball detection
    - Kalman filter with maximum speed gating
    - Gap interpolation with is_detected flags
    - Pluggable fine-tuned ball weights
    """
    
    SPORTS_BALL_CLASS_ID = 32
    
    # Physical constraints
    MAX_BALL_SPEED_MS = 35.0  # ~126 km/h, professional shot speed
    MAX_BALL_SPEED_PIXELFRAME = None  # Computed from video FPS and pitch calibration
    
    def __init__(
        self,
        model_path: str = "yolov8x.pt",
        ball_conf: float = 0.25,
        device: str = "auto",
        fps: float = 30.0,
        max_gap_frames: int = 15,
        use_tiling: bool = True,
        tile_overlap: float = 0.2,
        imgsz: int = 1280
    ):
        """Initialize ball tracker.
        
        Args:
            model_path: Path to YOLO model (can be fine-tuned ball model)
            ball_conf: Confidence threshold for ball detection
            device: Device for inference
            fps: Video FPS (for speed gating)
            max_gap_frames: Maximum frames to interpolate across
            use_tiling: Use tiled inference for better small object detection
            tile_overlap: Overlap ratio for tiles (0.0-0.5)
            imgsz: Inference resolution (higher = better for small objects)
        """
        self.model_path = model_path
        self.ball_conf = ball_conf
        self.device = device
        self.fps = fps
        self.max_gap_frames = max_gap_frames
        self.use_tiling = use_tiling
        self.tile_overlap = tile_overlap
        self.imgsz = imgsz
        
        # Statistics
        self.ball_gated_count = 0  # Count of detections rejected by speed gating
        
        # Auto-detect device
        if device == "auto":
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
            elif torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        
        print(f"Loading ball detection model from {model_path}")
        self.model = YOLO(model_path)
        
        # Ball detection history for Kalman filter and interpolation
        self.ball_history: List[Optional[Dict]] = []
        
        # Kalman filter for ball tracking
        self.kf = self._init_kalman_filter()
        self.kf_initialized = False
        
        # Compute max pixel speed per frame (conservative estimate)
        # Assume ~100m pitch visible in 1920px → ~19.2 px/m
        # At 35 m/s and 30 fps: ~22 px/frame
        self.MAX_BALL_SPEED_PIXELFRAME = (35.0 / self.fps) * 20.0  # ~23 px/frame @ 30fps
    
    def _init_kalman_filter(self) -> KalmanFilter:
        """Initialize Kalman filter for ball position and velocity."""
        # State: [x, y, vx, vy] (position and velocity)
        kf = KalmanFilter(dim_x=4, dim_z=2)
        
        # State transition matrix (constant velocity model)
        dt = 1.0 / self.fps
        kf.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        
        # Measurement matrix (we observe position only)
        kf.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ])
        
        # Measurement noise (detection uncertainty)
        kf.R = np.eye(2) * 25.0  # ~5 pixel std dev
        
        # Process noise (acceleration/unpredictability)
        q = 500.0
        kf.Q = np.array([
            [dt**4/4, 0, dt**3/2, 0],
            [0, dt**4/4, 0, dt**3/2],
            [dt**3/2, 0, dt**2, 0],
            [0, dt**3/2, 0, dt**2]
        ]) * q
        
        # Initial covariance
        kf.P *= 1000.0
        
        return kf
    
    def detect_ball(
        self,
        frame: np.ndarray,
        frame_idx: int
    ) -> Optional[Dict]:
        """Detect ball in frame with optional tiling.
        
        Args:
            frame: Input video frame
            frame_idx: Frame index
        
        Returns:
            Ball detection dict or None
        """
        if self.use_tiling:
            return self._detect_ball_tiled(frame, frame_idx)
        else:
            return self._detect_ball_simple(frame, frame_idx)
    
    def _detect_ball_simple(self, frame: np.ndarray, frame_idx: int) -> Optional[Dict]:
        """Simple ball detection at high resolution."""
        results = self.model(
            frame,
            classes=[self.SPORTS_BALL_CLASS_ID],
            conf=self.ball_conf,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False
        )
        
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            if len(boxes) > 0:
                best_idx = boxes.conf.argmax()
                x1, y1, x2, y2 = boxes.xyxy[best_idx].cpu().numpy()
                conf = float(boxes.conf[best_idx].cpu().numpy())
                
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                
                return {
                    'bbox': [float(x1), float(y1), float(x2), float(y2)],
                    'center': [cx, cy],
                    'confidence': conf,
                    'frame_idx': frame_idx,
                    'is_detected': True,
                    'is_interpolated': False
                }
        
        return None
    
    def _detect_ball_tiled(self, frame: np.ndarray, frame_idx: int) -> Optional[Dict]:
        """Detect ball using tiled/sliced inference (SAHI-style)."""
        h, w = frame.shape[:2]
        
        # Tile size: aim for overlap and good coverage
        tile_size = self.imgsz
        overlap_px = int(tile_size * self.tile_overlap)
        stride = tile_size - overlap_px
        
        all_detections = []
        
        # Generate tiles
        for y in range(0, h, stride):
            for x in range(0, w, stride):
                x1 = x
                y1 = y
                x2 = min(x + tile_size, w)
                y2 = min(y + tile_size, h)
                
                # Skip tiny edge tiles
                if (x2 - x1) < tile_size // 2 or (y2 - y1) < tile_size // 2:
                    continue
                
                tile = frame[y1:y2, x1:x2]
                
                # Detect in tile
                results = self.model(
                    tile,
                    classes=[self.SPORTS_BALL_CLASS_ID],
                    conf=self.ball_conf,
                    imgsz=tile_size,
                    device=self.device,
                    verbose=False
                )
                
                if results and results[0].boxes is not None:
                    boxes = results[0].boxes
                    for i in range(len(boxes)):
                        bx1, by1, bx2, by2 = boxes.xyxy[i].cpu().numpy()
                        conf = float(boxes.conf[i].cpu().numpy())
                        
                        # Transform to full image coordinates
                        bx1_full = bx1 + x1
                        by1_full = by1 + y1
                        bx2_full = bx2 + x1
                        by2_full = by2 + y1
                        
                        cx = (bx1_full + bx2_full) / 2.0
                        cy = (by1_full + by2_full) / 2.0
                        
                        all_detections.append({
                            'bbox': [bx1_full, by1_full, bx2_full, by2_full],
                            'center': [cx, cy],
                            'confidence': conf
                        })
        
        if not all_detections:
            return None
        
        # NMS: merge overlapping detections
        best_detection = self._nms_detections(all_detections)
        
        if best_detection:
            best_detection['frame_idx'] = frame_idx
            best_detection['is_detected'] = True
            best_detection['is_interpolated'] = False
        
        return best_detection
    
    def _nms_detections(self, detections: List[Dict], iou_threshold: float = 0.5) -> Optional[Dict]:
        """Non-maximum suppression on detections."""
        if not detections:
            return None
        
        # Sort by confidence
        detections = sorted(detections, key=lambda d: d['confidence'], reverse=True)
        
        # Simple NMS: keep best, remove overlapping
        keep = []
        while detections:
            best = detections.pop(0)
            keep.append(best)
            
            # Remove overlapping
            detections = [
                d for d in detections
                if self._iou(best['bbox'], d['bbox']) < iou_threshold
            ]
        
        # Return highest confidence
        return keep[0] if keep else None
    
    def _iou(self, box1: List[float], box2: List[float]) -> float:
        """Compute IoU between two boxes."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        if x2 <= x1 or y2 <= y1:
            return 0.0
        
        inter = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        
        return inter / union if union > 0 else 0.0
    
    def track_ball(
        self,
        detection: Optional[Dict]
    ) -> Optional[Dict]:
        """Track ball with Kalman filter and speed gating.
        
        Args:
            detection: Ball detection from current frame or None
        
        Returns:
            Tracked/predicted ball position with is_detected flag
        """
        if detection is not None:
            # New detection
            center = detection['center']
            
            # Speed gating: reject implausible jumps
            if self.kf_initialized and len(self.ball_history) > 0:
                last_ball = self._get_last_valid_ball()
                if last_ball:
                    dx = center[0] - last_ball['center'][0]
                    dy = center[1] - last_ball['center'][1]
                    distance = np.sqrt(dx**2 + dy**2)
                    
                    # Reject if too fast
                    if distance > self.MAX_BALL_SPEED_PIXELFRAME * 2.0:  # Allow 2x margin
                        self.ball_gated_count += 1
                        detection = None
            
            # Update Kalman filter with detection
            if detection:
                if not self.kf_initialized:
                    # Initialize filter
                    self.kf.x = np.array([center[0], center[1], 0, 0])
                    self.kf_initialized = True
                else:
                    # Kalman update
                    self.kf.predict()
                    self.kf.update(np.array([center[0], center[1]]))
                
                self.ball_history.append(detection)
                return detection
        
        # No detection: try Kalman prediction or interpolation
        if self.kf_initialized:
            self.kf.predict()
            predicted_center = self.kf.x[:2]
            
            # Create predicted ball
            predicted_ball = {
                'bbox': [
                    predicted_center[0] - 5,
                    predicted_center[1] - 5,
                    predicted_center[0] + 5,
                    predicted_center[1] + 5
                ],
                'center': [float(predicted_center[0]), float(predicted_center[1])],
                'confidence': 0.0,
                'frame_idx': len(self.ball_history),
                'is_detected': False,
                'is_interpolated': True
            }
            
            self.ball_history.append(predicted_ball)
            return predicted_ball
        
        # No filter initialized and no detection
        self.ball_history.append(None)
        return None
    
    def _get_last_valid_ball(self) -> Optional[Dict]:
        """Get last valid (detected) ball from history."""
        for ball in reversed(self.ball_history):
            if ball and ball.get('is_detected', False):
                return ball
        return None
    
    def interpolate_gaps(self) -> List[Optional[Dict]]:
        """Post-process history to interpolate short gaps with linear motion.
        
        Returns:
            Updated ball history with interpolated detections
        """
        if len(self.ball_history) < 2:
            return self.ball_history
        
        interpolated = []
        
        i = 0
        while i < len(self.ball_history):
            ball = self.ball_history[i]
            
            if ball and ball.get('is_detected', False):
                # Valid detection
                interpolated.append(ball)
                i += 1
            else:
                # Find gap
                gap_start = i - 1
                gap_end = i
                
                # Find next valid detection
                while gap_end < len(self.ball_history) and (
                    self.ball_history[gap_end] is None or 
                    not self.ball_history[gap_end].get('is_detected', False)
                ):
                    gap_end += 1
                
                gap_size = gap_end - gap_start - 1
                
                # Interpolate if gap is small enough
                if gap_size > 0 and gap_size <= self.max_gap_frames and gap_start >= 0 and gap_end < len(self.ball_history):
                    ball_before = self.ball_history[gap_start]
                    ball_after = self.ball_history[gap_end]
                    
                    if ball_before and ball_after:
                        # Linear interpolation
                        for j in range(gap_start + 1, gap_end):
                            alpha = (j - gap_start) / (gap_end - gap_start)
                            
                            cx = ball_before['center'][0] * (1 - alpha) + ball_after['center'][0] * alpha
                            cy = ball_before['center'][1] * (1 - alpha) + ball_after['center'][1] * alpha
                            
                            interpolated.append({
                                'bbox': [cx - 5, cy - 5, cx + 5, cy + 5],
                                'center': [cx, cy],
                                'confidence': 0.0,
                                'frame_idx': j,
                                'is_detected': False,
                                'is_interpolated': True
                            })
                    else:
                        # Can't interpolate, add Nones
                        for j in range(gap_start + 1, gap_end):
                            interpolated.append(None)
                else:
                    # Gap too large or at boundaries
                    for j in range(gap_start + 1, gap_end):
                        if j < len(self.ball_history):
                            interpolated.append(self.ball_history[j])
                
                i = gap_end
        
        return interpolated
