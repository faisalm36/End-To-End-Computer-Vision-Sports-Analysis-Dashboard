"""Homography-based coordinate transformation from pixels to pitch meters."""

import cv2
import numpy as np
from typing import List, Tuple, Optional


class HomographyTransform:
    """Transform pixel coordinates to pitch coordinates using homography."""
    
    def __init__(
        self,
        image_points: List[List[float]],
        pitch_points: List[List[float]],
        pitch_width_m: float = 68.0,
        pitch_length_m: float = 105.0
    ):
        """Initialize homography from point correspondences.
        
        Args:
            image_points: List of [x, y] pixel coordinates
            pitch_points: List of [x, y] pitch coordinates in meters
            pitch_width_m: Pitch width in meters
            pitch_length_m: Pitch length in meters
        """
        if len(image_points) < 4 or len(pitch_points) < 4:
            raise ValueError("Need at least 4 point correspondences")
        
        if len(image_points) != len(pitch_points):
            raise ValueError("Image and pitch points must have same length")
        
        self.pitch_width_m = pitch_width_m
        self.pitch_length_m = pitch_length_m
        
        # Convert to numpy arrays
        src_points = np.array(image_points, dtype=np.float32)
        dst_points = np.array(pitch_points, dtype=np.float32)
        
        # Compute homography matrix
        self.H, self.status = cv2.findHomography(src_points, dst_points, cv2.RANSAC, 5.0)
        
        if self.H is None:
            raise ValueError("Failed to compute homography matrix")
    
    def transform_point(self, x: float, y: float) -> Optional[Tuple[float, float]]:
        """Transform single point from pixel to pitch coordinates.
        
        Args:
            x: Pixel x coordinate
            y: Pixel y coordinate
        
        Returns:
            (pitch_x, pitch_y) in meters, or None if invalid
        """
        if self.H is None:
            return None
        
        # Transform using homography
        point = np.array([[[x, y]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.H)
        
        pitch_x = float(transformed[0, 0, 0])
        pitch_y = float(transformed[0, 0, 1])
        
        # Validate within pitch bounds (with some margin for error)
        margin = 5.0  # meters
        if (-margin <= pitch_x <= self.pitch_length_m + margin and
            -margin <= pitch_y <= self.pitch_width_m + margin):
            return pitch_x, pitch_y
        
        return None
    
    def transform_bbox_center(self, bbox: List[float]) -> Optional[Tuple[float, float]]:
        """Transform bounding box center to pitch coordinates.
        
        Args:
            bbox: Bounding box [x1, y1, x2, y2]
        
        Returns:
            (pitch_x, pitch_y) in meters, or None if invalid
        """
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        
        return self.transform_point(center_x, center_y)
    
    def transform_foot_position(self, bbox: List[float]) -> Optional[Tuple[float, float]]:
        """Transform player foot position (bottom center) to pitch coordinates.
        
        Args:
            bbox: Player bounding box [x1, y1, x2, y2]
        
        Returns:
            (pitch_x, pitch_y) in meters, or None if invalid
        """
        foot_x = (bbox[0] + bbox[2]) / 2
        foot_y = bbox[3]  # Bottom of bbox
        
        return self.transform_point(foot_x, foot_y)
