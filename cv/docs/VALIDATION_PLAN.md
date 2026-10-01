# Validation Plan

Ground-truth validation strategy for real soccer match clips.

**Status**: Framework defined, metrics to be measured on real footage.

---

## Overview

This plan outlines how to validate the CV pipeline against ground-truth data from real match clips. No accuracy claims are made until validation is complete.

---

## 1. Measured Sprint Test

### Goal
Validate speed and distance calculations against known measurements.

### Setup
1. Film a player running a measured distance (e.g., 40m sprint)
2. Time with stopwatch (ground truth time)
3. Mark start/end positions on pitch

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Distance Error** | \|measured_distance - pipeline_distance\| | < 2m (5%) |
| **Speed Error** | \|measured_speed - pipeline_top_speed\| | < 1 km/h |
| **Time Error** | \|measured_time - pipeline_time\| | < 0.5s |

### Procedure
1. Calibrate camera on measured pitch
2. Run pipeline on sprint clip
3. Extract player stats (distance_m, top_speed_kmh, sprint duration)
4. Compare to ground truth
5. Record errors in table

### Results (To Be Measured)

| Clip | Ground Truth Distance | Pipeline Distance | Error | Ground Truth Speed | Pipeline Speed | Error |
|------|----------------------|-------------------|-------|-------------------|----------------|-------|
| Sprint 1 | \_\_m | \_\_m | \_\_m | \_\_km/h | \_\_km/h | \_\_km/h |
| Sprint 2 | \_\_m | \_\_m | \_\_m | \_\_km/h | \_\_km/h | \_\_km/h |
| Sprint 3 | \_\_m | \_\_m | \_\_m | \_\_km/h | \_\_km/h | \_\_km/h |

---

## 2. Detection Precision/Recall (Frame Sample)

### Goal
Measure person detection accuracy on manually annotated frames.

### Setup
1. Select 100 random frames from a match clip
2. Manually annotate all visible players (bounding boxes)
3. Run pipeline and extract detections
4. Compare annotations to detections

### Metrics

| Metric | Definition | Formula |
|--------|------------|---------|
| **Precision** | True detections / All detections | TP / (TP + FP) |
| **Recall** | True detections / All ground truth | TP / (TP + FN) |
| **F1 Score** | Harmonic mean of precision/recall | 2 × (P × R) / (P + R) |

**Matching criterion**: IoU ≥ 0.5 (bounding box overlap)

### Procedure
1. Load 100 frames + manual annotations
2. Run YOLO detection (--model yolov8x.pt)
3. For each frame:
   - Match detections to annotations (Hungarian, IoU ≥ 0.5)
   - Count TP, FP, FN
4. Aggregate metrics across all frames

### Results (To Be Measured)

| Model | Precision | Recall | F1 Score | Mean IoU |
|-------|-----------|--------|----------|----------|
| yolov8n | \_\_% | \_\_% | \_\_% | \_\_ |
| yolov8s | \_\_% | \_\_% | \_\_% | \_\_ |
| yolov8m | \_\_% | \_\_% | \_\_% | \_\_ |
| yolov8x | \_\_% | \_\_% | \_\_% | \_\_ |

---

## 3. ID Switch Rate

### Goal
Measure tracking stability (how often player IDs switch incorrectly).

### Setup
1. Select a 60-second clip with continuous player visibility
2. Manually annotate ground-truth IDs for 5 players
3. Run pipeline with BoT-SORT and ByteTrack
4. Count ID switches

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **ID Switches** | Count of incorrect ID reassignments | < 2 per minute per player |
| **ID Persistence** | Frames with correct ID / Total frames | > 95% |

**ID Switch**: When ground-truth player A is assigned track_id X, then track_id Y in next appearance

### Procedure
1. Load 60s clip (1800 frames @ 30fps)
2. Run pipeline (tracker={botsort, bytetrack})
3. For each player:
   - Compare pipeline track_id to ground-truth ID
   - Count switches (ID changes without occlusion/exit)
4. Compute ID persistence percentage

### Results (To Be Measured)

| Tracker | Total ID Switches | ID Switches/min | ID Persistence | MOTA | IDF1 |
|---------|-------------------|-----------------|----------------|------|------|
| BoT-SORT | \_\_ | \_\_ | \_\_% | \_\_ | \_\_ |
| ByteTrack | \_\_ | \_\_ | \_\_% | \_\_ | \_\_ |

**Note**: MOTA (Multiple Object Tracking Accuracy) and IDF1 (ID F1 Score) are standard MOT metrics from MOTChallenge.

---

## 4. Jersey OCR Accuracy

