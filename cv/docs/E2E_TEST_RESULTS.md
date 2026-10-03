# E2E Test Report

## 1. Full Test Suite - PASSING

**Command**: `python -m unittest discover -s cv/tests -v`

**Result**: **134 tests, 0 failures**
- 91 tests from main (existing)
- 43 tests added (32 target tracking + 10 interface contract + 1 e2e)
- All tests PASS

## 2. Bug Fixes

### Fixed: `jersey_numbers` UnboundLocalError  
**Line**: `cv/pipeline.py:505`  
**Fix**: Initialize `jersey_numbers = {}` before `if self.ocr:` block  
**Impact**: Prevents crash when `--no-ocr` is used

### Verified: track_player independence
- Does NOT depend on global stitching assigning uids
- Builds own maps (`player_uid_map`, `team_map`, `jersey_map`, `appearance_map`)
- Target tracker does own re-acquisition
- Works even if stitching assigns uid to only 1 track

## 3. Real E2E Test

**Status**: Test runs but YOLOv8n doesn't detect synthetic players (expects real people)

**Exit code 3 test**: ✅ **VERIFIED**
- Command: `track_player --jersey 99 --team A` (no match)
- Exit code: **3** ✓
- `meta.json`: Contains `"error": "target_not_found"` ✓

**meta.json output**:
```json
{
  "pipeline_version": "2.0.0",
  "tracker": "botsort",
  "coverage_pct": 0.0,
  "lost_frames": 0,
  "warnings": ["No jersey number information available"],
  "error": "target_not_found"
}
```

## 4. Schema Validation - VERIFIED

All schemas tested and validated with exact key-by-key checks:

### candidates.json
```json
{
  "frame": 30,
  "t": 1.0,
  "width": 1280,
  "height": 720,
  "candidates": []
}
```
✅ Schema correct (frame, t, width, height, candidates array)

### track.json (from schema tests)
✅ Required fields: fps, width, height, total_frames, target, frames
✅ Additive fields: schema_version, player_uid, track_ids, state, pitch_x, pitch_y
✅ Status mapping verified: tracked/reacquired→tracked, occluded→interpolated, lost→lost

### meta.json (error case)
✅ Contains: pipeline_version, tracker, coverage_pct, lost_frames, warnings
✅ Exit code 3: Contains `error:"target_not_found"`

## 5. Rebase Status

✅ Rebased onto `origin/cursor/hotfix-pipeline-bugs-014f`
✅ jersey_numbers fix identical to hotfix (no conflict)
✅ Ready to retarget PR #3 base to hotfix branch

## 6. Requirements

✅ `cv/requirements.txt`: Only adds `imageio-ffmpeg>=0.4.9`, no duplicates
✅ FFmpeg available: `/usr/bin/ffmpeg`
✅ imageio-ffmpeg bundled: Available as fallback

---

## Summary

- **134 tests, 0 failures** ✅
- **Exit code 3 verified** with correct meta.json ✅
- **Bug fixed**: jersey_numbers UnboundLocalError ✅
- **Rebased** on hotfix branch ✅
- **Schema validation**: All correct ✅
- **Real people e2e**: Needs real video (YOLO doesn't detect synthetic shapes)

**Note**: YOLOv8 requires real people for detection. The synthetic video test framework is ready, but actual e2e validation requires running on a real soccer video with the Mac/GPU setup.
