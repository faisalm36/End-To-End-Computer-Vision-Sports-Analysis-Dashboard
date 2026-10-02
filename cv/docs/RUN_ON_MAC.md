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

### Mac Folder Layout

Your capstone folder `/Users/faisalmusa/End-To-EndCompVisionCapstoneProject` contains:
- `backend/` - Backend server (NOT in GitHub repo, local only)
- `frontend/` - Frontend app (IS in GitHub repo)
- Potentially: `cv/` and other repo files (if already cloned)

**Note**: Only `backend/` is untracked. `frontend/` is part of the repository.

---

### Case Detection: Is the Folder a Git Clone?

Check if the capstone folder is already a git repository:

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
git -C . rev-parse --is-inside-work-tree 2>/dev/null

# Output:
# - "true" = Case A (git clone exists)
# - empty/error = Case B (not a git clone)
```

---

### Case A: Folder IS a Git Clone

If the capstone folder is already a git repository:

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject

# Fetch latest changes
git fetch origin

# Option 1: Checkout PR #2 directly (stacked branch)
git checkout cursor/cv-pipeline-v2-commercial-quality-023d
git pull origin cursor/cv-pipeline-v2-commercial-quality-023d

# Option 2: After PRs merged to main
git checkout main
git pull origin main
```

**Important**: Git will NOT touch untracked files (`backend/`). Your local backend is safe.

---

### Case B: Folder is NOT a Git Clone

If the capstone folder is not a git repo (only contains `backend/` and `frontend/`):

**Option 1: Clone repo elsewhere and point env vars at it**

```bash
# Clone to a separate location
cd ~
git clone https://github.com/faisalm36/End-To-End-Computer-Vision-Sports-Analysis-Dashboard cv-pipeline
cd cv-pipeline

# Checkout PR #2
git checkout cursor/cv-pipeline-v2-commercial-quality-023d
git pull origin cursor/cv-pipeline-v2-commercial-quality-023d

# Set up venv here
python3.13 -m venv cv/venv
source cv/venv/bin/activate
pip install -r cv/requirements.txt
```

Then in `backend/.env`:
```bash
CV_PIPELINE_PATH=/Users/faisalmusa/cv-pipeline/cv/run_pipeline.py
CV_PYTHON=/Users/faisalmusa/cv-pipeline/cv/venv/bin/python
```

**Option 2: Copy `cv/` into capstone folder**

```bash
# Clone temporarily
cd /tmp
git clone https://github.com/faisalm36/End-To-End-Computer-Vision-Sports-Analysis-Dashboard temp-cv
cd temp-cv
git checkout cursor/cv-pipeline-v2-commercial-quality-023d

# Copy cv/ to capstone folder
cp -r cv /Users/faisalmusa/End-To-EndCompVisionCapstoneProject/

# Set up venv in capstone folder
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then in `backend/.env`:
```bash
CV_PIPELINE_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/run_pipeline.py
CV_PYTHON=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/venv/bin/python
```

---

### Merge Strategy

**Status**: PR #2 has been merged into PR #1's branch, and PR #1 has been merged into `main` (commits 9c1d144 and 5a5b8d0).

The target tracking PR (`cursor/target-tracking-replay-97fa`) is rebased on `main` and merges directly into `main`.

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

**Expected result**:
```
Ran X tests in X.XXs

OK
```

**All tests should pass**. If any fail, check:
- Python version (`python --version` should show 3.13.x or 3.12.x)
- Dependencies installed correctly
- No conflicting packages

**Note**: Tests ran on Python 3.12 in the VM. Python 3.13 on Mac is the first real 3.13 run. If `pip install` fails on 3.13, likely culprits are `easyocr`, `networkx`, or `scikit-learn`. Try installing them individually to isolate issues.

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

### Exact Backend v0.4.0 Contract

The backend reads these environment variables from `backend/.env`:

```bash
# ============================================================================
# CV Pipeline Configuration (backend v0.4.0)
# ============================================================================

