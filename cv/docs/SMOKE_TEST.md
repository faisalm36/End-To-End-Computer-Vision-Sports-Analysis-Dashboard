# Real-Video Smoke Test Instructions

Since YOLO does not detect synthetic shapes, the following smoke test should be performed with real footage containing people.

## Prerequisites
- Real video clip with people/players (e.g., soccer broadcast, training footage)
- YOLO model: `yolov8n.pt` or `yolov8x.pt` (auto-downloaded on first run)
- Device: `cpu`, `cuda`, or `mps` (Mac)

## Test 1: detect_frame

```bash
python3 -m cv.detect_frame \
  --video /path/to/real_clip.mp4 \
  --t 2.0 \
  --out /tmp/detect_test \
  --device mps
```

Expected outputs:
- `/tmp/detect_test/frame.jpg` - Annotated frame at t=2.0s
- `/tmp/detect_test/candidates.json` - List of detected players

Verify candidates.json schema:
```json
{
  "frame": 115,
  "t": 2.0,
  "width": 3456,
  "height": 2234,
  "candidates": [
    {
      "bbox": [1068, 1210, 1123, 1359],
      "confidence": 0.87,
      "team": "A",
      "jersey_number": null,
      "class": "player"
    }
  ]
}
```

## Test 2: track_player (bbox mode)

Pick the largest candidate from step 1 and track it:

```bash
python3 -m cv.track_player \
  --video /path/to/real_clip.mp4 \
  --frame 115 \
  --bbox 1068,1210,1123,1359 \
  --out /tmp/track_test \
  --device mps
```

Expected outputs:
- `/tmp/track_test/track.json` - Frame-by-frame track with bbox, status
- `/tmp/track_test/replay.mp4` - H.264 annotated replay
- `/tmp/track_test/meta.json` - Pipeline metadata
- `/tmp/track_test/target_stats.json` - Coverage and re-acquisition stats

Verify replay.mp4 encoding:
```bash
ffprobe /tmp/track_test/replay.mp4 2>&1 | grep -E "(codec_name|pix_fmt)"
```

Expected:
```
codec_name=h264
pix_fmt=yuv420p
```

Verify moov atom before mdat (faststart):
```bash
xxd /tmp/track_test/replay.mp4 | head -50 | grep -E "(moov|mdat)"
```

Should see `moov` before `mdat` in hex dump.

## Test 3: track_player (jersey mode, target not found)

Request a non-existent jersey:

```bash
python3 -m cv.track_player \
  --video /path/to/real_clip.mp4 \
  --jersey 99 \
  --team A \
  --out /tmp/notfound_test \
  --device mps
```

Expected:
- Exit code: 3 (not 1)
- `/tmp/notfound_test/meta.json` exists with `"error": "target_not_found"`
- No `track.json` or `replay.mp4`

## VM Smoke Test (with synthetic video)

Since YOLO doesn't detect synthetic shapes, the VM test only verifies:
1. CLIs run without crashing (no AttributeError)
2. Output files are created with correct schema
3. Exit codes are correct

For full end-to-end verification with detections, use real footage as above.

## Results Format

Document test results as:

```
Real-Video Smoke Test Results (Mac, Python 3.13.1, MPS, yolov8n.pt)

1. detect_frame: OK
   - Video: clip.mp4 (3456x2234, 58fps, 0:05 duration)
   - Detected: 18 candidates at t=2.0s
   - Largest: bbox=[1068,1210,1123,1359], conf=0.87, team="A", class="player"
   
2. track_player (bbox): OK
   - Tracked: 285/290 frames (98.3%)
   - Re-acquisitions: 2
   - Lost segments: 0
   - replay.mp4: H.264/yuv420p/faststart verified ✓
   
3. track_player (jersey 99): OK
   - Exit code: 3 ✓
   - meta.json: {"error": "target_not_found"} ✓
```
