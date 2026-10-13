"""Jersey number OCR using EasyOCR."""

import cv2
import numpy as np
import easyocr
from typing import Dict, List, Optional
from collections import defaultdict, Counter


class JerseyNumberReader:
    """Read jersey numbers from player bounding boxes."""
    
    def __init__(self, languages: List[str] = ['en'], gpu: bool = True):
        """Initialize EasyOCR reader.
        
        Args:
            languages: List of languages for OCR
            gpu: Use GPU if available
        """
        print("Initializing EasyOCR reader...")
        
        # Suppress torch quantization deprecation warnings
        import warnings
        warnings.filterwarnings('ignore', category=UserWarning, message='.*quantize_per_tensor.*')
        
        # Pass quantize=False on mps/cpu to avoid deprecation warning
        # (quantization mainly benefits CUDA inference)
        self.reader = easyocr.Reader(languages, gpu=gpu, quantize=False if not gpu else True)
        
        # Track readings per player for majority voting
        self.track_numbers: Dict[int, List[int]] = defaultdict(list)
    
    def read_jersey_number(
        self,
        frame: np.ndarray,
        bbox: List[float],
        conf_threshold: float = 0.5,
        allowlist: str = '0123456789'
    ) -> Optional[int]:
        """Read jersey number from player crop.
        
        Args:
            frame: Full video frame
            bbox: Player bounding box [x1, y1, x2, y2]
            conf_threshold: Minimum OCR confidence
            allowlist: Characters to allow (digits only)
        
        Returns:
            Jersey number or None
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
        
        # Preprocessing for better OCR
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        
        # Contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)
        
        # Resize if too small
        min_height = 64
        if enhanced.shape[0] < min_height:
            scale = min_height / enhanced.shape[0]
            enhanced = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        
        # Run OCR with allowlist
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
            
            return best_number
        
        except Exception as e:
            return None
    
    def add_reading(self, track_id: int, jersey_number: Optional[int]):
        """Add a jersey number reading for a track."""
        if jersey_number is not None:
            self.track_numbers[track_id].append(jersey_number)
    
    def get_majority_vote(self, track_id: int, min_readings: int = 3) -> Optional[int]:
        """Get majority voted jersey number for a track.
        
        Args:
            track_id: Player track ID
            min_readings: Minimum readings before returning result
        
        Returns:
            Most common jersey number or None
        """
        readings = self.track_numbers.get(track_id, [])
        
        if len(readings) < min_readings:
            return None
        
        counter = Counter(readings)
        most_common = counter.most_common(1)
        
        if most_common:
            return most_common[0][0]
        
        return None
    
    def get_all_jersey_numbers(self) -> Dict[int, Optional[int]]:
        """Get majority voted jersey numbers for all tracks."""
        result = {}
        for track_id in self.track_numbers.keys():
            result[track_id] = self.get_majority_vote(track_id)
        return result
