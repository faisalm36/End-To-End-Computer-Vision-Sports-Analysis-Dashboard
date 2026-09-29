"""Main pipeline orchestration."""

import cv2
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List
from tqdm import tqdm

from .config import Config
from .detection import DetectionTracker
from .ocr import JerseyNumberReader
from .homography import HomographyTransform
from .metrics import PerformanceAnalyzer


class SoccerAnalyticsPipeline:
    """End-to-end soccer video analytics pipeline."""
    
    def __init__(
        self,
        config: Config,
        model_path: str = "yolov8x.pt",
        device: str = "auto",
        enable_ocr: bool = True
    ):
        """Initialize pipeline.
        
        Args:
            config: Pipeline configuration
            model_path: Path to YOLO model weights
            device: Device for inference
            enable_ocr: Enable jersey number OCR
        """
        self.config = config
        self.device = device
        
        # Initialize components
        print("Initializing detection tracker...")
        self.detector = DetectionTracker(
            model_path=model_path,
            person_conf=config.PERSON_CONF_THRESHOLD,
            ball_conf=config.BALL_CONF_THRESHOLD,
            iou_threshold=config.IOU_THRESHOLD,
            device=device
        )
        
        self.ocr = None
        if enable_ocr:
            print("Initializing OCR reader...")
            try:
                # Try GPU first, fall back to CPU
                gpu = device in ['cuda', 'auto']
                self.ocr = JerseyNumberReader(gpu=gpu)
            except Exception as e:
                print(f"Warning: OCR initialization failed: {e}")
                print("Continuing without OCR...")
        
        self.homography = None
        if config.image_points and config.pitch_points:
            print("Initializing homography transform...")
            self.homography = HomographyTransform(
                config.image_points,
                config.pitch_points,
                config.PITCH_WIDTH_M,
                config.PITCH_LENGTH_M
            )
        
        # Results storage
        self.detections: List[Dict] = []
        self.performance_analyzer: Optional[PerformanceAnalyzer] = None
    
    def process_video(
        self,
        video_path: str,
        output_dir: str,
        annotate_video: bool = False,
        sample_ocr_every_n_frames: int = 10
    ):
        """Process video end-to-end.
        
        Args:
            video_path: Path to input video
            output_dir: Output directory for results
            annotate_video: Whether to write annotated video
            sample_ocr_every_n_frames: Run OCR every N frames (for performance)
        """
        video_path = Path(video_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\nProcessing video: {video_path}")
        
        # Open video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS) or self.config.FPS_DEFAULT
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        print(f"Video info: {total_frames} frames @ {fps} FPS, {width}x{height}")
        
        # Initialize performance analyzer
        self.performance_analyzer = PerformanceAnalyzer(
            fps=fps,
            max_plausible_speed_mph=self.config.MAX_PLAUSIBLE_SPEED_MPH,
            speed_smoothing_window=self.config.SPEED_SMOOTHING_WINDOW,
            high_speed_threshold_mph=self.config.HIGH_SPEED_THRESHOLD_MPH,
            sprint_threshold_mph=self.config.SPRINT_THRESHOLD_MPH
        )
        
        # Video writer for annotation
        writer = None
        if annotate_video:
            output_video_path = output_dir / f"{video_path.stem}_annotated.mp4"
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
        
        # Process frames
        frame_idx = 0
        pbar = tqdm(total=total_frames, desc="Processing frames")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            timestamp = frame_idx / fps
            
            # Detect and track
            persons, ball = self.detector.detect_and_track(
                frame,
                frame_idx,
                imgsz=self.config.DEFAULT_IMGSZ
            )
            
            # Process each person
            for person in persons:
                track_id = person['track_id']
                bbox = person['bbox']
                
                # OCR for jersey number (sample every N frames)
                jersey_number = None
                if self.ocr and frame_idx % sample_ocr_every_n_frames == 0:
                    jersey_number = self.ocr.read_jersey_number(
                        frame,
                        bbox,
                        conf_threshold=self.config.OCR_CONF_THRESHOLD,
                        allowlist=self.config.OCR_ALLOWLIST
                    )
                    if jersey_number is not None:
                        self.ocr.add_reading(track_id, jersey_number)
                
                # Transform to pitch coordinates
                pitch_coords = None
                if self.homography:
                    pitch_coords = self.homography.transform_foot_position(bbox)
                    if pitch_coords:
                        self.performance_analyzer.add_position(
                            track_id,
                            pitch_coords[0],
                            pitch_coords[1],
                            timestamp
                        )
                
                # Store detection
                detection = {
                    'frame': frame_idx,
                    'timestamp': round(timestamp, 3),
                    'track_id': track_id,
                    'class': person['class_name'],
                    'bbox_x1': round(bbox[0], 2),
                    'bbox_y1': round(bbox[1], 2),
                    'bbox_x2': round(bbox[2], 2),
                    'bbox_y2': round(bbox[3], 2),
                    'confidence': round(person['confidence'], 3),
                    'pitch_x': round(pitch_coords[0], 2) if pitch_coords else None,
                    'pitch_y': round(pitch_coords[1], 2) if pitch_coords else None,
                    'jersey_number': jersey_number
                }
                self.detections.append(detection)
            
            # Process ball
            if ball:
                bbox = ball['bbox']
                pitch_coords = None
                if self.homography:
                    pitch_coords = self.homography.transform_bbox_center(bbox)
                
                detection = {
                    'frame': frame_idx,
                    'timestamp': round(timestamp, 3),
                    'track_id': -1,  # Special ID for ball
                    'class': 'ball',
                    'bbox_x1': round(bbox[0], 2),
                    'bbox_y1': round(bbox[1], 2),
                    'bbox_x2': round(bbox[2], 2),
                    'bbox_y2': round(bbox[3], 2),
                    'confidence': round(ball['confidence'], 3),
                    'pitch_x': round(pitch_coords[0], 2) if pitch_coords else None,
                    'pitch_y': round(pitch_coords[1], 2) if pitch_coords else None,
                    'jersey_number': None
                }
                self.detections.append(detection)
            
            # Annotate frame
            if writer:
                annotated = self._annotate_frame(frame, persons, ball)
                writer.write(annotated)
            
            frame_idx += 1
            pbar.update(1)
        
        pbar.close()
        cap.release()
        if writer:
            writer.release()
        
        print(f"\nProcessed {frame_idx} frames")
        
        # Finalize jersey numbers with majority voting
        if self.ocr:
            print("Finalizing jersey numbers with majority voting...")
            jersey_numbers = self.ocr.get_all_jersey_numbers()
            
            # Update detections with final jersey numbers
            for detection in self.detections:
                track_id = detection['track_id']
                if track_id in jersey_numbers and detection['jersey_number'] is None:
                    detection['jersey_number'] = jersey_numbers[track_id]
        
        # Calculate player statistics
        print("Calculating player statistics...")
        player_stats = self.performance_analyzer.analyze_all_players()
        
        # Add jersey numbers to stats
        if self.ocr:
            jersey_numbers = self.ocr.get_all_jersey_numbers()
            for stat in player_stats:
                track_id = stat['track_id']
                stat['jersey_number'] = jersey_numbers.get(track_id)
        else:
            for stat in player_stats:
                stat['jersey_number'] = None
        
        # Save outputs
        self._save_outputs(output_dir, player_stats)
        
        print(f"\nResults saved to: {output_dir}")
        if annotate_video:
            print(f"Annotated video: {output_video_path}")
    
    def _annotate_frame(
        self,
        frame: np.ndarray,
        persons: List[Dict],
        ball: Optional[Dict]
    ) -> np.ndarray:
        """Annotate frame with detections."""
        annotated = frame.copy()
        
        # Draw persons
        for person in persons:
            bbox = person['bbox']
            x1, y1, x2, y2 = [int(c) for c in bbox]
            track_id = person['track_id']
            
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            label = f"ID:{track_id}"
            cv2.putText(
                annotated,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )
        
        # Draw ball
        if ball:
            bbox = ball['bbox']
            x1, y1, x2, y2 = [int(c) for c in bbox]
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(
                annotated,
                "Ball",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                2
            )
        
        return annotated
    
    def _save_outputs(self, output_dir: Path, player_stats: List[Dict]):
        """Save detection and statistics outputs."""
        # Save detections as JSON
        detections_json_path = output_dir / "tracking_detections.json"
        with open(detections_json_path, 'w') as f:
            json.dump(self.detections, f, indent=2)
        print(f"Saved detections JSON: {detections_json_path}")
        
        # Save detections as CSV
        detections_csv_path = output_dir / "tracking_detections.csv"
        df_detections = pd.DataFrame(self.detections)
        df_detections.to_csv(detections_csv_path, index=False)
        print(f"Saved detections CSV: {detections_csv_path}")
        
        # Save player stats as JSON
        stats_json_path = output_dir / "player_match_stats.json"
        with open(stats_json_path, 'w') as f:
            json.dump(player_stats, f, indent=2)
        print(f"Saved player stats JSON: {stats_json_path}")
        
        # Save player stats as CSV
        stats_csv_path = output_dir / "player_match_stats.csv"
        df_stats = pd.DataFrame(player_stats)
        df_stats.to_csv(stats_csv_path, index=False)
        print(f"Saved player stats CSV: {stats_csv_path}")
