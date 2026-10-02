"""Main pipeline orchestration for v2.0 with commercial-quality tracking."""

import cv2
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List
from tqdm import tqdm
from datetime import datetime
import time

from .config import Config

# v2.0 modules
from .tracking import EnhancedTracker
from .ball_tracking import BallTracker
from .calibration import HomographyTransformEnhanced, PitchKeypointCalibrator
from .ocr_enhanced import EnhancedJerseyReader, LegibilityFilter
from .team_classifier_enhanced import TeamClassifierEnhanced
from .tracklet_stitching import TrackletStitcher
from .metrics import PerformanceAnalyzer

# Legacy modules (for backward compatibility)
from .detection import DetectionTracker
from .ocr import JerseyNumberReader
from .homography import HomographyTransform
from .team_classifier import TeamClassifier

# Pipeline version
__version__ = "2.0.0"


class SoccerAnalyticsPipeline:
    """End-to-end soccer video analytics pipeline with v2.0 commercial-quality tracking."""
    
    def __init__(
        self,
        config: Config,
        model_path: str = "yolov8x.pt",
        ball_model_path: Optional[str] = None,
        device: str = "auto",
        enable_ocr: bool = True,
        enable_team_classification: bool = True,
        tracker: str = "botsort"  # v2.0: 'botsort' or 'bytetrack'
    ):
        """Initialize pipeline.
        
        Args:
            config: Pipeline configuration
            model_path: Path to YOLO model weights
            ball_model_path: Path to fine-tuned ball model (optional, uses model_path if None)
            device: Device for inference
            enable_ocr: Enable jersey number OCR
            enable_team_classification: Enable team/role classification
            tracker: Tracker type ('botsort' or 'bytetrack')
        """
        self.config = config
        self.device = device
        self.model_path = model_path
        self.ball_model_path = ball_model_path or model_path
        self.enable_team_classification = enable_team_classification
        self.tracker = tracker
        
        # v2.0: Use enhanced tracker
        print(f"Initializing enhanced tracker ({tracker})...")
        self.detector = EnhancedTracker(
            model_path=model_path,
            person_conf=config.PERSON_CONF_THRESHOLD,
            ball_conf=config.BALL_CONF_THRESHOLD,
            iou_threshold=config.IOU_THRESHOLD,
            device=device,
            tracker=tracker
        )
        
        # v2.0: Dedicated ball tracker
        print("Initializing dedicated ball tracker...")
        self.ball_tracker = BallTracker(
            model_path=self.ball_model_path,
            ball_conf=config.BALL_CONF_THRESHOLD,
            device=device,
            fps=config.FPS_DEFAULT,
            max_gap_frames=config.BALL_MAX_GAP_FRAMES,
            use_tiling=config.BALL_USE_TILING,
            tile_overlap=config.BALL_TILE_OVERLAP,
            imgsz=config.BALL_IMGSZ
        )
        
        # v2.0: Enhanced OCR with legibility filter and roster
        self.ocr = None
        if enable_ocr:
            print("Initializing enhanced OCR reader...")
            try:
                gpu = device in ['cuda', 'auto']
                self.ocr = EnhancedJerseyReader(
                    languages=['en'],
                    gpu=gpu,
                    backend=config.OCR_BACKEND,
                    legibility_filter=LegibilityFilter() if config.OCR_USE_LEGIBILITY_FILTER else None,
                    roster_team_a=config.roster_team_a,
                    roster_team_b=config.roster_team_b
                )
            except Exception as e:
                print(f"Warning: OCR initialization failed: {e}")
                print("Continuing without OCR...")
        
        # v2.0: Enhanced homography with calibration quality
        self.homography = None
        if config.image_points and config.pitch_points:
            print("Initializing enhanced homography transform...")
            self.homography = HomographyTransformEnhanced(
                image_points=config.image_points,
                pitch_points=config.pitch_points,
                pitch_width_m=config.PITCH_WIDTH_M,
                pitch_length_m=config.PITCH_LENGTH_M
            )
        
        # v2.0: Enhanced team classifier with kit priors
        self.team_classifier = None
        if enable_team_classification:
            print("Initializing enhanced team classifier...")
            self.team_classifier = TeamClassifierEnhanced(
                n_teams=2,
                early_frames_count=300,
                kit_colours=config.kit_colours,
                use_siglip=False
            )
        
        # v2.0: Tracklet stitcher for stable player_uid
        self.tracklet_stitcher = None
        if config.USE_TRACKLET_STITCHING:
            self.tracklet_stitcher = TrackletStitcher(
                max_speed_ms=config.MAX_PLAYER_SPEED_MS,
                fps=config.FPS_DEFAULT,
                appearance_threshold=0.5,
                use_appearance=True
            )
        
        # Results storage
        self.detections: List[Dict] = []
        self.performance_analyzer: Optional[PerformanceAnalyzer] = None
        self.metadata: Dict = {}
        self.warnings: List[str] = []
    
    def process_video(
        self,
        video_path: str,
        output_dir: str,
        annotate_video: bool = False,
        sample_ocr_every_n_frames: int = 10,
        target_spec: Optional['TargetSpec'] = None,
        render_replay: bool = False,
        replay_max_height: Optional[int] = None,
    ):
        """Process video end-to-end with v2.0 features.
        
        Args:
            video_path: Path to input video
            output_dir: Output directory for results
            annotate_video: Whether to write annotated video
            sample_ocr_every_n_frames: Run OCR every N frames (for performance)
            target_spec: Optional target specification for single-player tracking
            render_replay: Whether to render replay video (target mode)
            replay_max_height: Maximum height for replay video downscaling
        """
        start_time = time.time()
        start_timestamp = datetime.now().isoformat()
        
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
        duration_s = total_frames / fps if fps > 0 else 0
        
        print(f"Video info: {total_frames} frames @ {fps} FPS, {width}x{height}, duration: {duration_s:.1f}s")
        
        # Initialize metadata with v2.0 fields
        self.metadata = {
            'pipeline_version': __version__,
            'video_path': str(video_path),
            'fps': fps,
            'frame_count': total_frames,
            'duration_s': round(duration_s, 2),
            'resolution': f"{width}x{height}",
            'width': width,
            'height': height,
            'model_path': self.model_path,
            'ball_model_path': self.ball_model_path,
            'device': self.device,
            'tracker': self.tracker,  # v2.0
            'ball_tracking_method': 'tiled' if self.config.BALL_USE_TILING else 'simple',  # v2.0
            'tracklet_stitching_enabled': self.config.USE_TRACKLET_STITCHING,  # v2.0
            'calibration': self.config.calibration_source or 'none',
            'start_timestamp': start_timestamp,
            'warnings': []
        }
        
        # Add calibration quality if available
        if self.homography:
            cal_quality = self.homography.get_calibration_quality()
            if cal_quality:
                self.metadata['calibration_quality'] = cal_quality
        
        # Add calibration warnings
        if self.config.calibration_warning:
            self.warnings.append(self.config.calibration_warning)
            self.metadata['warnings'].append(self.config.calibration_warning)
        
        if not self.homography:
            warning = "No calibration - pitch coordinates and speed/distance metrics will be null"
            self.warnings.append(warning)
            self.metadata['warnings'].append(warning)
        
        # Initialize performance analyzer
        self.performance_analyzer = PerformanceAnalyzer(
            fps=fps,
            max_plausible_speed_mph=self.config.MAX_PLAUSIBLE_SPEED_MPH,
            speed_smoothing_window=self.config.SPEED_SMOOTHING_WINDOW,
            sustained_speed_window_s=self.config.SUSTAINED_SPEED_WINDOW_S,
            high_speed_threshold_mph=self.config.HIGH_SPEED_THRESHOLD_MPH,
            sprint_threshold_mph=self.config.SPRINT_THRESHOLD_MPH,
            speed_preset=self.config.SPEED_PRESET,
            zone_walk_kmh=self.config.ZONE_WALK_KMH,
            zone_jog_kmh=self.config.ZONE_JOG_KMH,
            zone_run_kmh=self.config.ZONE_RUN_KMH,
            zone_hsr_kmh=self.config.ZONE_HSR_KMH,
            accel_high_ms2=self.config.ACCEL_HIGH_MS2,
            accel_dwell_s=self.config.ACCEL_DWELL_S,
            heatmap_grid=self.config.HEATMAP_GRID,
            pitch_length_m=self.config.PITCH_LENGTH_M,
            pitch_width_m=self.config.PITCH_WIDTH_M,
            total_video_frames=total_frames
        )
        
        # Add speed preset to metadata
        self.metadata['speed_preset'] = self.config.SPEED_PRESET
        self.metadata['hsr_threshold_kmh'] = round(self.config.HIGH_SPEED_THRESHOLD_MPH * 1.60934, 1)
        self.metadata['sprint_threshold_kmh'] = round(self.config.SPRINT_THRESHOLD_MPH * 1.60934, 1)
        
        # Add speed zone edges to metadata
        self.metadata['zone_edges_kmh'] = {
            'walk': self.config.ZONE_WALK_KMH,
            'jog': self.config.ZONE_JOG_KMH,
            'run': self.config.ZONE_RUN_KMH,
            'hsr': self.config.ZONE_HSR_KMH
        }
        
        # Video writer for annotation
        writer = None
        if annotate_video:
            output_video_path = output_dir / f"{video_path.stem}_annotated.mp4"
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
        
        # Process frames
        frame_idx = 0
        pbar = tqdm(total=total_frames, desc="Processing frames")
        last_progress_pct = -1  # For backend progress tracking
        
        # Track positions for tracklet data (with frame indices for accurate timestamps)
        tracklet_positions: Dict[int, List[Tuple[float, float, int]]] = {}  # track_id -> [(x, y, frame), ...]
        tracklet_frame_ranges: Dict[int, Tuple[int, int]] = {}
        
        # Frame processing timing
        frame_times = []
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Backend progress tracking (emit "Processing frames: N%" for backend log parser)
            current_progress_pct = int((frame_idx / total_frames) * 100)
            if current_progress_pct > last_progress_pct:
                print(f"Processing frames: {current_progress_pct}%", flush=True)
                last_progress_pct = current_progress_pct
            
            frame_start_time = time.time()
            timestamp = frame_idx / fps
            
            # v2.0: Detect and track with enhanced tracker
            persons, _ = self.detector.detect_and_track(
                frame,
                frame_idx,
                imgsz=self.config.DEFAULT_IMGSZ
            )
            
            # v2.0: Detect ball with dedicated ball tracker
            ball_detection = self.ball_tracker.detect_ball(frame, frame_idx)
            ball = self.ball_tracker.track_ball(ball_detection)
            
            # Process each person
            for person in persons:
                track_id = person['track_id']
                bbox = person['bbox']
                
                # Team classification (collect colors during early frames)
                if self.team_classifier and frame_idx < self.team_classifier.early_frames_count:
                    self.team_classifier.add_observation(track_id, frame, bbox)
                
                # OCR for jersey number (sample every N frames)
                jersey_reading = None
                if self.ocr and frame_idx % sample_ocr_every_n_frames == 0:
                    jersey_reading = self.ocr.read_jersey_number(
                        frame,
                        bbox,
                        conf_threshold=self.config.OCR_CONF_THRESHOLD,
                        allowlist=self.config.OCR_ALLOWLIST,
                        check_legibility=self.config.OCR_USE_LEGIBILITY_FILTER
                    )
                    if jersey_reading:
                        # reading is (number, confidence, quality)
                        self.ocr.add_reading(track_id, jersey_reading, team=None)  # team assigned later
                
                # Transform to pitch coordinates
                pitch_coords = None
                if self.homography:
                    pitch_coords = self.homography.transform_foot_position(bbox)
                    if pitch_coords:
                        # v2.0: Add position with is_detected=True (real detection)
                        self.performance_analyzer.add_position(
                            track_id,
                            pitch_coords[0],
                            pitch_coords[1],
                            timestamp,
                            is_detected=True  # v2.0
                        )
                        
                        # Track for tracklet stitching
                        if track_id not in tracklet_positions:
                            tracklet_positions[track_id] = []
                            tracklet_frame_ranges[track_id] = (frame_idx, frame_idx)
                        tracklet_positions[track_id].append((pitch_coords[0], pitch_coords[1], frame_idx))
                        tracklet_frame_ranges[track_id] = (
                            tracklet_frame_ranges[track_id][0],
                            frame_idx
                        )
                
                # Store detection (team/role/player_uid will be filled later)
                detection = {
                    'frame': frame_idx,
                    'timestamp': round(timestamp, 3),
                    'track_id': track_id,
                    'player_uid': None,  # v2.0: Filled after stitching
                    'class': person['class_name'],
                    'bbox_x1': round(bbox[0], 2),
                    'bbox_y1': round(bbox[1], 2),
                    'bbox_x2': round(bbox[2], 2),
                    'bbox_y2': round(bbox[3], 2),
                    'confidence': round(person['confidence'], 3),
                    'pitch_x': round(pitch_coords[0], 2) if pitch_coords else None,
                    'pitch_y': round(pitch_coords[1], 2) if pitch_coords else None,
                    'is_detected': True,  # v2.0: Real detection
                    'jersey_number': jersey_reading[0] if jersey_reading else None,
                    'team': None,  # Filled after team classification
                    'role': 'player'  # Default, updated after classification
                }
                self.detections.append(detection)
            
            # Process ball (v2.0: with is_detected flag)
            if ball:
                bbox = ball['bbox']
                pitch_coords = None
                if self.homography:
                    pitch_coords = self.homography.transform_bbox_center(bbox)
                
                detection = {
                    'frame': frame_idx,
                    'timestamp': round(timestamp, 3),
                    'track_id': -1,  # Special ID for ball
                    'player_uid': None,  # N/A for ball
                    'class': 'ball',
                    'bbox_x1': round(bbox[0], 2),
                    'bbox_y1': round(bbox[1], 2),
                    'bbox_x2': round(bbox[2], 2),
                    'bbox_y2': round(bbox[3], 2),
                    'confidence': round(ball['confidence'], 3),
                    'pitch_x': round(pitch_coords[0], 2) if pitch_coords else None,
                    'pitch_y': round(pitch_coords[1], 2) if pitch_coords else None,
                    'is_detected': ball.get('is_detected', True),  # v2.0
                    'is_interpolated': ball.get('is_interpolated', False),  # v2.0: Ball only
                    'jersey_number': None,
                    'team': None,
                    'role': 'ball'
                }
                self.detections.append(detection)
            
            # Fit team classifier after early frames
            if self.team_classifier and not self.team_classifier.fitted:
                fit_at_frame = min(self.team_classifier.early_frames_count, total_frames - 1)
                if frame_idx >= fit_at_frame:
                    print(f"\nFitting team classifier at frame {frame_idx}...")
                    self.team_classifier.fit_teams()
                    self.team_classifier.assign_teams()
                    self.team_classifier.refine_with_voting(min_observations=5)
            
            # Annotate frame
            if writer:
                annotated = self._annotate_frame(frame, persons, ball)
                writer.write(annotated)
            
            frame_idx += 1
            frame_times.append(time.time() - frame_start_time)
            pbar.update(1)
        
        pbar.close()
        cap.release()
        if writer:
            writer.release()
        
        print(f"\nProcessed {frame_idx} frames")
        
        # Fit team classifier if not yet fitted
        if self.team_classifier and not self.team_classifier.fitted:
            print("Fitting team classifier on collected frames...")
            self.team_classifier.frame_count = frame_idx
            self.team_classifier.fit_teams()
            if self.team_classifier.fitted:
                self.team_classifier.assign_teams()
                self.team_classifier.refine_with_voting(min_observations=3)
        
        # Collect warnings from team classifier (bug fix: log once, not flooding console)
        if self.team_classifier and hasattr(self.team_classifier, 'warnings'):
            for warning in self.team_classifier.warnings:
                if warning not in self.warnings:
                    self.warnings.append(warning)
        
        # v2.0: Detect goalkeepers based on positions
        if self.team_classifier and self.team_classifier.fitted and tracklet_positions:
            print("Detecting goalkeepers...")
            self.team_classifier.detect_goalkeepers(
                tracklet_positions,
                self.config.PITCH_LENGTH_M
            )
        
        # Finalize team assignments
        if self.team_classifier and self.team_classifier.fitted:
            print("Finalizing team and role assignments...")
            for detection in self.detections:
                track_id = detection['track_id']
                if track_id > 0:  # Not ball
                    team = self.team_classifier.get_team(track_id)
                    role = self.team_classifier.get_role(track_id)
                    detection['team'] = team
                    detection['role'] = role if role != 'unknown' else 'player'
        
        # Finalize jersey numbers with weighted voting
        jersey_numbers = {}
        if self.ocr:
            print("Finalizing jersey numbers with confidence-weighted voting...")
            jersey_numbers = self.ocr.get_all_jersey_numbers()
            
            # Update detections with final jersey numbers
            for detection in self.detections:
                track_id = detection['track_id']
                if track_id in jersey_numbers and detection['jersey_number'] is None:
                    detection['jersey_number'] = jersey_numbers[track_id]
        
        # v2.0: Tracklet stitching to create stable player_uid
        if self.tracklet_stitcher and tracklet_positions:
            print("Processing frames: 95%", flush=True)  # Backend progress (stitching stage)
            print("Stitching tracklets into stable player IDs...")
            
            # Add tracklets to stitcher
            for track_id in tracklet_positions.keys():
                team = self.team_classifier.get_team(track_id) if self.team_classifier else None
                jersey = jersey_numbers.get(track_id) if self.ocr else None
                
                # Compute appearance vector (simple: median LAB color from team classifier)
                appearance = None
                if self.team_classifier and track_id in self.team_classifier.track_median_colors:
                    appearance = self.team_classifier.track_median_colors[track_id]
                
                # Get positions with actual frame-based timestamps
                # Bug fix: positions now include frame indices for accurate timestamps
                positions_with_time = [
                    (x, y, frame / fps) 
                    for x, y, frame in tracklet_positions[track_id]
                ]
                
                self.tracklet_stitcher.add_tracklet(
                    track_id=track_id,
                    team=team,
                    jersey_number=jersey,
                    appearance_vector=appearance,
                    positions=positions_with_time,
                    frame_range=tracklet_frame_ranges[track_id]
                )
            
            # Stitch
            track_to_player = self.tracklet_stitcher.stitch_tracklets()
            
            # Sanity check: warn if stitching collapsed too much
            num_uids = len(set(track_to_player.values()))
            num_tracks = len(track_to_player)
            if num_uids < num_tracks * 0.3:  # UIDs < 30% of tracks
                warning = f"Stitching: {num_uids} player UIDs from {num_tracks} tracks (potential over-stitching)"
                print(f"Warning: {warning}")
                self.warnings.append(warning)
            
            # Update detections with player_uid
            for detection in self.detections:
                track_id = detection['track_id']
                if track_id > 0:  # Not ball
                    player_uid = track_to_player.get(track_id)
                    detection['player_uid'] = player_uid
            
            # Check coverage: how many player detections got a player_uid?
            player_detections = [d for d in self.detections if d['track_id'] > 0]
            detections_with_uid = [d for d in player_detections if d['player_uid'] is not None]
            coverage_pct = 100.0 * len(detections_with_uid) / len(player_detections) if player_detections else 0.0
            if coverage_pct < 50.0:
                warning = f"Stitching: only {len(detections_with_uid)}/{len(player_detections)} player detections ({coverage_pct:.1f}%) assigned a player_uid"
                print(f"Warning: {warning}")
                self.warnings.append(warning)
        
        # Calculate player statistics (per player_uid if stitching, otherwise per track_id)
        print("Calculating player statistics...")
        player_stats = self.performance_analyzer.analyze_all_players()
        
        # Add jersey numbers, team, role, and v2.0 fields to stats
        if self.ocr:
            jersey_numbers = self.ocr.get_all_jersey_numbers()
        
        # Group stats by player_uid if stitching enabled
        if self.tracklet_stitcher:
            print("Aggregating stats per player_uid...")
            player_uid_stats = self._aggregate_stats_by_player_uid(player_stats, jersey_numbers)
            filtered_stats = player_uid_stats
        else:
            # No stitching: use track_id as player_uid
            filtered_stats = []
            for stat in player_stats:
                track_id = stat['track_id']
                
                # Add v2.0 fields
                stat['player_uid'] = track_id  # No stitching: uid = track_id
                stat['contributing_track_ids'] = [track_id]  # v2.0
                
                if self.ocr:
                    stat['jersey_number'] = jersey_numbers.get(track_id)
                else:
                    stat['jersey_number'] = None
                
                if self.team_classifier and self.team_classifier.fitted:
                    team = self.team_classifier.get_team(track_id)
                    role = self.team_classifier.get_role(track_id)
                    stat['team'] = team
                    stat['role'] = role if role != 'unknown' else 'player'
                    
                    # Exclude referees
                    if stat['role'] == 'referee':
                        continue
                else:
                    stat['team'] = None
                    stat['role'] = 'player'
                
                filtered_stats.append(stat)
        
        # Update metadata
        end_time = time.time()
        end_timestamp = datetime.now().isoformat()
        runtime_s = end_time - start_time
        
        unique_tracks = len(set(d['track_id'] for d in self.detections if d['track_id'] > 0))
        player_count = len(filtered_stats)
        
        # Add ball gating statistics
        ball_gated_frames = self.ball_tracker.ball_gated_count if hasattr(self.ball_tracker, 'ball_gated_count') else 0
        if ball_gated_frames > 0:
            print(f"Ball speed gating: rejected {ball_gated_frames} detections")
        
        # Frame timing statistics
        avg_frame_time = np.mean(frame_times) if frame_times else 0.0
        print(f"Average per-frame processing time: {avg_frame_time*1000:.1f} ms")
        
        self.metadata.update({
            'end_timestamp': end_timestamp,
            'runtime_s': round(runtime_s, 2),
            'avg_frame_time_ms': round(avg_frame_time * 1000, 2),
            'unique_tracks': unique_tracks,
            'player_count': player_count,
            'ball_gated_frames': ball_gated_frames,
            'warnings': self.warnings
        })
        
        # Target tracking mode
        target_frames = None
        target_stats = None
        
        if target_spec:
            print("Processing frames: 90%", flush=True)  # Backend progress
            print("\n=== Target Tracking Mode ===")
            
            from cv.target_tracking import TargetTracker
            
            # Create tracker
            target_tracker = TargetTracker(
                max_speed_ms=self.config.MAX_PLAYER_SPEED_MS,
                fps=fps,
                appearance_threshold=0.7,
                color_similarity_threshold=0.6,
                motion_gate_multiplier=1.5,
                occlusion_max_frames=30
            )
            
            # Build maps for resolution
            player_uid_map = {}
            team_map = {}
            jersey_map = {}
            appearance_map = {}
            
            if self.tracklet_stitcher:
                for track_id in self.tracklet_stitcher.tracklets.keys():
                    player_uid = self.tracklet_stitcher.get_player_uid(track_id)
                    if player_uid:
                        player_uid_map[track_id] = player_uid
            
            if self.team_classifier and self.team_classifier.fitted:
                for track_id in self.team_classifier.track_votes.keys():
                    team = self.team_classifier.get_team(track_id)
                    if team is not None:
                        team_map[track_id] = team
            
            if self.ocr:
                jersey_numbers = self.ocr.get_all_jersey_numbers()
                for track_id, jersey in jersey_numbers.items():
                    if jersey:
                        jersey_map[track_id] = jersey
            
            if self.team_classifier:
                for track_id, color in self.team_classifier.track_median_colors.items():
                    appearance_map[track_id] = color
            
            # Resolve target
            print("Resolving target specification...")
            success, error = target_tracker.resolve_target(
                target_spec,
                self.detections,
                player_uid_map=player_uid_map,
                team_map=team_map,
                jersey_map=jersey_map,
                appearance_map=appearance_map
            )
            
            if not success:
                print(f"Error: Failed to resolve target - {error}")
                self.warnings.append(f"Target tracking failed: {error}")
                self.metadata['warnings'].append(f"Target tracking failed: {error}")
            else:
                print(f"Target resolved: player_uid={target_tracker.target_player_uid}, "
                      f"jersey={target_tracker.target_jersey}, team={target_tracker.target_team}")
                
                # Track target through all frames
                print("Tracking target through video...")
                target_frames = target_tracker.track_target(
                    self.detections,
                    fps,
                    team_map=team_map,
                    jersey_map=jersey_map,
                    appearance_map=appearance_map
                )
                
                # Get statistics
                target_stats_dict = target_tracker.get_statistics(total_frames, fps)
                
                # Find player stats for target
                target_player_stats = None
                for stat in filtered_stats:
                    if stat.get('player_uid') == target_tracker.target_player_uid:
                        target_player_stats = stat
                        break
                
                if target_player_stats:
                    # Merge with tracking stats
                    target_stats = {**target_player_stats, **target_stats_dict}
                else:
                    target_stats = target_stats_dict
                
                print(f"Target tracked: {target_stats['tracked_frames']}/{total_frames} frames "
                      f"({target_stats['tracked_pct']:.1f}%), "
                      f"{target_stats['reacquisition_count']} re-acquisitions")
                
                # Add target section to metadata
                self.metadata['target'] = {
                    'spec': target_spec.to_dict(),
                    'resolved_player_uid': target_tracker.target_player_uid,
                    'resolved_track_ids': target_tracker.target_track_ids,
                    'jersey': target_tracker.target_jersey,
                    'team': target_tracker.target_team,
                    'tracked_pct': target_stats['tracked_pct'],
                    'reacquisition_count': target_stats['reacquisition_count'],
                    'lost_segments_count': len(target_stats['lost_segments'])
                }
                
                if len(target_tracker.warnings) > 0:
                    self.metadata['target']['warnings'] = target_tracker.warnings
        
        # Save outputs
        self._save_outputs(
            output_dir, 
            filtered_stats,
            target_frames=target_frames,
            target_stats=target_stats
        )
        
        # Render replay if requested
        if render_replay and target_frames:
            print("Processing frames: 95%", flush=True)  # Backend progress
            print("\nRendering replay video...")
            
            from cv.replay_renderer import ReplayRenderer
            
            replay_path = output_dir / "replay.mp4"
            
            renderer = ReplayRenderer(
                video_path=str(video_path),
                target_frames=target_frames,
                output_path=str(replay_path),
                fps=fps,
                target_jersey=target_tracker.target_jersey if target_spec else None,
                max_height=replay_max_height,
                show_speed=self.homography is not None,
                trail_length=15,
                preserve_audio=True
            )
            
            def progress_callback(pct):
                # Map 0-100 to 95-100 for backend progress
                backend_pct = 95 + int(pct * 0.05)
                print(f"Processing frames: {backend_pct}%", flush=True)
            
            renderer.render(progress_callback=progress_callback)
            
            print(f"Replay video saved: {replay_path}")
            
            # Verify H.264 encoding
            self._verify_replay_codec(replay_path)
        
        print(f"\nResults saved to: {output_dir}")
        if annotate_video:
            print(f"Annotated video: {output_video_path}")
        if target_frames:
            print(f"Target track: {output_dir / 'target_track.json'}")
            print(f"Target stats: {output_dir / 'target_stats.json'}")
        if render_replay and target_frames:
            print(f"Replay video: {output_dir / 'replay.mp4'}")
        print(f"Runtime: {runtime_s:.1f}s")
    
    def _aggregate_stats_by_player_uid(
        self,
        track_stats: List[Dict],
        jersey_numbers: Dict[int, Optional[int]]
    ) -> List[Dict]:
        """Aggregate per-track stats into per-player_uid stats.
        
        Args:
            track_stats: List of stats per track_id
            jersey_numbers: Dict of track_id -> jersey_number
        
        Returns:
            List of aggregated stats per player_uid
        """
        from collections import defaultdict
        
        # Group tracks by player_uid
        uid_to_tracks: Dict[int, List[int]] = defaultdict(list)
        uid_to_stats: Dict[int, List[Dict]] = defaultdict(list)
        
        for stat in track_stats:
            track_id = stat['track_id']
            player_uid = self.tracklet_stitcher.get_player_uid(track_id)
            
            if player_uid is not None:
                uid_to_tracks[player_uid].append(track_id)
                uid_to_stats[player_uid].append(stat)
        
        # Aggregate stats
        aggregated = []
        
        for player_uid, track_ids in uid_to_tracks.items():
            stats_list = uid_to_stats[player_uid]
            
            # Sum numeric fields
            total_distance = sum(s.get('distance_km', 0) or 0 for s in stats_list)
            total_visible_mins = sum(s.get('visible_minutes', 0) or 0 for s in stats_list)
            total_hsr_dist = sum(s.get('high_speed_distance_km', 0) or 0 for s in stats_list)
            total_sprint_dist = sum(s.get('sprint_distance_km', 0) or 0 for s in stats_list)
            total_hsr_count = sum(s.get('hsr_count', 0) or 0 for s in stats_list)
            total_sprint_count = sum(s.get('sprint_count', 0) or 0 for s in stats_list)
            total_detected_frames = sum(s.get('detected_frames', 0) or 0 for s in stats_list)
            total_frames = sum(s.get('total_frames', 0) or 0 for s in stats_list)
            
            # Max/average fields
            top_speed_mph = max((s.get('top_speed_mph', 0) or 0 for s in stats_list), default=0)
            
            # Team and role (from first track, should all agree after stitching)
            team = stats_list[0].get('team')
            role = stats_list[0].get('role', 'player')
            
            # Jersey number (majority across tracks)
            jersey_votes = [jersey_numbers.get(tid) for tid in track_ids if jersey_numbers.get(tid) is not None]
            jersey_number = max(set(jersey_votes), key=jersey_votes.count) if jersey_votes else None
            
            # Exclude referees
            if role == 'referee':
                continue
            
            aggregated_stat = {
                'player_uid': player_uid,  # v2.0
                'contributing_track_ids': track_ids,  # v2.0
                'track_id': track_ids[0],  # Legacy compatibility (first track)
                'jersey_number': jersey_number,
                'team': team,
                'role': role,
                'top_speed_mph': round(top_speed_mph, 2),
                'top_speed_kmh': round(top_speed_mph * 1.60934, 2),
                'distance_km': round(total_distance, 2),
                'visible_minutes': round(total_visible_mins, 2),
                'high_speed_distance_km': round(total_hsr_dist, 2),
                'sprint_distance_km': round(total_sprint_dist, 2),
                'hsr_count': total_hsr_count,
                'sprint_count': total_sprint_count,
                'hi_efforts_count': total_hsr_count + total_sprint_count,
                'detected_frames': total_detected_frames,  # v2.0
                'total_frames': total_frames,  # v2.0
                # Other fields would need averaging or re-computation
                # For simplicity, including main metrics
            }
            
            aggregated.append(aggregated_stat)
        
        return aggregated
    
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
            
            # Color based on detected vs interpolated
            color = (0, 0, 255) if ball.get('is_detected', True) else (0, 165, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            
            label = "Ball" + (" (interp)" if ball.get('is_interpolated', False) else "")
            cv2.putText(
                annotated,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )
        
        return annotated
    
    def _verify_replay_codec(self, video_path: Path):
        """Verify replay video is H.264 encoded properly."""
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=codec_name,pix_fmt',
                 '-of', 'default=noprint_wrappers=1', str(video_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if 'codec_name=h264' not in result.stdout:
                self.warnings.append(f"Warning: Replay video may not be H.264 encoded")
            
            if 'pix_fmt=yuv420p' not in result.stdout:
                self.warnings.append(f"Warning: Replay video may not use yuv420p pixel format")
        
        except Exception as e:
            # ffprobe not available, skip verification
            pass
    
    def _save_outputs(
        self, 
        output_dir: Path, 
        player_stats: List[Dict],
        target_frames: Optional[List[Dict]] = None,
        target_stats: Optional[Dict] = None
    ):
        """Save detection and statistics outputs."""
        # Convert numpy types to native Python types for JSON serialization
        def convert_numpy(obj):
            """Recursively convert numpy types to native Python types."""
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_numpy(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy(item) for item in obj]
            else:
                return obj
        
        # Convert all outputs
        self.detections = convert_numpy(self.detections)
        player_stats = convert_numpy(player_stats)
        self.metadata = convert_numpy(self.metadata)
        
        # If no calibration, nullify all physical (not temporal) metrics
        # Bug fix 1c: Keep temporal metrics (visible_minutes, coverage_pct, minutes_played)
        if not self.homography:
            for stat in player_stats:
                stat['top_speed_mph'] = None
                stat['top_speed_kmh'] = None
                stat['distance_km'] = None
                # visible_minutes, minutes_played, coverage_pct are temporal → keep them
                stat['distance_per_min_m'] = None if 'distance_per_min_m' in stat else None
                stat['avg_pitch_x'] = None if 'avg_pitch_x' in stat else None
                stat['avg_pitch_y'] = None if 'avg_pitch_y' in stat else None
                stat['high_speed_distance_km'] = None
                stat['sprint_distance_km'] = None
                stat['hsr_count'] = None
                stat['sprint_count'] = None
                stat['hi_efforts_count'] = None
                if 'zone_walk_km' in stat:
                    stat['zone_walk_km'] = None
                    stat['zone_jog_km'] = None
                    stat['zone_run_km'] = None
                    stat['zone_hsr_km'] = None
                    stat['zone_sprint_km'] = None
                if 'accel_count_high' in stat:
                    stat['accel_count_high'] = None
                    stat['decel_count_high'] = None
                # coverage_pct is temporal → keep it
        
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
        
        # Save heatmaps as JSON (always write, empty if no calibration for backend compatibility)
        heatmaps_json_path = output_dir / "heatmaps.json"
        if self.homography:
            heatmaps = self.performance_analyzer.get_all_heatmaps()
            with open(heatmaps_json_path, 'w') as f:
                json.dump(heatmaps, f, indent=2)
            print(f"Saved heatmaps JSON: {heatmaps_json_path}")
        else:
            # Empty heatmaps for backend compatibility
            with open(heatmaps_json_path, 'w') as f:
                json.dump({}, f, indent=2)
            print(f"Saved heatmaps JSON (empty, no calibration): {heatmaps_json_path}")
        
        # Save metadata
        meta_json_path = output_dir / "meta.json"
        with open(meta_json_path, 'w') as f:
            json.dump(self.metadata, f, indent=2)
        print(f"Saved metadata JSON: {meta_json_path}")
        
        # Save target tracking outputs (if in target mode)
        if target_frames:
            # Get video info from metadata
            video_info = {
                'width': self.metadata['width'],
                'height': self.metadata['height'],
                'fps': self.metadata['fps'],
                'frame_count': self.metadata['frame_count']
            }
            
            # Build target track output
            target_track_output = {
                'schema_version': '1.0',
                'video': video_info,
                'target': {
                    'player_uid': self.metadata['target']['resolved_player_uid'],
                    'track_ids': self.metadata['target']['resolved_track_ids'],
                    'jersey': self.metadata['target']['jersey'],
                    'team': self.metadata['target']['team'],
                    'spec': self.metadata['target']['spec']
                },
                'frames': target_frames
            }
            
            # Save target_track.json
            target_track_path = output_dir / "target_track.json"
            with open(target_track_path, 'w') as f:
                json.dump(target_track_output, f, indent=2)
            print(f"Saved target track JSON: {target_track_path}")
        
        if target_stats:
            # Save target_stats.json
            target_stats_path = output_dir / "target_stats.json"
            with open(target_stats_path, 'w') as f:
                json.dump(target_stats, f, indent=2)
            print(f"Saved target stats JSON: {target_stats_path}")
