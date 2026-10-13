"""
Pitch keypoint calibration with:
- Pluggable keypoint model
- RANSAC homography estimation
- Reprojection error gating
- Temporal smoothing for fixed/moving cameras
- Lens undistortion support
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict
from pathlib import Path


class PitchKeypointCalibrator:
    """
    Automatic pitch calibration using keypoint detection.
    
    Supports:
    - Pluggable pitch keypoint models (e.g., roboflow/sports 32-keypoint)
    - RANSAC-based homography with outlier rejection
    - Reprojection error gating
    - Temporal smoothing (one H for fixed camera, per-frame for moving)
    - Optional lens undistortion
    """
    
    # Standard pitch dimensions (FIFA)
    PITCH_LENGTH_M = 105.0
    PITCH_WIDTH_M = 68.0
    
    # Keypoint template: 32 pitch markings (corners, penalty areas, etc.)
    # These would be populated by a trained keypoint model
    STANDARD_PITCH_KEYPOINTS_M = [
        # Format: [x, y] in meters
        # Corners
        [0, 0], [105, 0], [105, 68], [0, 68],
        # Penalty areas, center circle, etc. (placeholder)
        # A real implementation would use the full 32-point template
    ]
    
    def __init__(
        self,
        pitch_length_m: float = 105.0,
        pitch_width_m: float = 68.0,
        ransac_threshold: float = 5.0,
        max_reprojection_error: float = 10.0,
        min_keypoints: int = 4,
        temporal_smoothing_alpha: float = 0.7,
        undistort_coeffs: Optional[Tuple] = None
    ):
        """Initialize calibrator.
        
        Args:
            pitch_length_m: Pitch length in meters
            pitch_width_m: Pitch width in meters
            ransac_threshold: RANSAC inlier threshold (pixels)
            max_reprojection_error: Maximum mean reprojection error to accept (pixels)
            min_keypoints: Minimum keypoints required for homography
            temporal_smoothing_alpha: Smoothing factor for temporal filtering (0=no smooth, 1=full smooth)
            undistort_coeffs: Optional (k1, k2, p1, p2, k3) distortion coefficients
        """
        self.pitch_length_m = pitch_length_m
        self.pitch_width_m = pitch_width_m
        self.ransac_threshold = ransac_threshold
        self.max_reprojection_error = max_reprojection_error
        self.min_keypoints = min_keypoints
        self.temporal_smoothing_alpha = temporal_smoothing_alpha
        self.undistort_coeffs = undistort_coeffs
        
        # Previous homography for temporal smoothing
        self.prev_H = None
        
        # Keypoint model (placeholder - would be loaded from trained model)
        self.keypoint_model = None
    
    def load_keypoint_model(self, model_path: str):
        """Load pitch keypoint detection model.
        
        Args:
            model_path: Path to trained keypoint model
        """
        # Placeholder: in a real implementation, this would load a model
        # e.g., from roboflow/sports or a custom trained model
        print(f"Note: Keypoint model loading not implemented. Using manual calibration fallback.")
        self.keypoint_model = None
    
    def detect_pitch_keypoints(self, frame: np.ndarray) -> Optional[List[Tuple[float, float]]]:
        """Detect pitch keypoints in frame.
        
        Args:
            frame: Input video frame
        
        Returns:
            List of [x, y] keypoint coordinates, or None if detection fails
        """
        if self.keypoint_model is None:
            return None
        
        # Placeholder: run keypoint model
        # Real implementation would return detected keypoint image coordinates
        return None
    
    def estimate_homography(
        self,
        image_points: List[Tuple[float, float]],
        pitch_points: List[Tuple[float, float]]
    ) -> Tuple[Optional[np.ndarray], Dict]:
        """Estimate homography with RANSAC and quality metrics.
        
        Args:
            image_points: List of [x, y] pixel coordinates
            pitch_points: List of [x, y] pitch coordinates in meters
        
        Returns:
            Tuple of (homography matrix or None, quality dict)
        """
        if len(image_points) < self.min_keypoints or len(pitch_points) < self.min_keypoints:
            return None, {'error': 'insufficient_points', 'count': len(image_points)}
        
        if len(image_points) != len(pitch_points):
            return None, {'error': 'mismatched_points'}
        
        src_pts = np.array(image_points, dtype=np.float32)
        dst_pts = np.array(pitch_points, dtype=np.float32)
        
        # Compute homography with RANSAC
        H, mask = cv2.findHomography(
            src_pts, 
            dst_pts, 
            cv2.RANSAC, 
            self.ransac_threshold
        )
        
        if H is None:
            return None, {'error': 'homography_failed'}
        
        # Compute reprojection error
        inliers = mask.sum() if mask is not None else len(src_pts)
        reprojection_errors = []
        
        for i, (src, dst) in enumerate(zip(src_pts, dst_pts)):
            # Transform src through H
            src_h = np.array([[src[0]], [src[1]], [1.0]])
            dst_pred_h = H @ src_h
            dst_pred = dst_pred_h[:2] / dst_pred_h[2]
            
            error = np.linalg.norm(dst - dst_pred.flatten())
            reprojection_errors.append(error)
        
        mean_error = np.mean(reprojection_errors)
        max_error = np.max(reprojection_errors)
        
        quality = {
            'inliers': int(inliers),
            'total_points': len(src_pts),
            'inlier_ratio': inliers / len(src_pts),
            'mean_reprojection_error': float(mean_error),
            'max_reprojection_error': float(max_error),
            'method': 'RANSAC'
        }
        
        # Reject if reprojection error too high
        if mean_error > self.max_reprojection_error:
            return None, {**quality, 'error': 'high_reprojection_error'}
        
        return H, quality
    
    def smooth_homography(self, H_new: np.ndarray) -> np.ndarray:
        """Apply temporal smoothing to homography (for fixed camera).
        
        Args:
            H_new: New homography matrix
        
        Returns:
            Smoothed homography
        """
        if self.prev_H is None:
            self.prev_H = H_new.copy()
            return H_new
        
        # Exponential moving average
        alpha = self.temporal_smoothing_alpha
        H_smooth = alpha * self.prev_H + (1 - alpha) * H_new
        
        # Normalize
        H_smooth = H_smooth / H_smooth[2, 2]
        
        self.prev_H = H_smooth.copy()
        return H_smooth
    
    def undistort_frame(self, frame: np.ndarray, camera_matrix: np.ndarray) -> np.ndarray:
        """Apply lens undistortion to frame.
        
        Args:
            frame: Input frame
            camera_matrix: Camera intrinsic matrix
        
        Returns:
            Undistorted frame
        """
        if self.undistort_coeffs is None:
            return frame
        
        dist_coeffs = np.array(self.undistort_coeffs)
        h, w = frame.shape[:2]
        
        # Get optimal new camera matrix
        new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
            camera_matrix, dist_coeffs, (w, h), 1, (w, h)
        )
        
        # Undistort
        undistorted = cv2.undistort(frame, camera_matrix, dist_coeffs, None, new_camera_matrix)
        
        # Crop to ROI
        x, y, w, h = roi
        undistorted = undistorted[y:y+h, x:x+w]
        
        return undistorted
    
    def calibrate_from_keypoints(
        self,
        frame: np.ndarray,
        smooth: bool = True
    ) -> Tuple[Optional[np.ndarray], Dict]:
        """Automatic calibration from detected keypoints.
        
        Args:
            frame: Input video frame
            smooth: Apply temporal smoothing
        
        Returns:
            Tuple of (homography matrix or None, quality dict)
        """
        # Detect keypoints
        image_keypoints = self.detect_pitch_keypoints(frame)
        
        if image_keypoints is None:
            return None, {'error': 'keypoint_detection_failed'}
        
        # Match to pitch template (placeholder - would use model output)
        pitch_keypoints = self.STANDARD_PITCH_KEYPOINTS_M[:len(image_keypoints)]
        
        # Estimate homography
        H, quality = self.estimate_homography(image_keypoints, pitch_keypoints)
        
        if H is None:
            return None, quality
        
        # Smooth if requested
        if smooth:
            H = self.smooth_homography(H)
            quality['smoothed'] = True
        
        return H, quality


class HomographyTransformEnhanced:
    """Enhanced homography transform with per-frame support and quality tracking."""
    
    def __init__(
        self,
        image_points: Optional[List[List[float]]] = None,
        pitch_points: Optional[List[List[float]]] = None,
        pitch_width_m: float = 68.0,
        pitch_length_m: float = 105.0,
        calibrator: Optional[PitchKeypointCalibrator] = None
    ):
        """Initialize enhanced homography transform.
        
        Args:
            image_points: Manual image points (fallback)
            pitch_points: Manual pitch points (fallback)
            pitch_width_m: Pitch width
            pitch_length_m: Pitch length
            calibrator: Optional PitchKeypointCalibrator for automatic calibration
        """
        self.pitch_width_m = pitch_width_m
        self.pitch_length_m = pitch_length_m
        self.calibrator = calibrator
        
        # Manual homography (fallback)
        self.H_manual = None
        self.calibration_quality = None
        
        if image_points and pitch_points:
            self._compute_manual_homography(image_points, pitch_points)
    
    def _compute_manual_homography(
        self,
        image_points: List[List[float]],
        pitch_points: List[List[float]]
    ):
        """Compute homography from manual point correspondences."""
        if len(image_points) < 4 or len(pitch_points) < 4:
            raise ValueError("Need at least 4 point correspondences")
        
        if len(image_points) != len(pitch_points):
            raise ValueError("Image and pitch points must have same length")
        
        src_points = np.array(image_points, dtype=np.float32)
        dst_points = np.array(pitch_points, dtype=np.float32)
        
        # Use RANSAC for robustness
        self.H_manual, status = cv2.findHomography(src_points, dst_points, cv2.RANSAC, 5.0)
        
        if self.H_manual is None:
            raise ValueError("Failed to compute homography matrix")
        
        # Compute quality metrics
        inliers = status.sum() if status is not None else len(src_points)
        self.calibration_quality = {
            'method': 'manual',
            'inliers': int(inliers),
            'total_points': len(src_points),
            'inlier_ratio': inliers / len(src_points)
        }
    
    def transform_point(
        self,
        x: float,
        y: float,
        H: Optional[np.ndarray] = None
    ) -> Optional[Tuple[float, float]]:
        """Transform point from pixel to pitch coordinates.
        
        Args:
            x: Pixel x
            y: Pixel y
            H: Homography matrix (uses manual if None)
        
        Returns:
            (pitch_x, pitch_y) or None
        """
        if H is None:
            H = self.H_manual
        
        if H is None:
            return None
        
        point = np.array([[[x, y]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, H)
        
        pitch_x = float(transformed[0, 0, 0])
        pitch_y = float(transformed[0, 0, 1])
        
        # Validate within pitch bounds (with margin)
        margin = 5.0
        if (-margin <= pitch_x <= self.pitch_length_m + margin and
            -margin <= pitch_y <= self.pitch_width_m + margin):
            return pitch_x, pitch_y
        
        return None
    
    def transform_bbox_center(
        self,
        bbox: List[float],
        H: Optional[np.ndarray] = None
    ) -> Optional[Tuple[float, float]]:
        """Transform bbox center to pitch coordinates."""
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        return self.transform_point(center_x, center_y, H)
    
    def transform_foot_position(
        self,
        bbox: List[float],
        H: Optional[np.ndarray] = None
    ) -> Optional[Tuple[float, float]]:
        """Transform player foot position (bottom center) to pitch coordinates."""
        foot_x = (bbox[0] + bbox[2]) / 2
        foot_y = bbox[3]  # Bottom of bbox
        return self.transform_point(foot_x, foot_y, H)
    
    def get_calibration_quality(self) -> Optional[Dict]:
        """Get calibration quality metrics."""
        return self.calibration_quality
