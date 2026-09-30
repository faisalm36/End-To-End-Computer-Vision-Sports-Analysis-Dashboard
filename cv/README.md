# Soccer Video Analytics - Computer Vision Pipeline

This directory contains the computer vision pipeline for soccer video analytics, including player/ball detection, tracking, jersey number OCR, pitch coordinate mapping, and performance metrics calculation.

## Features

1. **Detection & Tracking**
   - YOLOv8-based player, referee, and ball detection (pretrained COCO weights)
   - ByteTrack multi-object tracking for persistent player IDs
   - Ball interpolation for short gaps when occluded
   - Configurable confidence/IoU thresholds per class
   - Higher inference resolution for small ball detection
   - Optional pitch mask/ROI filtering to exclude non-pitch people

2. **Jersey Number OCR**
   - EasyOCR-based number recognition on player torso crops
   - Preprocessing: CLAHE contrast enhancement, resizing
   - Digits-only allowlist (0-9)
   - Majority voting across frames per track_id for robustness

3. **Team & Role Classification** ⭐ NEW in v1.1
   - Automatic team assignment via jersey color clustering (KMeans on LAB color space)
   - Referee detection based on color outliers
   - Majority voting across frames for robustness
   - Team field: 0, 1, or null (referee)
   - Role field: player, referee, goalkeeper, ball

4. **Pitch Coordinate Mapping**
   - OpenCV homography transformation from pixels to pitch meters
   - Configurable calibration via JSON/YAML (4+ point correspondences)
   - Optional default calibration for quick testing
   - Default 105m × 68m FIFA pitch dimensions
   - Foot position (bottom bbox center) for players, bbox center for ball
   - Graceful handling: outputs null for speed/distance when no calibration

5. **Performance Metrics**
   - **Speed**: Instantaneous and smoothed speed (mph), capped at plausible max
   - **Distance**: Total distance covered (km) with teleport filtering
   - **Injury Risk**: Low/Medium/High based on workload (distance, sprint count, high-speed running)
   - Per-player tracking: top_speed_mph, distance_km, sprint_count, high_speed_distance_km

6. **Outputs**
   - JSON & CSV for `tracking_detections` (frame-by-frame: track_id, bbox, pitch coords, jersey number, team, role)
   - JSON & CSV for `player_match_stats` (per-player aggregates, referees excluded)
   - JSON for `meta.json` (pipeline metadata: fps, resolution, runtime, warnings)
   - Optional annotated output video

## Installation

### Prerequisites

- **Python**: 3.11, 3.12, or 3.13 supported
- **macOS** (Apple Silicon): Uses `mps` device for GPU acceleration
- **CUDA** (Linux/Windows with GPU): Auto-detected if available

### Setup

1. **Create a virtual environment** (recommended to avoid conflicts):

```bash
# From the project root
cd cv
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Download YOLO weights** (first run downloads automatically):

The pipeline uses `yolov8x.pt` (pretrained COCO) by default. On first run, Ultralytics will auto-download from the official source (~130MB).

To use a fine-tuned model, specify `--model path/to/custom_model.pt`.

## Usage

### Basic Command

```bash
# Recommended: module invocation (works from any directory with PYTHONPATH set)
python -m cv.run_pipeline --video path/to/video.mp4 --out outputs/

# Alternative: direct script execution
python cv/run_pipeline.py --video path/to/video.mp4 --out outputs/
```

### Full Options

```bash
python -m cv.run_pipeline \
  --video clip.mp4 \
  --out outputs/ \
  --calibration cv/config/example_calibration.json \
  --device auto \
  --annotate \
  --model yolov8x.pt \
  --ocr-sample-rate 10
