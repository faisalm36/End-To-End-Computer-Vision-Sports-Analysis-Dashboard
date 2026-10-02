# Target Tracking and Replay System

Single-player target tracking with re-acquisition and annotated replay rendering for the soccer CV pipeline.

---

## Overview

The target tracking system enables tracking a specific player throughout a match, even through:
- Track ID switches (when the tracker assigns a new ID)
- Occlusions (temporary disappearances)
- Player leaving and re-entering the frame
- Similar-looking teammates

**Key principle**: Never silently jump to the wrong player. The system marks frames as `lost` rather than guessing.

---

## CLI Usage

### Target Specification Methods

#### Method 1: Frame + Bounding Box

```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-frame 100 \
  --target-bbox 850,320,920,480 \
  --calibration calibration.json
```

Tracks the player whose bbox at frame 100 has the highest IoU with `[850, 320, 920, 480]`.

#### Method 2: Frame + Click Point

```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-frame 100 \
  --target-point 885,400 \
  --calibration calibration.json
```

Tracks the player whose bbox at frame 100 contains the point `(885, 400)`, or the nearest player if no bbox contains it.

#### Method 3: Jersey Number

```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-jersey 10 \
  --calibration calibration.json
```

Tracks the player wearing jersey #10. Fails with a clear error if:
- No player detected with that jersey
- Multiple different players detected with the same jersey (ambiguous)

#### Method 4: Jersey + Team

```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-jersey 7 \
  --target-team 0 \
  --calibration calibration.json
```

Tracks jersey #7 on team 0 (reduces ambiguity when both teams have a #7).

#### Method 5: Target JSON File

```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target target.json \
  --calibration calibration.json
```

Where `target.json` contains:

```json
{
  "target_frame": 100,
  "target_point": [885, 400],
  "target_bbox": null,
  "target_jersey": null,
  "target_team": null
}
```

Or for jersey-based targeting:

```json
{
  "target_frame": null,
  "target_point": null,
  "target_bbox": null,
  "target_jersey": 10,
  "target_team": 0
}
```

**Backend integration**: The backend can generate `target.json` and pass it via `--target /path/to/target.json`, or use `CV_EXTRA_ARGS` to pass individual flags.

---

## Replay Video

### Automatic Rendering

Replay rendering is **automatically enabled** when any target specification is provided (unless `--no-replay` is used).

```bash
# Replay is rendered automatically
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-jersey 10
```

### Manual Control

```bash
# Disable replay in target mode
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-jersey 10 \
  --no-replay

# Enable replay without target mode
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --render-replay
```

### Downscaling

```bash
# Limit replay height to 720p
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --target-jersey 10 \
  --replay-max-height 720
```

Downscaling:
- Reduces file size
- Speeds up rendering
- Maintains aspect ratio
- Ensures even dimensions (required for H.264)

---

## Output Files

When target tracking is enabled, the pipeline writes additional files to the `--out` directory:

### `target_track.json`

Frame-by-frame tracking results. **Written for EVERY frame** (even when lost) so the frontend can sync with the video timestamp.

```json
{
  "schema_version": "1.0",
  "video": {
    "width": 1920,
    "height": 1080,
    "fps": 30.0,
    "frame_count": 9000
  },
  "target": {
    "player_uid": 3,
    "track_ids": [12, 45, 67],
    "jersey": 10,
    "team": 0,
    "spec": {
      "target_frame": 100,
      "target_point": [885, 400],
      "target_bbox": null,
      "target_jersey": null,
      "target_team": null
    }
  },
  "frames": [
    {
      "frame": 0,
      "t": 0.0,
      "bbox": [850.2, 320.5, 920.8, 480.3],
      "confidence": 0.87,
      "state": "tracked",
      "source": "detected",
      "pitch_x": 52.3,
      "pitch_y": 34.1
    },
    {
      "frame": 1,
      "t": 0.033,
      "bbox": [851.0, 321.0, 921.5, 481.0],
      "confidence": 0.89,
      "state": "tracked",
      "source": "detected",
      "pitch_x": 52.4,
      "pitch_y": 34.2
    },
    {
      "frame": 450,
      "t": 15.0,
      "bbox": null,
      "confidence": 0.0,
      "state": "lost",
      "source": "lost",
      "pitch_x": null,
      "pitch_y": null
    }
  ]
}
```

**Field descriptions**:

