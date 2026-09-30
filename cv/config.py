"""Configuration management for the CV pipeline."""

import yaml
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class Config:
    """Pipeline configuration (v2.0: commercial-quality tracking)."""
    
    # Pipeline version
    VERSION = "2.0.0"
    
    # Default pitch dimensions in meters (standard FIFA pitch)
    PITCH_WIDTH_M = 68.0
    PITCH_LENGTH_M = 105.0
    
    # Detection thresholds
    PERSON_CONF_THRESHOLD = 0.3
    BALL_CONF_THRESHOLD = 0.25
    IOU_THRESHOLD = 0.5
    
    # Tracking configuration (v2.0)
    TRACKER = 'botsort'  # 'botsort' or 'bytetrack'
    USE_REID = False  # Enable ReID for BoT-SORT (requires more compute)
    USE_GMC = True  # Camera motion compensation (enabled by default)
    
    # Ball tracking configuration (v2.0)
    BALL_USE_TILING = True  # Tiled inference for better small-object detection
    BALL_TILE_OVERLAP = 0.2  # Tile overlap ratio
    BALL_IMGSZ = 1280  # Ball inference resolution (higher for small objects)
    BALL_MAX_GAP_FRAMES = 15  # Maximum gap to interpolate
    
    # General inference resolution
    DEFAULT_IMGSZ = 640
    
    # OCR settings (v2.0: enhanced)
    OCR_CONF_THRESHOLD = 0.5
    OCR_ALLOWLIST = '0123456789'
    OCR_BACKEND = 'easyocr'  # 'easyocr' or 'parseq' (if available)
    OCR_USE_LEGIBILITY_FILTER = True  # Filter blurry/low-contrast crops
    
    # Tracklet stitching (v2.0)
    USE_TRACKLET_STITCHING = True  # Create stable player_uid across tracklets
    MAX_PLAYER_SPEED_MS = 12.0  # ~43 km/h, for motion gating in stitching
    
    # Speed/distance settings
    FPS_DEFAULT = 30.0
    MAX_PLAUSIBLE_SPEED_MPH = 25.0  # ~40 km/h, filters only extreme outliers
    MAX_ACCELERATION_MS2 = 6.0  # Maximum plausible acceleration (v2.0)
    SPEED_SMOOTHING_WINDOW = 5
    SUSTAINED_SPEED_WINDOW_S = 1.0  # Require speed to be sustained for ~1 second
    
    # Sprint/HSR threshold presets (with ≥1s dwell + hysteresis)
    # GPS standard: 19.8 km/h HSR, 25.2 km/h Sprint
    SPEED_PRESET = 'gps_standard'  # Options: 'gps_standard', 'gps_round', 'percent_max'
    HIGH_SPEED_THRESHOLD_MPH = 12.3  # 19.8 km/h (GPS standard)
    SPRINT_THRESHOLD_MPH = 15.7  # 25.2 km/h (GPS standard)
    
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
    
    def __init__(
        self,
        calibration_path: Optional[str] = None,
        use_default_if_missing: bool = False,
        kits_path: Optional[str] = None,
        roster_path: Optional[str] = None,
        tracker: str = 'botsort',
        device: str = 'auto'
    ):
        """Initialize config with optional calibration, kits, and roster.
        
        Args:
            calibration_path: Path to calibration file
            use_default_if_missing: Try default calibration if path not provided
            kits_path: Path to kit colours JSON (optional)
            roster_path: Path to roster JSON (optional)
            tracker: Tracker type ('botsort' or 'bytetrack')
            device: Device for inference
        """
        self.homography_matrix = None
        self.image_points = None
        self.pitch_points = None
        self.calibration_source = None
        self.calibration_warning = None  # Store warning for meta.json
        
        # Kit colours and roster
        self.kit_colours = None
        self.roster_team_a = None
        self.roster_team_b = None
        
        # Tracker config
        self.TRACKER = tracker
        self.DEVICE = device
        
        # Load calibration
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
        
        # Load kit colours
        if kits_path:
            self.load_kits(kits_path)
        
        # Load roster
        if roster_path:
            self.load_roster(roster_path)
    
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
    
    def load_kits(self, path: str):
        """Load kit colours from JSON file.
        
        Expected format:
        {
            "team_a": {"colour": [B, G, R]},
            "team_b": {"colour": [B, G, R]}
        }
        """
        path_obj = Path(path)
        
        with open(path_obj, 'r') as f:
            data = json.load(f)
        
        self.kit_colours = {
            'team_a': tuple(data['team_a']['colour']),
            'team_b': tuple(data['team_b']['colour'])
        }
        
        print(f"Loaded kit colours from {path}")
    
    def load_roster(self, path: str):
        """Load roster (valid jersey numbers) from JSON file.
        
        Expected format:
        {
            "team_a": [1, 2, 3, ..., 23],
            "team_b": [1, 2, 3, ..., 23]
        }
        """
        path_obj = Path(path)
        
        with open(path_obj, 'r') as f:
            data = json.load(f)
        
        self.roster_team_a = data.get('team_a', [])
        self.roster_team_b = data.get('team_b', [])
        
        print(f"Loaded rosters: Team A ({len(self.roster_team_a)} players), Team B ({len(self.roster_team_b)} players)")
    
    def get_example_kits(self) -> Dict:
        """Return example kit colours structure."""
        return {
            "team_a": {"colour": [255, 0, 0], "name": "Blue"},
            "team_b": {"colour": [0, 255, 255], "name": "Yellow"}
        }
    
    def get_example_roster(self) -> Dict:
        """Return example roster structure."""
        return {
            "team_a": list(range(1, 24)),
            "team_b": list(range(1, 24))
        }
    
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
