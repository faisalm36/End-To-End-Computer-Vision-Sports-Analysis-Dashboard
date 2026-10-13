# Soccer CV Pipeline v2.0 Field Summary

This document describes all output fields in pipeline v2.0, highlighting additions over v1.2.0.

## `meta.json` (Pipeline Metadata)

### v1.2.0 Fields (Preserved)

| Field | Type | Description |
|-------|------|-------------|
| `pipeline_version` | string | Pipeline version (now `"2.0.0"`) |
| `video_path` | string | Input video path |
| `fps` | number | Video frame rate |
| `frame_count` | integer | Total frames in video |
| `duration_s` | number | Video duration in seconds |
| `resolution` | string | e.g., `"1920x1080"` |
| `width` | integer | Frame width in pixels |
| `height` | integer | Frame height in pixels |
| `model_path` | string | YOLO model path used |
| `device` | string | Inference device (`cpu`, `mps`, `cuda`) |
| `calibration` | string/null | Calibration file path or `null` |
| `start_timestamp` | string | ISO timestamp when run started |
| `end_timestamp` | string | ISO timestamp when run ended |
| `runtime_s` | number | Total runtime in seconds |
| `unique_tracks` | integer | Number of unique `track_id` detected |
| `player_count` | integer | Number of players in stats (referees excluded) |
| `warnings` | array[string] | Warnings (e.g., missing calibration) |
| `speed_preset` | string | Speed preset used (e.g., `"gps_standard"`) |
| `hsr_threshold_kmh` | number | High-speed running threshold (km/h) |
| `sprint_threshold_kmh` | number | Sprint threshold (km/h) |
| `zone_edges_kmh` | object | Speed zone thresholds |

### v2.0 New Fields ⭐

| Field | Type | Description |
|-------|------|-------------|
| `tracker` | string | Tracker used: `"botsort"` or `"bytetrack"` |
| `ball_model_path` | string | Ball detection model path |
| `ball_tracking_method` | string | `"tiled"` (sliced inference) or `"simple"` |
| `tracklet_stitching_enabled` | boolean | Whether stitching was enabled |
| `calibration_quality` | object/null | Calibration quality metrics (if available) |

#### `calibration_quality` Structure (v2.0)

```json
{
  "method": "manual" | "ransac" | "model",
  "inliers": 4,
  "total_points": 4,
  "inlier_ratio": 1.0,
  "mean_reprojection_error_px": 2.3
}
```

## `tracking_detections.json/.csv` (Per-Frame Detections)

### v1.2.0 Fields (Preserved)

| Field | Type | Description |
|-------|------|-------------|
| `frame` | integer | Frame number (0-indexed) |
| `timestamp` | number | Time in seconds from video start |
| `track_id` | integer | Track ID (`-1` for ball, >0 for players) |
| `class` | string | Object class: `"person"`, `"ball"` |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | number | Bounding box in pixels |
| `confidence` | number | Detection confidence (0–1) |
| `pitch_x`, `pitch_y` | number/null | Pitch coordinates in meters (null if no calibration) |
| `jersey_number` | integer/null | OCR-detected jersey number |
| `team` | string/null | Team assignment: `"A"`, `"B"`, or `null` (referee/ball) |
| `role` | string | Role: `"player"`, `"goalkeeper"`, `"referee"`, `"ball"` |

### v2.0 New Fields ⭐

| Field | Type | Description |
|-------|------|-------------|
| `player_uid` | integer/null | Stable player ID across track switches (v2.0 stitching) |
| `is_detected` | boolean | `true` if real detection, `false` if interpolated |
| `is_interpolated` | boolean | `true` if ball position was interpolated (ball only) |

**Key change**: `player_uid` is stable across ID switches when tracklet stitching is enabled. `track_id` still present for backward compatibility.

## `player_match_stats.json/.csv` (Per-Player Aggregates)

### v1.2.0 Fields (Preserved)

