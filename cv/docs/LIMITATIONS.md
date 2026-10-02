# Limitations

Known limitations and constraints of the soccer CV pipeline v2.0.

---

## 1. Single Camera System

### Limitation
The pipeline processes video from **one fixed camera only**. No multi-camera fusion.

### Impact
- **Occlusion**: Players hidden behind others are not tracked
- **Partial pitch coverage**: Camera may not see entire pitch
- **Depth ambiguity**: Distance from camera affects apparent speed/size
- **Blind spots**: Areas far from camera or out of frame are not covered

### Workarounds
- Use wide-angle camera positioned to maximize pitch coverage
- Position camera at midfield height for balanced view
- Accept gaps in tracking data when players leave frame

### Future Work
- Multi-camera calibration and fusion
- 3D reconstruction from multiple viewpoints
- Automatic camera selection/switching

---

## 2. Occlusion Handling

### Limitation
When players overlap or are blocked by others/objects, tracking may:
- Lose track (ID switch)
- Assign wrong team/jersey (from occluding player)
- Produce gaps in trajectory

### Impact
- **ID switches**: ~1-3 per minute per player (varies by tracker)
- **Missing detections**: ~5-10% of frames with heavy occlusion
- **Incorrect metrics**: Gaps in position reduce accuracy of distance/speed

### Partial Mitigations
- BoT-SORT uses appearance embeddings to re-identify after occlusion
- Kalman filter predicts position during brief occlusions
- Tracklet stitching merges pre/post-occlusion tracks

### Limitations Remain
- Long occlusions (>2 seconds) often cause ID loss
- Overlapping players with similar kits confuse team classifier
- Jersey numbers unreadable when occluded

### Future Work
- Pose estimation (skeletal tracking through partial occlusion)
- 3D tracking (depth estimation reduces confusion)
- Contextual reasoning (team positioning priors)

---

## 3. Calibration Dependence

### Limitation
Physical metrics (speed, distance, position) **require pitch calibration**.

Without calibration:
- All physical metrics are **nulled** (set to `None`)
- Only temporal metrics available: `visible_minutes`, `minutes_played`, `coverage_pct`
- Team classification and OCR still work (use pixel-space only)

### Impact
- **Manual calibration step** required before processing
- **Calibration quality** directly affects metric accuracy:
  - Poor keypoints → incorrect positions
  - Moving camera → calibration drift (not supported)
  - Low-angle camera → high projection error
- **No auto-calibration**: Pitch keypoint detection not implemented

### Requirements for Calibration
- 4+ pitch keypoints visible in frame
- Known real-world coordinates (meters)
- Fixed camera (no panning/zooming)
- Clear pitch markings (lines, corners, boxes)

### Workarounds
- Use interactive calibration tool (`cv/calibrate_interactive.py`)
- Calibrate once per camera position, reuse for all clips
- For uncalibrated clips, use temporal metrics only

### Future Work
- Automatic pitch keypoint detection (deep learning)
- Line detection + homography estimation
- Camera motion tracking (for moving cameras)
- Single-point calibration (known scale marker)

---

## 4. No Event Detection

### Limitation
The pipeline tracks **players and ball only**. No semantic understanding of match events:
- ❌ Passes
- ❌ Shots
- ❌ Tackles
- ❌ Fouls
- ❌ Ball possession
- ❌ Offsides
- ❌ Set pieces

### Impact
- Cannot answer questions like:
  - "Who passed to whom?"
  - "How many shots on goal?"
  - "Which team had possession?"
- Limited tactical analysis (only position-based)

### Available Metrics
- ✅ Player positions, trajectories
- ✅ Speed, distance, accelerations
- ✅ High-intensity efforts (sprints, HSR)
- ✅ Heatmaps
- ✅ Ball position (no ownership)

### Future Work
- Ball possession detection (proximity + motion analysis)
- Pass detection (ball trajectory + player positions)
- Shot detection (ball toward goal + speed threshold)
- Action recognition (deep learning on player crops)

---

## 5. Small Ball Detection

### Limitation
Soccer balls are small objects (~22 cm diameter, ~10-30 pixels in video).

### Challenges
- **Low detection rate**: Ball detected in ~60-80% of frames (typical)
- **False positives**: Other round objects (logos, ads) misidentified as ball
- **Occlusion**: Ball often hidden by players, grass, or out of frame
- **Motion blur**: Fast-moving ball is blurry → low confidence

### Mitigations
- Tiled/sliced inference (SAHI-style) for small objects
- Kalman filter + interpolation for gaps
- Speed gating rejects impossible jumps (>35 m/s)
- Track single ball (highest confidence)

