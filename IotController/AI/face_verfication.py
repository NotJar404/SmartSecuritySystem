"""
Face Verification Module for Smart Security System

VERIFICATION FLOW:
1. Camera continuously detects faces → store_detected_face() saves the live encoding
2. RFID tap → main.py gets faceEmbedding from ASP.NET API (database)
3. verify_rfid_with_face() compares live encoding vs database embedding
4. Result: GRANTED (match) or MISMATCH (no match)

ENROLLMENT:
- Face enrollment happens via the ASP.NET Personnel dashboard
- The enrolled face encoding is stored as base64-encoded numpy array in
  the face_embedding column of the authorized_personnel table
- register_user_face() can be called to generate the encoding from an image

COMPATIBILITY:
- Uses face_recognition library (dlib-based) for 128-dim face encodings
- Falls back gracefully if face_recognition is not installed
- Works on both Raspberry Pi 5 (ARM64) and laptop (x86_64)
"""

import cv2
import numpy as np

try:
    import face_recognition
    _HAS_FACE_RECOGNITION = True
except ImportError:
    _HAS_FACE_RECOGNITION = False
    print("[WARN] face_recognition not installed — face verification disabled (install dlib + face_recognition for Pi)")

import base64
import json
import os
from datetime import datetime
from pathlib import Path