### Goal
Measure jersey number recognition accuracy.

### Setup
1. Manually annotate jersey numbers for all players in a clip
2. Include only frames where numbers are clearly visible
3. Run pipeline with OCR enabled
4. Compare recognized numbers to annotations

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Accuracy** | Correct readings / Total attempts | > 80% |
| **Precision** | Correct / (Correct + Incorrect) | > 85% |
| **Recall** | Correct / Ground Truth | > 75% |

**Correct**: Pipeline number matches ground truth  
**Incorrect**: Pipeline number differs from ground truth  
**Missed**: No number detected (None)

### Procedure
1. Load clip with manual number annotations
2. Run pipeline with OCR (--ocr-sample-rate 5)
3. For each player track:
   - Final assigned number (after voting)
   - Compare to ground truth
4. Classify as Correct, Incorrect, or Missed
5. Compute metrics

### Results (To Be Measured)

| Configuration | Correct | Incorrect | Missed | Accuracy | Precision | Recall |
|---------------|---------|-----------|--------|----------|-----------|--------|
| EasyOCR, sample=1 | \_\_ | \_\_ | \_\_ | \_\_% | \_\_% | \_\_% |
| EasyOCR, sample=5 | \_\_ | \_\_ | \_\_ | \_\_% | \_\_% | \_\_% |
| EasyOCR + roster | \_\_ | \_\_ | \_\_ | \_\_% | \_\_% | \_\_% |

---

## 5. Calibration Reprojection Error

### Goal
Measure calibration accuracy.

### Setup
1. Calibrate camera with 10+ pitch keypoints
2. Manually annotate additional 20 test keypoints (not used in calibration)
3. Project test keypoints to image using calibration
4. Measure pixel error

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Mean Reprojection Error** | Mean pixel distance to ground truth | < 5 px |
| **Max Reprojection Error** | Maximum pixel error | < 10 px |
| **Inlier Ratio** | RANSAC inliers / Total points | > 90% |

### Procedure
1. Load calibration JSON (homography matrix)
2. For each test keypoint:
   - Project pitch coordinates to image: `H × [x, y, 1]`
   - Measure pixel distance to manual annotation
3. Compute mean, max, std dev of errors

### Results (To Be Measured)

| Clip | Keypoints Used | Inliers | Inlier Ratio | Mean Error (px) | Max Error (px) | Std Dev (px) |
|------|----------------|---------|--------------|-----------------|----------------|--------------|
| Clip 1 | \_\_ | \_\_ | \_\_% | \_\_ | \_\_ | \_\_ |
| Clip 2 | \_\_ | \_\_ | \_\_% | \_\_ | \_\_ | \_\_ |
| Clip 3 | \_\_ | \_\_ | \_\_% | \_\_ | \_\_ | \_\_ |

---

## 6. Metrica Speed/Distance RMSE

### Goal
Validate metrics against Metrica Sports open tracking data.

### Setup
1. Download Metrica Sports sample data (EPTS tracking + video)
2. Run pipeline on Metrica video
3. Compare pipeline metrics to ground-truth EPTS data

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Position RMSE** | Root mean square position error | < 1.0 m |
| **Speed RMSE** | Root mean square speed error | < 2.0 km/h |
| **Distance Error** | Total distance error per player | < 5% |

### Procedure
1. Load Metrica EPTS tracking (ground truth positions)
2. Run pipeline on Metrica video
3. Match pipeline player_uid to EPTS player IDs
4. For each frame:
   - Compare positions (x, y)
   - Compare speeds
5. Compute RMSE over all frames

### Results (To Be Measured)

| Player | Position RMSE (m) | Speed RMSE (km/h) | Distance Error (%) | Total Distance (km) |
|--------|-------------------|-------------------|--------------------|---------------------|
| Player 1 | \_\_ | \_\_ | \_\_% | \_\_ |
| Player 2 | \_\_ | \_\_ | \_\_% | \_\_ |
| ...      | \_\_ | \_\_ | \_\_% | \_\_ |
| **Mean** | \_\_ | \_\_ | \_\_% | \_\_ |

