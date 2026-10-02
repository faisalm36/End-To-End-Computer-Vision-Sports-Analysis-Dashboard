"""
Replay renderer: Generate browser-playable H.264 annotated video with target overlay.

Creates replay.mp4 with:
- Bounding box + label around the target
- Jersey/name + speed label
- Dashed box for occlusion/prediction
- 'LOST' or 'Re-acquiring' indicators
- Optional motion trail
- H.264 (libx264) + yuv420p + faststart for browser compatibility
"""

import cv2
import numpy as np
import subprocess
import json
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import shutil


class ReplayRenderer:
    """Render annotated replay video with target tracking overlay."""
    
    def __init__(
        self,
        video_path: str,
        target_frames: List[Dict],
        output_path: str,
        fps: float,
        target_jersey: Optional[int] = None,
        max_height: Optional[int] = None,
        show_speed: bool = True,
        trail_length: int = 15,
        preserve_audio: bool = True,
    ):
        """Initialize replay renderer.
        
        Args:
            video_path: Path to input video
            target_frames: Target tracking results (frame-by-frame)
            output_path: Path to output replay.mp4
            fps: Video FPS
            target_jersey: Target jersey number (for label)
            max_height: Maximum height for downscaling (optional)
            show_speed: Show speed in label (if calibrated)
            trail_length: Number of frames for motion trail
            preserve_audio: Copy audio from input video
        """
        self.video_path = video_path
        self.target_frames = target_frames
        self.output_path = output_path
        self.fps = fps
        self.target_jersey = target_jersey
        self.max_height = max_height
        self.show_speed = show_speed
        self.trail_length = trail_length
        self.preserve_audio = preserve_audio
        
        # Build frame lookup
        self.frame_lookup = {frame['frame']: frame for frame in target_frames}
        
        # Check for ffmpeg
        self.ffmpeg_path = self._find_ffmpeg()
    
    def _find_ffmpeg(self) -> str:
        """Find ffmpeg executable (system or imageio-ffmpeg)."""
        # Try system ffmpeg
        if shutil.which('ffmpeg'):
            return 'ffmpeg'
        
        # Try imageio-ffmpeg
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            raise RuntimeError("ffmpeg not found. Install imageio-ffmpeg: pip install imageio-ffmpeg")
    
    def render(self, progress_callback: Optional[callable] = None):
        """Render the replay video.
        
        Args:
            progress_callback: Optional callback(progress_pct) for progress updates
        """
        # Open input video
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {self.video_path}")
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Apply downscaling if requested
        if self.max_height and height > self.max_height:
            scale = self.max_height / height
            new_width = int(width * scale)
            new_height = self.max_height
            
            # Ensure even dimensions (required for yuv420p)
            new_width = new_width - (new_width % 2)
            new_height = new_height - (new_height % 2)
        else:
            new_width = width - (width % 2)  # Ensure even
            new_height = height - (height % 2)
        
        # Setup ffmpeg pipe for H.264 encoding
        temp_video = str(Path(self.output_path).with_suffix('.temp.mp4'))
        
        ffmpeg_cmd = [
            self.ffmpeg_path,
            '-y',  # Overwrite
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{new_width}x{new_height}',
            '-pix_fmt', 'bgr24',
            '-r', str(self.fps),
            '-i', '-',  # stdin
            '-an',  # No audio in this pass
            '-vcodec', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-preset', 'medium',
            '-crf', '23',
            '-movflags', '+faststart',
            temp_video
        ]
        
        # Start ffmpeg process
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Process frames
        frame_idx = 0
        trail_positions = []  # [(x, y), ...] for motion trail
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Resize if needed
                if (new_width, new_height) != (width, height):
                    frame = cv2.resize(frame, (new_width, new_height))
                
                # Get target info for this frame
                target_info = self.frame_lookup.get(frame_idx)
                
                if target_info:
                    frame = self._annotate_frame(
                        frame, target_info, trail_positions,
                        new_width, new_height
                    )
                
                # Write frame to ffmpeg
                ffmpeg_process.stdin.write(frame.tobytes())
                
                frame_idx += 1
                
                # Progress callback
                if progress_callback and frame_idx % 30 == 0:
                    progress = int((frame_idx / total_frames) * 100)
                    progress_callback(progress)
            
            # Close ffmpeg stdin
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
            
            cap.release()
            
            # Add audio if requested
            if self.preserve_audio and self._has_audio(self.video_path):
                self._add_audio(temp_video, self.video_path, self.output_path)
                Path(temp_video).unlink()  # Remove temp
            else:
                # No audio, just rename
                Path(temp_video).rename(self.output_path)
        
        except Exception as e:
            ffmpeg_process.kill()
            cap.release()
            if Path(temp_video).exists():
                Path(temp_video).unlink()
            raise e
    
    def _annotate_frame(
        self,
        frame: np.ndarray,
        target_info: Dict,
        trail_positions: List[Tuple[int, int]],
        frame_width: int,
        frame_height: int,
    ) -> np.ndarray:
        """Annotate frame with target tracking overlay."""
        state = target_info['state']
        bbox = target_info.get('bbox')
        
        if bbox is None:
            # Lost, no bbox
            self._draw_lost_indicator(frame, state)
            return frame
        
        x1, y1, x2, y2 = bbox
        center_x = int((x1 + x2) / 2)
        center_y = int((y1 + y2) / 2)
        
        # Draw trail
        if trail_positions:
            self._draw_trail(frame, trail_positions)
        
        # Update trail
        trail_positions.append((center_x, center_y))
        if len(trail_positions) > self.trail_length:
            trail_positions.pop(0)
        
        # Draw bounding box
        if state in ['tracked', 'reacquired']:
            # Solid box for tracked
            color = (0, 255, 0)  # Green
            thickness = 3
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, thickness)
        
        elif state == 'occluded':
            # Dashed box for occluded
            color = (0, 165, 255)  # Orange
            self._draw_dashed_rect(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, thickness=2)
        
        # Draw label
        label_parts = []
        
        if self.target_jersey:
            label_parts.append(f"#{self.target_jersey}")
        else:
            label_parts.append("Target")
        
        if self.show_speed and target_info.get('pitch_x') is not None:
            # TODO: Compute speed from position history
            # For now, just show state
            pass
        
        if state == 'reacquired':
            label_parts.append("(Re-acquired)")
        elif state == 'occluded':
            label_parts.append("(Occluded)")
        
        label = " ".join(label_parts)
        
        # Draw label with background
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        font_thickness = 2
        
        (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, font_thickness)
        
        label_x = int(x1)
        label_y = int(y1) - 10
        
        if label_y < text_height + 10:
            label_y = int(y2) + text_height + 10
        
        # Background rectangle
        cv2.rectangle(
            frame,
            (label_x, label_y - text_height - 5),
            (label_x + text_width + 10, label_y + 5),
            (0, 0, 0),
            -1
        )
        
        # Text
        cv2.putText(
            frame,
            label,
            (label_x + 5, label_y),
            font,
            font_scale,
            (255, 255, 255),
            font_thickness
        )
        
        # State indicator for lost/reacquiring
        if state in ['lost', 'reacquired']:
            self._draw_state_indicator(frame, state, frame_width, frame_height)
        
        return frame
    
    def _draw_trail(self, frame: np.ndarray, positions: List[Tuple[int, int]]):
        """Draw motion trail."""
        if len(positions) < 2:
            return
        
        for i in range(len(positions) - 1):
            alpha = (i + 1) / len(positions)
            color = (0, int(255 * alpha), 0)
            thickness = max(1, int(3 * alpha))
            
            cv2.line(frame, positions[i], positions[i + 1], color, thickness)
    
    def _draw_dashed_rect(
        self,
        frame: np.ndarray,
        pt1: Tuple[int, int],
        pt2: Tuple[int, int],
        color: Tuple[int, int, int],
        thickness: int = 2,
        dash_length: int = 10
    ):
        """Draw dashed rectangle."""
        x1, y1 = pt1
        x2, y2 = pt2
        
        # Top
        self._draw_dashed_line(frame, (x1, y1), (x2, y1), color, thickness, dash_length)
        # Right
        self._draw_dashed_line(frame, (x2, y1), (x2, y2), color, thickness, dash_length)
        # Bottom
        self._draw_dashed_line(frame, (x2, y2), (x1, y2), color, thickness, dash_length)
        # Left
        self._draw_dashed_line(frame, (x1, y2), (x1, y1), color, thickness, dash_length)
    
    def _draw_dashed_line(
        self,
        frame: np.ndarray,
        pt1: Tuple[int, int],
        pt2: Tuple[int, int],
        color: Tuple[int, int, int],
        thickness: int,
        dash_length: int
    ):
        """Draw dashed line."""
        x1, y1 = pt1
        x2, y2 = pt2
        
        dist = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        if dist < 1:
            return
        
        dashes = int(dist / dash_length)
        
        for i in range(dashes):
            if i % 2 == 0:
                start = (
                    int(x1 + (x2 - x1) * i / dashes),
                    int(y1 + (y2 - y1) * i / dashes)
                )
                end = (
                    int(x1 + (x2 - x1) * (i + 1) / dashes),
                    int(y1 + (y2 - y1) * (i + 1) / dashes)
                )
                cv2.line(frame, start, end, color, thickness)
    
    def _draw_lost_indicator(self, frame: np.ndarray, state: str):
        """Draw 'LOST' or 'Re-acquiring' indicator."""
        h, w = frame.shape[:2]
        
        if state == 'lost':
            text = "TARGET LOST"
            color = (0, 0, 255)  # Red
        else:
            text = "Re-acquiring..."
            color = (0, 165, 255)  # Orange
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.0
        font_thickness = 2
        
        (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
        
        x = (w - text_width) // 2
        y = 50
        
        # Background
        cv2.rectangle(
            frame,
            (x - 10, y - text_height - 10),
            (x + text_width + 10, y + 10),
            (0, 0, 0),
            -1
        )
        
        # Text
        cv2.putText(frame, text, (x, y), font, font_scale, color, font_thickness)
    
    def _draw_state_indicator(self, frame: np.ndarray, state: str, w: int, h: int):
        """Draw state indicator in corner."""
        if state == 'reacquired':
            text = "RE-ACQUIRED"
            color = (0, 255, 0)
        else:
            return
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        font_thickness = 2
        
        (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, font_thickness)
        
        x = w - text_width - 20
        y = 40
        
        # Background
        cv2.rectangle(
            frame,
            (x - 5, y - text_height - 5),
            (x + text_width + 5, y + 5),
            (0, 0, 0),
            -1
        )
        
        # Text
        cv2.putText(frame, text, (x, y), font, font_scale, color, font_thickness)
    
    def _has_audio(self, video_path: str) -> bool:
        """Check if video has audio stream."""
        try:
            result = subprocess.run(
                [
                    self.ffmpeg_path,
                    '-i', video_path,
                    '-hide_banner'
                ],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Check stderr for audio stream
            return 'Audio:' in result.stderr
        
        except Exception:
            return False
    
    def _add_audio(self, video_path: str, source_path: str, output_path: str):
        """Add audio from source to video."""
        cmd = [
            self.ffmpeg_path,
            '-y',
            '-i', video_path,
            '-i', source_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-map', '0:v:0',
            '-map', '1:a:0?',
            '-shortest',
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