- `bbox`: `[x1, y1, x2, y2]` in pixels, or `null` when lost
- `confidence`: Detection confidence (0-1), or 0.0 when lost/interpolated
- `state`: `'tracked'`, `'occluded'`, `'lost'`, or `'reacquired'`
  - `tracked`: Target detected in current frame
  - `occluded`: Target not detected but expected to return soon (< 30 frames)
  - `lost`: Target not detected for extended period (motion gate failed or left frame)
  - `reacquired`: Target found again after being lost
- `source`: `'detected'`, `'interpolated'`, or `'lost'`
- `pitch_x`, `pitch_y`: Pitch coordinates in meters (null if no calibration or lost)

### `target_stats.json`

Per-player statistics for the target, merging all contributing tracklets:

```json
{
  "player_uid": 3,
  "track_ids": [12, 45, 67],
  "jersey": 10,
  "team": 0,
  "tracked_frames": 8234,
  "total_frames": 9000,
  "tracked_pct": 91.49,
  "lost_segments": [
    {"start_t": 45.2, "end_t": 48.7},
    {"start_t": 120.5, "end_t": 122.0}
  ],
  "reacquisition_count": 2,
  "top_speed_mph": 18.3,
  "top_speed_kmh": 29.4,
  "distance_km": 5.43,
  "visible_minutes": 4.57,
  "high_speed_distance_km": 0.82,
  "sprint_distance_km": 0.21,
  "hsr_count": 12,
  "sprint_count": 3
}
```

**New fields** (compared to `player_match_stats.json`):

- `tracked_frames`: Number of frames where target was detected
- `tracked_pct`: Percentage of video where target was tracked
- `lost_segments`: List of time ranges (seconds) where target was lost
- `reacquisition_count`: Number of times target was re-acquired after being lost

All other fields (speed, distance, etc.) are computed from the target's detections only.

### `replay.mp4`

Annotated video with target overlay:

- **Green box + label**: Tracked target with jersey/speed
- **Orange dashed box**: Occluded target (predicted position)
- **No box + "TARGET LOST"**: Lost target
- **Green "RE-ACQUIRED"**: Target found again
- **Motion trail**: Optional 15-frame trail

**Video specs** (browser-compatible):
- Codec: H.264 (libx264)
- Pixel format: yuv420p
- Container: MP4 with faststart flag (moov atom before mdat)
- Audio: Copied from source (if present)
- Dimensions: Even width/height (required for yuv420p)

### `meta.json`

The standard metadata file gains a `target` section:

```json
{
  "pipeline_version": "2.0.0",
  "target": {
    "spec": {
      "target_frame": 100,
      "target_point": [885, 400],
      "target_bbox": null,
      "target_jersey": null,
      "target_team": null
    },
    "resolved_player_uid": 3,
    "resolved_track_ids": [12, 45, 67],
    "jersey": 10,
    "team": 0,
    "tracked_pct": 91.49,
    "reacquisition_count": 2,
    "lost_segments_count": 2,
    "warnings": []
  }
}
```

---

## Interactive Target Selection

The `cv/select_target.py` tool helps you pick a target interactively:

### Interactive Mode (GUI)

```bash
python -m cv.select_target \
  --video match.mp4 \
  --frame 100 \
  --output target.json
```

Opens an OpenCV window showing frame 100 with all detected player bounding boxes. Click on a player to select them. The tool writes `target.json` with the selected point.

### Headless Mode (JSON output)

```bash
python -m cv.select_target \
  --video match.mp4 \
  --frame 100 \
  --list
```

Outputs JSON to stdout:

```json
{
  "frame": 100,
  "candidates": [
    {
      "index": 0,
      "bbox": [850.2, 320.5, 920.8, 480.3],
      "confidence": 0.87,
      "center": [885.5, 400.4]
    },
    {
      "index": 1,
      "bbox": [1200.0, 450.0, 1270.5, 610.2],
      "confidence": 0.91,
      "center": [1235.25, 530.1]
    }
  ]
}
```

**Backend/frontend integration**: The frontend can call the pipeline with `--list` to get candidate boxes, display them on a video frame, and let the user click. Then pass the clicked point via `--target-point`.

---

## Backend Integration

### Environment Variables

The backend can enable target tracking via `CV_EXTRA_ARGS` in `.env`:

```bash
# Via individual flags
CV_EXTRA_ARGS=--target-jersey 10 --target-team 0

# Via target file
CV_EXTRA_ARGS=--target /path/to/target.json

# With replay control
CV_EXTRA_ARGS=--target-jersey 10 --replay-max-height 720

# Disable replay
CV_EXTRA_ARGS=--target-jersey 10 --no-replay
```

### Invocation

The backend already constructs:

```bash
$CV_PYTHON -m cv.run_pipeline \
  --video <abs path> \
  --out <abs dir> \
  --device <d> \
  [--calibration <abs path>] \
  [--model <model>] \
  $CV_EXTRA_ARGS
```

Target flags are passed via `$CV_EXTRA_ARGS` (shlex-split).

### Progress Tracking

The backend parses `'Processing frames: N%'` from stdout. The pipeline emits monotonic progress:

- **0-80%**: Detection and tracking
- **80-90%**: Target tracking (if enabled)
- **90-95%**: Metadata and file writing
- **95-100%**: Replay rendering (if enabled)

### Output Parsing

The backend reads these **new** files from `--out` (when target mode enabled):

1. `target_track.json` - Frame-by-frame tracking (for video overlay)
2. `target_stats.json` - Per-player stats (same schema as `player_match_stats.json`, plus tracking fields)
3. `replay.mp4` - Annotated video (optional)

All **existing** outputs (`tracking_detections.json`, `player_match_stats.json`, `meta.json`, `heatmaps.json`) remain unchanged.

---

## Frontend Overlay

The frontend can overlay the target track on the original video:

1. Load `target_track.json`
2. Sync frames by timestamp `t` (use `video.currentTime` to find the matching frame)
3. Draw bbox on the video canvas:
   - Green box for `state == 'tracked'`
   - Orange dashed box for `state == 'occluded'`
   - Red "LOST" text for `state == 'lost'`
   - Green "RE-ACQUIRED" flash for `state == 'reacquired'`

**Timestamp sync**:

```javascript
const currentTime = videoElement.currentTime;
const targetFrame = targetTrack.frames.find(f => 
  Math.abs(f.t - currentTime) < 0.02 // 20ms tolerance
);
```

The frontend can also directly play `replay.mp4` if generated.

---

## How It Works

### Resolution

1. **Frame + bbox/point**: Find the player detection at the specified frame that matches the bbox (IoU) or contains the point.
2. **Jersey + team**: Find the player_uid whose stitched jersey vote matches. Fails clearly if ambiguous or missing.

### Re-acquisition Gates

After the target is resolved to a `player_uid`, the tracker re-acquires it through tracklet switches by checking (in priority order):

1. **Track ID match**: If the detection's track_id is already associated with the target, accept it.
2. **Jersey + team match**: If the detection has the same jersey and team, and passes the motion gate, accept it.
3. **Appearance + team + motion**: If the detection has similar appearance (color histogram), same team, and passes motion gate, accept it.

**Motion gate**: A detection is rejected if the distance from the last known position exceeds `v_max * dt * 1.5` (allows for brief acceleration or prediction error).

### State Transitions

- **Tracked → Occluded**: Target not found for 1-30 frames (motion gate may still accept a nearby detection)
- **Occluded → Tracked**: Target re-detected within motion gate
- **Occluded → Lost**: Target not found for > 30 frames
- **Lost → Reacquired**: Target re-detected after being lost (jersey/appearance match)
- **Tracked/Reacquired → Tracked**: Target continues to be detected

### Thresholds (configurable in `config.py`)

- `max_speed_ms`: 12.0 m/s (~43 km/h) - maximum plausible player speed
- `motion_gate_multiplier`: 1.5 - allows 1.5x max speed for occlusion gaps
- `appearance_threshold`: 0.7 - appearance similarity threshold (0-1)
- `occlusion_max_frames`: 30 - max frames in occlusion before marking lost

---

## Accuracy Limitations

### Known Failure Cases

1. **Look-alike teammates in identical kits**: If two players have the same jersey number (or no numbers detected), same team, and similar appearance, the tracker may lose the target or pick the wrong player after an occlusion.

2. **Long occlusions**: If the target is occluded for > 30 frames (~1 second at 30 FPS), the state becomes `lost`. Re-acquisition depends on jersey/appearance matching when the player reappears.

3. **Player leaves frame**: When the player leaves the frame, all detections fail the motion gate (no plausible detection nearby). State: `lost`. Re-acquisition when the player re-enters depends on jersey/appearance.

4. **Panning cameras**: Camera motion can cause large apparent displacements. The current motion gate uses pitch coordinates (if calibrated), which are camera-motion-invariant. Without calibration, motion gating is less reliable.

5. **Low resolution or distant players**: Small bounding boxes yield poor appearance features and unreliable jersey OCR. The tracker may lose the target during occlusions.

6. **Jersey OCR failures**: OCR is unreliable on amateur footage (motion blur, low resolution, non-standard fonts). If the target was resolved by jersey but OCR fails during the match, re-acquisition relies on appearance only.

