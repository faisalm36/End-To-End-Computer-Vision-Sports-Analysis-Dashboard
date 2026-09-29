"""Generate a synthetic test video for pipeline validation."""

import cv2
import numpy as np
from pathlib import Path


def generate_test_video(output_path: str, duration_sec: float = 5.0, fps: int = 30):
    """Generate a synthetic soccer-like test video.
    
    Args:
        output_path: Output video path
        duration_sec: Video duration in seconds
        fps: Frames per second
    """
    width, height = 1920, 1080
    total_frames = int(duration_sec * fps)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    print(f"Generating synthetic test video: {output_path}")
    print(f"Duration: {duration_sec}s, FPS: {fps}, Total frames: {total_frames}")
    
    # Draw pitch background
    pitch_color = (50, 150, 50)  # Green
    line_color = (255, 255, 255)  # White
    
    for frame_idx in range(total_frames):
        # Create frame with pitch
        frame = np.full((height, width, 3), pitch_color, dtype=np.uint8)
        
        # Draw pitch lines
        cv2.rectangle(frame, (100, 100), (1820, 980), line_color, 2)  # Outer boundary
        cv2.line(frame, (960, 100), (960, 980), line_color, 2)  # Center line
        cv2.circle(frame, (960, 540), 100, line_color, 2)  # Center circle
        
        # Goal boxes
        cv2.rectangle(frame, (100, 350), (300, 730), line_color, 2)
        cv2.rectangle(frame, (1620, 350), (1820, 730), line_color, 2)
        
        # Simulate moving players (simple rectangles)
        t = frame_idx / total_frames
        
        # Player 1: moving left to right
        player1_x = int(200 + 1400 * t)
        player1_y = 400
        cv2.rectangle(
            frame,
            (player1_x - 30, player1_y - 80),
            (player1_x + 30, player1_y + 80),
            (0, 0, 255),  # Red
            -1
        )
        # Jersey number "10"
        cv2.putText(
            frame,
            "10",
            (player1_x - 20, player1_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (255, 255, 255),
            3
        )
        
        # Player 2: moving right to left
        player2_x = int(1700 - 1400 * t)
        player2_y = 600
        cv2.rectangle(
            frame,
            (player2_x - 30, player2_y - 80),
            (player2_x + 30, player2_y + 80),
            (255, 0, 0),  # Blue
            -1
        )
        # Jersey number "7"
        cv2.putText(
            frame,
            "7",
            (player2_x - 15, player2_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (255, 255, 255),
            3
        )
        
        # Player 3: stationary
        player3_x = 960
        player3_y = 540
        cv2.rectangle(
            frame,
            (player3_x - 30, player3_y - 80),
            (player3_x + 30, player3_y + 80),
            (0, 255, 0),  # Green
            -1
        )
        cv2.putText(
            frame,
            "3",
            (player3_x - 10, player3_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (255, 255, 255),
            3
        )
        
        # Simulate moving ball (small circle)
        ball_x = int(400 + 1000 * t + 200 * np.sin(t * 8 * np.pi))
        ball_y = int(500 + 100 * np.cos(t * 6 * np.pi))
        cv2.circle(frame, (ball_x, ball_y), 12, (255, 255, 255), -1)
        
        writer.write(frame)
    
    writer.release()
    print(f"✓ Test video generated: {output_path}")


if __name__ == '__main__':
    output_dir = Path('cv/outputs')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / 'synthetic_test.mp4'
    generate_test_video(str(output_path), duration_sec=5.0, fps=30)
