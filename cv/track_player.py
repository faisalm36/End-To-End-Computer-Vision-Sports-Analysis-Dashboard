#!/usr/bin/env python3
"""
Track a specific player through the entire video with re-acquisition and replay rendering.

Usage:
    python -m cv.track_player --video <abs> --out <abs dir> --device <d> \
           (--frame N --bbox x1,y1,x2,y2 | --jersey N --team A|B) \
           [--model m] [--calibration path]

Outputs:
    <out>/track.json - Frame-by-frame tracking with status
    <out>/replay.mp4 - H.264 annotated video
    <out>/meta.json - Pipeline metadata and warnings
    <out>/target_stats.json - Per-player metrics (additive)
"""

import argparse
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Support both `python -m cv.track_player` and `python cv/track_player.py`
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from cv.config import Config
from cv.pipeline import SoccerAnalyticsPipeline
from cv.target_tracking import TargetSpec, TargetTracker
from cv.replay_renderer import ReplayRenderer


def track_player(
    video_path: str,
    output_dir: str,
    device: str,
    target_frame: int = None,
    target_bbox: tuple = None,
    target_jersey: int = None,
    target_team: str = None,
    model_path: str = 'yolov8x.pt',
    calibration_path: str = None
):
    """Track a specific player through video.
    
    Args:
        video_path: Absolute path to video
        output_dir: Output directory
        device: Device for inference
        target_frame: Target frame number (for bbox mode)
        target_bbox: Target bbox (x1,y1,x2,y2)
        target_jersey: Target jersey number
        target_team: Target team ('A' or 'B')
        model_path: Path to YOLO model
        calibration_path: Path to calibration file
    
    Returns:
        Exit code (0 = success, 1 = error, 3 = target not found/ambiguous)
    """
    start_time = time.time()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build target spec
    spec = None
    if target_frame is not None and target_bbox is not None:
        spec = TargetSpec(target_frame=target_frame, target_bbox=target_bbox)
    elif target_jersey is not None:
        # Map team label A/B to internal 0/1
        team_int = None
        if target_team == 'A':
            team_int = 0
        elif target_team == 'B':
            team_int = 1
        spec = TargetSpec(target_jersey=target_jersey, target_team=team_int)
    else:
        print("Error: Must specify either (--frame + --bbox) or --jersey", file=sys.stderr)
        return 1
    
    # Load config
    config = Config(
        calibration_path=calibration_path,
        use_default_if_missing=False,
        device=device
    )
    
    # Initialize pipeline
    print("Initializing pipeline...")
    pipeline = SoccerAnalyticsPipeline(
        config=config,
        model_path=model_path,
        device=device,
        enable_ocr=True,
        tracker='botsort'
    )
    
    # Process video with progress tracking
    print("Processing frames: 0%", flush=True)
    
    try:
        result = pipeline.process_video_for_target_tracking(
            video_path=video_path,
            output_dir=str(output_dir),
            target_spec=spec,
            progress_callback=lambda pct: print(f"Processing frames: {pct}%", flush=True)
        )
        
        if not result['success']:
            # Target resolution failed
            error_type = result.get('error_type', 'target_resolution_failed')
            error_message = result.get('error_message', 'Unknown error')
            
            # Write meta.json with error
            meta = {
                'pipeline_version': '2.0.0',
                'tracker': 'botsort',
                'coverage_pct': 0.0,
                'lost_frames': 0,
                'warnings': [error_message]
            }
            
            if error_type == 'target_not_found':
                meta['error'] = 'target_not_found'
                if result.get('candidates'):
                    meta['candidates'] = result['candidates']
                
                meta_path = output_dir / "meta.json"
                with open(meta_path, 'w') as f:
                    json.dump(meta, f, indent=2)
                
                print(f"Error: {error_message}", file=sys.stderr)
                return 3  # Exit code 3 for target not found/ambiguous
            else:
                meta_path = output_dir / "meta.json"
                with open(meta_path, 'w') as f:
                    json.dump(meta, f, indent=2)
                
                print(f"Error: {error_message}", file=sys.stderr)
                return 1
        
        print("Processing frames: 100%", flush=True)
        print(f"\n✓ Tracking completed successfully!")
        print(f"Runtime: {time.time() - start_time:.1f}s")
        
        return 0
    
    except Exception as e:
        print(f"Error during processing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Track a specific player through video with re-acquisition"
    )
    
    parser.add_argument(
        '--video',
        type=str,
        required=True,
        help='Absolute path to video file'
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
        required=True,
        choices=['auto', 'cuda', 'mps', 'cpu'],
        help='Device for inference'
    )
    
    # Target specification: frame + bbox
    parser.add_argument(
        '--frame',
        type=int,
        default=None,
        help='Target frame number (for --bbox mode)'
    )
    
    parser.add_argument(
        '--bbox',
        type=str,
        default=None,
        help='Target bbox as "x1,y1,x2,y2" (requires --frame)'
    )
    
    # Target specification: jersey + team
    parser.add_argument(
        '--jersey',
        type=int,
        default=None,
        help='Target jersey number'
    )
    
    parser.add_argument(
        '--team',
        type=str,
        default=None,
        choices=['A', 'B'],
        help='Target team (A or B, required with --jersey)'
    )
    
    # Optional args
    parser.add_argument(
        '--model',
        type=str,
        default='yolov8x.pt',
        help='Path to YOLO model weights (default: yolov8x.pt)'
    )
    
    parser.add_argument(
        '--calibration',
        type=str,
        default=None,
        help='Path to calibration file (optional)'
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if not Path(args.video).exists():
        print(f"Error: Video file not found: {args.video}", file=sys.stderr)
        sys.exit(1)
    
    # Validate target specification
    if args.frame is not None and args.bbox is None:
        print("Error: --frame requires --bbox", file=sys.stderr)
        sys.exit(1)
    
    if args.bbox is not None and args.frame is None:
        print("Error: --bbox requires --frame", file=sys.stderr)
        sys.exit(1)
    
    if args.jersey is None and args.frame is None:
        print("Error: Must specify either (--frame + --bbox) or --jersey", file=sys.stderr)
        sys.exit(1)
    
    if args.jersey is not None and args.frame is not None:
        print("Error: Cannot specify both (--frame + --bbox) and --jersey", file=sys.stderr)
        sys.exit(1)
    
    if args.jersey is not None and args.team is None:
        print("Error: --jersey requires --team", file=sys.stderr)
        sys.exit(1)
    
    # Parse bbox if provided
    target_bbox = None
    if args.bbox:
        try:
            parts = [float(x) for x in args.bbox.split(',')]
            if len(parts) != 4:
                raise ValueError("bbox must be x1,y1,x2,y2")
            target_bbox = tuple(parts)
        except ValueError as e:
            print(f"Error parsing --bbox: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Run tracking
    exit_code = track_player(
        video_path=args.video,
        output_dir=args.out,
        device=args.device,
        target_frame=args.frame,
        target_bbox=target_bbox,
        target_jersey=args.jersey,
        target_team=args.team,
        model_path=args.model,
        calibration_path=args.calibration
    )
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
