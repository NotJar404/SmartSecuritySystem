import cv2
import numpy as np
try:
    import face_recognition
    _HAS_FACE_RECOGNITION = True
except ImportError:
    _HAS_FACE_RECOGNITION = False
    print("[WARN] face_recognition not installed — face verification disabled (install dlib + face_recognition for Pi)")
import base64
import pickle
import os
from datetime import datetime
from pathlib import Path


class FaceVerifier:
    """AI-based Face Recognition using embeddings (Raspberry Pi compatible)"""

    def __init__(self, storage_dir="face_data"):
        self.storage_dir = storage_dir
        Path(self.storage_dir).mkdir(parents=True, exist_ok=True)

        self.current_encoding = None
        self.current_time = None

        # tolerance (lower = stricter)
        self.tolerance = 0.5

    # =========================
    # ENCODING
    # =========================
    def extract_encoding(self, image):
        if image is None or not _HAS_FACE_RECOGNITION:
            return None

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        encodings = face_recognition.face_encodings(rgb)

        if len(encodings) == 0:
            return None

        return encodings[0]

    # =========================
    # STORE LIVE FACE
    # =========================
    def store_detected_face(self, face_image):
        encoding = self.extract_encoding(face_image)

        if encoding is None:
            return False

        self.current_encoding = encoding
        self.current_time = datetime.now()

        return True

    # =========================
    # REGISTER USER
    # =========================
    def register_user_face(self, user_id, face_image):
        encoding = self.extract_encoding(face_image)

        if encoding is None:
            print("No face detected for registration")
            return False

        path = os.path.join(self.storage_dir, f"{user_id}.pkl")

        with open(path, "wb") as f:
            pickle.dump(encoding, f)

        print(f"[REGISTERED] {user_id}")
        return True

    # =========================
    # LOAD USER FACE
    # =========================
    def load_user_face(self, user_id):
        path = os.path.join(self.storage_dir, f"{user_id}.pkl")

        if not os.path.exists(path):
            return None

        with open(path, "rb") as f:
            return pickle.load(f)

    # =========================
    # VERIFY RFID + FACE
    # =========================
    def verify_rfid_with_face(self, user_id):
        result = {
            "verified": False,
            "confidence": 0,
            "message": "",
            "user_id": user_id
        }

        if self.current_encoding is None:
            result["message"] = "No face detected"
            return result

        # timeout check (FIXED: was .seconds which only returns partial seconds)
        if (datetime.now() - self.current_time).total_seconds() > 30:
            self.current_encoding = None
            result["message"] = "Face expired"
            return result

        stored_encoding = self.load_user_face(user_id)

        if stored_encoding is None:
            result["message"] = "No registered face"
            return result

        # AI comparison
        if not _HAS_FACE_RECOGNITION:
            result["message"] = "face_recognition not installed"
            return result

        distance = face_recognition.face_distance(
            [stored_encoding],
            self.current_encoding
        )[0]

        confidence = (1 - distance) * 100

        if distance < self.tolerance:
            result["verified"] = True
            result["message"] = "ACCESS GRANTED"
            self.current_encoding = None  # Clear after SUCCESSFUL use
        else:
            result["message"] = "FACE MISMATCH"
            self.current_encoding = None  # Clear on confirmed mismatch

        result["confidence"] = round(confidence, 2)

        return result

    # =========================
    # STATUS
    # =========================
    def get_detection_status(self):
        return {
            "detected": self.current_encoding is not None,
            "time": str(self.current_time)
        }