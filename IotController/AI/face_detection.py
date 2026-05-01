import cv2
import numpy as np

class FaceDetector:
    """Lightweight face detector optimized for Raspberry Pi + live stream"""

    def __init__(self):
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        # Tuned for better stability
        self.min_face_size = (40, 40)
        self.scale_factor = 1.1
        self.min_neighbors = 6

    # =========================
    # FACE DETECTION CORE
    # =========================
    def detect_faces(self, frame):
        """
        Detect faces and extract ROI

        Returns:
            faces: list of bounding boxes
            face_images: cropped face regions
        """

        if frame is None:
            return [], []

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=self.scale_factor,
                minNeighbors=self.min_neighbors,
                minSize=self.min_face_size
            )

            face_images = []

            for (x, y, w, h) in faces:
                # Safety crop check
                if w <= 0 or h <= 0:
                    continue

                face = frame[y:y+h, x:x+w]

                # skip too small or corrupted ROI
                if face.size == 0:
                    continue

                face_images.append(face)

            return list(faces), face_images

        except Exception as e:
            print("Face detection error:", e)
            return [], []

    # =========================
    # DRAW OVERLAY (UI DEBUG)
    # =========================
    def draw_detections(self, frame, faces):
        """Draw bounding boxes for visualization"""

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