```

**Arguments**:
- `--video`: Path to input video (required)
- `--out`: Output directory (required)
- `--calibration`: Calibration file for pitch mapping (optional, uses default if omitted with warning)
- `--device`: Device for inference (`auto`, `cuda`, `mps`, `cpu`). Default: `auto` (detects GPU)
- `--annotate`: Generate annotated video with bboxes overlaid
- `--model`: YOLO model weights path (default: `yolov8x.pt`)
- `--no-ocr`: Disable jersey number OCR (faster, but no numbers)
- `--ocr-sample-rate`: Run OCR every N frames (default: 10, reduces overhead)

**Note**: If `--calibration` is omitted, the pipeline will try to use `cv/config/default_calibration.json` if it exists. When no calibration is available, `pitch_x`, `pitch_y`, and speed/distance metrics will be `null` in outputs.

### Calibration Setup

**Important**: Calibration is **per camera setup**. A fixed camera at a venue can reuse the same calibration file across multiple matches, as long as the camera position and angle remain unchanged.

To create a calibration file with 4+ point correspondences:

1. Open the first frame of your video
2. Identify 4+ landmarks (e.g., pitch corners, penalty box corners)
3. Record pixel coordinates and corresponding real pitch coordinates (meters)
4. Save as JSON:

```json
{
  "pitch_dimensions": {
    "width_m": 68.0,
    "length_m": 105.0
  },
  "correspondences": [
    {"image": [245, 180], "pitch": [0, 0]},
    {"image": [1675, 180], "pitch": [105, 0]},
    {"image": [1880, 920], "pitch": [105, 68]},
    {"image": [40, 920], "pitch": [0, 68]}
  ]
}
```

See `cv/config/example_calibration.json` for a template.

**Default Calibration**: If no calibration is provided, the pipeline will attempt to use `cv/config/default_calibration.json`. This is useful for quick testing but should be replaced with a camera-specific calibration for accurate results.

**Without calibration**: Detection and tracking still work, but `pitch_x`/`pitch_y` and performance metrics (speed/distance) will be `null`.

## Output Schema

### `tracking_detections.csv` / `.json`

Frame-by-frame detections matching the MySQL `tracking_detections` table:

| Column | Type | Description |
|--------|------|-------------|
| `frame` | int | Frame index |
| `timestamp` | float | Timestamp in seconds |
| `track_id` | int | Persistent track ID (-1 for ball) |
| `class` | str | `player`, `ball` |
| `bbox_x1, bbox_y1, bbox_x2, bbox_y2` | float | Bounding box in pixels |
| `confidence` | float | Detection confidence (0.0 if interpolated) |
| `pitch_x, pitch_y` | float | Pitch coordinates in meters (null if no calibration) |
| `jersey_number` | int | Jersey number (null if OCR disabled or not detected) |
| **`team`** ⭐ | int | Team assignment (0, 1, or null for referee) |
| **`role`** ⭐ | str | Role: `player`, `referee`, `goalkeeper`, or `ball` |

### `player_match_stats.csv` / `.json`

Per-player aggregates matching the MySQL `player_match_stats` table (referees excluded):

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `track_id` | int | - | Player track ID |
| `jersey_number` | int | - | Majority-voted jersey number |
| `team` ⭐ | int | - | Team assignment (0, 1, or null) |
| `role` ⭐ | str | - | Role: `player`, `goalkeeper` (referees not included) |
| `top_speed_mph` | float | mph | Maximum sustained speed in mph (null if no calibration) |
| `top_speed_kmh` | float | km/h | Maximum sustained speed in km/h (null if no calibration) |
| `distance_km` | float | km | Total distance covered (null if no calibration) |
| `minutes_played` | float | minutes | Time from first to last visible frame (null if no calibration) |
| `visible_minutes` | float | minutes | Total time player was tracked (null if no calibration) |
| `distance_per_min_m` | float | m/min | Distance per visible minute (null if no calibration) |
| `avg_pitch_x` | float | meters | Average pitch X position (null if no calibration) |
| `avg_pitch_y` | float | meters | Average pitch Y position (null if no calibration) |
| `high_speed_distance_km` | float | km | Distance at ≥19.8 km/h (null if no calibration) |
| `sprint_distance_km` | float | km | Distance at ≥25.2 km/h (null if no calibration) |
| `hsr_count` | int | - | Number of high-speed running bursts ≥1s (null if no calibration) |
| `sprint_count` | int | - | Number of sprint bursts ≥1s (null if no calibration) |
| `hi_efforts_count` | int | - | Total high-intensity efforts (hsr_count + sprint_count, null if no calibration) |
| `zone_walk_km` | float | km | Distance in walk zone (0-7 km/h, null if no calibration) |
| `zone_jog_km` | float | km | Distance in jog zone (7-15 km/h, null if no calibration) |
| `zone_run_km` | float | km | Distance in run zone (15-20 km/h, null if no calibration) |
| `zone_hsr_km` | float | km | Distance in HSR zone (20-25 km/h, null if no calibration) |
| `zone_sprint_km` | float | km | Distance in sprint zone (≥25 km/h, null if no calibration) |
| `accel_count_high` | int | - | High acceleration events ≥3 m/s² for ≥0.7s (estimate, null if no calibration) |
| `decel_count_high` | int | - | High deceleration events ≤-3 m/s² for ≥0.7s (estimate, null if no calibration) |
| `coverage_pct` | float | % | Percentage of video frames player was tracked (null if no calibration) |
| `injury_risk` | str | - | Injury risk category: `Low`, `Medium`, or `High` |

**Note on accelerations**: `accel_count_high` and `decel_count_high` are estimates based on smoothed velocity changes. They may overcount or undercount compared to GPS data due to detection noise and frame rate limitations.

#### Version 1.2.0 Fields Summary

The following fields were added in version 1.2.0 for comprehensive match analytics:

**Speed & Distance**:
- `top_speed_kmh`: Top speed in km/h (converted from mph)
- `distance_per_min_m`: Distance efficiency metric

**Temporal Coverage**:
- `minutes_played`: Time span from first to last appearance
- `visible_minutes`: Actual tracked time
- `coverage_pct`: Percentage of video frames tracked

**Spatial Position**:
- `avg_pitch_x`, `avg_pitch_y`: Average position on pitch

**High-Intensity Efforts**:
- `hsr_count`: Count of high-speed running bursts ≥1s
- `hi_efforts_count`: Total high-intensity efforts (HSR + sprints)

**Speed Zone Distances**:
- `zone_walk_km`: 0-7 km/h
- `zone_jog_km`: 7-15 km/h
- `zone_run_km`: 15-20 km/h
- `zone_hsr_km`: 20-25 km/h
- `zone_sprint_km`: ≥25 km/h

**Acceleration Estimates**:
- `accel_count_high`: High acceleration events (≥3 m/s²)
- `decel_count_high`: High deceleration events (≤-3 m/s²)

**Heatmaps** (separate file `heatmaps.json`):
- 21×14 grid of time-in-cell for spatial visualization

### `heatmaps.json`

Spatial heatmaps for each player (only generated when calibration is available):

```json
{
  "1": [
    [0.0, 0.33, 1.2, ...],  // Row 0 (y=0)
    [0.5, 2.1, 3.4, ...],   // Row 1 (y=~4.857m)
    ...
  ],
  "2": [...],
  ...
}
```

**Structure**:
- Top-level keys: track IDs (as strings)
- Values: 2D arrays (lists of lists) with dimensions `[14 rows × 21 columns]`
- Grid covers 105m × 68m pitch with 5m × ~4.857m cells
- Each cell value: time spent in cell (seconds)
- Grid coordinates:
  - X (columns): 0 to 21, covering 0-105m (length)
  - Y (rows): 0 to 14, covering 0-68m (width)

### `meta.json` ⭐

Pipeline metadata and diagnostics:

| Field | Type | Description |
|-------|------|-------------|
| `pipeline_version` | str | Pipeline version (e.g., "1.2.0") |
| `video_path` | str | Input video path |
| `fps` | float | Video frames per second |
| `frame_count` | int | Total frames processed |
| `duration_s` | float | Video duration in seconds |
| `resolution` | str | Video resolution (e.g., "1920x1080") |
| `width` | int | Video width in pixels |
| `height` | int | Video height in pixels |
| `model_path` | str | YOLO model weights path |
| `device` | str | Device used (cuda/mps/cpu) |
| `calibration` | str | Calibration file used or "none" |
| `speed_preset` | str | Sprint/HSR preset used (e.g., "gps_standard") |
| `hsr_threshold_kmh` | float | High-speed running threshold in km/h |
| `sprint_threshold_kmh` | float | Sprint threshold in km/h |
| `zone_edges_kmh` | dict | Speed zone boundaries: walk, jog, run, hsr (km/h) |
| `start_timestamp` | str | Processing start time (ISO 8601) |
| `end_timestamp` | str | Processing end time (ISO 8601) |
| `runtime_s` | float | Total processing time in seconds |
| `unique_tracks` | int | Number of unique tracks (players) |
| `player_count` | int | Number of players in stats (excludes referees) |
| `warnings` | list | List of warning messages |

## Fine-Tuning for Soccer

The default `yolov8x.pt` (COCO) works reasonably for players and balls, but fine-tuning improves accuracy:

### Recommended Public Datasets

- **Roboflow Soccer Players**: https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc
- **DFL Bundesliga Dataset**: https://www.kaggle.com/c/dfl-bundesliga-data-shootout
- **SoccerNet**: https://www.soccer-net.org/

### Fine-Tuning Steps

1. **Prepare dataset** in YOLO format:
   ```
   dataset/
     images/
       train/
       val/
     labels/
       train/
       val/
     data.yaml
   ```

2. **Train**:
   ```bash
   yolo train model=yolov8x.pt data=dataset/data.yaml epochs=100 imgsz=1280
   ```

3. **Use trained model**:
   ```bash
   python cv/run_pipeline.py --video clip.mp4 --out outputs/ --model runs/train/exp/weights/best.pt
   ```

## Testing

Run unit tests:

```bash
# From project root
python -m pytest cv/tests/ -v

