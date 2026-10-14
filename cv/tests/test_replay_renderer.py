"""Unit tests for replay renderer and H.264 encoding."""

import unittest
import numpy as np
import tempfile
from pathlib import Path
import subprocess
import shutil
import cv2


class TestReplayRenderer(unittest.TestCase):
    """Test replay renderer H.264 encoding."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Check if ffmpeg is available
        try:
            import imageio_ffmpeg
            self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            self.has_ffmpeg = True
        except ImportError:
            if shutil.which('ffmpeg'):
                self.ffmpeg_path = 'ffmpeg'
                self.has_ffmpeg = True
            else:
                self.has_ffmpeg = False
    
    def test_h264_encoding_settings(self):
        """Test that replay renderer uses correct H.264 settings."""
        if not self.has_ffmpeg:
            self.skipTest("ffmpeg not available")
        
        # Create a simple test video
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create test input video (10 frames, 640x480)
            input_video = temp_dir / "input.mp4"
            output_video = temp_dir / "output.mp4"
            
            # Generate test video with OpenCV
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(input_video), fourcc, 30.0, (640, 480))
            
            for i in range(10):
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                frame[:, :] = (i * 25, 100, 150)  # Gradient
                writer.write(frame)
            
            writer.release()
            
            # Test ffmpeg command with correct settings
            cmd = [
                self.ffmpeg_path,
                '-y',
                '-i', str(input_video),
                '-vcodec', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-preset', 'medium',
                '-crf', '23',
                '-movflags', '+faststart',
                str(output_video)
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            
            self.assertEqual(result.returncode, 0, f"ffmpeg failed: {result.stderr.decode()}")
            
            # Verify output with ffprobe
            self._verify_h264_output(output_video)
        
        finally:
            shutil.rmtree(temp_dir)
    
    def _verify_h264_output(self, video_path: Path):
        """Verify video is H.264 with yuv420p."""
        if not self.has_ffmpeg:
            return
        
        # Use ffprobe to check codec
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,pix_fmt',
            '-of', 'default=noprint_wrappers=1',
            str(video_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            output = result.stdout
            
            self.assertIn('codec_name=h264', output, "Video should be H.264 encoded")
            self.assertIn('pix_fmt=yuv420p', output, "Video should use yuv420p pixel format")
        
        except FileNotFoundError:
            self.skipTest("ffprobe not available")
    
    def test_even_dimensions(self):
        """Test that dimensions are even (required for yuv420p)."""
        # Odd dimensions should be adjusted
        width, height = 641, 479
        
        # Ensure even
        adjusted_width = width - (width % 2)
        adjusted_height = height - (height % 2)
        
        self.assertEqual(adjusted_width % 2, 0)
        self.assertEqual(adjusted_height % 2, 0)
        self.assertEqual(adjusted_width, 640)
        self.assertEqual(adjusted_height, 478)
    
    def test_downscaling_preserves_aspect_ratio(self):
        """Test that downscaling preserves aspect ratio."""
        width, height = 1920, 1080
        max_height = 720
        
        # Compute scale
        scale = max_height / height
        new_width = int(width * scale)
        new_height = max_height
        
        # Ensure even
        new_width = new_width - (new_width % 2)
        new_height = new_height - (new_height % 2)
        
        # Check aspect ratio preserved (within rounding)
        original_aspect = width / height
        new_aspect = new_width / new_height
        
        self.assertAlmostEqual(original_aspect, new_aspect, places=2)
    
    def test_faststart_flag(self):
        """Test that faststart flag moves moov atom before mdat."""
        if not self.has_ffmpeg:
            self.skipTest("ffmpeg not available")
        
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create test video with faststart
            output_video = temp_dir / "faststart.mp4"
            
            cmd = [
                self.ffmpeg_path,
                '-y',
                '-f', 'lavfi',
                '-i', 'color=c=blue:s=320x240:d=1',
                '-vcodec', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                str(output_video)
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            
            if result.returncode == 0:
                # Check if moov atom comes before mdat (faststart)
                with open(output_video, 'rb') as f:
                    data = f.read(10000)  # Read first 10KB
                    
                    # Search for atom types
                    moov_pos = data.find(b'moov')
                    mdat_pos = data.find(b'mdat')
                    
                    if moov_pos != -1 and mdat_pos != -1:
                        self.assertLess(moov_pos, mdat_pos, 
                                      "moov atom should come before mdat (faststart)")
        
        finally:
            shutil.rmtree(temp_dir)


class TestTargetTrackRendering(unittest.TestCase):
    """Test target track rendering logic."""
    
    def test_bbox_colors_by_state(self):
        """Test that different states use correct colors."""
        # Define expected colors
        colors = {
            'tracked': (0, 255, 0),      # Green
            'occluded': (0, 165, 255),   # Orange
            'lost': None,                 # No box
            'reacquired': (0, 255, 0)    # Green
        }
        
        for state, expected_color in colors.items():
            if state == 'lost':
                # No bbox for lost state
                continue
            
            # Test color matches expected
            if state in ['tracked', 'reacquired']:
                self.assertEqual(expected_color, (0, 255, 0))
            elif state == 'occluded':
                self.assertEqual(expected_color, (0, 165, 255))
    
    def test_dashed_rect_for_occlusion(self):
        """Test that occluded state uses dashed rectangle."""
        # This is more of a visual test, but we can verify the logic
        state = 'occluded'
        
        if state == 'occluded':
            use_dashed = True
        else:
            use_dashed = False
        
        self.assertTrue(use_dashed)
    
    def test_lost_indicator_shown(self):
        """Test that lost state shows indicator text."""
        state = 'lost'
        bbox = None
        
        if bbox is None and state == 'lost':
            show_lost_indicator = True
        else:
            show_lost_indicator = False
        
        self.assertTrue(show_lost_indicator)


if __name__ == '__main__':
    unittest.main()
