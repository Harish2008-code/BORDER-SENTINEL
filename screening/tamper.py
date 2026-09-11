"""
Module 3 - Tampering Detection (core AI innovation).

A suite of forensic detectors, each returning {name, score(0-100), detail,
regions}.  Because identity documents are covered in printing (text strokes,
guilloche, stamps), statistics are computed on *flat* blocks only - forgery
signatures live in the smooth areas between the print, exactly where a
forger's splice or local recompression leaves traces.

  * Error Level Analysis   - double JPEG recompression energy discontinuities
  * Noise residual maps    - sensor/quantisation noise inconsistency
  * Copy-move detection    - duplicated patches on the noise residual
  * Metadata forensics     - editing-software fingerprints in EXIF
  * Photo splice detection - seam + statistics divergence around the portrait
  * Text region analysis   - value regions compared against their peers
"""
from __future__ import annotations

import cv2
import numpy as np

BLOCK = 16


def _block_grid(shape, size=BLOCK):
    h, w = shape[:2]
    ys = range(0, h - size + 1, size)
    xs = range(0, w - size + 1, size)
    return [(y, x) for y in ys for x in xs], size


def _flat_blocks(img):
    """Per-block mean gradient magnitude; flat = below median gradient."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    coords, size = _block_grid(img.shape)
    grads = np.array([grad[y:y + size, x:x + size].mean() for y, x in coords])
    return coords, grads <= np.percentile(grads, 55)


def _robust_z(vals):
    med = np.median(vals)
    mad = np.median(np.abs(vals - med)) + 1e-6
    return 0.6745 * (vals - med) / mad, float(med), float(mad)


def _anomaly_score(z, coords, flat, z_thresh=4.0):
    zf = z[flat]
    frac = float((np.abs(zf) > z_thresh).mean()) if len(zf) else 0.0
    p99 = float(np.percentile(np.abs(zf), 99)) if len(zf) else 0.0
    med = float(np.median(np.abs(zf))) + 1e-6
    ratio = p99 / med
    score = min(100.0, frac * 500.0 + max(0.0, ratio - 5.0) * 8.0)
    regions = [(coords[i][1], coords[i][0], BLOCK, BLOCK)
               for i in range(len(z)) if flat[i] and abs(z[i]) > z_thresh + 1.0]
    return score, regions, frac, ratio


def _ela_diff(img, quality=90):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    resaved = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return np.abs(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) -
                  cv2.cvtColor(resaved, cv2.COLOR_BGR2GRAY).astype(np.float32))


def ela_detector(img):
    diff = _ela_diff(img)
    if diff is None:
        return {"name": "Error Level Analysis", "score": 0, "detail": "n/a",
                "regions": []}
    coords, flat = _flat_blocks(img)
    size = BLOCK
    vals = np.array([diff[y:y + size, x:x + size].mean() for y, x in coords])
    z, med, mad = _robust_z(vals)
    score, regions, frac, ratio = _anomaly_score(z, coords, flat)
    return {
        "name": "Error Level Analysis",
        "score": round(score, 1),
        "detail": f"flat-block anomaly {frac:.1%}, p99/med {ratio:.1f}",
        "regions": regions[:40],
    }


def _blockiness(gray_f, ox=0, oy=0):
    """Ratio of gradient energy sitting exactly on the 8px JPEG block grid.
    Locally re-compressed forgeries show elevated grid blockiness.

    The JPEG grid is anchored at the *image* origin, so (ox, oy) - the crop
    offset modulo 8 - must be supplied or the measurement aliases."""
    gx = np.abs(np.diff(gray_f, axis=1))
    gy = np.abs(np.diff(gray_f, axis=0))
    onx_idx = [j for j in range(gx.shape[1]) if (j + ox) % 8 == 7]
    ony_idx = [j for j in range(gy.shape[0]) if (j + oy) % 8 == 7]
    offx = np.delete(gx, onx_idx, axis=1).mean() + 1e-6
    offy = np.delete(gy, ony_idx, axis=0).mean() + 1e-6
    onx = gx[:, onx_idx].mean() if onx_idx else 0.0
    ony = gy[ony_idx, :].mean() if ony_idx else 0.0
    return float(((onx / offx) + (ony / offy)) / 2.0)


def noise_detector(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    residual = np.abs(gray.astype(np.float32) -
                      cv2.medianBlur(gray, 3).astype(np.float32))
    residual = cv2.blur(residual, (5, 5))
    coords, flat = _flat_blocks(img)
    vals = np.array([residual[y:y + BLOCK, x:x + BLOCK].mean()
                     for y, x in coords])
    z, med, mad = _robust_z(vals)
    score, regions, frac, ratio = _anomaly_score(z, coords, flat, z_thresh=4.5)
    return {
        "name": "Noise Residual Inconsistency",
        "score": round(score, 1),
        "detail": f"flat-block residual outliers {frac:.1%}",
        "regions": regions[:40],
    }


def copy_move_detector(img):
    """Duplicate-patch search over the noise residual: printed graphics are
    removed, so only cloned raster content (pasted stamps / copied regions)
    produces matches."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    residual = (gray.astype(np.float32) - cv2.medianBlur(gray, 3).astype(np.float32))
    residual = cv2.normalize(residual, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    orb = cv2.ORB_create(2000)
    kp, des = orb.detectAndCompute(residual, None)
    if des is None or len(kp) < 30:
        return {"name": "Copy-Move / Duplicated Patch", "score": 0,
                "detail": f"{0 if des is None else len(kp)} residual keypoints",
                "regions": []}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = bf.knnMatch(des, des, k=5)
    pairs = 0
    regions = []
    for mlist in matches:
        for m in mlist[1:]:
            if m.distance > 18:
                continue
            p1, p2 = kp[m.queryIdx].pt, kp[m.trainIdx].pt
            if np.hypot(p1[0] - p2[0], p1[1] - p2[1]) < 100:
                continue
            pairs += 1
            if len(regions) < 24:
                regions.append((int(p1[0]) - 8, int(p1[1]) - 8, 16, 16))
    # conservative: printed glyphs (MRZ fillers etc.) legitimately repeat, so
    # only large-scale cloning of whole patches is scored
    score = min(100.0, max(0.0, (pairs - 400) * 0.5))
    return {
        "name": "Copy-Move / Duplicated Patch",
        "score": round(score, 1),
        "detail": f"{pairs} duplicated residual-keypoint pairs",
        "regions": regions,
    }


def metadata_detector(path):
    flags = []
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
        for tag in (b"Photoshop", b"Adobe", b"GIMP", b"Paint", b"ImageMagick"):
            if tag in blob:
                flags.append(tag.decode())
        from PIL import Image
        exif = Image.open(path).getexif()
        software = str(exif.get(305, ""))
        if software:
            flags.append(software)
    except Exception as exc:
        return {"name": "Metadata Forensics", "score": 0,
                "detail": f"unreadable: {exc}", "regions": []}
    suspicious = [f for f in flags if any(k in f.lower() for k in
                  ("photoshop", "gimp", "paint", "imagemagick", "adobe"))]
    score = min(100.0, 30 * len(suspicious) + (10 if flags and not suspicious else 0))
    return {
        "name": "Metadata Forensics",
        "score": score,
        "detail": "; ".join(flags) if flags else "no editing software fingerprints",
        "regions": [],
    }


def photo_splice_detector(img, face_bbox):
    if not face_bbox:
        return {"name": "Portrait Splice Analysis", "score": 0,
                "detail": "no portrait located", "regions": []}
    x, y, w, h = [int(v) for v in face_bbox]
    H, W = img.shape[:2]
    pad = 0.12
    xi, yi = max(0, int(x - w * pad)), max(0, int(y - h * pad))
    wi, hi = min(W - xi, int(w * (1 + 2 * pad))), min(H - yi, int(h * (1 + 2 * pad)))
    mask = np.ones((H, W), bool)
    mask[yi:yi + hi, xi:xi + wi] = False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    blk_in = _blockiness(gray[yi:yi + hi, xi:xi + wi], xi % 8, yi % 8)
    blk_out = _blockiness(gray)
    blk_ratio = blk_in / (blk_out + 1e-6)
    resid = np.abs(gray - cv2.medianBlur(gray.astype(np.uint8), 3).astype(np.float32))
    resid_in = float(resid[yi:yi + hi, xi:xi + wi].mean())
    resid_out = float(resid[mask].mean()) if mask.any() else 1.0
    resid_ratio = resid_in / (resid_out + 1e-6)

    # seam search strictly inside the portrait window (the printed frame is
    # legitimate, so it is excluded)
    ix0, iy0 = xi + int(wi * 0.12), yi + int(hi * 0.12)
    ix1, iy1 = xi + wi - int(wi * 0.12), yi + hi - int(hi * 0.12)
    inner = img[iy0:iy1, ix0:ix1]
    seam = 0.0
    if inner.size:
        edges = cv2.Canny(cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY), 90, 200)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 70,
                                minLineLength=int((ix1 - ix0) * 0.7), maxLineGap=6)
        if lines is not None:
            axis_lines = 0
            for l in np.asarray(lines).reshape(-1, 4):
                x1, y1, x2, y2 = (int(v) for v in l)
                if abs(x1 - x2) < 5 or abs(y1 - y2) < 5:
                    axis_lines += 1
            seam = min(1.0, axis_lines / 3.0)
    # conservative: portrait texture varies a lot between legitimate photo
    # sources, so only seam geometry and extreme statistics are scored;
    # impersonation itself is Module 4's job
    score = min(100.0, seam * 60.0 + max(0.0, blk_ratio - 1.6) * 150.0
                + max(0.0, resid_ratio - 2.2) * 100.0)
    return {
        "name": "Portrait Splice Analysis",
        "score": round(score, 1),
        "detail": (f"blockiness ratio {blk_ratio:.2f}, noise ratio "
                   f"{resid_ratio:.2f}, seam {seam:.2f}"),
        "regions": [(xi, yi, wi, hi)] if score > 35 else [],
    }


