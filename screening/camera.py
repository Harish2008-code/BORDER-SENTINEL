"""Server-side OpenCV camera capture for live traveller photos."""
import base64
import time
import uuid
from pathlib import Path

import cv2
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET


def _open_camera(index=0, retries=3):
    """Open camera with retries."""
    for _ in range(retries):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            # warm-up frame
            cap.read()
            return cap
        cap.release()
        time.sleep(0.3)
    return None


@require_GET
def camera_snapshot(request):
    """Return a single JPEG frame as base64 JSON for preview."""
    cap = _open_camera()
    if cap is None:
        return JsonResponse({"ok": False, "error": "Cannot open camera"}, status=503)
    try:
        ret, frame = cap.read()
        if not ret:
            return JsonResponse({"ok": False, "error": "Failed to read frame"}, status=503)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        b64 = base64.b64encode(buf.tobytes()).decode()
        return JsonResponse({"ok": True, "image": b64})
    finally:
        cap.release()


def _generate_mjpeg(cap):
    """Yield MJPEG frames for streaming."""
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
            time.sleep(0.05)  # ~20 fps cap
    finally:
        cap.release()


@require_GET
def camera_stream(request):
    """MJPEG stream for live preview in the browser."""
    cap = _open_camera()
    if cap is None:
        return JsonResponse({"ok": False, "error": "Cannot open camera"}, status=503)
    return StreamingHttpResponse(
        _generate_mjpeg(cap),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )


@csrf_exempt
@require_POST
def camera_capture(request):
    """Capture a frame, save it to media/live/, return the relative path."""
    cap = _open_camera()
    if cap is None:
        return JsonResponse({"ok": False, "error": "Cannot open camera"}, status=503)
    try:
        ret, frame = cap.read()
        if not ret:
            return JsonResponse({"ok": False, "error": "Failed to capture"}, status=503)
        fname = f"{uuid.uuid4().hex[:10]}_live_capture.jpg"
        out_dir = Path(settings.MEDIA_ROOT) / "live"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / fname
        cv2.imwrite(str(out_path), frame)
        return JsonResponse({"ok": True, "path": f"live/{fname}"})
    finally:
        cap.release()
