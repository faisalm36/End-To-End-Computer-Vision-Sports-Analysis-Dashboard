"""Configuration management for the CV pipeline."""

import yaml
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class Config:
    """Pipeline configuration."""
    
    # Default pitch dimensions in meters (standard FIFA pitch)
    PITCH_WIDTH_M = 68.0
    PITCH_LENGTH_M = 105.0
    
    # Detection thresholds
    PERSON_CONF_THRESHOLD = 0.3
    BALL_CONF_THRESHOLD = 0.25
    IOU_THRESHOLD = 0.5
    
    # Ball inference resolution (higher for small object)
    BALL_IMGSZ = 1280
    DEFAULT_IMGSZ = 640
    
    # OCR settings
    OCR_CONF_THRESHOLD = 0.5
    OCR_ALLOWLIST = '0123456789'
    
    # Speed/distance settings
    FPS_DEFAULT = 30.0
    MAX_PLAUSIBLE_SPEED_MPH = 25.0  # ~40 km/h, filters only extreme outliers (fastest PL: 37.3 km/h = 23.2 mph)
    SPEED_SMOOTHING_WINDOW = 5
    SUSTAINED_SPEED_WINDOW_S = 1.0  # Require speed to be sustained for ~1 second
    
    # Sprint/HSR threshold presets (with ≥1s dwell + hysteresis)
    # GPS standard: 19.8 km/h HSR, 25.2 km/h Sprint
    SPEED_PRESET = 'gps_standard'  # Options: 'gps_standard', 'gps_round', 'percent_max'
    HIGH_SPEED_THRESHOLD_MPH = 12.3  # 19.8 km/h (GPS standard)
    SPRINT_THRESHOLD_MPH = 15.7  # 25.2 km/h (GPS standard)
    
    # Alternative presets (applied if SPEED_PRESET changed):
    # 'gps_round': 20 km/h (12.4 mph) HSR, 25 km/h (15.5 mph) sprint
    # 'percent_max': 60% of personal max for HSR, 80% for sprint
    
    # Injury risk thresholds (based on workload)
    INJURY_RISK_LOW_DISTANCE_KM = 5.0
    INJURY_RISK_HIGH_DISTANCE_KM = 10.0
    INJURY_RISK_LOW_SPRINTS = 20
    INJURY_RISK_HIGH_SPRINTS = 50
    
    # Speed zone thresholds (km/h) - configurable, written to meta.json
    ZONE_WALK_KMH = 7.0
    ZONE_JOG_KMH = 15.0
    ZONE_RUN_KMH = 20.0
    ZONE_HSR_KMH = 25.0
    # Sprint zone: >= ZONE_HSR_KMH
    
    # Acceleration/deceleration thresholds
    ACCEL_HIGH_MS2 = 3.0  # High acceleration/deceleration threshold
    ACCEL_DWELL_S = 0.7  # Minimum duration for accel/decel event
    
    # Heatmap grid configuration
    HEATMAP_GRID = (21, 14)  # 21 cells x 14 cells = 5m x ~4.857m cells
    
    def __init__(self, calibration_path: Optional[str] = None, use_default_if_missing: bool = False):
        """Initialize config with optional calibration.
        
        Args:
            calibration_path: Path to calibration file
            use_default_if_missing: Try default calibration if path not provided
        """
        self.homography_matrix = None
        self.image_points = None
        self.pitch_points = None
        self.calibration_source = None
        self.calibration_warning = None  # Store warning for meta.json
        
        if calibration_path:
            self.load_calibration(calibration_path)
            self.calibration_source = calibration_path
        elif use_default_if_missing:
            # Try default calibration
            default_path = Path(__file__).parent / "config" / "default_calibration.json"
            if default_path.exists():
                self.calibration_warning = f"Using default calibration from {default_path.name} - create custom calibration for accurate results"
                print(f"Warning: {self.calibration_warning}")
                self.load_calibration(str(default_path))
                self.calibration_source = str(default_path)
    
    def load_calibration(self, path: str):
        """Load calibration from JSON or YAML file.
        
        Expected format:
        {
            "pitch_dimensions": {"width_m": 68.0, "length_m": 105.0},
            "correspondences": [
                {"image": [x1, y1], "pitch": [px1, py1]},
                {"image": [x2, y2], "pitch": [px2, py2]},
                ...
            ]
        }
        """
        path_obj = Path(path)
        
        if path_obj.suffix == '.json':
            with open(path_obj, 'r') as f:
                data = json.load(f)
        elif path_obj.suffix in ['.yaml', '.yml']:
            with open(path_obj, 'r') as f:
                data = yaml.safe_load(f)
        else:
            raise ValueError(f"Unsupported calibration format: {path_obj.suffix}")
        
        if 'pitch_dimensions' in data:
            self.PITCH_WIDTH_M = data['pitch_dimensions'].get('width_m', self.PITCH_WIDTH_M)
            self.PITCH_LENGTH_M = data['pitch_dimensions'].get('length_m', self.PITCH_LENGTH_M)
        
        correspondences = data.get('correspondences', [])
        if len(correspondences) < 4:
            raise ValueError("Need at least 4 point correspondences for homography")
        
        self.image_points = [c['image'] for c in correspondences]
        self.pitch_points = [c['pitch'] for c in correspondences]
    
    def get_example_calibration(self) -> Dict:
        """Return example calibration structure."""
        return {
            "pitch_dimensions": {
                "width_m": 68.0,
                "length_m": 105.0
            },
            "correspondences": [
                {"image": [100, 200], "pitch": [0, 0]},
                {"image": [1800, 200], "pitch": [105, 0]},
                {"image": [1800, 900], "pitch": [105, 68]},
                {"image": [100, 900], "pitch": [0, 68]}
            ]
        }
