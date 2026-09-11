"""
Module 4 - Face Detection & Verification.

Primary backend: OpenCV DNN - YuNet face detector + SFace 128-d recogniser
(ONNX models shipped in screening/models).  Fallback: Haar cascade detection
with a classical histogram descriptor so the pipeline still runs on machines
without the ONNX weights.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
YUNET = os.path.join(_MODEL_DIR, "face_detection_yunet_2023mar.onnx")
SFACE = os.path.join(_MODEL_DIR, "face_recognition_sface_2021dec.onnx")

_det = None
_rec = None
_haar = None


def _detector():
    global _det
    if _det is None and os.path.exists(YUNET):
        try:
            _det = cv2.FaceDetectorYN.create(YUNET, "", (320, 320), 0.6, 0.3, 1000)
        except cv2.error:
            _det = None
    return _det


def _recogniser():
    global _rec
    if _rec is None and os.path.exists(SFACE):
        try:
            _rec = cv2.FaceRecognizerSF.create(SFACE, "")
        except cv2.error:
            _rec = None
    return _rec


def _haar_cascade():
    global _haar
    if _haar is None:
        try:
            _haar = cv2.CascadeClassifier(
                os.path.join(cv2.data.haarcascades,
                             "haarcascade_frontalface_default.xml"))
            if _haar.empty():
                _haar = False  # loaded but no data
        except Exception:
            # cv2 build without CascadeClassifier / cv2.data (broken install)
            _haar = False
    return _haar or None


def backend_name():
    return "yunet+sface" if (_detector() and _recogniser()) else "haar+classical"


def detect_faces(img, max_faces=3):
    """Return list of [x, y, w, h] bounding boxes, best first.

    Degrades gracefully: if neither the YuNet DNN detector nor the Haar
    cascade is available (e.g. a broken OpenCV build), returns [] instead
    of crashing, so the rest of the screening pipeline still runs.
    """
    # Primary: YuNet DNN detector
    try:
        det = _detector()
        if det is not None:
            det.setInputSize((img.shape[1], img.shape[0]))
            _, faces = det.detect(img)
            if faces is not None and len(faces):
                boxes = [tuple(float(v) for v in f[:4]) for f in faces]
                boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
                return boxes[:max_faces]
    except Exception:
        pass

    # Fallback: Haar cascade (may be unavailable on some cv2 builds)
    try:
        haar = _haar_cascade()
        if haar is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            found = haar.detectMultiScale(gray, 1.1, 6, minSize=(60, 60))
            boxes = [tuple(float(v) for v in f) for f in found]
            boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
            return boxes[:max_faces]
    except Exception:
        pass

    return []


def _classical_descriptor(img, bbox):
    x, y, w, h = [int(v) for v in bbox]
    face = img[max(0, y):y + h, max(0, x):x + w]
    if face.size == 0:
        return np.zeros(96)
    face = cv2.resize(face, (96, 96))
    hsv = cv2.cvtColor(face, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [32], [0, 180]).flatten()
    hist_s = cv2.calcHist([hsv], [1], None, [16], [0, 256]).flatten()
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    lbp = np.zeros_like(gray)
    for i, (dx, dy, bit) in enumerate([(-1, -1, 1), (0, -1, 2), (1, -1, 4),
                                      (1, 0, 8), (1, 1, 16), (0, 1, 32),
                                      (-1, 1, 64), (-1, 0, 128)]):
        shifted = np.roll(np.roll(gray, -dy, axis=0), -dx, axis=1)
        lbp += (shifted >= gray).astype(np.uint8) * bit
    hist_l = cv2.calcHist([lbp], [0], None, [48], [0, 256]).flatten()
    desc = np.concatenate([hist_h / (hist_h.sum() + 1e-9),
                           hist_s / (hist_s.sum() + 1e-9),
                           hist_l / (hist_l.sum() + 1e-9)])
    return desc


def embed(img, bbox):
    rec = _recogniser()
    if rec is not None:
        det = _detector()
        if det is not None:
            det.setInputSize((img.shape[1], img.shape[0]))
            _, faces = det.detect(img)
            if faces is not None:
                best = min(faces, key=lambda f: abs(f[0] - bbox[0]) + abs(f[1] - bbox[1]))
                aligned = rec.alignCrop(img, best)
                return rec.feature(aligned)[0], "sface"
    return _classical_descriptor(img, bbox), "classical"


def compare(feat_a, feat_b):
    """Cosine similarity (identical to FaceRecognizerSF FR_COSINE)."""
    a = np.asarray(feat_a, dtype=np.float64).ravel()
    b = np.asarray(feat_b, dtype=np.float64).ravel()
    if a.shape != b.shape or a.size == 0:
        return 0.0
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(a @ b / (na * nb))


def face_quality(img, bbox):
    x, y, w, h = [int(v) for v in bbox]
    face = img[max(0, y):max(1, y + h), max(0, x):max(1, x + w)]
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    return {
        "size_px": int(min(w, h)),
        "sharpness": round(sharp, 1),
        "brightness": round(brightness, 1),
        "ok": bool(min(w, h) >= 70 and sharp > 40 and 40 < brightness < 220),
    }


def verify(document_img, live_img, threshold):
    """Full verification result between document portrait and live capture."""
    doc_faces = detect_faces(document_img)
    live_faces = detect_faces(live_img)
    result = {
        "backend": backend_name(),
        "doc_faces": len(doc_faces),
        "live_faces": len(live_faces),
        "faces": [{"bbox": [int(v) for v in f] , "quality": face_quality(document_img, f)}
                  for f in doc_faces],
    }
    if not doc_faces:
        result.update(matched=False, similarity=None,
                      detail="No portrait detected on the document")
        return result
    if not live_faces:
        result.update(matched=False, similarity=None,
                      detail="No face detected in the live capture")
        return result
    feat_d, kind_d = embed(document_img, doc_faces[0])
    feat_l, _ = embed(live_img, live_faces[0])
    sim = compare(feat_d, feat_l)
    thr = threshold if kind_d == "sface" else 0.80
    result.update(
        matched=bool(sim >= thr), similarity=round(float(sim), 3),
        threshold=thr, engine=kind_d,
        detail=f"cosine similarity {sim:.3f} vs threshold {thr:.3f}")
    return result
