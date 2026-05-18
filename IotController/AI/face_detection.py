"""
FaceDetector — Smart Security System
Optimised for Raspberry Pi 5 + Camera Module 3 (CSI ribbon, libcamera/picamera2).

HOW IT WORKS
  1. BGR → RGB  (Camera Module 3 outputs BGR; face_recognition requires RGB)
  2. Try 50% scale first with upsample=2 — best for arm's-length / below-face camera
  3. Try 25% scale with upsample=2  — catches very large / close faces
  4. Try 75% scale with upsample=1  — catches small / distant / partially-framed faces
  5. Stop as soon as any scale finds a face — no wasted CPU
  6. Falls back to Haar cascade when face_recognition is not installed

The same detector is used for:
  - IDLE / ACCESS overlay bounding boxes
  - Face buffer used by FaceVerifier.store_detected_face()
"""

import cv2
import numpy as np

try:
    import face_recognition
    _HAS_FACE_RECOGNITION = True
except ImportError:
    _HAS_FACE_RECOGNITION = False
    print("[FACE DETECTOR] face_recognition not installed — using Haar cascade fallback.")

# Shared dlib mutex — face_recognition is NOT thread-safe.
# Import the same lock used by FaceVerifier so both share one global lock.
try:
    from IotController.AI.face_verfication import _DLIB_LOCK
except Exception:
    import threading as _threading
    _DLIB_LOCK = _threading.Lock()  # fallback if import path differs


class FaceDetector:
    """
    Face detector optimised for Camera Module 3 on Raspberry Pi 5.
    Public API (unchanged):  detect_faces(frame)  →  (boxes, face_images)
    """

    def __init__(self):
        # Haar fallback when face_recognition not installed
        # cv2.data.haarcascades exists on OpenCV ≥ 4.x; fall back for older Pi builds
        try:
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        except AttributeError:
            import os as _os
            cascade_path = _os.path.join(
                _os.path.dirname(cv2.__file__),
                'data', 'haarcascade_frontalface_default.xml'
            )
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        # ── Blur rejection ──────────────────────────────────────────────────
        # Frames with Laplacian variance below this are too blurry to detect.
        # Lower this if the camera is legitimately soft (e.g. wide aperture).
        self.blur_threshold = 8.0
        self.last_blur_score = 0.0

    # =========================================================================
    # PUBLIC: FACE DETECTION
    # =========================================================================
    def detect_faces(self, frame):
        """
        Detect all faces in a BGR frame (Camera Module 3 native format).

        Returns
        -------
        boxes       : list of (x, y, w, h) in original-frame pixel coords
        face_images : list of cropped BGR face patches (same order as boxes)

        Never raises.  Returns ([], []) on any error.
        """
        if frame is None:
            return [], []

        try:
            # ── Blur guard ──────────────────────────────────────────────────
            gray_check = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self.last_blur_score = cv2.Laplacian(gray_check, cv2.CV_64F).var()
            if self.last_blur_score < self.blur_threshold:
                return [], []          # Autofocus cycling — skip frame

            # ── Detection ───────────────────────────────────────────────────
            raw_locs = (self._detect_hog(frame) if _HAS_FACE_RECOGNITION
                        else self._detect_haar(frame))

            if not raw_locs:
                return [], []

            # ── Clamp & crop ────────────────────────────────────────────────
            fh, fw = frame.shape[:2]
            boxes       = []
            face_images = []
            for (x, y, w, h) in raw_locs:
                x = max(0, int(x));  y = max(0, int(y))
                w = min(int(w), fw - x);  h = min(int(h), fh - y)
                if w > 0 and h > 0:
                    boxes.append((x, y, w, h))
                    face_images.append(frame[y:y + h, x:x + w])

            return boxes, face_images

        except Exception as exc:
            print(f"[FACE DETECTOR ERROR] {exc}")
            return [], []

    # =========================================================================
    # PRIVATE: HOG DETECTION  (face_recognition)
    # =========================================================================
    def _detect_hog(self, frame):
        """
        Multi-scale HOG detection — three passes in priority order.

        3-pass multi-scale HOG detection.

        Scale order is calibrated for Camera Module 3 held BELOW face level
        (looking upward at an arm's-length face):

          Pass 1 — 50% / upsample=2  BEST for arm's-length distance.
                    A face ~20-40 cm away occupies 15-40% of the frame.
                    50% scale keeps it large enough to detect reliably.

          Pass 2 — 25% / upsample=2  Very close / large face.
                    Camera under chin; face dominates the frame.

          Pass 3 — 75% / upsample=1  Distant / partially-framed face.
                    Camera further away or person is stepping back.

        Stops at the first pass that finds faces — zero wasted CPU.
        BGR → RGB converted once, reused for all three passes.
        """
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # ── Pass 1: 50%, upsample=2  (arm's-length, camera below face) ────
        small50 = cv2.resize(rgb, (0, 0), fx=0.50, fy=0.50)
        with _DLIB_LOCK:
            locs = face_recognition.face_locations(
                small50, model="hog", number_of_times_to_upsample=2)
        if locs:
            return self._dlib_to_opencv(locs, scale=2)

        # ── Pass 2: 25%, upsample=2  (very close / large face) ────────────
        small25 = cv2.resize(rgb, (0, 0), fx=0.25, fy=0.25)
        with _DLIB_LOCK:
            locs = face_recognition.face_locations(
                small25, model="hog", number_of_times_to_upsample=2)
        if locs:
            return self._dlib_to_opencv(locs, scale=4)

        # ── Pass 3: 75%, upsample=1  (distant / partially-framed face) ─────
        small75 = cv2.resize(rgb, (0, 0), fx=0.75, fy=0.75)
        with _DLIB_LOCK:
            locs = face_recognition.face_locations(
                small75, model="hog", number_of_times_to_upsample=1)
        if locs:
            return [(int(l * 4 // 3), int(t * 4 // 3),
                     int((r - l) * 4 // 3), int((b - t) * 4 // 3))
                    for (t, r, b, l) in locs]

        return []


    # =========================================================================
    # PRIVATE: HAAR CASCADE FALLBACK
    # =========================================================================
    def _detect_haar(self, frame):
        """
        Haar cascade detector — used when face_recognition is not installed.
        Works on BGR directly (no conversion needed).
        """
        small = cv2.resize(frame, (320, 240))
        gray  = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        if not isinstance(faces, np.ndarray) or len(faces) == 0:
            return []
        sx = frame.shape[1] / 320.0
        sy = frame.shape[0] / 240.0
        return [(int(x * sx), int(y * sy), int(w * sx), int(h * sy))
                for (x, y, w, h) in faces]

    # =========================================================================
    # PRIVATE: COORDINATE CONVERSION
    # =========================================================================
    @staticmethod
    def _dlib_to_opencv(locations, scale):
        """
        dlib / face_recognition returns (top, right, bottom, left).
        OpenCV uses (x, y, w, h).  Also applies the inverse of the resize scale.
        """
        result = []
        for (top, right, bottom, left) in locations:
            x = left  * scale
            y = top   * scale
            w = (right  - left)   * scale
            h = (bottom - top)    * scale
            result.append((x, y, w, h))
        return result

    # =========================================================================
    # PUBLIC: DRAW (debug / overlay use)
    # =========================================================================
    def draw_detections(self, frame, faces):
        """Draw BLUE bounding boxes around detected faces (debug overlay)."""
        if frame is None:
            return frame
        out = frame.copy()
        for (x, y, w, h) in faces:
            cv2.rectangle(out, (x, y), (x + w, y + h), (255, 100, 0), 2)
        return out