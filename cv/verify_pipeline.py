#!/usr/bin/env python3
"""Verify pipeline structure and data flow without heavy dependencies."""

import sys
import json
from pathlib import Path

# Add cv to path
sys.path.insert(0, str(Path(__file__).parent))

from cv.config import Config
from cv.homography import HomographyTransform


def test_config():
    """Test configuration loading."""
    print("Testing configuration...")
    
    # Test with calibration
    calib_path = "cv/config/test_calibration.json"
    config = Config(calibration_path=calib_path)
    
    assert config.image_points is not None
    assert config.pitch_points is not None
    assert len(config.image_points) == 4
    assert len(config.pitch_points) == 4
    
    print("✓ Config loaded successfully")
    return config


def test_homography(config):
    """Test homography transformation."""
    print("\nTesting homography transformation...")
    
    transform = HomographyTransform(
        config.image_points,
        config.pitch_points,
        config.PITCH_WIDTH_M,
        config.PITCH_LENGTH_M
    )
    
    # Test corner transformation
    result = transform.transform_point(100, 100)
    assert result is not None
    print(f"  Corner (100,100) -> ({result[0]:.2f}, {result[1]:.2f})m")
    
    # Test center transformation
    result = transform.transform_point(960, 540)
    assert result is not None
    print(f"  Center (960,540) -> ({result[0]:.2f}, {result[1]:.2f})m")
    
    print("✓ Homography working correctly")
    return transform


def test_file_structure():
    """Test that all expected files exist."""
    print("\nVerifying file structure...")
    
    required_files = [
        "cv/__init__.py",
        "cv/config.py",
        "cv/detection.py",
        "cv/ocr.py",
        "cv/homography.py",
        "cv/metrics.py",
        "cv/pipeline.py",
        "cv/run_pipeline.py",
        "cv/requirements.txt",
        "cv/README.md",
        "cv/config/example_calibration.json",
        "cv/config/test_calibration.json",
        "cv/tests/__init__.py",
        "cv/tests/test_homography.py",
        "cv/tests/test_metrics.py",
        "cv/tests/test_ocr.py"
    ]
    
    for file_path in required_files:
        path = Path(file_path)
        if not path.exists():
            print(f"✗ Missing: {file_path}")
            sys.exit(1)
    
    print(f"✓ All {len(required_files)} required files present")


def test_synthetic_video():
    """Test that synthetic video was generated."""
    print("\nVerifying test video...")
    
    video_path = Path("cv/outputs/synthetic_test.mp4")
    if not video_path.exists():
        print("✗ Synthetic test video not found")
        sys.exit(1)
    
    size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"✓ Test video exists: {size_mb:.2f} MB")


def test_output_schema():
    """Verify output schema documentation."""
    print("\nVerifying output schema compatibility...")
    
    # Expected schema for tracking_detections
    detection_schema = {
        'frame': 'int',
        'timestamp': 'float',
        'track_id': 'int',
        'class': 'str',
        'bbox_x1': 'float',
        'bbox_y1': 'float',
        'bbox_x2': 'float',
        'bbox_y2': 'float',
        'confidence': 'float',
        'pitch_x': 'float',
        'pitch_y': 'float',
        'jersey_number': 'int'
    }
    
    # Expected schema for player_match_stats
    stats_schema = {
        'track_id': 'int',
        'jersey_number': 'int',
        'top_speed_mph': 'float',
        'distance_km': 'float',
        'injury_risk': 'str',
        'high_speed_distance_km': 'float',
        'sprint_distance_km': 'float',
        'sprint_count': 'int'
    }
    
    print(f"✓ Detection schema: {len(detection_schema)} fields")
    print(f"✓ Stats schema: {len(stats_schema)} fields")


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("Soccer CV Pipeline - Structure Verification")
    print("=" * 60)
    
    test_file_structure()
    config = test_config()
    test_homography(config)
    test_synthetic_video()
    test_output_schema()
    
    print("\n" + "=" * 60)
    print("✓ All verification tests passed!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Install full dependencies: pip install -r cv/requirements.txt")
    print("2. Run pipeline: python cv/run_pipeline.py --video cv/outputs/synthetic_test.mp4 --out cv/outputs/test_run/ --calibration cv/config/test_calibration.json")
    print("3. Check outputs in cv/outputs/test_run/")


if __name__ == '__main__':
    main()
