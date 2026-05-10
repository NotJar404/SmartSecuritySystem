import cv2
import numpy as np

class FaceDetector:
    """
    Lightweight face detector optimized for:
    - Laptop webcam testing
    - Raspberry Pi camera module
    - Real-time occupancy detection
    """

    def __init__(self):

        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        # =========================
        # TUNING PARAMETERS
        # =========================
        self.min_face_size = (30, 30)
        self.scale_factor = 1.1
        self.min_neighbors = 5  # balanced: fewer false positives, still detects reliably

        # OPTIONAL PERFORMANCE MODE (Pi friendly)
        self.use_resize = True
        self.resize_width = 320
        self.resize_height = 240

        # =========================
        # BLUR REJECTION (AUTOFOCUS STABILITY)
        # Frames below this Laplacian variance are too blurry
        # for reliable face detection — skip entirely
        # =========================
        self.blur_threshold = 8.0
        self.last_blur_score = 0

    # =========================
    # FACE DETECTION CORE
    # =========================
    def detect_faces(self, frame):
        """
        Detect faces and return bounding boxes + cropped faces.
        Rejects blurry frames to prevent autofocus-induced false detections.
        """

        if frame is None:
            return [], []

        try:
            original_frame = frame

            # =========================
            # BLUR CHECK (MUST COME FIRST)
            # Reject frames during autofocus cycling
            # =========================
            gray_check = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self.last_blur_score = cv2.Laplacian(gray_check, cv2.CV_64F).var()

            if self.last_blur_score < self.blur_threshold:
                # Frame is too blurry — do not attempt detection
                return [], []

            # =========================
            # PERFORMANCE OPTIMIZATION
            # =========================
            if self.use_resize:
                frame = cv2.resize(frame, (self.resize_width, self.resize_height))

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # =========================
            # IMPROVE LIGHTING ROBUSTNESS
            # =========================
            gray = cv2.equalizeHist(gray)

            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=self.scale_factor,
                minNeighbors=self.min_neighbors,
                minSize=self.min_face_size
            )

            face_images = []
            scaled_faces = []

            # =========================
            # PROCESS DETECTED FACES
            # =========================
            for (x, y, w, h) in faces:

                if w <= 0 or h <= 0:
                    continue

                # SCALE BACK IF RESIZED
                if self.use_resize:
                    scale_x = original_frame.shape[1] / self.resize_width
                    scale_y = original_frame.shape[0] / self.resize_height

                    x = int(x * scale_x)
                    y = int(y * scale_y)
                    w = int(w * scale_x)
                    h = int(h * scale_y)

                # Clamp to frame bounds
                x = max(0, x)
                y = max(0, y)
                w = min(w, original_frame.shape[1] - x)
                h = min(h, original_frame.shape[0] - y)

                face = original_frame[y:y+h, x:x+w]

                if face.size == 0:
                    continue

                scaled_faces.append((x, y, w, h))
                face_images.append(face)

            return scaled_faces, face_images

        except Exception as e:
            print("[FACE DETECTION ERROR]", e)
            return [], []

    # =========================
    # DRAW OVERLAY (DEBUG / UI)
    # =========================
    def draw_detections(self, frame, faces):

        if frame is None:
            return None

        output = frame.copy()

        for (x, y, w, h) in faces:
            cv2.rectangle(output, (x, y), (x+w, y+h), (0, 255, 0), 2)

            cv2.putText(
                output,
                "FACE",
                (x, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )

        return output