# Or using unittest
python -m unittest discover cv/tests/
```

**Test coverage**:
- Homography transformation (corner mapping, center, bbox, validation)
- Performance metrics (speed, distance, injury risk, smoothing)
- OCR majority voting (adding readings, tie-breaking, filtering)

## Known Limitations & Future Improvements

### Detection Accuracy
- **Ball detection**: Small ball (often 10-20 pixels) is challenging; higher resolution helps but increases compute
  - Future: Use specialized soccer ball detector or track-by-detection with motion model
- **Referee vs Player**: Currently all detected as "player"; distinguish via jersey color clustering
- **Occlusions**: Players clustered together may lose track ID or merge
  - Future: Re-identification (ReID) model to recover lost tracks

### OCR Reliability
- **Jersey visibility**: OCR only works when number is clearly visible (frontal/back view, good lighting)
  - Typical success: 60-80% of frames for well-positioned players
  - Majority voting helps, but short appearances may fail
- **False positives**: Stadium ads, pitch markings can trigger false detections (filtered by bbox size/position)

### Pitch Mapping
- **Calibration**: Manual 4-point correspondence works for static cameras; moving/zooming cameras need per-frame calibration
  - Future: Automatic pitch line detection + homography per frame
- **Projection errors**: Distortion near image edges; use more correspondences (8-12 points) for better accuracy

### Performance Metrics
- **Speed jitter**: Despite smoothing, detection noise causes jitter
  - Future: Kalman filter or more sophisticated motion model
- **Injury risk**: Simple heuristic; real models use machine learning on longitudinal data
  - Future: Integrate with biomechanics data (acceleration, deceleration, change of direction)

### Video Formats
- Tested with `.mp4` (H.264); other formats should work via OpenCV
- High frame rate videos (60fps+) increase processing time; consider downsampling to 30fps

## Example End-to-End Run

```bash
# 1. Activate environment
cd /workspace/cv
source venv/bin/activate

