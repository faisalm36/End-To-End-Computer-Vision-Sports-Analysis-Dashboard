# Running the CV Pipeline on Mac (Apple Silicon)

Complete setup guide for macOS with Python 3.13 and Apple Silicon MPS acceleration.

---

## Prerequisites

- macOS with Apple Silicon (M1/M2/M3)
- Python 3.13 installed (`python3.13 --version`)
- Git installed
- ~2 GB disk space for models

---

## 1. Repository Setup & PR Merge Order

### Recommended Merge Strategy

The soccer CV pipeline v2.0 is stacked on two PRs:

- **PR #1** (`cursor/soccer-cv-pipeline-236d`): Base v1.2.0 features
- **PR #2** (`cursor/cv-pipeline-v2-commercial-quality-023d`): v2.0 enhancements

**Safest merge order**:

1. Merge PR #1 into `main` first
2. After PR #1 is merged, retarget PR #2 to `main` and merge it

**Alternative** (if you want to test the combined stack before merging):
```bash
# Merge PR #2 into PR #1's branch locally
git checkout cursor/soccer-cv-pipeline-236d
git merge cursor/cv-pipeline-v2-commercial-quality-023d
# Test, then merge cursor/soccer-cv-pipeline-236d into main
```

### Clone/Pull Latest Code

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
git pull origin main  # After PRs are merged
```

Or if testing the stacked branches:
```bash
git fetch origin
git checkout cursor/cv-pipeline-v2-commercial-quality-023d
git pull origin cursor/cv-pipeline-v2-commercial-quality-023d
```

---

## 2. Python Environment Setup

### Create Virtual Environment (Python 3.13)

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
python3.13 -m venv cv/venv
source cv/venv/bin/activate
```

### Install Dependencies

```bash
pip install --upgrade pip
pip install -r cv/requirements.txt
```

**Expected install time**: 3-5 minutes (torch/torchvision are large)

### Verify Installation

```bash
python -c "import torch; print(f'PyTorch {torch.__version__}, MPS available: {torch.backends.mps.is_available()}')"
python -c "import ultralytics; print(f'Ultralytics {ultralytics.__version__}')"
```

Expected output:
```
PyTorch 2.1.0+, MPS available: True
Ultralytics 8.0.0+
```

---

## 3. Model Downloads (One-Time)

### YOLOv8 Weights

The pipeline downloads models automatically on first run. Weights are stored in:

```
~/.cache/torch/hub/ultralytics/
```

**Models used**:
- `yolov8n.pt` (~6 MB) - Nano model for testing
- `yolov8x.pt` (~136 MB) - Large model for production

**Pre-download** (optional):
```bash
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
python -c "from ultralytics import YOLO; YOLO('yolov8x.pt')"
```

**Note**: Model weights are **NOT committed to git** (listed in `.gitignore`).

### EasyOCR Models

EasyOCR downloads language models (~100 MB) on first use. Stored in:

```
~/.EasyOCR/model/
```

First run will download automatically (adds 30s-60s).

---

## 4. Unit Tests Verification

Run the full test suite to verify installation:

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
source cv/venv/bin/activate
python -m unittest discover -s cv/tests -v
```

**Expected result** (as of this build):
```
Ran 87 tests in X.XXs

OK
```

**All tests should pass**. If any fail, check:
- Python version (`python --version` should show 3.13.x)
- Dependencies installed correctly
- No conflicting packages

---

## 5. Calibration (Required for Physical Metrics)

### Interactive Calibration Tool

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
source cv/venv/bin/activate

python cv/calibrate_interactive.py \
  --video /path/to/match_video.mp4 \
  --output cv/calibration_match.json
```

**Instructions**:
1. Click on 4+ pitch keypoints in the video frame
2. Enter corresponding real-world coordinates (meters)
3. Press 's' to save, 'q' to quit
4. Calibration JSON is saved to `cv/calibration_match.json`

**Example keypoints**:
- Corner flags: (0, 0), (105, 0), (105, 68), (0, 68)
- Penalty box corners
- Center circle points

**Standard pitch dimensions**:
- Length: 105 m
- Width: 68 m

---

## 6. Standalone Pipeline Run (Independent of Backend)

Test the pipeline directly on a video file:

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
source cv/venv/bin/activate

# Basic run (CPU or MPS auto-detected)
python -m cv.run_pipeline \
  --video backend/uploads/match_clip.mp4 \
  --out cv/results/ \
  --calibration cv/calibration_match.json \
  --model yolov8x.pt \
  --device mps

