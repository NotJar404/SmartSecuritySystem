import cv2
import numpy as np
import os


class PersonDetection:
    """Single detected person with bounding box and confidence."""
    __slots__ = ['x', 'y', 'w', 'h', 'confidence']

    def __init__(self, x, y, w, h, confidence):
        self.x = int(x)
        self.y = int(y)
        self.w = int(w)
        self.h = int(h)
        self.confidence = float(confidence)

    @property
    def bbox(self):
        return (self.x, self.y, self.w, self.h)

    @property
    def centroid(self):
        return (self.x + self.w // 2, self.y + self.h // 2)


class PersonDetector:
    """
    Lightweight person detector for indoor room monitoring.
    Uses MobileNet SSD v2 via OpenCV DNN (no GPU required).

    Only detects class 15 (person) from the 21-class COCO output.
    Optimized for Raspberry Pi 5: ~8-12 FPS at 300x300 input.

    Fallback: If model files not found, falls back to HOG+SVM
    (slower but requires no external model files).
    """

    # MobileNet SSD class 15 = person
    PERSON_CLASS_ID = 15

    def __init__(self, confidence_threshold=0.5, model_dir="models"):
        self.confidence_threshold = confidence_threshold
        self.model_dir = model_dir
        self.net = None
        self.use_hog_fallback = False

        # HOG always pre-initialized as emergency fallback.
        # This prevents NoneType errors when MobileNet SSD loads OK but
        # fails at inference time (OpenCV 4.13 BatchNorm assertion bug).
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        self._load_model()

    def _load_model(self):
        """Load MobileNet SSD model with HOG+SVM fallback."""
        prototxt = os.path.join(self.model_dir, "MobileNetSSD_deploy.prototxt")
        caffemodel = os.path.join(self.model_dir, "MobileNetSSD_deploy.caffemodel")

        if os.path.exists(prototxt) and os.path.exists(caffemodel):
            try:
                self.net = cv2.dnn.readNetFromCaffe(prototxt, caffemodel)

                # Prefer default backend for best ARM64 compatibility
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_DEFAULT)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

                print("[PERSON DETECTOR] ✓ MobileNet SSD loaded")
                return
            except Exception as e:
                print(f"[PERSON DETECTOR] MobileNet SSD load failed: {e}")

        # Fallback to HOG+SVM (self._hog already initialized in __init__ — no re-creation)
        print("[PERSON DETECTOR] Model files not found — using HOG+SVM fallback")
        print(f"[PERSON DETECTOR] Expected: {prototxt}")
        self.use_hog_fallback = True

    def detect_persons(self, frame):
        """
        Detect persons in frame.

        Returns:
            list[PersonDetection]: Detected persons with bounding boxes.
        """
        if frame is None:
            return []

        if self.use_hog_fallback:
            return self._detect_hog(frame)
        else:
            return self._detect_mobilenet(frame)

    def _detect_mobilenet(self, frame):
        """MobileNet SSD person detection (primary method)."""
        try:
            # Validate frame dimensions
            if frame is None or len(frame.shape) != 3:
                return []
            
            h, w = frame.shape[:2]
            if h < 50 or w < 50:
                return []  # Frame too small

            # Create blob — 300x300 is MobileNet SSD's native input size
            try:
                resized = cv2.resize(frame, (300, 300))
                if resized is None or resized.size == 0:
                    return []
                    
                blob = cv2.dnn.blobFromImage(
                    resized,
                    0.007843,       # scale factor (1/127.5)
                    (300, 300),     # spatial size
                    127.5,          # mean subtraction
                    swapRB=False,   # Keep BGR as-is (camera native)
                    crop=False      # Don't crop to square
                )
                
                if blob is None or blob.size == 0:
                    print("[PERSON DETECTOR] Blob creation failed — switching to HOG fallback")
                    self.use_hog_fallback = True
                    return self._detect_hog(frame)
                    
            except Exception as blob_err:
                print(f"[PERSON DETECTOR] Blob creation error: {blob_err} — switching to HOG")
                self.use_hog_fallback = True
                return self._detect_hog(frame)

            self.net.setInput(blob)
            detections = self.net.forward()

            persons = []

            for i in range(detections.shape[2]):
                class_id = int(detections[0, 0, i, 1])
                confidence = float(detections[0, 0, i, 2])

                # Only keep person detections above threshold
                if class_id != self.PERSON_CLASS_ID:
                    continue
                if confidence < self.confidence_threshold:
                    continue

                # Scale bounding box back to original frame size
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                x1, y1, x2, y2 = box.astype(int)

                # Clamp to frame bounds
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w, x2)
                y2 = min(h, y2)

                bw = x2 - x1
                bh = y2 - y1

                # Skip tiny detections (noise)
                if bw < 30 or bh < 30:
                    continue

                persons.append(PersonDetection(x1, y1, bw, bh, confidence))

            return persons

        except (cv2.error, RuntimeError) as e:
            # OpenCV batch norm or other DNN errors — switch to HOG
            error_str = str(e).lower()
            if "batch_norm" in error_str or "assertion failed" in error_str or "blobs.size()" in error_str:
                print(f"[PERSON DETECTOR] *** DNN LAYER FAILURE DETECTED ***")
                print(f"[PERSON DETECTOR] *** FALLING BACK TO HOG+SVM FALLBACK ***")
                self.use_hog_fallback = True
                try:
                    return self._detect_hog(frame)
                except Exception as hog_err:
                    print(f"[PERSON DETECTOR] HOG fallback also failed: {hog_err}")
                    return []
            else:
                print(f"[PERSON DETECTOR ERROR] {e}")
                return []
        except Exception as e:
            print(f"[PERSON DETECTOR ERROR] Unexpected error: {e}")
            return []

    def _detect_hog(self, frame):
        """HOG+SVM fallback (slower, no model files needed)."""
        try:
            # Resize for performance
            small = cv2.resize(frame, (640, 480))
            scale_x = frame.shape[1] / 640
            scale_y = frame.shape[0] / 480

            boxes, weights = self._hog.detectMultiScale(
                small,
                winStride=(8, 8),
                padding=(4, 4),
                scale=1.05
            )

            persons = []
            for (x, y, w, h), weight in zip(boxes, weights):
                if weight < self.confidence_threshold:
                    continue

                # Scale back to original frame size
                ox = int(x * scale_x)
                oy = int(y * scale_y)
                ow = int(w * scale_x)
                oh = int(h * scale_y)

                persons.append(PersonDetection(ox, oy, ow, oh, float(weight)))

            # Apply NMS to remove overlapping detections
            if len(persons) > 1:
                persons = self._nms(persons, overlap_thresh=0.4)

            return persons

        except Exception as e:
            print(f"[HOG DETECTOR ERROR] {e}")
            return []

    def _nms(self, detections, overlap_thresh=0.4):
        """Non-maximum suppression to remove duplicate detections."""
        if len(detections) == 0:
            return []

        boxes = np.array([[d.x, d.y, d.x + d.w, d.y + d.h] for d in detections])
        scores = np.array([d.confidence for d in detections])

        indices = cv2.dnn.NMSBoxes(
            [[d.x, d.y, d.w, d.h] for d in detections],
            scores.tolist(),
            self.confidence_threshold,
            overlap_thresh
        )

        if len(indices) == 0:
            return []

        # OpenCV 4.x returns nested array
        if isinstance(indices[0], (list, np.ndarray)):
            indices = [i[0] for i in indices]

        return [detections[i] for i in indices]

    def get_status(self):
        """Return detector status for debugging."""
        return {
            "model": "MobileNet SSD v2" if not self.use_hog_fallback else "HOG+SVM (fallback)",
            "confidence_threshold": self.confidence_threshold,
            "ready": self.net is not None or self._hog is not None
        }