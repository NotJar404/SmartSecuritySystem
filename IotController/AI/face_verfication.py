import cv2
import numpy as np
import pickle
import os
from datetime import datetime
from pathlib import Path

class FaceVerifier:
    """Improved ORB-based face verifier (stable version for project use)"""

    def __init__(self, storage_dir="face_data"):
        self.storage_dir = storage_dir

        # Improved ORB settings
        self.orb = cv2.ORB_create(
            nfeatures=1000,
            scaleFactor=1.2,
            nlevels=8
        )

        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        self.current_des = None
        self.current_time = None

        Path(self.storage_dir).mkdir(parents=True, exist_ok=True)

    # =========================
    # FEATURE EXTRACTION
    # =========================
    def extract(self, image):
        if image is None:
            return None

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        kp, des = self.orb.detectAndCompute(gray, None)
        return des

    # =========================
    # STORE LIVE FACE
    # =========================
    def store_detected_face(self, face_image):
        des = self.extract(face_image)

        if des is None:
            return False

        self.current_des = des
        self.current_time = datetime.now()

        print("Face stored at", self.current_time)
        return True

    # =========================
    # LOAD FACE
    # =========================
    def load_user_face(self, user_id):
        path = os.path.join(self.storage_dir, f"{user_id}.pkl")

        if not os.path.exists(path):
            return None

        with open(path, "rb") as f:
            return pickle.load(f)

    # =========================
    # REGISTER FACE
    # =========================
    def register_user_face(self, user_id, face_image):
        des = self.extract(face_image)

        if des is None:
            print("No features found")
            return False

        path = os.path.join(self.storage_dir, f"{user_id}.pkl")

        with open(path, "wb") as f:
            pickle.dump(des, f)

        print(f"Registered face: {user_id}")
        return True

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

        if self.current_des is None:
            result["message"] = "No face detected"
            return result

        # timeout check
        if (datetime.now() - self.current_time).seconds > 30:
            self.current_des = None
            result["message"] = "Face expired"
            return result

        stored = self.load_user_face(user_id)

        if stored is None:
            result["message"] = "No registered face"
            return result

        matches = self.bf.match(self.current_des, stored)

        if not matches:
            result["message"] = "No match found"
            return result

        # sort best matches
        matches = sorted(matches, key=lambda x: x.distance)

        # FILTER GOOD MATCHES
        good = [m for m in matches if m.distance < 60]

        confidence = len(good) / max(len(matches), 1) * 100

        if len(good) >= 30:   # threshold
            result["verified"] = True
            result["message"] = "ACCESS GRANTED"
        else:
            result["message"] = "FACE MISMATCH"

        result["confidence"] = round(confidence, 2)

        self.current_des = None
        return result

    # =========================
    # STATUS
    # =========================
    def get_detection_status(self):
        return {
            "detected": self.current_des is not None,
            "time": str(self.current_time)
        }