def text_region_detector(img, regions):
    """Value regions are compared against their peers (other value regions),
    not against the page background: a locally recompressed edit stands out
    within the population of printed fields."""
    if not regions or len(regions) < 3:
        return {"name": "Text Region Forensics", "score": 0,
                "detail": "not enough value regions", "regions": []}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    page_blk = _blockiness(gray)
    H, W = img.shape[:2]
    ratios, boxes, seen = [], [], set()
    for (rx, ry, rw, rh) in regions:
        rx, ry = max(0, int(rx)), max(0, int(ry))
        rw, rh = max(8, min(int(rw), W - rx)), max(8, min(int(rh), H - ry))
        # regions smaller than ~3 JPEG blocks per side are too tiny for
        # stable grid statistics (single glyphs like "F" would mislead us)
        if rw < 24 or rh < 24:
            continue
        if (rx, ry, rw, rh) in seen:
            continue
        seen.add((rx, ry, rw, rh))
        ratios.append(_blockiness(gray[ry:ry + rh, rx:rx + rw], rx % 8, ry % 8)
                      / (page_blk + 1e-6))
        boxes.append((rx, ry, rw, rh))
    # conservative tails: only extreme grid-energy deviation is reported so
    # that layout variety never causes false positives; subtle local edits
    # are left to the validation gates (Module 2)
    suspects = [(boxes[i], ratios[i]) for i in range(len(ratios))
                if ratios[i] > 1.9 or ratios[i] < 0.45]
    dev = max((abs(s[1] - 1.0) for s in suspects), default=0.0)
    score = min(100.0, 40 * len(suspects) + 60 * max(0.0, dev - 0.9))
    return {
        "name": "Text Region Forensics",
        "score": round(score, 1),
        "detail": (f"{len(suspects)} of {len(ratios)} value regions show "
                   f"recompression (max deviation {dev:.2f})"),
        "regions": [s[0] for s in suspects],
    }


def run_tamper_suite(img, path, face_bbox=None, text_regions=None):
    detectors = [
        ela_detector(img),
        noise_detector(img),
        copy_move_detector(img),
        metadata_detector(path),
        photo_splice_detector(img, face_bbox),
        text_region_detector(img, text_regions or []),
    ]
    scores = sorted((d["score"] for d in detectors), reverse=True)
    combined = scores[0]
    if len(scores) > 1 and scores[1] > 25:
        combined = min(100.0, combined + 0.25 * scores[1])
    regions = []
    for d in detectors:
        regions += d["regions"]
    return {
        "score": round(float(combined), 1),
        "detectors": detectors,
        "regions": regions[:60],
    }
