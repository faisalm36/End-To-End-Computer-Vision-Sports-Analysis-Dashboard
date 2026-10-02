#!/usr/bin/env python3
"""
End-to-end test for target tracking with synthetic video.

Creates a video with 3 moving players in two kit colors, where the target:
- Is occluded (leaves frame)
- Re-enters the frame
- Should be re-acquired

Then runs detect_frame and track_player commands and verifies outputs.
"""

import subprocess
import sys
import json
import tempfile
from pathlib import Path
import numpy as np
import cv2


def create_synthetic_video(output_path: str, total_frames: int = 300, fps: int = 30):
    """Create synthetic video with 3 moving players.
    
    - Player 1 (blue, jersey 10): Moves left to right, exits frame at 100-150, re-enters at 151
    - Player 2 (red, jersey 7): Moves in circle
    - Player 3 (blue, jersey 3): Static in corner
    """
    width, height = 1280, 720  # Higher res for better detection
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    for frame_idx in range(total_frames):
        # Create frame with grass-like background
        frame = np.ones((height, width, 3), dtype=np.uint8)
        frame[:, :] = [40, 100, 40]  # Green grass (BGR)
        
        # Add some texture
        noise = np.random.randint(0, 20, (height, width, 3), dtype=np.uint8)
        frame = cv2.add(frame, noise)
        
        # Player 1 (blue, jersey 10) - target player (person-sized)
        if frame_idx < 100 or frame_idx > 150:
            # Visible
            x1 = int(100 + frame_idx * 3) % (width - 80)
            y1 = 300
            # Draw person shape
            cv2.ellipse(frame, (x1 + 40, y1 + 70), (35, 50), 0, 0, 180, (255, 150, 100), -1)  # Blue shirt
            cv2.ellipse(frame, (x1 + 40, y1 + 20), (20, 25), 0, 0, 360, (200, 180, 160), -1)  # Head
            cv2.rectangle(frame, (x1 + 10, y1 + 100), (x1 + 70, y1+ 140), (50, 50, 150), -1)  # Shorts
            # Jersey number
            cv2.putText(frame, "10", (x1 + 25, y1 + 80), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        
        # Player 2 (red, jersey 7)
        angle = frame_idx * 0.05
        x2 = int(width / 2 + 200 * np.cos(angle))
        y2 = int(height / 2 + 150 * np.sin(angle))
        # Draw person shape
        cv2.ellipse(frame, (x2, y2 + 50), (35, 50), 0, 0, 180, (80, 80, 255), -1)  # Red shirt
        cv2.ellipse(frame, (x2, y2), (20, 25), 0, 0, 360, (200, 180, 160), -1)  # Head
        cv2.rectangle(frame, (x2 - 30, y2 + 80), (x2 + 30, y2 + 120), (50, 50, 150), -1)  # Shorts
        cv2.putText(frame, "7", (x2 - 15, y2 + 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        
        # Player 3 (blue, jersey 3)
        x3, y3 = 1000, 100
        cv2.ellipse(frame, (x3, y3 + 50), (35, 50), 0, 0, 180, (255, 150, 100), -1)  # Blue shirt
        cv2.ellipse(frame, (x3, y3), (20, 25), 0, 0, 360, (200, 180, 160), -1)  # Head
        cv2.rectangle(frame, (x3 - 30, y3 + 80), (x3 + 30, y3 + 120), (50, 50, 150), -1)  # Shorts
        cv2.putText(frame, "3", (x3 - 15, y3 + 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        
        writer.write(frame)
    
    writer.release()
    print(f"Created synthetic video: {output_path}")


def run_detect_frame(video_path: str, t: float, output_dir: str):
    """Run detect_frame command."""
    cmd = [
        sys.executable, '-m', 'cv.detect_frame',
        '--video', video_path,
        '--t', str(t),
        '--out', output_dir,
        '--device', 'cpu',
        '--model', 'yolov8n.pt'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\ndetect_frame exit code: {result.returncode}")
    print(f"stdout: {result.stdout}")
    if result.stderr:
        print(f"stderr: {result.stderr}")
    
    return result.returncode


def run_track_player_bbox(video_path: str, output_dir: str, frame: int, bbox: str):
    """Run track_player with bbox."""
    cmd = [
        sys.executable, '-m', 'cv.track_player',
        '--video', video_path,
        '--out', output_dir,
        '--device', 'cpu',
        '--frame', str(frame),
        '--bbox', bbox,
        '--model', 'yolov8n.pt'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\ntrack_player (bbox) exit code: {result.returncode}")
    print(f"stdout (last 500 chars): ...{result.stdout[-500:]}")
    if result.stderr:
        print(f"stderr (last 300 chars): ...{result.stderr[-300:]}")
    
    return result.returncode


def run_track_player_jersey(video_path: str, output_dir: str, jersey: int, team: str):
    """Run track_player with jersey (should fail - no match)."""
    cmd = [
        sys.executable, '-m', 'cv.track_player',
        '--video', video_path,
        '--out', output_dir,
        '--device', 'cpu',
        '--jersey', str(jersey),
        '--team', team,
        '--model', 'yolov8n.pt'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\ntrack_player (jersey) exit code: {result.returncode}")
    print(f"stdout: {result.stdout}")
    if result.stderr:
        print(f"stderr: {result.stderr}")
    
    return result.returncode


def verify_ffprobe(video_path: str):
    """Verify H.264 encoding with ffprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_streams', '-show_format',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            print(f"\nffprobe output for {Path(video_path).name}:")
            print(json.dumps(data, indent=2))
            
            # Check video stream
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    codec_name = stream.get('codec_name')
                    pix_fmt = stream.get('pix_fmt')
                    print(f"\nVideo codec: {codec_name}, pix_fmt: {pix_fmt}")
                    
                    if codec_name == 'h264' and pix_fmt == 'yuv420p':
                        print("✓ H.264 + yuv420p verified")
                    else:
                        print(f"✗ Expected h264/yuv420p, got {codec_name}/{pix_fmt}")
            
            # Check for faststart
            with open(video_path, 'rb') as f:
                data = f.read(10000)
                moov_pos = data.find(b'moov')
                mdat_pos = data.find(b'mdat')
                
                if moov_pos != -1 and mdat_pos != -1:
                    if moov_pos < mdat_pos:
                        print(f"✓ Faststart verified (moov at {moov_pos}, mdat at {mdat_pos})")
                    else:
                        print(f"✗ moov after mdat (moov at {moov_pos}, mdat at {mdat_pos})")
    
    except FileNotFoundError:
        print("ffprobe not available, skipping H.264 verification")
    except Exception as e:
        print(f"ffprobe error: {e}")


def main():
    print("=== E2E Test: Target Tracking with Synthetic Video ===\n")
    
    # Create temp directory
    temp_dir = Path(tempfile.mkdtemp())
    print(f"Temp dir: {temp_dir}\n")
    
    try:
        # Create synthetic video
        video_path = str(temp_dir / "synthetic.mp4")
        create_synthetic_video(video_path, total_frames=300, fps=30)
        
        # Test 1: detect_frame
        print("\n--- Test 1: detect_frame ---")
        detect_dir = temp_dir / "detect"
        detect_dir.mkdir()
        
        exit_code = run_detect_frame(video_path, t=1.0, output_dir=str(detect_dir))
        
        if exit_code == 0:
            # Read candidates.json
            candidates_path = detect_dir / "candidates.json"
            if candidates_path.exists():
                with open(candidates_path) as f:
                    candidates = json.load(f)
                print(f"\ncandidates.json:")
                print(json.dumps(candidates, indent=2))
            else:
                print("✗ candidates.json not found")
        
        # Test 2: track_player with bbox
        print("\n--- Test 2: track_player (bbox mode) ---")
        track_dir = temp_dir / "track"
        track_dir.mkdir()
        
        # Target player 1 at frame 10 (should be around x=130)
        exit_code = run_track_player_bbox(video_path, str(track_dir), frame=10, bbox="130,300,210,440")
        
        if exit_code == 0:
            # Read track.json
            track_path = track_dir / "track.json"
            if track_path.exists():
                with open(track_path) as f:
                    track_data = json.load(f)
                
                print(f"\ntrack.json excerpt (frames around occlusion 95-155):")
                for frame_info in track_data['frames'][95:156]:
                    print(f"  Frame {frame_info['frame']}: status={frame_info['status']}, bbox={'present' if frame_info['bbox'] else 'null'}")
                
                # Count states
                tracked = sum(1 for f in track_data['frames'] if f['status'] == 'tracked')
                interpolated = sum(1 for f in track_data['frames'] if f['status'] == 'interpolated')
                lost = sum(1 for f in track_data['frames'] if f['status'] == 'lost')
                
                print(f"\nStatus counts: tracked={tracked}, interpolated={interpolated}, lost={lost}")
                
                # Check for re-acquisition
                reacquired = False
                for i in range(150, 170):
                    if i < len(track_data['frames']) and track_data['frames'][i]['status'] == 'tracked':
                        reacquired = True
                        print(f"✓ Target re-acquired at frame {i}")
                        break
                
                if not reacquired:
                    print("✗ Target not re-acquired after occlusion")
            
            # Read meta.json
            meta_path = track_dir / "meta.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                print(f"\nmeta.json:")
                print(json.dumps(meta, indent=2))
            
            # Verify replay.mp4
            replay_path = track_dir / "replay.mp4"
            if replay_path.exists():
                print(f"\n✓ replay.mp4 exists ({replay_path.stat().st_size} bytes)")
                verify_ffprobe(str(replay_path))
            else:
                print("✗ replay.mp4 not found")
        
        # Test 3: track_player with jersey (no match - should exit 3)
        print("\n--- Test 3: track_player (jersey mode, no match) ---")
        jersey_dir = temp_dir / "jersey"
        jersey_dir.mkdir()
        
        exit_code = run_track_player_jersey(video_path, str(jersey_dir), jersey=99, team="A")
        
        if exit_code == 3:
            print("✓ Exit code 3 for no match")
            
            meta_path = jersey_dir / "meta.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                print(f"\nmeta.json (error case):")
                print(json.dumps(meta, indent=2))
                
                if meta.get('error') == 'target_not_found':
                    print("✓ meta.json contains 'error': 'target_not_found'")
                else:
                    print(f"✗ Expected error='target_not_found', got {meta.get('error')}")
        else:
            print(f"✗ Expected exit code 3, got {exit_code}")
    
    finally:
        print(f"\nTemp files in: {temp_dir}")
        print("(Not cleaned up for inspection)")


if __name__ == '__main__':
    main()