### Limitations Remain
- Gaps in ball trajectory (2-10 frames common)
- No ball spin/rotation tracking
- Cannot distinguish between multiple balls (training session)

### Future Work
- Fine-tuned ball detection model (domain-specific)
- Temporal context (trajectory prediction)
- Multi-frame aggregation (optical flow + detection)

---

## 6. Compute Requirements

### Limitation
Real-time processing is **not achieved** on most hardware.

### Performance
Typical processing speeds (1920×1080 video, yolov8x):

| Hardware | FPS Processed | Real-Time Factor |
|----------|---------------|------------------|
| CPU (8-core) | ~2-3 fps | ~0.1x (10x slower) |
| Apple M1/M2 (MPS) | ~5-8 fps | ~0.2-0.3x |
| NVIDIA RTX 3090 (CUDA) | ~15-25 fps | ~0.5-0.8x |

**Note**: Actual speeds vary by resolution, model size, OCR sampling rate, and annotation settings.

### Bottlenecks
1. **YOLO inference**: 60-70% of compute time
2. **EasyOCR**: 10-15% (if enabled every frame)
3. **Tracking (BoT-SORT)**: 10% (Hungarian matching)
4. **Video I/O**: 5-10% (disk read/write)

### Workarounds
- Use smaller models (yolov8n, yolov8s) for faster processing
- Reduce OCR sampling rate (`--ocr-sample-rate 10`)
- Disable annotation (`--annotate` off)
- Downscale video to 720p
- Process offline (batch mode)

### Not Suitable For
- ❌ Live streaming analysis (requires ~1x real-time)
- ❌ Instant replay analysis (seconds delay)
- ❌ Real-time coaching feedback during match

### Suitable For
- ✅ Post-match analysis (hours after game)
- ✅ Video upload → process → results (minutes to hours)
- ✅ Batch processing of archived matches

### Future Work
- Model optimization (TensorRT, ONNX, quantization)
- Frame skipping (process every 2nd/3rd frame)
- Cloud processing (distributed inference)
- Edge devices (Jetson, Coral TPU)

---

## 7. Lighting & Weather Dependence

### Limitation
Performance degrades in poor visual conditions:

**Low light (night games, indoor)**:
- Lower detection confidence
- Increased occlusion confusion
- Color-based team classification fails
- OCR accuracy drops

**Glare/shadows**:
- False detections from shadows
- Team color extraction affected
- Calibration keypoints obscured

**Rain/snow**:
- Blurry detections
- Tracking instability
- Camera lens artifacts

### Mitigations
- Use high-quality camera (good low-light sensor)
- Enable video preprocessing (contrast enhancement)
- Adjust confidence thresholds per condition
- Use jersey numbers instead of colors (if visible)

### Limitations Remain
- No automatic adaptation to conditions
- Severe weather may make pipeline unusable

---

## 8. Jersey Number OCR Constraints

### Limitation
OCR only works when jerseys are:
- ✅ Facing camera (front or back)
- ✅ Unoccluded
- ✅ Close enough (>40 pixels height)
- ✅ High contrast (number vs kit color)
- ✅ Not motion-blurred

### Challenges
- **Low accuracy**: 60-80% typical (varies by clip)
- **Missed numbers**: ~20-40% of players
- **Incorrect reads**: Similar-looking digits (1/7, 6/8, 5/8)

### Mitigations
- Confidence-weighted voting (aggregate multiple frames)
- Legibility filter (reject blurry/small crops)
- Roster constraints (filter invalid numbers)
- Manual correction (post-processing)

### Limitations Remain
- Cannot read numbers on jerseys worn backward
- Decorative fonts (stylized numbers) fail
- Partial occlusion (one digit visible) produces garbage

### Future Work
- Fine-tuned OCR model (soccer jerseys only)
- Temporal tracking (follow same player, infer number)
- Context-aware correction (valid ranges per league)

---

## 9. Team Classification Assumptions

### Limitation
Team classifier assumes:
- Two teams with distinct kit colors
- One referee (optional, detected as outlier)
- Consistent lighting across pitch
- Players stay in same kit (no substitutions with different colors)

### Failure Modes
- **Similar kits**: Red vs Orange, Blue vs Purple
- **Third kit**: Goalkeeper different from team causes confusion
- **Mixed lighting**: Shadows make same color appear different
- **Small samples**: <4 players fails to cluster reliably

### Mitigations
- Kit color priors (`--kits` flag)
- Per-tracklet aggregation (median across frames)
- Goalkeeper heuristic (position + color difference)
- Minimum 2 tracks (was 4, lowered in v2.0)