class FaceVerifier:
    """AI-based Face Recognition using 128-dim face encodings.

    Compares live camera face against enrolled face embedding from the database.
    The database embedding is fetched by main.py via the ASP.NET RFID lookup API
    and passed to verify_rfid_with_face().
    """

    def __init__(self, storage_dir="face_data"):
        self.storage_dir = storage_dir
        Path(self.storage_dir).mkdir(parents=True, exist_ok=True)

        # Current live face encoding (from camera)
        self.current_encoding = None
        self.current_time = None

        # Tolerance: Euclidean distance threshold for face match.
        # 0.6 = face_recognition library's own recommended default for real-world use.
        # 0.5 = strict (good for identical twins / high-security), but causes
        #       false rejections with different lighting or photo quality.
        # 0.65 = lenient (good for poor lighting or web-uploaded photos).
        self.tolerance = 0.6

    # =========================
    # ENCODING EXTRACTION
    # =========================
    def extract_encoding(self, image, num_jitters=1):
        """Extract 128-dim face encoding from an image.

        Args:
            image: BGR frame (OpenCV format)
            num_jitters: How many times to re-sample face when encoding.
                         1  = fast (for live camera frames)
                         5  = more accurate (for enrollment photos)
                         Higher values give better encodings but take longer.

        Returns:
            numpy array (128-dim) or None if no face found.
        """
        if image is None or not _HAS_FACE_RECOGNITION:
            return None

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb, num_jitters=num_jitters)

        if len(encodings) == 0:
            return None

        return encodings[0]

    # =========================
    # STORE LIVE FACE (from camera)
    # =========================
    def store_detected_face(self, face_image):
        """Store the current live face encoding from the camera.
        Called continuously by main_loop when faces are detected.
        This is what gets compared against the database embedding on RFID tap."""
        encoding = self.extract_encoding(face_image)

        if encoding is None:
            return False

        self.current_encoding = encoding
        self.current_time = datetime.now()

        return True

    # =========================
    # DECODE DATABASE EMBEDDING
    # =========================
    def _decode_embedding(self, embedding_str):
        """Decode a face embedding string from the database.

        Supports three formats:
        1. base64 numpy bytes (128-dim float64)  -- produced by encode_for_database()
        2. JSON float array [0.1, 0.2, ...]       -- legacy import format
        3. base64 JPEG/PNG image                  -- uploaded from web Personnel form
           The ASP.NET form stores raw photo bytes; we decode the image and
           extract a 128-dim encoding on-the-fly so face verification works
           immediately after upload without a separate Pi-side enrollment step.

        Returns:
            numpy array (128-dim) or None
        """
        if not embedding_str or embedding_str == "PENDING_ENROLLMENT":
            return None

        # ── Path 1: base64 numpy bytes (preferred production format) ──────────
        try:
            raw = base64.b64decode(embedding_str)
            arr = np.frombuffer(raw, dtype=np.float64)
            if len(arr) == 128:
                return arr
        except Exception:
            pass

        # ── Path 2: JSON float array ──────────────────────────────────────────
        try:
            arr = np.array(json.loads(embedding_str), dtype=np.float64)
            if len(arr) == 128:
                return arr
        except Exception:
            pass

        # ── Path 3: base64 JPEG/PNG image (web Personnel photo upload) ─────────
        # extract_encoding() handles BGR→RGB conversion internally.
        # Use num_jitters=5 for enrollment photos: slower but gives a much more
        # accurate reference encoding that better tolerates real-world variation.
        if _HAS_FACE_RECOGNITION:
            try:
                raw = base64.b64decode(embedding_str)
                nparr = np.frombuffer(raw, dtype=np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)  # returns BGR
                if img is not None and img.size > 0:
                    encoding = self.extract_encoding(img, num_jitters=5)
                    if encoding is not None:
                        print("[FACE VERIFY] Extracted encoding from stored photo image")
                        return encoding
                    else:
                        print("[FACE VERIFY] Photo decoded but no face found in enrollment image")
            except Exception as e:
                print(f"[FACE VERIFY] Photo decode attempt failed: {e}")

        print(f"[FACE VERIFY] Cannot decode embedding "
              f"(len={len(embedding_str)}, starts='{embedding_str[:20]}...')")
        return None

    # =========================
    # ENCODE FOR DATABASE STORAGE
    # =========================
    @staticmethod
    def encode_for_database(encoding):
        """Encode a numpy face encoding to base64 string for database storage.
        Use this when enrolling faces via the ASP.NET API."""
        if encoding is None:
            return None
        return base64.b64encode(encoding.astype(np.float64).tobytes()).decode('utf-8')

    # =========================
    # REGISTER USER FACE (for enrollment)
    # =========================
    def register_user_face(self, user_id, face_image):
        """Extract encoding from face image and return as base64 string.

        The caller (main.py or enrollment script) should POST this to ASP.NET
        to update the face_embedding column in the database.

        Also saves a local backup .pkl for offline fallback.

        Returns:
            dict: {success, encoding_b64, message}
        """
        encoding = self.extract_encoding(face_image)

        if encoding is None:
            return {"success": False, "encoding_b64": None, "message": "No face detected"}

        # Base64 for database storage
        encoding_b64 = self.encode_for_database(encoding)

        # Local backup (offline fallback)
        try:
            import pickle
            path = os.path.join(self.storage_dir, f"{user_id}.pkl")
            with open(path, "wb") as f:
                pickle.dump(encoding, f)
        except Exception:
            pass

        print(f"[FACE REGISTER] Encoding generated for user {user_id}")
        return {"success": True, "encoding_b64": encoding_b64, "message": "Face enrolled"}

    # =========================
    # VERIFY RFID + FACE (CORE VERIFICATION)
    # =========================
    def verify_rfid_with_face(self, user_id, db_embedding_str=None):
        """Compare live camera face against enrolled face.

        Args:
            user_id: Person ID or RFID UID (for logging)
            db_embedding_str: Face embedding string from the database
                              (fetched via ASP.NET RFID lookup API).
                              If None, falls back to local .pkl file.

        Returns:
            dict: {verified, confidence, message, user_id}
        """
        result = {
            "verified": False,
            "confidence": 0,
            "message": "",
            "user_id": user_id
        }

        # Check 1: Do we have a live face from the camera?
        if self.current_encoding is None:
            result["message"] = "No face detected"
            return result

        # Check 2: Has the live face expired? (30s window)
        if (datetime.now() - self.current_time).total_seconds() > 30:
            self.current_encoding = None
            result["message"] = "Face expired"
            return result

        # Check 3: Get the stored/enrolled face encoding
        stored_encoding = None

        # PRIMARY: Use database embedding (from ASP.NET API response)
        if db_embedding_str:
            stored_encoding = self._decode_embedding(db_embedding_str)
            if stored_encoding is not None:
                print(f"[FACE VERIFY] Using database embedding for user {user_id}")

        # FALLBACK: Local .pkl file (offline mode)
        if stored_encoding is None:
            try:
                import pickle
                path = os.path.join(self.storage_dir, f"{user_id}.pkl")
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        stored_encoding = pickle.load(f)
                    print(f"[FACE VERIFY] Using local fallback for user {user_id}")
            except Exception:
                pass

        if stored_encoding is None:
            result["message"] = "No registered face"
            return result

        # Check 4: face_recognition library available?
        if not _HAS_FACE_RECOGNITION:
            result["message"] = "face_recognition not installed"
            return result

        # =========================
        # AI COMPARISON
        # =========================
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