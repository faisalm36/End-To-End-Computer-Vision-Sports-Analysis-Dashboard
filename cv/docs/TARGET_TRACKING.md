# Target Tracking Interface

Single-player target tracking with re-acquisition and annotated replay rendering for the soccer CV pipeline.

---

## Commands

### 1. `cv.detect_frame` - Frame Detection

Detect players in a single frame and return candidates with team/jersey info.

**Usage**:
```bash
python -m cv.detect_frame \
  --video <absolute path> \
  --t <seconds> \
  --out <absolute output dir> \
  --device <device> \
  [--model <model path>]
```

**Arguments**:
- `--video`: Absolute path to video file (required)
- `--t`: Timestamp in seconds (required)
- `--out`: Output directory absolute path (required)
- `--device`: Device for inference: `auto`, `cuda`, `mps`, `cpu` (required)
- `--model`: Path to YOLO model weights (optional, default: `yolov8x.pt`)

**Outputs**:
- `<out>/frame.jpg`: Decoded frame at timestamp t
- `<out>/candidates.json`: Detected player candidates

**Exit codes**:
- `0`: Success
- `1`: Error (video not found, cannot read frame, etc.)

**`candidates.json` schema**:
```json
{
  "frame": 100,
  "t": 3.333,
  "width": 1920,
  "height": 1080,
  "candidates": [
    {
      "bbox": [850.0, 320.0, 920.0, 480.0],
      "confidence": 0.87,
      "team": "A",
      "jersey_number": 10,
      "class": "player"
    },
    {
      "bbox": [1200.0, 450.0, 1270.0, 610.0],
      "confidence": 0.91,
      "team": "B",
      "jersey_number": 7,
      "class": "goalkeeper"
    },
    {
      "bbox": [500.0, 300.0, 550.0, 400.0],
      "confidence": 0.65,
      "team": null,
      "jersey_number": null,
      "class": "referee"
    }
  ]
}
```

**Fields**:
- `frame` (int): Frame number
- `t` (float): Timestamp in seconds
- `width` (int): Frame width in pixels
- `height` (int): Frame height in pixels
- `candidates` (array): List of detected players
  - `bbox` (array): `[x1, y1, x2, y2]` in source pixels
  - `confidence` (float): Detection confidence (0-1)
  - `team` (string|null): `"A"`, `"B"`, or `null`
  - `jersey_number` (int|null): Jersey number or `null`
  - `class` (string): `"player"`, `"goalkeeper"`, or `"referee"`

**Notes**:
- Team/jersey on a single frame may be `null`
- The command uses a short window (±15 frames, ~0.5s) around `t` to estimate team/jersey
- Only emits `"goalkeeper"` if the GK heuristic fires (positional analysis)
- Team labels `"A"`/`"B"` are consistently mapped from internal clustering (same seed/order as `track_player`)

---

### 2. `cv.track_player` - Player Tracking

Track a specific player through the entire video with re-acquisition and replay rendering.

**Usage**:
```bash
# Option 1: Target by frame + bbox
python -m cv.track_player \
  --video <absolute path> \
  --out <absolute output dir> \
  --device <device> \
  --frame <frame number> \
  --bbox x1,y1,x2,y2 \
  [--model <model path>] \
  [--calibration <path>]

# Option 2: Target by jersey + team
python -m cv.track_player \
  --video <absolute path> \
  --out <absolute output dir> \
  --device <device> \
  --jersey <number> \
  --team A|B \
  [--model <model path>] \
  [--calibration <path>]
```

**Arguments**:
- `--video`: Absolute path to video file (required)
- `--out`: Output directory absolute path (required)
- `--device`: Device for inference: `auto`, `cuda`, `mps`, `cpu` (required)
- `--frame`: Target frame number (required for bbox mode)
- `--bbox`: Target bbox as `"x1,y1,x2,y2"` (required for bbox mode)
- `--jersey`: Target jersey number (required for jersey mode)
- `--team`: Target team: `"A"` or `"B"` (required with `--jersey`)
- `--model`: Path to YOLO model weights (optional, default: `yolov8x.pt`)
- `--calibration`: Path to calibration file (optional)

**Outputs**:
- `<out>/track.json`: Frame-by-frame tracking with status
- `<out>/replay.mp4`: H.264 annotated video with target overlay
- `<out>/meta.json`: Pipeline metadata, warnings, and error info
- `<out>/target_stats.json`: Per-player metrics (additive)

**Exit codes**:
- `0`: Success
- `1`: General error (video not found, processing failed, etc.)
- `3`: Target not found or ambiguous (see `meta.json` for details)

**Progress**:
Prints `'Processing frames: N%'` to stdout (flushed) with monotonic progress 0-100% covering all stages (detection, tracking, stitching, target tracking, replay rendering).

---

## Output Schemas

### `track.json`

