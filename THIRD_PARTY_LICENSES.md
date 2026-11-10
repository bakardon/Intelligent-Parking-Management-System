# Third-Party Licences

Audit date: 2026-11-10. Versions are those pinned in `requirements.txt` and verified by the test suite.
Licence data was read from each installed package's metadata and, for Ultralytics, from Ultralytics' published licensing terms.

> **This is an engineering inventory, not legal advice.** ParkSight is **not** cleared for sale as closed-source
> proprietary software in its current form — see the Ultralytics section. Have a lawyer confirm the position before a commercial contract.

## 1. Summary of the licensing position

| Item | Licence | Effect on a commercial ParkSight |
|---|---|---|
| **Ultralytics** (`ultralytics` 8.4.138, `ultralytics-thop`) | **AGPL-3.0** | **Blocking for closed-source distribution.** See §2. |
| **YOLO11n weights** (`yolo11n.pt`) | **AGPL-3.0** (per Ultralytics: all Ultralytics YOLO models fall under AGPL-3.0 by default) | Same as above. Weights are *not* included in the Docker image or Git; each site mounts them. That does not remove the obligation if ParkSight ships with or depends on them. |
| PyTorch / torchvision | BSD-style (torch: Apache-2.0, BSD, MIT, BSL-1.0 components) | Permissive. Keep notices. |
| OpenCV (`opencv-python`, Docker: `opencv-python-headless`) | Apache-2.0 | Permissive. The wheels bundle FFmpeg (LGPL-2.1); the desktop wheel also bundles Qt (LGPL). Dynamic linking inside the wheel; keep notices and allow replacement. The Docker image uses the headless wheel (no Qt). |
| psycopg2-binary | LGPL-3.0 with linking exceptions | Permissive in practice for unmodified use. Bundles libpq (PostgreSQL Licence) and OpenSSL (Apache-2.0). |
| FastAPI | MIT | Permissive |
| Starlette | BSD-3-Clause | Permissive |
| Uvicorn | BSD-3-Clause | Permissive |
| Pydantic / pydantic-core | MIT | Permissive |
| NumPy | BSD-3-Clause | Permissive |
| cryptography | Apache-2.0 OR BSD-3-Clause | Permissive |
| python-dotenv | BSD-3-Clause | Permissive |
| psutil (via ultralytics; used by the benchmark script) | BSD-3-Clause | Permissive |
| Pillow, PyYAML, matplotlib, polars, requests (ultralytics dependencies) | MIT-CMU, MIT, PSF-style, MIT, Apache-2.0 | Permissive |
| certifi (transitive) | MPL-2.0 | File-level copyleft; unmodified use is fine. |
| pytest, httpx (development only, not shipped) | MIT, BSD-3-Clause | Not distributed |
| **PostgreSQL** server (Docker `postgres:17-alpine`) | PostgreSQL Licence (permissive) | Permissive. The Alpine base contains BusyBox (GPL-2.0) and musl (MIT): ship-as-is with source availability via upstream. |
| Docker base `python:3.12-slim-bookworm` | Debian packages (mixed: GPL, LGPL, MIT, …); CPython: PSF-2.0 | Normal for container distribution; GPL packages are unmodified Debian packages (source available from Debian). |
| Frontend | ParkSight's own code; **no third-party JS/CSS/fonts** (system fonts only) | Nothing to attribute |
| Demo video `data/videos/parking.mp4` | **Unknown provenance — not tracked in Git** | Do not show it to customers or ship it until its source and licence are confirmed. |
| COCO training data (behind the pretrained weights) | Annotations CC BY 4.0; images under various Flickr licences | Generally considered acceptable for pretrained weights, but not formally resolved. Note only. |

## 2. Ultralytics — what it means for ParkSight

Facts established:
- The `ultralytics` package metadata declares **AGPL-3.0**.
- Ultralytics states that using its code, models or trained/fine-tuned models requires either releasing the **entire project** under AGPL-3.0 or obtaining an **Ultralytics Enterprise Licence**, and that this applies even to internal use. ([ultralytics.com/license](https://ultralytics.com/license))
- AGPL-3.0 §13: users who interact with the software over a network (e.g. a customer's staff using the dashboard) must be offered the corresponding source code.
- Free download does **not** imply proprietary commercial use rights.

Therefore ParkSight, as it stands, can be sold or deployed commercially **only** in one of these ways:

| Option | What it requires | Cost | Engineering effort |
|---|---|---|---|
| **A. Distribute ParkSight under AGPL-3.0** | License the whole ParkSight code base under AGPL-3.0, give every customer the complete source (including modifications), keep licence notices, offer source to dashboard users. You may still charge for installation, hardware, support and maintenance. | None | Low: add `LICENSE` (AGPL-3.0) and a source-offer notice. Competitors may legally reuse the code. |
| **B. Ultralytics Enterprise Licence** | Commercial agreement with Ultralytics (or an authorised reseller). | Paid — **not purchased** (out of scope) | None |
| **C. Replace the detector with a permissively licensed model** | E.g. RT-DETR or D-FINE (code and COCO weights published under Apache-2.0), run via ONNX Runtime (MIT) or PyTorch. Remove `ultralytics`. | None | Medium: new `VehicleDetector` implementation (the rest of ParkSight only consumes `{box, class, confidence}` dicts, so the change is contained in `src/detector.py`), then **re-validate accuracy and CPU performance** on site footage before switching. Verify each weight file's licence at download time. |

Not done in this release: option C was not implemented because the brief requires demonstrating that a replacement is at least as accurate before changing the detection path, and no labelled evaluation footage is available yet.

**Recommendation:** for the Islamabad pilot, either adopt option A (simplest, compliant today) or start option C in parallel with a small labelled test set from the pilot site. Do not ship a closed-source build that includes `ultralytics` or YOLO weights without option B.

## 3. ParkSight's own licence

The repository currently has **no `LICENSE` file**, so by default all rights are reserved by the author. The owner must choose a licence consistent with §2 before distribution.

## 4. Re-running this audit

```bash
python - <<'EOF'
from importlib import metadata as m
for d in sorted(m.distributions(), key=lambda d: d.metadata["Name"].lower()):
    md = d.metadata
    print(md["Name"], d.version, md.get("License-Expression") or (md.get("License") or "").split("\n")[0])
EOF
```