7. **Referee/ball/other players near target**: The tracker may temporarily lock onto a nearby player if appearance is similar and the motion gate passes. The system prefers marking `lost` over wrong assignments, but brief mis-tracks can occur.

### Validation Needed

**No accuracy claims are made until the system is validated on real match footage.**

Validation should measure:
- **Tracked %**: Percentage of frames where target is correctly detected
- **Precision**: Percentage of tracked frames that are correct (no wrong player)
- **Re-acquisition success rate**: Percentage of lost segments that are successfully re-acquired
- **False re-acquisition rate**: Percentage of re-acquisitions that locked onto the wrong player

---

## Configuration

Target tracking thresholds are in `cv/config.py`:

```python
# Tracklet stitching (used by target tracking)
USE_TRACKLET_STITCHING = True
MAX_PLAYER_SPEED_MS = 12.0  # ~43 km/h

# Target tracking thresholds (defaults in TargetTracker)
# - max_speed_ms: 12.0
# - motion_gate_multiplier: 1.5
# - appearance_threshold: 0.7
# - color_similarity_threshold: 0.6
# - occlusion_max_frames: 30
```

To adjust thresholds, edit `cv/target_tracking.py` or expose them as CLI flags.

---

## Testing

See `cv/tests/test_target_tracking.py` for unit tests covering:

- Target resolution (bbox IoU, point-in-box, jersey match, ambiguity errors)
- Re-acquisition gating (rejects implausible jumps, wrong team; accepts feasible tracklets)
- State transitions (tracked → occluded → lost → reacquired)
- Output schema validation (target_track.json structure)

See `cv/tests/test_replay_renderer.py` for replay rendering tests:

- H.264 codec verification (ffprobe check)
- yuv420p pixel format
- Moov atom before mdat (faststart)
- Even dimensions

Run the full test suite:

```bash
python -m unittest discover -s cv/tests -v
```

---

## Merge Order

This feature is built on PR #2 (`cursor/cv-pipeline-v2-commercial-quality-023d`), which is stacked on PR #1 (`cursor/soccer-cv-pipeline-236d`).

**Recommended merge order**:

1. **This PR** (`cursor/target-tracking-replay-97fa`) merges into PR #2's branch (`cursor/cv-pipeline-v2-commercial-quality-023d`)
2. **PR #2** merges into PR #1's branch (`cursor/soccer-cv-pipeline-236d`)
3. **PR #1** merges into `main`

Or, if testing the full stack locally:

```bash
git checkout cursor/soccer-cv-pipeline-236d
git merge cursor/cv-pipeline-v2-commercial-quality-023d
git merge cursor/target-tracking-replay-97fa
# Test combined stack
```

Then merge `cursor/soccer-cv-pipeline-236d` into `main`.

---

## Dependencies

New dependency: **imageio-ffmpeg** (added to `cv/requirements.txt`)

```bash
pip install imageio-ffmpeg>=0.4.9
```

- Provides a bundled ffmpeg binary (no system ffmpeg required)
- Works on macOS arm64 + Python 3.13
- Used for H.264 encoding in replay renderer

---

## Example Commands

### Full workflow with target tracking

```bash
# Run pipeline with target tracking
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --calibration calibration.json \
  --target-jersey 10 \
  --target-team 0 \
  --replay-max-height 720 \
  --device mps

# Check outputs
ls results/
# tracking_detections.json
# player_match_stats.json
# meta.json
# heatmaps.json
# target_track.json          <- NEW
# target_stats.json          <- NEW
# replay.mp4                 <- NEW

# Verify replay codec
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt results/replay.mp4
# codec_name=h264
# pix_fmt=yuv420p
```

### Backend integration example

In `backend/.env`:

```bash
CV_EXTRA_ARGS=--target-jersey 10 --replay-max-height 720
```

Backend runs:

```bash
/path/to/venv/bin/python -m cv.run_pipeline \
  --video /abs/path/to/video.mp4 \
  --out /abs/path/to/output/ \
  --device mps \
  --calibration /abs/path/to/calibration.json \
  --target-jersey 10 \
  --replay-max-height 720
```

Backend parses progress from stdout lines `'Processing frames: N%'`.

Backend reads:
- `output/target_track.json` (frame-by-frame for overlay)
- `output/target_stats.json` (per-player stats)
- `output/replay.mp4` (annotated video)
- All existing outputs (unchanged)

---

## Support

For issues or questions:

1. Check `meta.json` → `target` → `warnings` for resolution/tracking errors
2. Check `meta.json` → `warnings` for general pipeline issues
3. Run tests: `python -m unittest discover -s cv/tests -v`
4. Verify ffmpeg: `python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`
