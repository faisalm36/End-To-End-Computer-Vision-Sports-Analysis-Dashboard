# Soccer CV Pipeline v2.0 - Commercial Quality Tracking

Upgraded soccer video analytics pipeline with tracking quality approaching commercial products (Veo, Pixellot, Spiideo, SkillCorner).

## Version 2.0 Upgrades

Based on competitor analysis and research briefs (`cv-gap-analysis-2026-09-30.md`, `competitor-cv-tech-2026-09-30.md`), v2.0 brings commercial-grade CV capabilities optimized for single-camera amateur footage on Apple Silicon Mac (MPS) or CPU.

### 1. Enhanced Tracking: BoT-SORT with GMC ✓
- **BoT-SORT** (Byte + CMC + ReID) as default tracker
- Camera Motion Compensation (GMC) for moving cameras
- Optional ReID for better identity persistence
- ByteTrack still available as fallback: `--tracker bytetrack`

### 2. Dedicated Ball Tracking ✓
- **Tiled/sliced inference** (SAHI-style) for small ball detection
- **Kalman filter** with maximum speed gating (~35 m/s)
- Gap interpolation with `is_detected` vs `is_interpolated` flags
- Pluggable fine-tuned ball weights: `--ball-model path/to/ball_model.pt`

### 3. Pitch Calibration ✓
- **Interactive click-to-calibrate tool**: `python cv/calibrate_interactive.py frame.jpg`
- Pluggable pitch-keypoint model support (interface ready, model not shipped)
- RANSAC homography with reprojection error gating
- Temporal smoothing (fixed camera) or per-frame (moving camera)
- Optional lens undistortion parameters
- Manual calibration JSON remains the fallback

### 4. Team Classification Enhancements ✓
- **Kit colour priors**: `--kits kits.json` (BGR colours for team_a, team_b)
- Per-tracklet classification (not per-frame)
- **Goalkeeper heuristic**: position-based + colour outlier detection
- Optional SigLIP embeddings (documented but not required)

### 5. Enhanced Jersey OCR ✓
- **Legibility filter**: size, sharpness, contrast checks before OCR
- **Confidence-weighted voting** per tracklet
- **Roster constraint**: `--roster roster.json` (valid numbers per team)
- Optional PARSeq backend (interface ready, EasyOCR default)

### 6. Tracklet Stitching → Stable `player_uid` ✓
- Offline stitching of short-term tracklets into stable player identities
- Cost function: team + jersey agreement + appearance similarity + motion feasibility
- Outputs `player_uid` (stable across match) + `track_id` (per tracklet)
- Stats aggregate per `player_uid` with `contributing_track_ids` list

### 7. Metrics Hygiene ✓
- `is_detected` flags on all positions (detected vs interpolated)
- **Top speed computed only from detected frames**
- **Acceleration cap**: ~6 m/s² (clips implausible spikes)
- `detected_frames` and `total_frames` fields in stats

### 8. Benchmark/Validation Harness (Planned)
- Scripts to evaluate against public datasets (Metrica, SoccerNet)
- Speed/distance RMSE against reference tracking data
- Jersey OCR accuracy on SoccerNet jersey benchmark
- Real-clip validation with known measured sprints
- *Note: Datasets not committed, download on demand*

## Installation

```bash
cd cv
pip install -r requirements.txt
```

**New dependencies in v2.0:**
- `filterpy>=1.4.5` (Kalman filtering)
- `networkx>=3.0` (graph-based tracklet stitching)

## Quick Start

### 1. Create Calibration (One-Time)

Extract a frame from your video:
```bash
ffmpeg -i match.mp4 -ss 00:01:00 -frames:v 1 frame.jpg
```

Run interactive calibration tool:
```bash
python cv/calibrate_interactive.py frame.jpg
```

**Instructions:**
- Click on pitch marking points (corners, penalty box corners, center circle)
- Enter corresponding pitch coordinates in meters for each point
- Press `s` to save `calibration.json`
- Press `u` to undo last point, `q` to quit

**Pitch coordinate system**: X: 0-105m (length), Y: 0-68m (width)

### 2. (Optional) Create Roster and Kits Files

**roster.json:**
```json
{
  "team_a": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  "team_b": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
}
```

**kits.json:**
```json
{
  "team_a": {"colour": [255, 0, 0], "name": "Red"},
  "team_b": {"colour": [0, 0, 255], "name": "Blue"}
}
```
*Note: Colours are BGR format (OpenCV convention)*

### 3. Run Pipeline

**Basic run:**
```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --model yolov8x.pt \
  --device mps
```

**With all v2.0 features:**
```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --roster roster.json \
  --kits kits.json \
  --tracker botsort \
  --device mps
```

**CLI flags (v2.0):**
- `--tracker {botsort,bytetrack}` - Tracker type (default: botsort)
- `--ball-model PATH` - Fine-tuned ball detection model (optional)
- `--kits PATH` - Kit colours JSON (optional)
- `--roster PATH` - Roster JSON with valid jersey numbers (optional)
- `--device {auto,cuda,mps,cpu}` - Device for inference

## Output Format (v2.0)

### New Fields in `tracking_detections.json`
```json
{
  "frame": 0,
  "track_id": 1,
  "player_uid": 0,           // NEW: Stable ID across tracklets
  "is_detected": true,       // NEW: True=detected, False=interpolated
  "pitch_x": 52.5,
  "pitch_y": 34.0,
  ...
}
```

