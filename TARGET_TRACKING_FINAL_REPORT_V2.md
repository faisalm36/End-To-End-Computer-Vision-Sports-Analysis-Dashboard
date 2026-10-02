# Target Tracking - Final Report

**PR #3**: https://github.com/faisalm36/End-To-End-Computer-Vision-Sports-Analysis-Dashboard/pull/3  
**Branch**: `cursor/target-tracking-replay-97fa` (rebased on `main`)  
**Base**: `main` (PRs #1 and #2 already merged: 9c1d144, 5a5b8d0)  
**Status**: ✅ Complete, ready to merge into `main`

---

## Summary

Single-player target tracking with re-acquisition and browser-playable H.264 replay, exposed via **exact backend contract** (`detect_frame` and `track_player` commands).

---

## Commands

### 1. `cv.detect_frame`
```bash
python -m cv.detect_frame --video <abs> --t <seconds> --out <abs dir> --device <d> [--model m]
```

**Outputs**:
- `<out>/frame.jpg`
- `<out>/candidates.json`: `{frame, t, width, height, candidates:[{bbox, confidence, team:"A"|"B"|null, jersey_number, class:"player"|"goalkeeper"|"referee"}]}`

**Exit codes**: 0 (success), 1 (error)

---

### 2. `cv.track_player`
```bash
# By bbox
python -m cv.track_player --video <abs> --out <abs dir> --device <d> --frame N --bbox x1,y1,x2,y2 [--model m] [--calibration path]

# By jersey
python -m cv.track_player --video <abs> --out <abs dir> --device <d> --jersey N --team A|B [--model m] [--calibration path]
```

**Progress**: `'Processing frames: N%'` (flushed, monotonic 0-100%)

**Outputs**:
- `<out>/track.json`: Required: `{fps, width, height, total_frames, target:{jersey_number, team, init_frame}, frames:[{frame, t, bbox|null, confidence|null, status:"tracked"|"interpolated"|"lost"}]}`. Additive: `schema_version`, `player_uid`, `track_ids`, `state`, `pitch_x`, `pitch_y`
- `<out>/replay.mp4`: H.264, yuv420p, +faststart
- `<out>/meta.json`: Required: `{pipeline_version, tracker, coverage_pct, lost_frames, warnings:[]}`. Additive: `reacquisition_count`, `lost_segments`. On error: `error:"target_not_found"` + `candidates` hint
- `<out>/target_stats.json`: Additive

**Status mapping**:
- tracked/reacquired → `"tracked"`
- occluded → `"interpolated"`
- lost → `"lost"`

**Exit codes**: 0 (success), 1 (error), 3 (target not found/ambiguous)

**Team labels**: A/B (mapped from internal 0/1, consistent with `detect_frame`)

---

## Tests

**32 tests total, 0 failures**

**Interface contract** (10 tests):
- ✅ `candidates.json` schema (exact)
- ✅ `track.json` schema (exact)
- ✅ `meta.json` schema (success + error cases)
- ✅ Status mapping
- ✅ Exit codes 0/1/3
- ✅ Team label mapping
- ✅ Ambiguous target with candidates

**Internal logic** (22 tests):
- ✅ Target resolution (bbox, point, jersey, ambiguity errors)
- ✅ Re-acquisition gating (motion, team, appearance)
- ✅ State transitions (tracked → occluded → lost → reacquired)
- ✅ IoU computation
- ✅ Serialization

```bash
python -m unittest cv.tests.test_interface_contract cv.tests.test_target_tracking -v
# Ran 32 tests in 0.002s, OK
```

---

## Files Changed

**New**:
- `cv/detect_frame.py` (299 lines)
- `cv/track_player.py` (215 lines)
- `cv/target_tracking.py` (523 lines) - Re-acquisition logic
- `cv/replay_renderer.py` (441 lines) - H.264 encoder
- `cv/select_target.py` (225 lines) - Interactive helper
- `cv/tests/test_interface_contract.py` (349 lines, 10 tests)
- `cv/tests/test_target_tracking.py` (462 lines, 22 tests)
- `cv/tests/test_target_tracking_e2e.py` (233 lines, e2e)
- `cv/tests/test_replay_renderer.py` (180 lines, H.264 validation)

**Modified**:
- `cv/pipeline.py`: Add `process_video_for_target_tracking`
- `cv/requirements.txt`: Add `imageio-ffmpeg>=0.4.9`
- `cv/docs/TARGET_TRACKING.md`: Complete interface doc
- `cv/docs/RUN_ON_MAC.md`: Update merge order

**Unchanged**:
- `cv/run_pipeline.py` (target tracking is separate commands)

**Total**: +3,900 lines, 13 files changed

---

## Exact Mac Commands

```bash
# Setup
cd ~/End-To-EndCompVisionCapstoneProject
git fetch origin
git checkout cursor/target-tracking-replay-97fa  # or main after merge
source cv/venv/bin/activate
pip install -r cv/requirements.txt  # includes imageio-ffmpeg

# Detect frame
python -m cv.detect_frame \
  --video backend/uploads/match.mp4 \
  --t 10.0 \
  --out cv/results/ \
  --device mps

# Track player
python -m cv.track_player \
  --video backend/uploads/match.mp4 \
  --out cv/results/ \
  --device mps \
  --jersey 10 \
  --team A \
  --calibration cv/calibration.json

# Verify H.264
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,pix_fmt \
  cv/results/replay.mp4
# Expected: codec_name=h264, pix_fmt=yuv420p
```

---

## Backend Integration

**No changes needed**. Backend calls:

```bash
$CV_PYTHON -m cv.detect_frame --video <abs> --t <s> --out <abs> --device <d>
$CV_PYTHON -m cv.track_player --video <abs> --out <abs> --device <d> --jersey N --team A|B
```

**Progress parsing**: Read `'Processing frames: N%'` from stdout

**Exit codes**: 0 (success), 3 (target not found → read meta.json), 1 (error)

---

## Accuracy Limitations

1. Look-alike teammates (identical kits, same jersey)
2. Long occlusions (> 30 frames)
3. Player leaves frame
4. Panning cameras (less reliable without calibration)
5. Low resolution / distant players
6. Jersey OCR failures
7. Nearby similar players

**Never silently jumps to wrong player**. Prefers `lost` over guessing.

**No accuracy claims until validated on real footage.**

---

## Dependencies

- `imageio-ffmpeg>=0.4.9` (bundled ffmpeg for H.264 encoding)
- Works on macOS arm64 + Python 3.13

---

## Documentation

- `cv/docs/TARGET_TRACKING.md`: Complete interface spec with exact schemas, status mapping, exit codes, examples
- `cv/docs/RUN_ON_MAC.md`: Updated merge order (rebased on main)

---

## Merge Strategy

**Current status**: PRs #1 and #2 merged to `main` (commits 9c1d144, 5a5b8d0)

**This PR**: Rebased on `main`, merges directly into `main`

---

## Checklist

✅ **Interface contract**:
- ✅ `detect_frame` command with exact schema
- ✅ `track_player` command with exact schema
- ✅ Status mapping (tracked/reacquired→tracked, occluded→interpolated, lost→lost)
- ✅ Exit codes 0/1/3
- ✅ Team labels A/B
- ✅ Progress monotonic 0-100%
- ✅ H.264 replay (libx264, yuv420p, faststart)

✅ **Tests**:
- ✅ 32 tests, 0 failures
- ✅ Exact schema validation (key-by-key)
- ✅ Status mapping verification
- ✅ Exit code handling
- ✅ Team label consistency

✅ **Documentation**:
- ✅ TARGET_TRACKING.md (interface spec)
- ✅ RUN_ON_MAC.md (merge order updated)

✅ **Code quality**:
- ✅ All internals preserved (stitching, re-ID, gating, encoder)
- ✅ `run_pipeline.py` unchanged
- ✅ Backward compatible (additive-only fields)
- ✅ Rebased on main

---

**Ready to merge into `main`.**
