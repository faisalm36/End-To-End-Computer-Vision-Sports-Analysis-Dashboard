#!/usr/bin/env python3
"""
Interactive target selection helper.

Opens a frame and lets you click on a player to generate target.json.
Also supports headless mode (--list) for backend/frontend integration.
"""

import argparse
import cv2
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional


# Support both `python -m cv.select_target` and `python cv/select_target.py`
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))


from cv.detection import DetectionTracker
from cv.tracking import EnhancedTracker
from ultralytics import YOLO


class TargetSelector:
    """Interactive target selection tool."""
    
    def __init__(self, video_path: str, frame_number: int, device: str = 'cpu'):
        """Initialize target selector.
        
        Args:
            video_path: Path to video file
            frame_number: Frame number to use for selection
            device: Device for detection ('cpu', 'cuda', 'mps')
        """
        self.video_path = video_path
        self.frame_number = frame_number
        self.device = device
        
        # Load video
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        # Seek to frame
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, self.frame = self.cap.read()
        if not ret:
            raise ValueError(f"Cannot read frame {frame_number}")
        
        self.cap.release()
        
        # Detect players
        print(f"Detecting players in frame {frame_number}...")
        self.detections = self._detect_players()
        print(f"Found {len(self.detections)} players")
    
    def _detect_players(self) -> List[Dict]:
        """Detect players in the frame."""
        # Use enhanced tracker for detection
        tracker = EnhancedTracker(
            model_path='yolov8n.pt',  # Use fast model
            person_conf=0.3,
            device=self.device
        )
        
        # Disable actual tracking, just detect
        model = YOLO('yolov8n.pt')
        results = model(
            self.frame,
            classes=[0],  # Person class
            conf=0.3,
            device=self.device,
            verbose=False
        )
        
        detections = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                
                detections.append({
                    'bbox': [float(x1), float(y1), float(x2), float(y2)],
                    'confidence': conf,
                    'index': i
                })
        
        return detections
    
    def list_candidates(self) -> List[Dict]:
        """List candidate boxes (for headless mode).
        
        Returns:
            List of candidate boxes with indices
        """
        candidates = []
        for det in self.detections:
            candidates.append({
                'index': det['index'],
                'bbox': det['bbox'],
                'confidence': round(det['confidence'], 3),
                'center': [
                    round((det['bbox'][0] + det['bbox'][2]) / 2, 2),
                    round((det['bbox'][1] + det['bbox'][3]) / 2, 2)
                ]
            })
        
        return candidates
    
    def interactive_select(self, output_path: str):
        """Interactive selection with OpenCV window.
        
        Args:
            output_path: Path to save target.json
        """
        # Create annotated frame
        display_frame = self.frame.copy()
        
        # Draw all detected boxes with indices
        for det in self.detections:
            bbox = det['bbox']
            x1, y1, x2, y2 = [int(c) for c in bbox]
            
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Draw index
            label = f"#{det['index']}"
            cv2.putText(
                display_frame,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )
        
        # Store selected point
        selected_point = [None, None]
        
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                selected_point[0] = x
                selected_point[1] = y
                print(f"Selected point: ({x}, {y})")
                cv2.destroyAllWindows()
        
        # Show window
        window_name = f"Select Target - Frame {self.frame_number}"
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, mouse_callback)
        
        print("\nClick on a player to select target.")
        print("Close window or press 'q' to cancel.")
        
        while True:
            cv2.imshow(window_name, display_frame)
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q') or selected_point[0] is not None:
                break
        
        cv2.destroyAllWindows()
        
        if selected_point[0] is None:
            print("Selection cancelled.")
            return False
        
        # Find closest detection
        clicked_x, clicked_y = selected_point
        best_det = None
        min_dist = float('inf')
        
        for det in self.detections:
            x1, y1, x2, y2 = det['bbox']
            
            # Check if point is inside
            if x1 <= clicked_x <= x2 and y1 <= clicked_y <= y2:
                best_det = det
                break
            
            # Otherwise compute distance to center
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            dist = ((clicked_x - center_x)**2 + (clicked_y - center_y)**2)**0.5
            
            if dist < min_dist:
                min_dist = dist
                best_det = det
        
        if not best_det:
            print("No detection found near click point.")
            return False
        
        # Create target spec
        target_spec = {
            'target_frame': self.frame_number,
            'target_point': [clicked_x, clicked_y],
            'target_bbox': None,  # Optional, can include detected bbox
            'target_jersey': None,
            'target_team': None
        }
        
        # Save to file
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(target_spec, f, indent=2)
        
        print(f"\nTarget specification saved to: {output_path}")
        print(f"Selected bbox: {best_det['bbox']}")
        
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Interactive target selection for player tracking"
    )
    
    parser.add_argument(
        '--video',
        type=str,
        required=True,
        help='Path to video file'
    )
    
    parser.add_argument(
        '--frame',
        type=int,
        required=True,
        help='Frame number to use for selection'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='target.json',
        help='Output path for target.json (default: target.json)'
    )
    
    parser.add_argument(
        '--device',
        type=str,
        default='cpu',
        choices=['cpu', 'cuda', 'mps'],
        help='Device for detection (default: cpu)'
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help='Headless mode: list candidate boxes as JSON and exit'
    )
    
    args = parser.parse_args()
    
    # Validate video
    if not Path(args.video).exists():
        print(f"Error: Video file not found: {args.video}", file=sys.stderr)
        sys.exit(1)
    
    try:
        selector = TargetSelector(
            video_path=args.video,
            frame_number=args.frame,
            device=args.device
        )
        
        if args.list:
            # Headless mode: output JSON
            candidates = selector.list_candidates()
            print(json.dumps({
                'frame': args.frame,
                'candidates': candidates
            }, indent=2))
        else:
            # Interactive mode
            success = selector.interactive_select(args.output)
            if not success:
                sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
