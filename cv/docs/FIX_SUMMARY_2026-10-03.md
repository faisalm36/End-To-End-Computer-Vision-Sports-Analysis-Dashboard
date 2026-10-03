# PR #3 Fix Summary - AttributeError Resolution

**Date**: 2026-10-03  
**Branch**: cursor/target-tracking-replay-97fa  
**Head SHA**: 8f2bb57059d08c2bc1a5a9d6bb95d4865462f38b  
**Status**: FIXED - Ready for Mac re-test

## Problem

Real-footage validation on user's Mac (Python 3.13.1, MPS, yolov8n) FAILED with:
```
AttributeError: 'TeamClassifierEnhanced' object has no attribute 'track_votes'. 
Did you mean: 'track_roles'?
```

Crash locations:
- `cv/detect_frame.py:164`
- `cv/pipeline.py:632`
- `cv/pipeline.py:922`

Impact:
- Both CLIs (`detect_frame` and `track_player`) crashed before producing any output
- Exit code 1 instead of exit code 3 for target_not_found
- Empty output directories

## Root Cause

Code referenced non-existent `team_classifier.track_votes` attribute instead of the correct `track_teams` attribute from TeamClassifierEnhanced API.

The existing test suite used mocks for TeamClassifierEnhanced, so this API mismatch was not caught.

## Fix

1. **Replaced all `track_votes` references with `track_teams`** (3 locations)
2. **Added real API tests** (`cv/tests/test_real_team_classifier.py`)
   - Constructs real TeamClassifierEnhanced without mocking
   - 3 tests verify correct attribute usage
   - All tests PASS
3. **Added smoke test documentation** (`cv/docs/SMOKE_TEST.md`)
   - Real-footage test procedure
   - H.264/yuv420p/faststart verification commands

## Test Results

### VM (Linux, Python 3.12, CPU)
```
Total tests: 149
Passed: 148
Failed: 1 (inherited: test_bug2_tracklet_timestamps from PR #4)

New tests:
- test_real_classifier_attributes: PASS
- test_classifier_lifecycle: PASS
- test_track_teams_keys_iteration: PASS

Smoke test (synthetic video):
- detect_frame: CLI runs, correct JSON schema (0 detections as expected)
- track_player: Not tested (YOLO requires real people)
```

### Expected Mac Results (User to verify)

After fix, the following should work:

```bash
# 1. detect_frame
python3 -m cv.detect_frame --video clip.mp4 --t 2.0 --out /tmp/x --device mps
# Expected: candidates.json with detected players

# 2. track_player (bbox mode)
python3 -m cv.track_player --video clip.mp4 --frame 115 --bbox 1068,1210,1123,1359 --out /tmp/y --device mps
# Expected: track.json, replay.mp4 (H.264/yuv420p), meta.json, target_stats.json

# 3. track_player (jersey mode, no match)
python3 -m cv.track_player --video clip.mp4 --jersey 99 --team A --out /tmp/z --device mps
# Expected: Exit code 3, meta.json with {"error": "target_not_found"}
```

## Commits

1. `1113dfa` - Fix AttributeError: use track_teams instead of non-existent track_votes
2. `fc4be5f` - Add comprehensive tests for TeamClassifierEnhanced API  
3. `8f2bb57` - Add real-video smoke test documentation

## Outstanding Issues

1. **Inherited test failure**: `test_bug2_tracklet_timestamps (0 != 1)` from PR #4 base
   - Will be resolved when PR #4 is updated
   - Does not affect target tracking functionality

2. **Real-video smoke test**: Cannot be performed in VM
   - YOLO does not detect synthetic shapes
   - Requires user's real footage on Mac for full validation

## Next Steps

1. User re-tests on Mac with real footage (head: 8f2bb57)
2. If successful, merge after PR #4 is resolved
3. Document actual Mac test results in PR

## Files Modified

- `cv/detect_frame.py` - Fixed track_votes -> track_teams (line 164)
- `cv/pipeline.py` - Fixed track_votes -> track_teams (lines 632, 922)
- `cv/tests/test_real_team_classifier.py` - New test file (3 tests)
- `cv/docs/SMOKE_TEST.md` - New documentation

## References

- PR #3: https://github.com/faisalm36/End-To-End-Computer-Vision-Sports-Analysis-Dashboard/pull/3
- PR #4 (base): cursor/hotfix-pipeline-bugs-014f (f5b8c63)
- TeamClassifierEnhanced: `cv/team_classifier_enhanced.py`