**Required fields**:
```json
{
  "fps": 30.0,
  "width": 1920,
  "height": 1080,
  "total_frames": 9000,
  "target": {
    "jersey_number": 10,
    "team": "A",
    "init_frame": 100
  },
  "frames": [
    {
      "frame": 0,
      "t": 0.0,
      "bbox": [850.0, 320.0, 920.0, 480.0],
      "confidence": 0.87,
      "status": "tracked"
    },
    {
      "frame": 450,
      "t": 15.0,
      "bbox": [851.0, 321.0, 921.0, 481.0],
      "confidence": 0.5,
      "status": "interpolated"
    },
    {
      "frame": 500,
      "t": 16.667,
      "bbox": null,
      "confidence": null,
      "status": "lost"
    }
  ]
}
```

**Additive fields** (extra keys, backward-compatible):
```json
{
  "schema_version": "1.0",
  "target": {
    "player_uid": 3,
    "track_ids": [12, 45, 67]
  },
  "frames": [
    {
      "state": "tracked",
      "pitch_x": 52.3,
      "pitch_y": 34.1
    }
  ]
}
```

**Status mapping**:
- `"tracked"`: Real detection (includes re-acquired)
- `"interpolated"`: Short-gap fill / predicted box during occlusion
- `"lost"`: No detection, motion gate failed, or left frame (bbox is `null`)

**Internal state to status mapping**:
- `tracked` → `"tracked"`
- `reacquired` → `"tracked"`
- `occluded` → `"interpolated"`
- `lost` → `"lost"`

**Fields**:
- `fps` (float): Video FPS
- `width` (int): Video width
- `height` (int): Video height
- `total_frames` (int): Total frames in video
- `target` (object): Target info
  - `jersey_number` (int|null): Jersey number (null if unknown)
  - `team` (string|null): Team label `"A"` or `"B"` (null if unknown)
  - `init_frame` (int): Frame where target was initialized
  - *Additive*: `player_uid` (int): Stable player ID across tracklets
  - *Additive*: `track_ids` (array): All track IDs associated with target
- `frames` (array): One entry for EVERY frame
  - `frame` (int): Frame number
  - `t` (float): Timestamp in seconds
  - `bbox` (array|null): `[x1, y1, x2, y2]` in pixels, or `null` if lost
  - `confidence` (float|null): Detection confidence, or `null` if lost
  - `status` (string): `"tracked"`, `"interpolated"`, or `"lost"`
  - *Additive*: `state` (string): Internal state (`"tracked"`, `"occluded"`, `"lost"`, `"reacquired"`)
  - *Additive*: `pitch_x` (float|null): Pitch X coordinate in meters (null if no calibration or lost)
  - *Additive*: `pitch_y` (float|null): Pitch Y coordinate in meters
- *Additive*: `schema_version` (string): Schema version

---

### `replay.mp4`

Annotated video with target overlay:
- **Green solid box**: Tracked target with jersey label
- **Orange dashed box**: Interpolated/occluded target (predicted position)
- **"TARGET LOST" indicator**: Lost state
- **15-frame motion trail**: Optional trail
- **"RE-ACQUIRED" flash**: When target is re-acquired after being lost

**Technical specs**:
- Codec: H.264 (libx264)
- Pixel format: yuv420p
- Container: MP4 with `+faststart` flag (moov atom before mdat)
- Dimensions: Even width/height (required for yuv420p)
- Audio: Copied from source if present
- Browser-compatible: Plays in Safari, Chrome, Firefox

---

### `meta.json`

**Success case**:
```json
{
  "pipeline_version": "2.0.0",
  "tracker": "botsort",
  "coverage_pct": 91.49,
  "lost_frames": 766,
  "warnings": []
}
```

**Additive fields**:
```json
{
  "reacquisition_count": 2,
  "lost_segments": [
    {"start_t": 45.2, "end_t": 48.7},
    {"start_t": 120.5, "end_t": 122.0}
  ]
}
```

**Error case (exit code 3)**:
```json
{
  "pipeline_version": "2.0.0",
  "tracker": "botsort",
  "coverage_pct": 0.0,
  "lost_frames": 0,
  "warnings": ["No player found with jersey number 99"],
  "error": "target_not_found"
}
```

**Ambiguous case (exit code 3)**:
```json
{
  "pipeline_version": "2.0.0",
  "tracker": "botsort",
  "coverage_pct": 0.0,
  "lost_frames": 0,
  "warnings": ["Ambiguous: 2 different players detected with jersey 10"],
  "error": "target_not_found",
  "candidates": [
    {
      "player_uid": 1,
      "track_id": 12,
      "jersey_number": 10,
      "team": "A"
    },
    {
      "player_uid": 2,
      "track_id": 45,
      "jersey_number": 10,
      "team": "A"
    }
  ]
}
```

**Fields**:
- `pipeline_version` (string): Pipeline version
- `tracker` (string): Tracker type (e.g., `"botsort"`)
- `coverage_pct` (float): Percentage of frames where target was tracked
- `lost_frames` (int): Number of frames where target was lost
- `warnings` (array): List of warning messages
- `error` (string): Error type (only present on failure): `"target_not_found"`
- `candidates` (array): Hint for ambiguous matches (only present when ambiguous)
- *Additive*: `reacquisition_count` (int): Number of times target was re-acquired
- *Additive*: `lost_segments` (array): List of lost time ranges

