#!/usr/bin/env python3
"""
Interactive click-to-calibrate helper for pitch calibration.

Usage:
    python cv/calibrate_interactive.py path/to/video_frame.jpg

Instructions:
    1. Click points on the image (corners, penalty box corners, etc.)
    2. Enter corresponding pitch coordinates in meters for each point
    3. Press 's' to save calibration to JSON
    4. Press 'q' to quit without saving
    5. Press 'u' to undo last point

The tool will write a calibration JSON file compatible with the pipeline.
"""

import cv2
import json
import sys
import numpy as np
from pathlib import Path
from typing import List, Tuple


class CalibrationTool:
    """Interactive calibration tool using OpenCV window."""
    
    def __init__(self, image_path: str, pitch_length_m: float = 105.0, pitch_width_m: float = 68.0):
        """Initialize calibration tool.
        
        Args:
            image_path: Path to video frame or image
            pitch_length_m: Pitch length in meters
            pitch_width_m: Pitch width in meters
        """
        self.image_path = Path(image_path)
        self.pitch_length_m = pitch_length_m
        self.pitch_width_m = pitch_width_m
        
        # Load image
        self.image = cv2.imread(str(self.image_path))
        if self.image is None:
            raise ValueError(f"Cannot load image: {image_path}")
        
        # Scale if too large
        max_display_height = 900
        if self.image.shape[0] > max_display_height:
            scale = max_display_height / self.image.shape[0]
            self.image = cv2.resize(self.image, None, fx=scale, fy=scale)
        
        self.display_image = self.image.copy()
        
        # Point correspondences
        self.image_points: List[Tuple[float, float]] = []
        self.pitch_points: List[Tuple[float, float]] = []
        
        # Window name
        self.window_name = "Pitch Calibration - Click points, press 's' to save, 'q' to quit, 'u' to undo"
    
    def mouse_callback(self, event, x, y, flags, param):
        """Handle mouse clicks."""
        if event == cv2.EVENT_LBUTTONDOWN:
            # Add point
            self.image_points.append((float(x), float(y)))
            
            # Prompt for pitch coordinates
            print(f"\nClicked image point {len(self.image_points)}: ({x}, {y})")
            print(f"Enter corresponding pitch coordinates (in meters):")
            print(f"  Pitch length: 0 to {self.pitch_length_m}m")
            print(f"  Pitch width: 0 to {self.pitch_width_m}m")
            
            # Get pitch coordinates from user input
            try:
                pitch_x = float(input("  Pitch X (meters): ").strip())
                pitch_y = float(input("  Pitch Y (meters): ").strip())
                self.pitch_points.append((pitch_x, pitch_y))
                
                print(f"Added correspondence: image ({x}, {y}) <-> pitch ({pitch_x:.1f}, {pitch_y:.1f})")
            except ValueError:
                print("Invalid input, point discarded")
                self.image_points.pop()
            
            # Redraw
            self.draw_points()
    
    def draw_points(self):
        """Draw clicked points on image."""
        self.display_image = self.image.copy()
        
        # Draw points
        for i, (x, y) in enumerate(self.image_points):
            cv2.circle(self.display_image, (int(x), int(y)), 5, (0, 255, 0), -1)
            cv2.putText(
                self.display_image,
                str(i + 1),
                (int(x) + 10, int(y) - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )
        
        # Draw lines between points
        if len(self.image_points) > 1:
            for i in range(len(self.image_points) - 1):
                pt1 = (int(self.image_points[i][0]), int(self.image_points[i][1]))
                pt2 = (int(self.image_points[i + 1][0]), int(self.image_points[i + 1][1]))
                cv2.line(self.display_image, pt1, pt2, (255, 0, 0), 2)
        
        # Show point count
        text = f"Points: {len(self.image_points)} (need >= 4 for homography)"
        cv2.putText(
            self.display_image,
            text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2
        )
        
        cv2.imshow(self.window_name, self.display_image)
    
    def undo_last_point(self):
        """Remove last added point."""
        if self.image_points:
            self.image_points.pop()
            self.pitch_points.pop()
            print("Undid last point")
            self.draw_points()
    
    def save_calibration(self, output_path: str):
        """Save calibration to JSON file.
        
        Args:
            output_path: Path to output JSON file
        """
        if len(self.image_points) < 4:
            print("Error: Need at least 4 point correspondences")
            return False
        
        # Build calibration data
        correspondences = []
        for img_pt, pitch_pt in zip(self.image_points, self.pitch_points):
            correspondences.append({
                'image': [img_pt[0], img_pt[1]],
                'pitch': [pitch_pt[0], pitch_pt[1]]
            })
        
        calibration_data = {
            'pitch_dimensions': {
                'width_m': self.pitch_width_m,
                'length_m': self.pitch_length_m
            },
            'correspondences': correspondences,
            'source_image': str(self.image_path),
            'note': 'Created with interactive calibration tool'
        }
        
        # Test homography
        src_pts = np.array([list(pt) for pt in self.image_points], dtype=np.float32)
        dst_pts = np.array([list(pt) for pt in self.pitch_points], dtype=np.float32)
        
        H, status = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        
        if H is None:
            print("Warning: Homography computation failed, but saving calibration anyway")
        else:
            inliers = status.sum() if status is not None else len(src_pts)
            print(f"Homography computed: {inliers}/{len(src_pts)} inliers")
        
        # Save to JSON
        output_path = Path(output_path)
        with open(output_path, 'w') as f:
            json.dump(calibration_data, f, indent=2)
        
        print(f"\nCalibration saved to: {output_path}")
        print(f"Use with: --calibration {output_path}")
        return True
    
    def run(self):
        """Run interactive calibration loop."""
        print("\n" + "="*70)
        print("Interactive Pitch Calibration Tool")
        print("="*70)
        print("\nInstructions:")
        print("  1. Click on pitch marking points (corners, penalty box corners, etc.)")
        print("  2. Enter corresponding pitch coordinates in meters for each point")
        print("  3. Press 's' to save calibration to JSON")
        print("  4. Press 'q' to quit without saving")
        print("  5. Press 'u' to undo last point")
        print("\nRecommended points (4-12 points):")
        print("  - Four pitch corners: (0,0), (105,0), (105,68), (0,68)")
        print("  - Penalty box corners, center circle, etc.")
        print("\nPitch coordinate system:")
        print("  - X: 0 to 105m (length)")
        print("  - Y: 0 to 68m (width)")
        print("  - Origin (0,0) = one corner")
        print("="*70 + "\n")
        
        # Create window
        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)
        
        # Show initial image
        self.draw_points()
        
        # Main loop
        while True:
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                print("Quit without saving")
                break
            elif key == ord('s'):
                # Save
                default_output = self.image_path.parent / 'calibration.json'
                output_path = input(f"\nSave calibration to [{default_output}]: ").strip()
                if not output_path:
                    output_path = default_output
                
                if self.save_calibration(output_path):
                    print("Press any key to close...")
                    cv2.waitKey(0)
                    break
            elif key == ord('u'):
                self.undo_last_point()
        
        cv2.destroyAllWindows()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python cv/calibrate_interactive.py path/to/frame.jpg")
        print("\nYou can extract a frame from a video with:")
        print("  ffmpeg -i video.mp4 -ss 00:01:00 -frames:v 1 frame.jpg")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    # Optional: custom pitch dimensions
    pitch_length = 105.0
    pitch_width = 68.0
    
    if len(sys.argv) > 2:
        pitch_length = float(sys.argv[2])
    if len(sys.argv) > 3:
        pitch_width = float(sys.argv[3])
    
    tool = CalibrationTool(image_path, pitch_length, pitch_width)
    tool.run()


if __name__ == '__main__':
    main()
