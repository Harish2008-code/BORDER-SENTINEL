"""Renders analyst overlays: suspect regions, portrait box, value regions."""
from __future__ import annotations

import cv2
import numpy as np

COLORS = {
    "suspect": (0, 0, 255),
    "portrait": (0, 200, 255),
    "value": (255, 200, 0),
    "face": (0, 255, 120),
}


def render_annotated(img, path_out, suspect_regions=(), portrait=None,
                     value_regions=(), face_boxes=()):
    canvas = img.copy()
    for (x, y, w, h) in suspect_regions:
        cv2.rectangle(canvas, (x, y), (x + w, y + h), COLORS["suspect"], 2)
    if portrait:
        x, y, w, h = (int(v) for v in portrait)
        cv2.rectangle(canvas, (x, y), (x + w, y + h), COLORS["portrait"], 3)
        cv2.putText(canvas, "PORTRAIT", (x, max(20, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLORS["portrait"], 2)
    for (x, y, w, h) in value_regions:
        cv2.rectangle(canvas, (x, y), (x + w, y + h), COLORS["value"], 1)
    for i, (x, y, w, h) in enumerate(face_boxes):
        cv2.rectangle(canvas, (int(x), int(y)), (int(x + w), int(y + h)),
                      COLORS["face"], 2)
        cv2.putText(canvas, f"FACE {i + 1}", (int(x), int(y) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLORS["face"], 2)
    cv2.putText(canvas, "BORDER SENTINEL ANALYST OVERLAY", (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 2)
    cv2.imwrite(str(path_out), canvas)
    return str(path_out)
