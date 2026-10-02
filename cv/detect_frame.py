#!/usr/bin/env python3
"""
Detect players in a single frame and return candidates with team/jersey info.

Usage:
    python -m cv.detect_frame --video <abs> --t <seconds> --out <abs dir> --device <d> [--model m]

Outputs:
    <out>/frame.jpg - Decoded frame at timestamp t
    <out>/candidates.json - Detected player candidates with bbox, team, jersey
"""

import argparse
import sys
import json
import cv2
import numpy as np
from pathlib import Path

# Support both `python -m cv.detect_frame` and `python cv/detect_frame.py`
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from cv.tracking import EnhancedTracker
from cv.team_classifier_enhanced import TeamClassifierEnhanced
from cv.ocr_enhanced import EnhancedJerseyReader, LegibilityFilter
from cv.config import Config


def detect_frame(
    video_path: str,
    timestamp_s: float,
    output_dir: str,
    device: str = 'auto',
    model_path: str = 'yolov8x.pt'
):
    """Detect players in a single frame.
    
    Args:
        video_path: Absolute path to video file
        timestamp_s: Timestamp in seconds
        output_dir: Output directory
        device: Device for inference
        model_path: Path to YOLO model
    
    Returns:
        Exit code (0 = success, 1 = error)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video: {video_path}", file=sys.stderr)
        return 1
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Compute frame number
    target_frame = int(timestamp_s * fps)
    
    if target_frame >= total_frames:
        print(f"Error: Timestamp {timestamp_s}s (frame {target_frame}) exceeds video length ({total_frames} frames)", 
              file=sys.stderr)
        cap.release()
        return 1
    
    # Seek to frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print(f"Error: Cannot read frame at timestamp {timestamp_s}s", file=sys.stderr)
        return 1
    
    # Save frame as JPEG
    frame_path = output_dir / "frame.jpg"
    cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    # Initialize detector
    print(f"Detecting players at t={timestamp_s}s (frame {target_frame})...")
    tracker = EnhancedTracker(
        model_path=model_path,
        person_conf=0.3,
        device=device
    )
    
    # Detect players (disable tracking, just detect)
    persons, _ = tracker.detect_and_track(frame, target_frame, imgsz=640)
    
    # Collect frames around target for team/jersey estimation (±15 frames, ~0.5s window)
    window_size = 15
    window_frames = []
    
    cap = cv2.VideoCapture(video_path)
    for offset in range(-window_size, window_size + 1):
        frame_idx = target_frame + offset
        if 0 <= frame_idx < total_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, f = cap.read()
            if ret:
                window_frames.append((frame_idx, f))
    cap.release()
    
    # Initialize team classifier and OCR for the window
    team_classifier = None
    ocr = None
    
    if window_frames:
        print(f"Estimating team/jersey from {len(window_frames)}-frame window...")
        
        # Team classification
        team_classifier = TeamClassifierEnhanced(n_teams=2, early_frames_count=len(window_frames))
        
        # Detect and track in window
        for frame_idx, f in window_frames:
            window_persons, _ = tracker.detect_and_track(f, frame_idx, imgsz=640)
            
            for person in window_persons:
                track_id = person['track_id']
                bbox = person['bbox']
                team_classifier.add_observation(track_id, f, bbox)
        
        # Fit team classifier
        team_classifier.fit_teams()
        if team_classifier.fitted:
            team_classifier.assign_teams()
            team_classifier.refine_with_voting(min_observations=2)
        
        # OCR for jersey numbers
        try:
            config = Config(device=device)
            ocr = EnhancedJerseyReader(
                languages=['en'],
                gpu=device in ['cuda', 'auto'],
                backend=config.OCR_BACKEND,
                legibility_filter=LegibilityFilter()
            )
            
            # Sample OCR on window frames
            for i, (frame_idx, f) in enumerate(window_frames):
                if i % 3 == 0:  # Sample every 3rd frame
                    window_persons, _ = tracker.detect_and_track(f, frame_idx, imgsz=640)
                    for person in window_persons:
                        track_id = person['track_id']
                        bbox = person['bbox']
                        reading = ocr.read_jersey_number(f, bbox, conf_threshold=0.5)
                        if reading:
                            team = team_classifier.get_team(track_id) if team_classifier else None
                            ocr.add_reading(track_id, reading, team=team)
        
        except Exception as e:
            print(f"Warning: OCR initialization failed: {e}", file=sys.stderr)
    
    # Get goalkeeper roles if available
    goalkeeper_track_ids = set()
    if team_classifier and team_classifier.fitted:
        # Simple heuristic: check if any track is marked as goalkeeper
        for track_id in team_classifier.track_votes.keys():
            role = team_classifier.get_role(track_id)
            if role == 'goalkeeper':
                goalkeeper_track_ids.add(track_id)
    
    # Get final jersey numbers
    jersey_numbers = ocr.get_all_jersey_numbers() if ocr else {}
    
    # Build candidates list
    candidates = []
    
    for person in persons:
        track_id = person['track_id']
        bbox = person['bbox']
        confidence = person['confidence']
        
        # Get team (map 0/1 to A/B)
        team_int = team_classifier.get_team(track_id) if team_classifier and team_classifier.fitted else None
        team_label = None
        if team_int == 0:
            team_label = "A"
        elif team_int == 1:
            team_label = "B"
        
        # Get jersey
        jersey = jersey_numbers.get(track_id)
        
        # Determine class
        if track_id in goalkeeper_track_ids:
            cls = "goalkeeper"
        elif team_classifier and team_classifier.fitted:
            role = team_classifier.get_role(track_id)
            if role == 'referee':
                cls = "referee"
            else:
                cls = "player"
        else:
            cls = "player"
        
        candidates.append({
            'bbox': [round(bbox[0], 2), round(bbox[1], 2), round(bbox[2], 2), round(bbox[3], 2)],
            'confidence': round(confidence, 3),
            'team': team_label,
            'jersey_number': jersey,
            'class': cls
        })
    
    # Build output JSON
    output = {
        'frame': target_frame,
        't': round(timestamp_s, 3),
        'width': width,
        'height': height,
        'candidates': candidates
    }
    
    # Save candidates.json
    candidates_path = output_dir / "candidates.json"
    with open(candidates_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Detected {len(candidates)} candidates")
    print(f"Saved: {frame_path}")
    print(f"Saved: {candidates_path}")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Detect players in a single frame with team/jersey info"
    )
    
    parser.add_argument(
        '--video',
        type=str,
        required=True,
        help='Absolute path to video file'
    )
    
    parser.add_argument(
        '--t',
        type=float,
        required=True,
        help='Timestamp in seconds'
    )
    
    parser.add_argument(
        '--out',
        type=str,
        required=True,
        help='Output directory (absolute path)'
    )
    
    parser.add_argument(
        '--device',
        type=str,
        default='auto',
        choices=['auto', 'cuda', 'mps', 'cpu'],
        help='Device for inference (default: auto)'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='yolov8x.pt',
        help='Path to YOLO model weights (default: yolov8x.pt)'
    )
    
    args = parser.parse_args()
    
    # Validate video exists
    if not Path(args.video).exists():
        print(f"Error: Video file not found: {args.video}", file=sys.stderr)
        sys.exit(1)
    
    # Run detection
    exit_code = detect_frame(
        video_path=args.video,
        timestamp_s=args.t,
        output_dir=args.out,
        device=args.device,
        model_path=args.model
    )
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