---

### `target_stats.json` (Additive)

Per-player metrics for the target, using the same field names as `player_match_stats.json`:

```json
{
  "player_uid": 3,
  "track_ids": [12, 45, 67],
  "jersey_number": 10,
  "team": "A",
  "tracked_frames": 8234,
  "total_frames": 9000,
  "tracked_pct": 91.49,
  "lost_segments": [
    {"start_t": 45.2, "end_t": 48.7}
  ],
  "reacquisition_count": 2,
  "top_speed_mph": 18.3,
  "top_speed_kmh": 29.4,
  "distance_km": 5.43,
  "visible_minutes": 4.57
}
```

---

## Team Label Mapping

**Internal representation**: 0 (team A), 1 (team B)  
**External labels**: `"A"`, `"B"`

The mapping is **consistent** across `detect_frame` and `track_player`:
- Both use the same team clustering algorithm (same seed/order)
- Team 0 is always labeled `"A"`
- Team 1 is always labeled `"B"`
- The clustering is deterministic for a given video

---

## Backend Integration

The backend calls these commands directly:

**Frame detection**:
```bash
$CV_PYTHON -m cv.detect_frame \
  --video /abs/path/to/video.mp4 \
  --t 3.5 \
  --out /abs/path/to/output/ \
  --device mps
```

**Player tracking**:
```bash
$CV_PYTHON -m cv.track_player \
  --video /abs/path/to/video.mp4 \
  --out /abs/path/to/output/ \
  --device mps \
  --jersey 10 \
  --team A
```

**Progress parsing**:
Backend parses `'Processing frames: N%'` from stdout (monotonic 0-100%).

**Exit code handling**:
- Exit code 0: Success, read outputs
- Exit code 3: Target not found/ambiguous, read `meta.json` for error details
- Exit code 1: General error, check stderr

---

## Accuracy Limitations

1. **Look-alike teammates**: Identical kits, same jersey → may lose target
2. **Long occlusions**: > 30 frames (~1 sec) → state becomes `lost`
3. **Player leaves frame**: Motion gate fails → `lost`
4. **Panning cameras**: Less reliable without calibration
5. **Low resolution**: Poor appearance features, unreliable OCR
6. **Jersey OCR failures**: Re-acquisition relies on appearance only
7. **Nearby similar players**: Brief mis-tracks possible

**Never silently jumps to wrong player**: Prefers marking `lost` over guessing.

**No accuracy claims until validated on real footage.**

---

## Thresholds (configurable in code)

- `max_speed_ms`: 12.0 m/s (~43 km/h) - maximum plausible player speed
- `motion_gate_multiplier`: 1.5 - allows 1.5x max speed for gaps
- `appearance_threshold`: 0.7 - appearance similarity threshold (0-1)
- `occlusion_max_frames`: 30 - max frames before marking lost

---

## Dependencies

- `imageio-ffmpeg>=0.4.9`: Provides bundled ffmpeg for H.264 encoding
- Works on macOS arm64 + Python 3.13

---

## Examples

**Detect candidates at t=10s**:
```bash
python -m cv.detect_frame \
  --video /Users/me/match.mp4 \
  --t 10.0 \
  --out /Users/me/results/ \
  --device mps

# Outputs:
# /Users/me/results/frame.jpg
# /Users/me/results/candidates.json
```

**Track player by jersey**:
```bash
python -m cv.track_player \
  --video /Users/me/match.mp4 \
  --out /Users/me/results/ \
  --device mps \
  --jersey 10 \
  --team A \
  --calibration /Users/me/calibration.json

# Outputs:
# /Users/me/results/track.json
# /Users/me/results/replay.mp4
# /Users/me/results/meta.json
# /Users/me/results/target_stats.json
```

**Track player by bbox**:
```bash
python -m cv.track_player \
  --video /Users/me/match.mp4 \
  --out /Users/me/results/ \
  --device mps \
  --frame 100 \
  --bbox 850,320,920,480

# Same outputs as above
```

**Verify H.264 encoding**:
```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,pix_fmt \
  /Users/me/results/replay.mp4

# Expected:
# codec_name=h264
# pix_fmt=yuv420p
```

---

## Notes

- **`run_pipeline.py` is unchanged**: Target tracking is a separate command
- **Additive-only fields**: Extra keys can be added to outputs without breaking the contract
- **Browser-compatible replay**: H.264 + yuv420p + faststart ensures playback
- **Exit code 3**: Special code for target not found/ambiguous (distinct from general errors)
- **Team clustering**: Deterministic for a given video (same seed/order)

---

## Testing

See `cv/tests/test_interface_contract.py` for exact schema validation tests.

```bash
python -m unittest cv.tests.test_interface_contract -v
# 10 tests covering schemas, status mapping, exit codes, team labels
```