### Limitations Remain
- Cannot handle >2 teams (scrimmages, training)
- Low-confidence warnings with <4 tracks
- May produce unbalanced splits (2/4 instead of 3/3) - **bug 1e**

---

## 10. No Pose Estimation

### Limitation
Tracks **bounding boxes only**, not body keypoints (joints, limbs).

### Impact
Cannot measure:
- ❌ Body orientation/facing direction
- ❌ Limb angles (knee/ankle angles)
- ❌ Biomechanics (running form, injury risk indicators)
- ❌ Actions (kicking, jumping, tackling)

### Available
- ✅ Bounding box (x1, y1, x2, y2)
- ✅ Center position (foot location)
- ✅ Size (height, width in pixels)

### Future Work
- Integrate pose estimation (YOLOv8-Pose, OpenPose, MMPose)
- Skeleton-based action recognition
- Gait analysis for injury prevention
- Fine-grained metrics (stride length, contact time)

---

## 11. Video Quality Requirements

### Minimum Requirements
- **Resolution**: 720p (1280×720) or higher
- **Frame rate**: 25-30 fps
- **Codec**: H.264 or H.265 (compressed OK)
- **Lighting**: Adequate (not pitch black)
- **Camera angle**: Elevated (not ground-level)

### Degraded Performance
Below minimum requirements:
- <720p: Small players hard to detect
- <25 fps: Tracking instability, speed errors
- Low bitrate: Compression artifacts confuse detector
- Ground-level: Extreme perspective distortion

### Optimal Setup
- **Resolution**: 1080p (1920×1080)
- **Frame rate**: 30 fps
- **Camera**: Midfield, elevated 5-10m
- **Lighting**: Outdoor daylight or well-lit stadium
- **Focus**: Sharp (not auto-focus hunting)

---

## 12. Output Interpretation Caveats

### Interpolated Data
- Ball positions with `is_interpolated=True` are **estimates**, not detections
- Interpolated positions may drift from true trajectory
- Do not use interpolated data for event detection

### Null Values
- `None` in physical metrics means:
  - No calibration available, OR
  - Player not visible long enough to compute, OR
  - Calculation failed (divide by zero, invalid data)
- Check `meta.json` → `warnings` for root cause

### Rounding
- `distance_km`: Rounded to 3 decimals (~1 meter precision)
- `top_speed_mph`: Rounded to 2 decimals
- Accumulated rounding may cause `sum(zones) ≠ distance_km` (within ±0.01 km)

### Temporal Gaps
- `visible_minutes` ≠ `minutes_played` (visible is frame count, played is time range)
- Use `coverage_pct` to assess tracking completeness
- Low coverage (<50%) indicates frequent occlusions or exits

---

## Summary Table

| Limitation | Impact Severity | Workaround Available | Future Fix |
|------------|-----------------|----------------------|------------|
| Single camera | High | Camera positioning | Multi-camera fusion |
| Occlusion | High | BoT-SORT + stitching | Pose estimation, 3D |
| Calibration required | Medium | Manual tool | Auto-calibration |
| No events | Medium | N/A | Event detection models |
| Small ball | Medium | Tiled inference | Fine-tuned detector |
| Slow compute | Medium | Smaller models | Optimization |
| Poor lighting | Medium | Preprocessing | Adaptive thresholds |
| OCR accuracy | Low-Medium | Voting + roster | Fine-tuned OCR |
| Team classification | Low | Kit priors | Better color extraction |
| No pose | Low | N/A | Pose estimation |
| Video quality | Low | Use better camera | N/A |
| Output caveats | Low | Read documentation | N/A |

**Severity**: High = Unusable in that scenario, Medium = Degraded but functional, Low = Minor inconvenience

---

## Recommendations

For best results:
1. ✅ Use 1080p+ video at 30 fps
2. ✅ Position camera at midfield, elevated
3. ✅ Ensure good lighting
4. ✅ Calibrate pitch carefully (4+ keypoints)
5. ✅ Use `yolov8x.pt` for production (accuracy over speed)
6. ✅ Provide kit priors (`--kits`) if colors are similar
7. ✅ Provide roster (`--roster`) for OCR validation
8. ✅ Accept offline processing (not real-time)
9. ✅ Validate outputs on sample clips before trusting
10. ✅ Check `meta.json` → `warnings` for pipeline issues

---

**Conclusion**: This pipeline is suitable for **post-match analysis** on **good-quality video** with **manual calibration**. It is not suitable for real-time coaching, poor video conditions, or fully automated workflows without human oversight.
