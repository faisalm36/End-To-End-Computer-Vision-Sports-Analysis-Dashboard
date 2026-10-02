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
    
    args = parser.parse_args()
    
    # Validate inputs
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}", file=sys.stderr)
        sys.exit(1)
    
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
            sample_ocr_every_n_frames=args.ocr_sample_rate
        )
        
        print("\n✓ Pipeline completed successfully!")
        
    except Exception as e:
        print(f"\nError during processing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