# Pipeline Mode
# - auto: Use real pipeline if CV_PIPELINE_PATH exists, else stub if CV_PIPELINE_STUB=true, else fail
# - real: Always use real pipeline, fail if CV_PIPELINE_PATH missing
# - stub: Always use fake data (for testing without pipeline)
CV_PIPELINE_MODE=real

# Stub Mode Toggle (only used when CV_PIPELINE_MODE=auto)
CV_PIPELINE_STUB=false

# Path to cv/run_pipeline.py, the cv/ directory, or repo root
# Default: <capstone root>/cv/run_pipeline.py
CV_PIPELINE_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/run_pipeline.py

# Python executable from cv venv (empty = use backend's python)
CV_PYTHON=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/venv/bin/python

# Device for inference
# - auto: Auto-detect (MPS if available, else CUDA, else CPU)
# - mps: Apple Silicon GPU
# - cuda: NVIDIA GPU
# - cpu: CPU only
CV_DEVICE=mps

# Model weights name or path (empty = pipeline default yolov8x.pt)
CV_MODEL=

# Calibration JSON path (empty = no --calibration flag passed)
CV_CALIBRATION_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/calibration_match.json

# Extra arguments (shlex-split, e.g. "--ocr-sample-rate 10" or "--no-ocr")
CV_EXTRA_ARGS=

# Timeout in seconds (default 14400 = 4 hours)
CV_TIMEOUT_SECONDS=14400

# Create unknown players in database (default true)
CV_CREATE_UNKNOWN_PLAYERS=true

# Output directory (default backend/uploads/cv_outputs)
CV_OUTPUT_DIR=backend/uploads/cv_outputs
```

### Backend Invocation Details

**Working directory**: Repository root (resolved from `CV_PIPELINE_PATH`)

**PYTHONPATH**: Repository root prepended

**Command**:
```bash
$CV_PYTHON -m cv.run_pipeline \
  --video <absolute path to upload> \
  --out <absolute path to CV_OUTPUT_DIR/video_<id>> \
  --device $CV_DEVICE \
  [--calibration <absolute path>] \
  [--model $CV_MODEL] \
  $CV_EXTRA_ARGS
```

**Output files** (all written to `--out` directory):
- `tracking_detections.json` - Frame-by-frame detections
- `player_match_stats.json` - Per-player statistics
- `meta.json` - Pipeline metadata
- `heatmaps.json` - Player heatmaps (empty `{}` if no calibration)
- `pipeline.log` - Pipeline stdout/stderr (backend captures)

**Progress tracking**: Backend parses lines matching `'Processing frames: N%'` from pipeline output for real-time progress display.

### Recommended Mac Settings

```bash
CV_PIPELINE_MODE=real
CV_PIPELINE_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/run_pipeline.py
CV_PYTHON=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/venv/bin/python
CV_DEVICE=mps
CV_CALIBRATION_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/calibration_match.json
```

**⚠️ Important**: Restart the backend after any `.env` changes (settings load at startup).

---

## 8. Smoke Test (Quick Verification)

Run a quick test on a short clip:

```bash
cd /Users/faisalmusa/End-To-EndCompVisionCapstoneProject
source cv/venv/bin/activate

# Find a video in backend/uploads
ls backend/uploads/

# Run quick test with yolov8n (fast) and no OCR
python -m cv.run_pipeline \
  --video backend/uploads/<filename>.mp4 \
  --out cv/smoke_test/ \
  --model yolov8n.pt \
  --no-ocr \
  --device mps
```

**Check outputs**:
```bash
ls -lh cv/smoke_test/
# Should see: meta.json, tracking_detections.json, player_match_stats.json, heatmaps.json

# Check runtime
cat cv/smoke_test/meta.json | grep runtime_s
# meta.json records runtime_s - measure on your hardware
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

Performance depends on video resolution, enabled features (OCR, annotation), model size, and system load.

**Measure on your hardware**. The `meta.json` output file records `runtime_s` for each run.

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
