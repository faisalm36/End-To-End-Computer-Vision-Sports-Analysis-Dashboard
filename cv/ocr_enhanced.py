"""
Enhanced jersey number OCR with:
- Legibility filter (size, sharpness, contrast)
- Confidence-weighted voting per tracklet
- Roster constraint
- Optional PARSeq backend
"""

import cv2
import numpy as np
import easyocr
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter


class LegibilityFilter:
    """Filter jersey crops for OCR quality."""
    
    def __init__(
        self,
        min_height_px: int = 40,
        min_width_px: int = 30,
        min_sharpness: float = 20.0,
        min_contrast: float = 30.0
    ):
        """Initialize legibility filter.
        
        Args:
            min_height_px: Minimum crop height in pixels
            min_width_px: Minimum crop width in pixels
            min_sharpness: Minimum Laplacian variance (sharpness)
            min_contrast: Minimum standard deviation (contrast)
        """
        self.min_height_px = min_height_px
        self.min_width_px = min_width_px
        self.min_sharpness = min_sharpness
        self.min_contrast = min_contrast
    
    def is_legible(self, crop: np.ndarray) -> Tuple[bool, Dict[str, float]]:
        """Check if crop is legible for OCR.
        
        Args:
            crop: Image crop (BGR or grayscale)
        
        Returns:
            (is_legible, quality_metrics)
        """
        if crop is None or crop.size == 0:
            return False, {'error': 'empty_crop'}
        
        h, w = crop.shape[:2]
        
        # Size check
        if h < self.min_height_px or w < self.min_width_px:
            return False, {
                'height': h,
                'width': w,
                'reason': 'too_small'
            }
        
        # Convert to grayscale if needed
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop
        
        # Sharpness: Laplacian variance
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = laplacian.var()
        
        # Contrast: standard deviation
        contrast = gray.std()
        
        quality = {
            'height': h,
            'width': w,
            'sharpness': float(sharpness),
            'contrast': float(contrast)
        }
        
        # Check thresholds
        if sharpness < self.min_sharpness:
            quality['reason'] = 'blurry'
            return False, quality
        
        if contrast < self.min_contrast:
            quality['reason'] = 'low_contrast'
            return False, quality
        
        return True, quality


