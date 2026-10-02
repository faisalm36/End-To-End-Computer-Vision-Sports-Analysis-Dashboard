# CV Pipeline v2.0 Implementation Status

## Completed (Committed)

### Core Modules Created ✓
1. **tracking.py** - EnhancedTracker with BoT-SORT/ByteTrack support
2. **ball_tracking.py** - BallTracker with tiled inference, Kalman filtering, interpolation flags
3. **calibration.py** - PitchKeypointCalibrator with RANSAC, temporal smoothing
4. **calibrate_interactive.py** - OpenCV click-to-calibrate helper tool
5. **ocr_enhanced.py** - EnhancedJerseyReader with legibility filter, roster constraints
6. **team_classifier_enhanced.py** - TeamClassifierEnhanced with kit priors, GK detection
7. **tracklet_stitching.py** - TrackletStitcher for stable player_uid
8. **Updated metrics.py** - is_detected flags, top speed from detected only, acceleration cap
9. **Updated config.py** - v2.0 options for tracker, ball, kits, roster
10. **Updated requirements.txt** - Added filterpy, networkx

### CLI Updated ✓
- Added `--tracker` (botsort/bytetrack)
- Added `--ball-model` for fine-tuned ball weights
- Added `--kits` for kit colour priors
- Added `--roster` for jersey number constraints

## Remaining Work (To Complete)

### 1. Integrate New Modules into Pipeline (CRITICAL)
The new modules exist but aren't yet integrated into `pipeline.py`. Need to:
- Replace old DetectionTracker with EnhancedTracker
- Integrate BallTracker for separate ball detection
- Use EnhancedJerseyReader and TeamClassifierEnhanced
- Implement tracklet stitching post-processing
- Add player_uid field to outputs
- Update detection format to include is_detected flags

### 2. Update Pipeline.py Structure
```python
# Pseudocode for integration:
# 1. Initialize EnhancedTracker (botsort/bytetrack)
# 2. Initialize BallTracker separately
# 3. For each frame:
#    - Track players with EnhancedTracker
#    - Detect ball with BallTracker
#    - Add positions with is_detected=True for detected frames
# 4. After all frames:
#    - Fit team classifier (per-tracklet)
#    - Run OCR with legibility filtering
#    - Create tracklet stitcher
#    - Stitch tracklets into player_uids
#    - Aggregate stats per player_uid
#    - Detect goalkeepers based on positions
```

### 3. Output Format Changes
Add to tracking_detections.json:
- `player_uid` field (stable across tracklets)
- `is_detected` flag (True/False/null)
- `is_interpolated` flag for ball

Add to player_match_stats.json:
- `player_uid` field
- `contributing_track_ids` list
- `detected_frames` count
- `total_frames` count

Add to meta.json:
- `pipeline_version`: "2.0.0"
- `tracker`: "botsort" or "bytetrack"
- `ball_tracking_method`: "tiled" or "simple"
- `tracklet_stitching_enabled`: true/false
- `calibration_quality` dict (if available)

### 4. Tests to Create/Update
Files to create:
- `cv/tests/test_ball_tracking.py`
- `cv/tests/test_calibration.py`
- `cv/tests/test_tracklet_stitching.py`
- `cv/tests/test_ocr_enhanced.py`
- `cv/tests/test_team_classifier_enhanced.py`

Update existing tests to handle:
- 4-tuple positions (x, y, t, is_detected)
- player_uid fields
- New config options

### 5. Benchmark/Validation Harness
Create `cv/benchmark/`:
- `benchmark_speed_distance.py` - Compare against Metrica sample data
- `benchmark_jersey.py` - Evaluate on SoccerNet jersey dataset (if accessible)
- `validate_real_clip.py` - Test against known measured sprint

Requirements:
- Download scripts for public datasets (document licenses)
- RMSE calculation for speed/distance
- Accuracy metrics for jersey OCR
- Clear documentation on what datasets can/cannot be used

### 6. Documentation
Create/update:
- `cv/README.md` - Full v2.0 documentation
- `cv/CHANGELOG.md` - v1.2.0 → v2.0 changes
- `cv/docs/CALIBRATION.md` - How to use calibrate_interactive.py
- `cv/docs/ROSTER_KITS.md` - JSON format examples
- `cv/docs/MODEL_WEIGHTS.md` - Where to get ball/keypoint models

### 7. Known Limitations to Document
- Keypoint calibration model: interface ready, but no trained model shipped
  - Fallback: manual calibration via calibrate_interactive.py
  - Users must download/train their own keypoint model