| Field | Type | Description |
|-------|------|-------------|
| `track_id` | integer | First track_id for this player (legacy compat) |
| `jersey_number` | integer/null | Jersey number (majority vote) |
| `team` | string/null | Team: `"A"`, `"B"`, or `null` |
| `role` | string | Role: `"player"`, `"goalkeeper"`, `"referee"` |
| `top_speed_mph` | number/null | Max speed in mph (null if no calibration) |
| `top_speed_kmh` | number/null | Max speed in km/h |
| `distance_km` | number/null | Total distance covered in km |
| `visible_minutes` | number | Time player was tracked (minutes) |
| `high_speed_distance_km` | number/null | Distance above HSR threshold |
| `sprint_distance_km` | number/null | Distance above sprint threshold |
| `hsr_count` | integer/null | Count of HSR bursts |
| `sprint_count` | integer/null | Count of sprint bursts |
| `hi_efforts_count` | integer/null | Total high-intensity efforts (HSR + sprint) |

### v2.0 New Fields ⭐

| Field | Type | Description |
|-------|------|-------------|
| `player_uid` | integer | Stable player ID (stitched across track switches) |
| `contributing_track_ids` | array[integer] | All `track_id`s stitched into this `player_uid` |
| `detected_frames` | integer | Number of frames with real detections (`is_detected=True`) |
| `total_frames` | integer | Total frames tracked (detected + interpolated) |

**Key changes**:
- `player_uid` is the primary identifier in v2.0 (replaces per-clip `track_id` as stable ID)
- `contributing_track_ids` shows which short-term IDs were merged
- `detected_frames` / `total_frames` reports tracking quality
- **Top speed calculated from `detected_frames` only** (v2.0 hygiene)
- **Accelerations capped at ±6.0 m/s²** (v2.0 hygiene)

## `heatmaps.json` (Position Density Grids)

**No schema changes in v2.0.** Same grid-based heatmap structure per player.

## Backward Compatibility

All v1.2.0 output fields are **preserved**. Existing backend/frontend code reading v1.2.0 outputs will work unchanged.

v2.0 **adds** fields:
- `player_uid`, `contributing_track_ids` (can be ignored if not using stitching)
- `is_detected`, `is_interpolated` (can be ignored for simple use cases)
- `detected_frames`, `total_frames` (optional tracking quality indicators)
- `tracker`, `ball_tracking_method`, `tracklet_stitching_enabled`, `calibration_quality` in meta (optional metadata)

**Migration path**: No migration needed. v2.0 outputs are a superset of v1.2.0.

## Example v2.0 Detection Entry (JSON)

```json
{
  "frame": 42,
  "timestamp": 1.4,
  "track_id": 3,
  "player_uid": 1001,
  "class": "person",
  "bbox_x1": 450.2,
  "bbox_y1": 120.5,
  "bbox_x2": 480.8,
  "bbox_y2": 200.1,
  "confidence": 0.92,
  "pitch_x": 52.3,
  "pitch_y": 34.1,
  "is_detected": true,
  "jersey_number": 10,
  "team": "A",
  "role": "player"
}
```

## Example v2.0 Player Stat Entry (JSON)

```json
{
  "player_uid": 1001,
  "contributing_track_ids": [3, 17],
  "track_id": 3,
  "jersey_number": 10,
  "team": "A",
  "role": "player",
  "top_speed_mph": 18.5,
  "top_speed_kmh": 29.8,
  "distance_km": 5.2,
  "visible_minutes": 12.3,
  "high_speed_distance_km": 0.8,
  "sprint_distance_km": 0.3,
  "hsr_count": 12,
  "sprint_count": 5,
  "hi_efforts_count": 17,
  "detected_frames": 350,
  "total_frames": 368
}
```

**Note**: `contributing_track_ids: [3, 17]` shows this player was tracked as `track_id=3` for part of the match, then ID switched to `track_id=17`, and v2.0 stitching merged them into `player_uid=1001`.

## Summary of Breaking Changes

**None.** v2.0 is backward compatible. All v1.2.0 fields are preserved.

New fields can be ignored by legacy consumers. Frontend/backend reading only v1.2.0 fields will work without changes.