class EnhancedJerseyReader:
    """Enhanced jersey number OCR with legibility filtering and roster constraints."""
    
    def __init__(
        self,
        languages: List[str] = ['en'],
        gpu: bool = True,
        backend: str = 'easyocr',  # 'easyocr' or 'parseq'
        legibility_filter: Optional[LegibilityFilter] = None,
        roster_team_a: Optional[List[int]] = None,
        roster_team_b: Optional[List[int]] = None
    ):
        """Initialize enhanced OCR reader.
        
        Args:
            languages: Languages for OCR
            gpu: Use GPU if available
            backend: OCR backend ('easyocr' or 'parseq')
            legibility_filter: Optional LegibilityFilter
            roster_team_a: Valid jersey numbers for team A
            roster_team_b: Valid jersey numbers for team B
        """
        self.backend = backend
        self.gpu = gpu
        
        # Legibility filter
        if legibility_filter:
            self.legibility_filter = legibility_filter
        else:
            self.legibility_filter = LegibilityFilter()
        
        # Roster constraints
        self.roster_team_a = set(roster_team_a) if roster_team_a else None
        self.roster_team_b = set(roster_team_b) if roster_team_b else None
        
        # Initialize backend
        if backend == 'easyocr':
            print("Initializing EasyOCR reader...")
            import warnings
            warnings.filterwarnings('ignore', category=UserWarning, message='.*quantize_per_tensor.*')
            self.reader = easyocr.Reader(languages, gpu=gpu, quantize=False if not gpu else True)
        elif backend == 'parseq':
            print("Note: PARSeq backend not implemented yet. Falling back to EasyOCR.")
            self.reader = easyocr.Reader(languages, gpu=gpu, quantize=False if not gpu else True)
            self.backend = 'easyocr'
        else:
            raise ValueError(f"Unknown backend: {backend}")
        
        # Track readings per player: track_id -> list of (number, confidence, quality)
        self.track_readings: Dict[int, List[Tuple[int, float, Dict]]] = defaultdict(list)
    
    def read_jersey_number(
        self,
        frame: np.ndarray,
        bbox: List[float],
        conf_threshold: float = 0.5,
        allowlist: str = '0123456789',
        check_legibility: bool = True
    ) -> Optional[Tuple[int, float, Dict]]:
        """Read jersey number from player crop with legibility check.
        
        Args:
            frame: Full video frame
            bbox: Player bounding box [x1, y1, x2, y2]
            conf_threshold: Minimum OCR confidence
            allowlist: Characters to allow
            check_legibility: Apply legibility filter
        
        Returns:
            (jersey_number, confidence, quality_dict) or None
        """
        x1, y1, x2, y2 = [int(c) for c in bbox]
        
        # Ensure bbox is within frame
        h, w = frame.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)
        
        if x2 <= x1 or y2 <= y1:
            return None
        
        # Crop to torso region (middle 60% height, full width)
        crop_h = y2 - y1
        torso_y1 = y1 + int(crop_h * 0.2)
        torso_y2 = y1 + int(crop_h * 0.8)
        
        crop = frame[torso_y1:torso_y2, x1:x2]
        
        if crop.size == 0:
            return None
        
        # Legibility check
        if check_legibility:
            legible, quality = self.legibility_filter.is_legible(crop)
            if not legible:
                return None
        else:
            quality = {}
        
        # Preprocessing for better OCR
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        
        # Contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Resize if too small
        min_height = 64
        if enhanced.shape[0] < min_height:
            scale = min_height / enhanced.shape[0]
            enhanced = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        
        # Run OCR
        try:
            results = self.reader.readtext(
                enhanced,
                allowlist=allowlist,
                detail=1,
                paragraph=False
            )
            
            # Find best result
            best_number = None
            best_conf = 0.0
            
            for (bbox_ocr, text, conf) in results:
                if conf >= conf_threshold and text.isdigit():
                    num = int(text)
                    if 0 <= num <= 99 and conf > best_conf:
                        best_number = num
                        best_conf = conf
            
            if best_number is not None:
                return (best_number, best_conf, quality)
        
        except Exception as e:
            return None
        
        return None
    
    def add_reading(
        self,
        track_id: int,
        reading: Optional[Tuple[int, float, Dict]],
        team: Optional[int] = None
    ):
        """Add a jersey number reading for a track.
        
        Args:
            track_id: Player track ID
            reading: (number, confidence, quality) tuple
            team: Team assignment (0 or 1) for roster constraint
        """
        if reading is None:
            return
        
        number, confidence, quality = reading
        
        # Apply roster constraint if available
        if team is not None:
            if team == 0 and self.roster_team_a is not None:
                if number not in self.roster_team_a:
                    return  # Invalid number for team A
            elif team == 1 and self.roster_team_b is not None:
                if number not in self.roster_team_b:
                    return  # Invalid number for team B
        
        self.track_readings[track_id].append((number, confidence, quality))
    
    def get_jersey_number_weighted(
        self,
        track_id: int,
        min_readings: int = 3
    ) -> Optional[int]:
        """Get jersey number with confidence-weighted voting.
        
        Args:
            track_id: Player track ID
            min_readings: Minimum readings before returning result
        
        Returns:
            Most likely jersey number or None
        """
        readings = self.track_readings.get(track_id, [])
        
        if len(readings) < min_readings:
            return None
        
        # Confidence-weighted voting
        vote_weights: Dict[int, float] = defaultdict(float)
        
        for number, confidence, quality in readings:
            vote_weights[number] += confidence
        
        if not vote_weights:
            return None
        
        # Return number with highest weight
        best_number = max(vote_weights.items(), key=lambda x: x[1])
        return best_number[0]
    
    def get_all_jersey_numbers(self, min_readings: int = 3) -> Dict[int, Optional[int]]:
        """Get confidence-weighted jersey numbers for all tracks.
        
        Args:
            min_readings: Minimum readings per track
        
        Returns:
            Dict mapping track_id to jersey_number
        """
        result = {}
        for track_id in self.track_readings.keys():
            result[track_id] = self.get_jersey_number_weighted(track_id, min_readings)
        return result
