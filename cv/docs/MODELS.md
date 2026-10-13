# Models & Licenses

Complete inventory of models, weights, and their licenses for the soccer CV pipeline.

---

## YOLO Models

### YOLOv8 (Ultralytics)

**Source**: [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)

**License**: **AGPL-3.0**

**⚠️ License Implications for Business Use**:

The AGPL-3.0 (GNU Affero General Public License) is a **copyleft license** with strong requirements:

1. **Source Code Disclosure**: If you run YOLOv8 as a network service (e.g., cloud API, web backend), you **must** provide the complete source code to all users of that service.

2. **Derivative Works**: Any modifications to YOLOv8 or software that incorporates it must also be licensed under AGPL-3.0.

3. **Commercial Use**: Permitted, but with the above restrictions. For closed-source commercial products, you need an **Ultralytics Enterprise License**.

**Commercial Licensing Options**:
- **Ultralytics Enterprise License**: Available for purchase to use YOLOv8 in closed-source commercial products without AGPL obligations.
- Contact: [Ultralytics Licensing](https://ultralytics.com/license)

**Our Use Case**:
- This pipeline is part of a capstone/academic project
- If deployed commercially, evaluate:
  - Open-sourcing the full pipeline (complies with AGPL)
  - Purchasing Ultralytics Enterprise License
  - Switching to a permissive-license model (e.g., YOLOv5 MIT, Detectron2 Apache-2.0)

**Weight Files**:
- `yolov8n.pt` - Nano (~6 MB)
- `yolov8s.pt` - Small (~22 MB)
- `yolov8m.pt` - Medium (~50 MB)
- `yolov8l.pt` - Large (~87 MB)
- `yolov8x.pt` - Extra-large (~136 MB)

**Training Data**: COCO dataset (person=class 0, sports ball=class 32)

**Download Location**: `~/.cache/torch/hub/ultralytics/`

**Auto-download**: First run triggers download via Ultralytics SDK

---

## EasyOCR

**Source**: [JaidedAI EasyOCR](https://github.com/JaidedAI/EasyOCR)

**License**: **Apache-2.0**

**License Summary**:
- ✅ Commercial use permitted
- ✅ Modification permitted
- ✅ Distribution permitted
- ✅ Private use permitted
- **No copyleft**: You can use it in closed-source software
- **Disclaimer of warranty**: No liability for damages

**Our Use**: Jersey number recognition (digits only)

**Models Used**:
- `craft_mlt_25k.pth` - Text detection (~20 MB)
- `latin_g2.pth` - Latin alphabet recognition (~80 MB)
- Language: English (`en`)

**Download Location**: `~/.EasyOCR/model/`

**Auto-download**: First OCR operation triggers download

---

## BoT-SORT Tracker

**Source**: [Ultralytics Tracker Integration](https://docs.ultralytics.com/modes/track/)

**Original Paper**: ["BoT-SORT: Robust Associations Multi-Pedestrian Tracking"](https://arxiv.org/abs/2206.14651) (Aharon et al., 2022)

**License**: Part of Ultralytics package → **AGPL-3.0** (same as YOLOv8)

**Components**:
1. **Kalman Filter**: Public domain (standard algorithm)
2. **Hungarian Algorithm**: Public domain (standard algorithm)
3. **GMC (Camera Motion Compensation)**: ORB feature matching (OpenCV, BSD-3-Clause)
4. **ReID Embeddings**: OSNet or similar (varies by implementation)

**Our Use**: Multi-object tracking for players

**Configuration**: `cv/config/botsort.yaml`

**Fallback**: ByteTrack (simpler, no ReID)

---

## ByteTrack

**Source**: [ByteTrack](https://github.com/ifzhang/ByteTrack)

**Original Paper**: ["ByteTrack: Multi-Object Tracking by Associating Every Detection Box"](https://arxiv.org/abs/2110.06864) (Zhang et al., 2021)

**License**: **MIT** (permissive)

**Our Use**: Fallback tracker (via `--tracker bytetrack`)

**Configuration**: `cv/config/bytetrack.yaml`

**Integrated**: Via Ultralytics (re-implemented)

---

## Kalman Filter (Ball Tracking)

**Source**: `filterpy` library ([GitHub](https://github.com/rlabbe/filterpy))

**License**: **MIT** (permissive)

**Algorithm**: Standard Kalman filter (public domain mathematical algorithm)

**Our Use**: Ball position prediction and smoothing

**Implementation**: `cv/ball_tracking.py` (`BallTracker`)

**State**: 4D `[x, y, vx, vy]` (position + velocity)

---

## OpenCV

**Source**: [OpenCV](https://opencv.org/)

**License**: **Apache-2.0** (permissive)

**Our Use**:
- Video I/O (`cv2.VideoCapture`, `cv2.VideoWriter`)
- Image processing (resize, color conversion, CLAHE)
- Homography estimation (`cv2.findHomography`)
- Feature detection (ORB for GMC)

**Version**: `>=4.8.0`

---

## PyTorch

**Source**: [PyTorch](https://pytorch.org/)

**License**: **BSD-3-Clause** (permissive)

**Our Use**:
- Deep learning framework (YOLOv8, EasyOCR backend)
- MPS acceleration (Apple Silicon)

**Version**: `>=2.1.0`

---

## scikit-learn

**Source**: [scikit-learn](https://scikit-learn.org/)

**License**: **BSD-3-Clause** (permissive)

**Our Use**:
- KMeans clustering (team classification)
- Normalization utilities

**Version**: `>=1.3.0`

---

## NetworkX

**Source**: [NetworkX](https://networkx.org/)

**License**: **BSD-3-Clause** (permissive)

**Our Use**:
- Graph algorithms (tracklet stitching)
- Connected components

**Version**: `>=3.2`

---

## Other Dependencies

All other dependencies (NumPy, Pandas, SciPy, tqdm, PyYAML, Pillow) use **permissive licenses** (BSD, MIT, Apache-2.0):

| Package | License |
|---------|---------|
| NumPy | BSD-3-Clause |
| Pandas | BSD-3-Clause |
| SciPy | BSD-3-Clause |
| tqdm | MPL-2.0 / MIT |
| PyYAML | MIT |
| Pillow | HPND (permissive) |

---

## License Summary Table

| Component | License | Commercial Use | Copyleft | Notes |
|-----------|---------|----------------|----------|-------|
| **YOLOv8** | AGPL-3.0 | ⚠️ With restrictions | ✅ Yes | Requires open-source or enterprise license |
| **BoT-SORT** | AGPL-3.0 | ⚠️ With restrictions | ✅ Yes | Part of Ultralytics |
| **EasyOCR** | Apache-2.0 | ✅ Unrestricted | ❌ No | Safe for closed-source |
| **ByteTrack** | MIT | ✅ Unrestricted | ❌ No | Safe for closed-source |
| **filterpy** | MIT | ✅ Unrestricted | ❌ No | Safe for closed-source |
| **OpenCV** | Apache-2.0 | ✅ Unrestricted | ❌ No | Safe for closed-source |
| **PyTorch** | BSD-3-Clause | ✅ Unrestricted | ❌ No | Safe for closed-source |
| **scikit-learn** | BSD-3-Clause | ✅ Unrestricted | ❌ No | Safe for closed-source |
| **NetworkX** | BSD-3-Clause | ✅ Unrestricted | ❌ No | Safe for closed-source |

---

## Recommendations for Commercial Deployment

### Option 1: Open-Source (AGPL Compliant)

**Approach**: Keep pipeline open-source under AGPL-3.0

**Pros**:
- ✅ Complies with YOLOv8 license
- ✅ No licensing costs
- ✅ Community contributions possible

**Cons**:
- ❌ Must disclose source code to all service users
- ❌ Competitors can use your code

**Best for**: Academic projects, open-source products, internal tools

---

### Option 2: Ultralytics Enterprise License

**Approach**: Purchase Ultralytics Enterprise License

**Pros**:
- ✅ Use YOLOv8 in closed-source products
- ✅ No AGPL obligations
- ✅ Commercial support from Ultralytics

**Cons**:
- ❌ Licensing costs (contact Ultralytics for pricing)

**Best for**: Commercial SaaS products, proprietary software

**Contact**: [https://ultralytics.com/license](https://ultralytics.com/license)

---

### Option 3: Alternative Models (MIT/Apache-2.0)

**Approach**: Replace YOLOv8 with permissive-license models

**Options**:
- **YOLOv5** (Ultralytics, GPL-3.0 → older versions MIT/Apache)
- **Detectron2** (Facebook, Apache-2.0)
- **MMDetection** (OpenMMLab, Apache-2.0)
- **YOLOv7** (WongKinYiu, GPL-3.0)
- **YOLOX** (Megvii, Apache-2.0)

**Trade-offs**:
- ✅ No copyleft restrictions
- ❌ May require retraining/fine-tuning
- ❌ Performance may differ from YOLOv8

**Best for**: Closed-source products without budget for enterprise licenses

---

## Compliance Checklist

For commercial deployment, verify:

- [ ] **License compatibility**: All components compatible with your product license
- [ ] **Attribution**: Proper credit to model authors (required by most licenses)
- [ ] **Source disclosure**: If using AGPL, provide source access to service users
- [ ] **Enterprise license**: If using YOLOv8 closed-source, purchase Ultralytics license
- [ ] **Model weights**: Ensure downloaded weights are from official sources (not redistributed)
- [ ] **Terms of service**: Check cloud platform terms (AWS, GCP, Azure) for ML model usage

---

## References

- **YOLOv8 License**: [https://github.com/ultralytics/ultralytics/blob/main/LICENSE](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)
- **AGPL-3.0 Explained**: [https://www.gnu.org/licenses/agpl-3.0.en.html](https://www.gnu.org/licenses/agpl-3.0.en.html)
- **Ultralytics Enterprise**: [https://ultralytics.com/license](https://ultralytics.com/license)
- **EasyOCR License**: [https://github.com/JaidedAI/EasyOCR/blob/master/LICENSE](https://github.com/JaidedAI/EasyOCR/blob/master/LICENSE)
- **OpenCV License**: [https://opencv.org/license/](https://opencv.org/license/)

---

**Disclaimer**: This document provides general guidance. Consult a legal professional for specific licensing advice for your commercial product.