### New Fields in `player_match_stats.json`
```json
{
  "player_uid": 0,                      // NEW: Stable player ID
  "contributing_track_ids": [1, 15],    // NEW: Which tracklets were stitched
  "detected_frames": 850,               // NEW: Frames with detection
  "total_frames": 900,                  // NEW: Total frames (incl interpolated)
  "top_speed_mph": 18.5,                // Now from detected frames only
  "jersey_number": 10,
  "team": 0,
  "role": "player",                     // or "goalkeeper", "referee"
  ...
}
```

### New Fields in `meta.json`
```json
{
  "pipeline_version": "2.0.0",
  "tracker": "botsort",
  "ball_tracking_method": "tiled",
  "tracklet_stitching_enabled": true,
  "calibration_quality": {              // NEW: Calibration metrics
    "method": "manual",
    "inliers": 4,
    "total_points": 4,
    "mean_reprojection_error": 2.3
  },
  ...
}
```

## Architecture

### v2.0 Pipeline Flow
```
1. Load video + calibration + roster/kits (if provided)
2. For each frame:
   - Detect & track players (EnhancedTracker: BoT-SORT/ByteTrack)
   - Detect ball (BallTracker: tiled inference + Kalman)
   - Add positions with is_detected=True for detected frames
3. Post-processing:
   - Fit team classifier (per-tracklet, with kit priors)
   - Run jersey OCR (with legibility filter, roster constraint)
   - Detect goalkeepers (position + colour heuristic)
   - Stitch tracklets → player_uid (team + jersey + appearance + motion)
   - Aggregate stats per player_uid
4. Save outputs with v2.0 fields
```

### Key Modules
- `tracking.py` - EnhancedTracker (BoT-SORT/ByteTrack + GMC)
- `ball_tracking.py` - BallTracker (tiled + Kalman + interpolation)
- `calibration.py` - PitchKeypointCalibrator (RANSAC + smoothing)
- `calibrate_interactive.py` - Interactive calibration tool
- `ocr_enhanced.py` - EnhancedJerseyReader (legibility + roster)
- `team_classifier_enhanced.py` - TeamClassifierEnhanced (kits + GK)
- `tracklet_stitching.py` - TrackletStitcher (offline stitching)
- `metrics.py` - Updated with is_detected support + accel cap

## Known Limitations

### Not Shipped (Interfaces Ready)
- **Pitch keypoint model**: Pluggable interface exists, but no trained model included
  - **Workaround**: Use `calibrate_interactive.py` for manual calibration
  - **Future**: Download or train roboflow/sports 32-keypoint model
  
- **PARSeq OCR backend**: Interface ready, EasyOCR default
  - **Workaround**: EasyOCR works well for most cases
  - **Future**: Integrate PARSeq for better jersey OCR accuracy
  
- **Fine-tuned ball weights**: Pluggable via `--ball-model`, but not shipped
  - **Workaround**: COCO "sports ball" class works reasonably
  - **Future**: Fine-tune YOLOv8 on soccer ball dataset
  
- **ReID for BoT-SORT**: Optional, off by default (performance cost)
  - **Workaround**: Tracklet stitching handles most re-ID cases
  - **Future**: Enable with custom ReID model if needed

### Hardware Constraints
Cannot match professional products that use:
- Fixed multi-lens panoramic cameras (Veo, Pixellot, Hudl Focus)
- 28-30 camera stadium rigs (Genius/Second Spectrum)
- PTZ auto-follow cameras (XbotGo gimbal)

**Recommendation**: Use fixed tripod, elevated, whole pitch in view, 1080p+ @ 25+ fps

## Testing

```bash
# Run all tests
python -m unittest discover -s cv/tests -v

# Or with pytest
pytest cv/tests/ -v

# Specific test
python -m unittest cv.tests.test_metrics
```

## Benchmarking

Create `cv/benchmark/` directory with:
- `benchmark_speed_distance.py` - Compare against Metrica sample data
- `benchmark_jersey.py` - Evaluate on SoccerNet jersey dataset
- `validate_real_clip.py` - Test against known measured sprint

*Note: Public datasets must be downloaded separately due to license terms*

## Documentation

- `V2_IMPLEMENTATION_STATUS.md` - Implementation progress and remaining work
- `CHANGELOG.md` - v1.2.0 → v2.0 changes (to be created)
- `docs/CALIBRATION.md` - Calibration guide (to be created)
- `docs/ROSTER_KITS.md` - JSON format examples (to be created)

## Upgrade from v1.2.0

**Breaking Changes:**
- Position tuples now (x, y, t, is_detected) instead of (x, y, t)
- New `player_uid` field in outputs
- Config initialization requires additional parameters

**Backward Compatibility:**
- All existing CLI flags still work
- Old calibration JSON format still supported
- ByteTrack available via `--tracker bytetrack`

## References

Implementation based on:
- `cv-gap-analysis-2026-09-30.md` - Gap analysis vs commercial products
- `competitor-cv-tech-2026-09-30.md` - Technical teardown of Veo, SkillCorner, etc.
- Open-source: Ultralytics, BoxMOT, filterpy, roboflow/sports

## License

See main repository LICENSE file.

## Contact

For questions about v2.0 implementation, see `V2_IMPLEMENTATION_STATUS.md` for detailed status and remaining work.