- PARSeq OCR backend: interface ready, EasyOCR default
- ReID for BoT-SORT: optional, off by default (performance)
- Ball fine-tuned weights: pluggable but not shipped
- SigLIP team classification: documented but not implemented

## File Changes Summary

### Modified Files
1. `cv/config.py` - Added v2.0 options
2. `cv/metrics.py` - Added is_detected support, acceleration cap
3. `cv/run_pipeline.py` - Added CLI flags for tracker, kits, roster, ball-model
4. `cv/requirements.txt` - Added filterpy, networkx

### New Files
1. `cv/tracking.py` - Enhanced tracker
2. `cv/ball_tracking.py` - Ball tracker with Kalman
3. `cv/calibration.py` - Keypoint calibration
4. `cv/calibrate_interactive.py` - Interactive calibration tool
5. `cv/ocr_enhanced.py` - Enhanced OCR
6. `cv/team_classifier_enhanced.py` - Enhanced team classifier
7. `cv/tracklet_stitching.py` - Tracklet stitching

### Files Needing Major Updates
1. `cv/pipeline.py` - Integrate all new modules
2. `cv/detection.py` - May be replaced by tracking.py
3. All test files - Update for v2.0 changes

## Testing Strategy

### Unit Tests (Synthetic Data)
- Test each module independently
- Use mock data for positions, detections
- Verify is_detected flags propagate correctly

### Integration Test (Generated Video)
- Use existing `generate_test_video.py`
- Run full v2.0 pipeline
- Verify all output fields present
- Check meta.json has v2.0 markers

### Real Video Test (If Available)
- Small test clip with known ground truth
- Verify calibration with interactive tool
- Test roster constraints with known jersey numbers

## Mac Commands for User

### One-Time Setup
```bash
# Install dependencies
cd cv
pip install -r requirements.txt

# Optional: Download fine-tuned ball model (if available)
# wget https://example.com/ball_model.pt -O models/ball_yolov8.pt

# Create calibration for your video
python calibrate_interactive.py path/to/video_frame.jpg
# -> Saves calibration.json

# Create roster file (if known)
cat > roster.json << EOF
{
  "team_a": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  "team_b": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
}
EOF

# Create kits file (optional)
cat > kits.json << EOF
{
  "team_a": {"colour": [255, 0, 0], "name": "Red"},
  "team_b": {"colour": [0, 0, 255], "name": "Blue"}
}
EOF
```

### Running the Pipeline
```bash
# Basic run (v2.0 with BoT-SORT)
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --model yolov8x.pt \
  --device mps

# With roster and kits (recommended)
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --roster roster.json \
  --kits kits.json \
  --tracker botsort \
  --device mps

# With fine-tuned ball model (if available)
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --ball-model models/ball_yolov8.pt \
  --device mps

# Use ByteTrack instead of BoT-SORT
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --tracker bytetrack \
  --device mps
```

### Running Tests
```bash
# Run all tests
python -m unittest discover -s cv/tests -v

# Or with pytest
pytest cv/tests/ -v

# Run specific test
python -m unittest cv.tests.test_metrics
```

## Next Steps Priority

1. **CRITICAL**: Integrate new modules into pipeline.py
2. **HIGH**: Update tests to pass with new format
3. **HIGH**: Run end-to-end test on synthetic video
4. **MEDIUM**: Create benchmark harness
5. **MEDIUM**: Write comprehensive documentation
6. **LOW**: Optimize performance, add logging

## Output Field Changes

### tracking_detections.json (New Fields)
```json
{
  "player_uid": 0,           // NEW: Stable player ID across tracklets
  "track_id": 1,             // EXISTING: Short-term track ID
  "is_detected": true,       // NEW: True if detected, False if interpolated
  "is_interpolated": false   // NEW: For ball only
}
```

### player_match_stats.json (New Fields)
```json
{
  "player_uid": 0,           // NEW: Stable player ID
  "track_id": 1,             // DEPRECATED: Use player_uid
  "contributing_track_ids": [1, 15, 28],  // NEW: Which tracklets were stitched
  "detected_frames": 850,    // NEW: Frames with actual detection
  "total_frames": 900,       // NEW: Total frames (including interpolated)
  "jersey_number": 10
}
```

### meta.json (New Fields)
```json
{
  "pipeline_version": "2.0.0",
  "tracker": "botsort",
  "tracker_config": {"gmc": true, "reid": false},
  "ball_tracking_method": "tiled",
  "tracklet_stitching_enabled": true,
  "calibration_quality": {
    "method": "manual",
    "inliers": 4,
    "total_points": 4,
    "inlier_ratio": 1.0
  }
}
```