# 2. Run on test video (without calibration)
python run_pipeline.py \
  --video test_video.mp4 \
  --out outputs/test_run/ \
  --device mps \
  --annotate

# 3. Check outputs
ls outputs/test_run/
# Expected:
#   tracking_detections.json
#   tracking_detections.csv
#   player_match_stats.json
#   player_match_stats.csv
#   test_video_annotated.mp4  (if --annotate)
```

## Backend Integration

The CSV/JSON outputs are designed to match the MySQL schema. To insert into the database:

```python
import pandas as pd
import mysql.connector

# Load detections
df = pd.read_csv('outputs/tracking_detections.csv')

# Connect to MySQL
conn = mysql.connector.connect(host='...', user='...', password='...', database='soccer_analytics')
cursor = conn.cursor()

# Insert detections
for _, row in df.iterrows():
    cursor.execute("""
        INSERT INTO tracking_detections 
        (frame, timestamp, track_id, class, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, pitch_x, pitch_y, jersey_number)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, tuple(row))

conn.commit()
```

## Troubleshooting

### Issue: `ImportError: No module named 'ultralytics'`
**Fix**: Activate virtual environment and reinstall dependencies:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Issue: `Slow inference on CPU`
**Fix**: Use GPU (`--device cuda` or `--device mps` on Mac M1/M2/M3)

### Issue: `OCR not detecting numbers`
**Causes**:
- Jersey number not visible (player facing away)
- Low resolution
- Poor lighting

**Fix**:
- Use higher resolution video
- Increase `--ocr-sample-rate` to 5 (more frequent sampling)
- Check that players have clear numbers (some jerseys have small/faded numbers)

### Issue: `Pitch coordinates all None`
**Cause**: No calibration file provided

**Fix**: Create calibration file and pass `--calibration config.json`

### Issue: `ModuleNotFoundError: No module named 'scipy'`
**Fix**: Install scipy (should be pulled by pandas, but explicitly install if needed):
```bash
pip install scipy
```

## Performance Benchmarks

Approximate processing speeds (on 1920×1080 video, yolov8x.pt):

| Device | FPS Processed | Real-time Factor |
|--------|---------------|------------------|
| CPU (8-core) | ~2 FPS | 0.07x |
| MPS (M2 Mac) | ~15 FPS | 0.5x |
| CUDA (RTX 3090) | ~45 FPS | 1.5x |

**Note**: OCR and annotated video output reduce speed by ~20-30%.

## Contact & Support

For issues with the CV pipeline, check:
1. This README for common issues
2. Test suite for validation: `python -m pytest cv/tests/ -v`
3. Example calibration: `cv/config/example_calibration.json`

For dataset questions or fine-tuning help, see the "Fine-Tuning for Soccer" section above.