# With all v2.0 features
python -m cv.run_pipeline \
  --video backend/uploads/match_clip.mp4 \
  --out cv/results/ \
  --calibration cv/calibration_match.json \
  --model yolov8x.pt \
  --device mps \
  --tracker botsort \
  --annotate
```

**Output files** (in `cv/results/`):
- `tracking_detections.json/csv` - Frame-by-frame detections
- `player_match_stats.json/csv` - Per-player aggregated stats
- `meta.json` - Pipeline metadata (version, thresholds, warnings)
- `heatmaps.json` - Player heatmaps (if calibration available)
- `*_annotated.mp4` - Annotated video (if `--annotate` used)

---

## 7. Backend Integration (.env Configuration)

**⚠️ Backend-specific variables** (confirm exact names/values against `backend/.env.example` or backend config):

```bash
# Edit backend/.env
CV_PIPELINE_MODE=real          # stub|real (use 'real' for actual processing)
CV_PYTHON=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/venv/bin/python
CV_DEVICE=mps                  # mps|cpu|cuda
CV_CALIBRATION_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/calibration_match.json
```

**Note**: These variable names are **illustrative** based on coordinator guidance. Verify against your actual backend configuration files:
- `backend/.env.example`
- `backend/config.py` or similar backend config module

The backend will invoke the pipeline as:
```bash
$CV_PYTHON -m cv.run_pipeline \
  --video backend/uploads/<filename>.mp4 \
  --out backend/results/<session_id>/ \
  --calibration $CV_CALIBRATION_PATH \
  --device $CV_DEVICE \
  --model yolov8x.pt
```

---

## 8. Smoke Test (Quick Verification)

Run a quick test on a short clip:

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
source cv/venv/bin/activate

# Use yolov8n (fast) on a 10-second clip
python -m cv.run_pipeline \
  --video backend/uploads/test_clip_10s.mp4 \
  --out cv/smoke_test/ \
  --model yolov8n.pt \
  --device mps
```

**Expected time**: 5-10 seconds for 10s of video (30 fps)

**Check outputs**:
```bash
ls -lh cv/smoke_test/
# Should see: meta.json, tracking_detections.json, player_match_stats.json
```

---

## 9. Troubleshooting

### MPS Fallback (if MPS operations fail)

Some PyTorch operations may not be implemented for MPS. Enable CPU fallback:

```bash
export PYTORCH_ENABLE_MPS_FALLBACK=1
python -m cv.run_pipeline ...
```

### EasyOCR First-Run Download

First run with OCR will download ~100 MB of models:

```bash
# Pre-download to avoid delays during actual run
python -c "import easyocr; reader = easyocr.Reader(['en'])"
```

### Slow Processing Tips

**If processing is too slow**:

1. **Use smaller model**: `yolov8n.pt` or `yolov8s.pt` instead of `yolov8x.pt`
2. **Reduce OCR sampling**: `--ocr-sample-rate 10` (OCR every 10 frames instead of every frame)
3. **Disable annotation**: Remove `--annotate` flag (writing annotated video is slow)
4. **Downscale video**: Pre-process video to 720p if it's 1080p or 4K

Example fast run:
```bash
python -m cv.run_pipeline \
  --video match.mp4 \
  --out results/ \
  --model yolov8n.pt \
  --device mps \
  --ocr-sample-rate 10
```

### Memory Issues

If you see OOM (out of memory) errors:

1. Close other applications
2. Use `yolov8n.pt` instead of `yolov8x.pt`
3. Process shorter clips (split video if needed)

---

## 10. Performance Expectations

Approximate processing speeds on Apple Silicon:

| Model | Device | Relative Speed |
|-------|--------|----------------|
| yolov8n | MPS | ~15-20 fps |
| yolov8s | MPS | ~10-15 fps |
| yolov8m | MPS | ~8-12 fps |
| yolov8x | MPS | ~5-8 fps |

**Note**: Actual speed depends on video resolution, enabled features (OCR, annotation), and system load. Test on your hardware to determine real performance.

---

## 11. Next Steps

After successful setup:

1. ✅ Calibrate your match videos
2. ✅ Run pipeline on uploaded clips
3. ✅ Verify output JSON matches backend expectations
4. ✅ Integrate with backend endpoints
5. ✅ Test frontend visualization with real data

---

## Support & Documentation

- **Pipeline README**: `cv/README.md`
- **V2.0 Fields Reference**: `cv/V2_FIELDS_SUMMARY.md`
- **Benchmark Scripts**: `cv/benchmark/`
- **Unit Tests**: `cv/tests/`

For issues, check:
- Unit test failures: `python -m unittest discover -s cv/tests -v`
- Calibration quality: Check `meta.json` → `calibration_quality`
- Pipeline warnings: Check `meta.json` → `warnings`
