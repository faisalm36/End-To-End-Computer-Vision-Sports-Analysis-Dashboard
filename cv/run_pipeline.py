#!/usr/bin/env python3
"""CLI entry point for soccer analytics pipeline."""

import argparse
import sys
from pathlib import Path

# Support both `python -m cv.run_pipeline` and `python cv/run_pipeline.py`
if __name__ == '__main__' and __package__ is None:
    # Running as script: add parent dir to path
    sys.path.insert(0, str(Path(__file__).parent.parent))

from cv.config import Config
from cv.pipeline import SoccerAnalyticsPipeline


def main():
    parser = argparse.ArgumentParser(
        description="Soccer video analytics pipeline - detection, tracking, OCR, and performance metrics"
    )
    
    parser.add_argument(
        '--video',
        type=str,
        required=True,
        help='Path to input video file'
    )
    
    parser.add_argument(
        '--out',
        type=str,
        required=True,
        help='Output directory for results'
    )
    
    parser.add_argument(
        '--calibration',
        type=str,
        default=None,
        help='Path to calibration file (JSON/YAML with pitch-to-image correspondences)'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='yolov8x.pt',
        help='Path to YOLO model weights (default: yolov8x.pt - pretrained COCO)'
    )
    
    parser.add_argument(
        '--device',
        type=str,
        default='auto',
        choices=['auto', 'cuda', 'mps', 'cpu'],
        help='Device for inference (default: auto-detect)'
    )
    
    # v2.0: Tracker options
    parser.add_argument(
        '--tracker',
        type=str,
        default='botsort',
        choices=['botsort', 'bytetrack'],
        help='Tracker type: botsort (default, with GMC) or bytetrack'
    )
    
    # v2.0: Ball tracking options
    parser.add_argument(
        '--ball-model',
        type=str,
        default=None,
        help='Path to fine-tuned ball detection model (optional, uses main model if not specified)'
    )
    
    # v2.0: Kit and roster options
    parser.add_argument(
        '--kits',
        type=str,
        default=None,
        help='Kit colours: JSON file (kits.json) or inline "#FF0000,#0000FF" (team_a,team_b hex RGB)'
    )
    
    parser.add_argument(
        '--roster',
        type=str,
        default=None,
        help='Roster: JSON file (roster.json) or inline "1,2,3,10,11" (comma-separated jersey numbers)'
    )
    
    parser.add_argument(
        '--annotate',
        action='store_true',
        help='Generate annotated output video'
    )
    
    parser.add_argument(
        '--no-ocr',
        action='store_true',
        help='Disable jersey number OCR'
    )
    
    parser.add_argument(
        '--ocr-sample-rate',
        type=int,
        default=10,
        help='Run OCR every N frames (default: 10)'
    )
    
    # Target tracking options
    parser.add_argument(
        '--target-frame',
        type=int,
        default=None,
        help='Target frame number (for --target-bbox or --target-point)'
    )
    
    parser.add_argument(
        '--target-bbox',
        type=str,
        default=None,
        help='Target bbox as "x1,y1,x2,y2" (requires --target-frame)'
    )
    
    parser.add_argument(
        '--target-point',
        type=str,
        default=None,
        help='Target click point as "x,y" (requires --target-frame)'
    )
    
    parser.add_argument(
        '--target-jersey',
        type=int,
        default=None,
        help='Target jersey number'
    )
    
    parser.add_argument(
        '--target-team',
        type=int,
        default=None,
        choices=[0, 1],
        help='Target team (0 or 1, optional with --target-jersey)'
    )
    
    parser.add_argument(
        '--target',
        type=str,
        default=None,
        help='Target specification JSON file (alternative to individual flags)'
    )
    
    parser.add_argument(
        '--render-replay',
        action='store_true',
        help='Render annotated replay video (implied in target mode unless --no-replay)'
    )
    
    parser.add_argument(
        '--no-replay',
        action='store_true',
        help='Disable replay rendering in target mode'
    )
    
    parser.add_argument(
        '--replay-max-height',
        type=int,
        default=None,
        help='Maximum height for replay video (downscaling, optional)'
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}", file=sys.stderr)
        sys.exit(1)
    
    # Parse target specification
    target_spec = None
    target_mode = False
    
    if args.target:
        # Load from file
        from cv.target_tracking import load_target_spec_from_file
        try:
            target_spec = load_target_spec_from_file(args.target)
            target_mode = True
        except Exception as e:
            print(f"Error loading target file: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif args.target_frame is not None and (args.target_bbox or args.target_point):
        # Build from frame + bbox/point
        from cv.target_tracking import TargetSpec
        
        if args.target_bbox:
            try:
                parts = [float(x) for x in args.target_bbox.split(',')]
                if len(parts) != 4:
                    raise ValueError("target-bbox must be x1,y1,x2,y2")
                target_bbox = tuple(parts)
            except ValueError as e:
                print(f"Error parsing target-bbox: {e}", file=sys.stderr)
                sys.exit(1)
            
            target_spec = TargetSpec(target_frame=args.target_frame, target_bbox=target_bbox)
        
        elif args.target_point:
            try:
                parts = [float(x) for x in args.target_point.split(',')]
                if len(parts) != 2:
                    raise ValueError("target-point must be x,y")
                target_point = tuple(parts)
            except ValueError as e:
                print(f"Error parsing target-point: {e}", file=sys.stderr)
                sys.exit(1)
            
            target_spec = TargetSpec(target_frame=args.target_frame, target_point=target_point)
        
        target_mode = True
    
    elif args.target_jersey is not None:
        # Build from jersey + team
        from cv.target_tracking import TargetSpec
        target_spec = TargetSpec(target_jersey=args.target_jersey, target_team=args.target_team)
        target_mode = True
    
    # Determine if replay should be rendered
    render_replay = target_mode and not args.no_replay
    if args.render_replay:
        render_replay = True
    
    # Load config
    print("Initializing pipeline configuration...")
    config = Config(
        calibration_path=args.calibration,
        use_default_if_missing=True,
        kits_path=args.kits,
        roster_path=args.roster,
        tracker=args.tracker,
        device=args.device
    )
    
    # Pipeline will handle warnings in meta.json
    
    # Initialize pipeline
    pipeline = SoccerAnalyticsPipeline(
        config=config,
        model_path=args.model,
        ball_model_path=args.ball_model,
        device=args.device,
        enable_ocr=not args.no_ocr,
        tracker=args.tracker
    )
    
    # Process video
    try:
        pipeline.process_video(
            video_path=str(video_path),
            output_dir=args.out,
            annotate_video=args.annotate,
            sample_ocr_every_n_frames=args.ocr_sample_rate,
            target_spec=target_spec,
            render_replay=render_replay,
            replay_max_height=args.replay_max_height
        )
        
        print("\n✓ Pipeline completed successfully!")
        
    except Exception as e:
        print(f"\nError during processing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