**Note**: Metrica data is CC BY 4.0 licensed. Available at: [https://github.com/metrica-sports/sample-data](https://github.com/metrica-sports/sample-data)

---

## 7. Team Classification Accuracy

### Goal
Measure team assignment accuracy.

### Setup
1. Manually label ground-truth teams for all players in a clip
2. Run pipeline with team classifier
3. Compare assignments

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Team Accuracy** | Correct assignments / Total players | > 90% |
| **Confusion Rate** | Swapped team labels | < 10% |

**Correct**: Pipeline team matches ground truth  
**Swapped**: Team A ↔ Team B confusion (systematic)  
**Unassigned**: Pipeline returns None (no team)

### Procedure
1. Load clip with manual team labels
2. Run pipeline (--kits optional)
3. For each player:
   - Compare pipeline team to ground truth
4. Allow for A/B swap (if consistent)
5. Compute accuracy

### Results (To Be Measured)

| Configuration | Correct | Swapped | Unassigned | Accuracy | Notes |
|---------------|---------|---------|------------|----------|-------|
| No kit priors | \_\_ | \_\_ | \_\_ | \_\_% | \_\_ |
| With kit priors | \_\_ | \_\_ | \_\_ | \_\_% | \_\_ |

---

## 8. End-to-End System Test

### Goal
Full pipeline validation on a complete match half (45 minutes).

### Setup
1. Process a full 45-minute half
2. Manually verify sample of outputs (100 random frames)
3. Check for crashes, errors, invalid data

### Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Completion Rate** | Frames processed / Total frames | 100% |
| **Output Validity** | Valid JSON/CSV outputs | 100% |
| **Crash-Free** | No exceptions or hangs | Yes |
| **Processing Speed** | Real-time factor (RTF) | Document actual |

### Procedure
1. Run full pipeline on 45-minute video
2. Check for:
   - Missing frames in output
   - Invalid JSON (malformed, NaN values)
   - Warnings/errors in meta.json
   - Memory leaks (monitor RAM usage)
3. Manually inspect sample of 100 frames for obvious errors

### Results (To Be Measured)

| Metric | Result | Notes |
|--------|--------|-------|
| Total Frames | \_\_ | |
| Processed Frames | \_\_ | |
| Completion Rate | \_\_% | |
| Processing Time | \_\_min | |
| Real-Time Factor | \_\_x | |
| Crashes | \_\_ | |
| Invalid Outputs | \_\_ | |
| Memory Usage (Peak) | \_\_GB | |

---

## Validation Tools

### Manual Annotation Tools

**For bounding boxes**:
- LabelImg ([https://github.com/heartexlabs/labelImg](https://github.com/heartexlabs/labelImg))
- CVAT ([https://cvat.org/](https://cvat.org/))

**For tracking ground truth**:
- MOTChallenge toolkit
- Custom annotation script (frame-by-frame ID assignment)

**For jersey numbers**:
- Custom spreadsheet (frame, track_id, jersey_number)

### Comparison Scripts

Create `cv/validation/` with:
- `compare_detections.py` - Precision/recall calculator
- `compare_tracking.py` - ID switch counter, MOTA/IDF1
- `compare_ocr.py` - OCR accuracy metrics
- `compare_metrics.py` - Speed/distance RMSE vs Metrica

---

## Success Criteria Summary

| Test | Target | Status |
|------|--------|--------|
| Sprint Distance Error | < 5% | ⬜ Not measured |
| Detection F1 Score | > 85% | ⬜ Not measured |
| ID Switch Rate | < 2/min | ⬜ Not measured |
| OCR Accuracy | > 80% | ⬜ Not measured |
| Calibration Error | < 5px | ⬜ Not measured |
| Metrica Position RMSE | < 1m | ⬜ Not measured |
| Team Classification | > 90% | ⬜ Not measured |
| End-to-End Completion | 100% | ⬜ Not measured |

---

## Timeline (Proposed)

1. **Week 1**: Measured sprint test (1 clip)
2. **Week 2**: Detection annotations (100 frames)
3. **Week 3**: Tracking ground truth (60s clip)
4. **Week 4**: OCR annotations (full clip)
5. **Week 5**: Calibration test (3 clips)
6. **Week 6**: Metrica validation (open data)
7. **Week 7**: Team classification (2 clips)
8. **Week 8**: End-to-end 45-min test

**Total**: ~2 months for complete validation

---

## Notes

- **No accuracy claims** should be made until validation is complete
- Targets are **goals**, not guarantees
- Results may vary by:
  - Video quality (resolution, lighting, camera angle)
  - Model size (yolov8n vs yolov8x)
  - Calibration quality
  - Player visibility (occlusion, distance)
- Document all failure cases for future improvements

---

## References

- **MOTChallenge**: [https://motchallenge.net/](https://motchallenge.net/)
- **Metrica Sports Data**: [https://github.com/metrica-sports/sample-data](https://github.com/metrica-sports/sample-data)
- **COCO Metrics**: [https://cocodataset.org/#detection-eval](https://cocodataset.org/#detection-eval)
