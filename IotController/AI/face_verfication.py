"""
Face Verification Module — Smart Security System (v3, Euclidean Distance)

ROOT CAUSE OF PREVIOUS BUG (cosine similarity always-high):
  dlib ResNet-34 embeddings are NOT perfect unit vectors (norm ≈ 0.9–1.4).
  Doing dot(stored_unnormalized, live_normalized) ≠ cosine similarity — it
  equals ||stored|| × cos(θ).  With ||stored|| ≈ 1.3 and cos(θ) ≈ 0.72 for
  any two faces, the result was ≈ 0.93 (93%) for EVERYONE.

FIX:
  Use face_recognition.face_distance() — the Euclidean metric that dlib is
  actually calibrated for.  Threshold on distance directly.

  distance < 0.45  → GRANTED   (same person, different conditions)
  distance ≥ 0.45  → DENIED    (different person)
  distance < 0.6   → face_recognition default tolerance (too lenient for security)

THREAD SAFETY:
  _DLIB_LOCK (exported) is a module-level mutex shared with face_detection.py.
  Every face_recognition call acquires this lock — dlib is NOT thread-safe.
"""

import cv2
import numpy as np
import threading
import time
import base64
import json
import os
from datetime import datetime
from pathlib import Path

try:
    import face_recognition
    _HAS_FACE_RECOGNITION = True
except ImportError:
    _HAS_FACE_RECOGNITION = False
    print("[WARN] face_recognition not installed — verification disabled.")

# =============================================================================
# GLOBAL DLIB MUTEX — imported by face_detection.py too (one shared lock)
# =============================================================================
_DLIB_LOCK = threading.Lock()


# =============================================================================
# EMBEDDING LOADER  (standalone — called before spawning the worker thread)
# =============================================================================
def load_embedding_from_db(raw_value):
    """
    Auto-detect format and return a validated (128,) float64 numpy array.
    Tries: JSON list → base64 numpy bytes → base64 JPEG extract → raw bytes.

    Returns None if loading or validation fails (logs reason).
    """
    if raw_value is None:
        print("[VERIFY] load_embedding_from_db: value is None")
        return None

    # Strip data-URI prefix if present  (e.g. "data:image/jpeg;base64,...")
    raw_str = raw_value if isinstance(raw_value, str) else raw_value.decode("utf-8", errors="replace")
    is_jpeg_data_uri = raw_str.startswith("data:image")

    # ── Path 1: JSON list ────────────────────────────────────────────────────
    if not is_jpeg_data_uri:
        try:
            parsed = json.loads(raw_str)
            if isinstance(parsed, list) and len(parsed) == 128:
                enc = np.array(parsed, dtype=np.float64)
                return _validate_embedding(enc, source="JSON")
        except Exception:
            pass

    # ── Path 2: base64-encoded numpy bytes ───────────────────────────────────
    if not is_jpeg_data_uri:
        try:
            b = base64.b64decode(raw_str)
            enc = np.frombuffer(b, dtype=np.float64)
            if enc.shape == (128,):
                return _validate_embedding(enc, source="base64-numpy")
            # Try float32 → upcast
            enc32 = np.frombuffer(b, dtype=np.float32)
            if enc32.shape == (128,):
                return _validate_embedding(enc32.astype(np.float64), source="base64-float32")
        except Exception:
            pass

    # ── Path 3: base64 JPEG image — extract embedding from the photo ─────────
    # SKIP if face_recognition is not available
    if _HAS_FACE_RECOGNITION:
        try:
            b64_part = raw_str.split(",", 1)[1] if "," in raw_str else raw_str
            img_bytes = base64.b64decode(b64_part)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                with _DLIB_LOCK:
                    locs = face_recognition.face_locations(rgb, model="hog")
                    if not locs:
                        locs = face_recognition.face_locations(rgb, model="hog",
                                                               number_of_times_to_upsample=2)
                if locs:
                    loc = max(locs, key=lambda l: (l[2]-l[0])*(l[1]-l[3]))
                    with _DLIB_LOCK:
                        encs = face_recognition.face_encodings(rgb, [loc], num_jitters=5)
                    if encs:
                        return _validate_embedding(np.array(encs[0], dtype=np.float64),
                                                   source="JPEG-photo")
                else:
                    print("[VERIFY] Path 3: no face found in stored JPEG photo")
        except Exception as e:
            print(f"[VERIFY] Path 3 failed: {e}")
    else:
        print("[VERIFY] Path 3 skipped: face_recognition not installed")

    print("[VERIFY] load_embedding_from_db: all decode paths failed")
    return None


def _validate_embedding(enc, source="?"):
    """Return enc if it passes sanity checks, else None."""
    if enc is None or enc.shape != (128,):
        print(f"[VERIFY] Validation FAIL ({source}): shape={getattr(enc,'shape','?')}, expected (128,)")
        return None
    if np.any(np.isnan(enc)) or np.any(np.isinf(enc)):
        print(f"[VERIFY] Validation FAIL ({source}): contains NaN/Inf")
        return None
    if np.allclose(enc, 0) or np.std(enc) < 1e-6:
        print(f"[VERIFY] Validation FAIL ({source}): all-zero or flat — bad serialization")
        return None
    if np.max(np.abs(enc)) > 10.0:
        print(f"[VERIFY] Validation FAIL ({source}): values out of range (max={np.max(np.abs(enc)):.2f})")
        return None
    print(f"[VERIFY] Embedding loaded OK ({source}) — "
          f"shape={enc.shape}  first5={[round(float(v),4) for v in enc[:5]]}")
    return enc.astype(np.float64)


# =============================================================================
# FACE VERIFIER
# =============================================================================
class FaceVerifier:
    """
    Euclidean-distance face verification using dlib ResNet-34 via face_recognition.
    Spawns a background thread; never blocks the MJPEG stream.
    """

    # ── Tunable constants ─────────────────────────────────────────────────────
    # Euclidean distance threshold.  LOWER = stricter.
    #
    #   NON-FIXED / HANDHELD CAMERA (this setup):
    #     0.52 ← USE THIS  (handheld Camera Module 3, user holds it themselves;
    #                       angle variation pushes same-person distances to 0.40-0.52)
    #
    #   FIXED WALL-MOUNTED CAMERA:
    #     0.45  (stricter — camera angle is consistent every time)
    #     0.40  (very strict — tightly controlled environment)
    #
    #   face_recognition default = 0.60  (too lenient for a security door)
    DISTANCE_THRESHOLD = 0.52

    # SECURITY GATE: minimum number of frames that must individually pass
    # the threshold before GRANTED is issued.
    # 1 = best-single-frame (lenient — one lucky angle grants anyone)
    # 2 = recommended for non-fixed camera  ← DEFAULT
    #     → enrolled person needs 2 good angles (easy over 15 s)
    #     → stranger needs 2 sub-threshold frames (very unlikely at 0.50)
    # 3 = use for fixed camera at 0.45 threshold
    MIN_PASSING_FRAMES = 2

    MAX_FRAMES       = 7     # more attempts for a moving camera
    WINDOW_SECONDS   = 15.0  # 15 s window (was 10 s) — camera movement needs time
    FRAME_INTERVAL   = 0.25  # seconds between captures (~4 fps)
    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, storage_dir="face_data"):
        self.storage_dir = storage_dir
        Path(self.storage_dir).mkdir(parents=True, exist_ok=True)

        # Legacy buffer — kept so face-guide overlay still works in IDLE state
        self.current_encoding = None
        self.current_time     = datetime.now()

        # Expose for overlay / config display compatibility
        self.similarity_threshold = 1.0 - self.DISTANCE_THRESHOLD
        self.tolerance            = self.DISTANCE_THRESHOLD

        # Worker thread state
        self._collecting     = False
        self._collect_thread = None
        self._collect_lock   = threading.Lock()

    # ── Public property ───────────────────────────────────────────────────────
    @property
    def is_collecting(self):
        return self._collecting

    # =========================================================================
    # ENCODING EXTRACTION  (used by enrollment + face buffer)
    # =========================================================================
    def extract_encoding(self, image, num_jitters=1):
        """
        Extract 128-dim face encoding from a BGR frame.
        Returns (encoding_float64, bbox_xywh) or (None, None).
        """
        if image is None:
            return None, None
        if not _HAS_FACE_RECOGNITION:
            print("[ERROR] face_recognition not installed — cannot extract encodings. "
                  "Install: pip install face-recognition dlib")
            return None, None
        try:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            # Same 3-scale priority as face_detection.py and the verifier loop.
            # Pass 1: 50% / upsample=2  — arm's-length, camera held below face
            small50 = cv2.resize(rgb, (0, 0), fx=0.50, fy=0.50)
            with _DLIB_LOCK:
                locs = face_recognition.face_locations(
                    small50, model="hog", number_of_times_to_upsample=2)
            if locs:
                locs = [(t*2, r*2, b*2, l*2) for t, r, b, l in locs]
            else:
                # Pass 2: 25% / upsample=2  — very close / large face
                small25 = cv2.resize(rgb, (0, 0), fx=0.25, fy=0.25)
                with _DLIB_LOCK:
                    locs = face_recognition.face_locations(
                        small25, model="hog", number_of_times_to_upsample=2)
                if locs:
                    locs = [(t*4, r*4, b*4, l*4) for t, r, b, l in locs]
                else:
                    # Pass 3: 75% / upsample=1  — distant / partially-framed face
                    small75 = cv2.resize(rgb, (0, 0), fx=0.75, fy=0.75)
                    with _DLIB_LOCK:
                        locs = face_recognition.face_locations(
                            small75, model="hog", number_of_times_to_upsample=1)
                    if locs:
                        locs = [(int(t*4/3), int(r*4/3),
                                 int(b*4/3), int(l*4/3)) for t, r, b, l in locs]

            if not locs:
                return None, None

            # Use largest face
            loc = max(locs, key=lambda l: (l[2]-l[0]) * (l[1]-l[3]))
            with _DLIB_LOCK:
                encs = face_recognition.face_encodings(
                    rgb, [loc], num_jitters=num_jitters, model="large")
            if not encs:
                return None, None

            enc  = np.array(encs[0], dtype=np.float64)
            top, right, bottom, left = loc
            bbox = (left, top, right - left, bottom - top)
            return enc, bbox

        except Exception as e:
            print(f"[FACE DETECTOR ERROR] extract_encoding: {e}")
            return None, None

    # =========================================================================
    # ENROLLMENT HELPERS
    # =========================================================================
    def encode_for_database(self, encoding):
        """Serialize a (128,) float64 array to a base64 string for DB storage."""
        arr = np.array(encoding, dtype=np.float64)
        return base64.b64encode(arr.tobytes()).decode("utf-8")

    def store_detected_face(self, face_image):
        """Update legacy single-frame buffer (used by face-guide overlay)."""
        if face_image is None:
            return
        enc, _ = self.extract_encoding(face_image, num_jitters=1)
        if enc is not None:
            self.current_encoding = enc
            self.current_time     = datetime.now()
            print("[VERIFY] Face stored in buffer (encoding ready for RFID verification)")
        else:
            print("[VERIFY] Failed to extract encoding from detected face — buffer empty")

    # =========================================================================
    # MULTI-FRAME VERIFICATION ENTRY POINT
    # =========================================================================
    def start_multiframe_window(self, user_id, stored_embedding_str,
                                camera_get_frame_fn, overlay_setter_fn,
                                result_callback_fn,
                                guidance_fn=None):
        """
        Spawn a background thread that collects up to MAX_FRAMES face frames
        and decides GRANTED / DENIED using Euclidean distance.

        guidance_fn (optional): zero-arg callable that plays an audio cue.
          Called when no face is detected for >3 seconds to prompt the user
          to reposition the camera toward their face.
          Example: lambda: self.buzzer.pattern_beep(times=2, interval=0.1)

        Non-blocking — returns immediately so MJPEG stream stays live.
        """
        with self._collect_lock:
            if self._collecting:
                print("[VERIFY] Already collecting — ignoring duplicate call")
                return
            self._collecting = True

        print(f"\n[VERIFY] ══════ Starting verification: user_id={user_id} ══════")
        print(f"[VERIFY] Goal: up to {self.MAX_FRAMES} frames within {self.WINDOW_SECONDS}s")
        print(f"[VERIFY] Distance threshold: {self.DISTANCE_THRESHOLD} "
              f"(lower = stricter, 0.6 = face_recognition default)")

        t = threading.Thread(
            target=self._run_verification,
            args=(user_id, stored_embedding_str,
                  camera_get_frame_fn, overlay_setter_fn,
                  result_callback_fn, guidance_fn),
            daemon=True,
            name=f"FaceVerify-{user_id}"
        )
        self._collect_thread = t
        t.start()

    # =========================================================================
    # WORKER THREAD
    # =========================================================================
    def _run_verification(self, user_id, stored_embedding_str,
                          camera_get_frame_fn, overlay_setter_fn,
                          result_callback_fn, guidance_fn=None):
        try:
            self._do_verify(user_id, stored_embedding_str,
                            camera_get_frame_fn, overlay_setter_fn,
                            result_callback_fn, guidance_fn)
        finally:
            with self._collect_lock:
                self._collecting = False
            self.current_encoding = None

    def _do_verify(self, user_id, stored_embedding_str,
                   camera_get_frame_fn, overlay_setter_fn,
                   result_callback_fn, guidance_fn=None):

        # ── Library guard (must be first) ────────────────────────────────────────
        # face_recognition must be installed for ANY biometric verification.
        # Without it, Path 3 (JPEG → embedding) and all frame encoding fail.
        # Return NO_LIBRARY so main.py routes to IDLE instead of ALERT.
        if not _HAS_FACE_RECOGNITION:
            print("[VERIFY] *** face_recognition library NOT installed ***")
            print("[VERIFY] Biometric verification impossible without it.")
            print("[VERIFY] Fix on Raspberry Pi:  sudo pip3 install face-recognition dlib")
            result_callback_fn(self._make_result(
                verified=False, confidence=0.0, best_distance=9.99,
                frames_checked=0, reason="NO_LIBRARY", user_id=user_id))
            return

        # ── Load stored embedding ───────────────────────────────────────────────
        stored_enc = load_embedding_from_db(stored_embedding_str)
        if stored_enc is None:
            print("[VERIFY] LOAD_ERROR — stored embedding is invalid/missing")
            result_callback_fn(self._make_result(
                verified=False, confidence=0.0, best_distance=9.99,
                frames_checked=0, reason="LOAD_ERROR", user_id=user_id))
            return

        threshold = self.DISTANCE_THRESHOLD
        print(f"[VERIFY] Stored embedding valid — beginning frame collection\n")

        # ── Frame collection loop ─────────────────────────────────────────────
        distances           = []
        frames_tried        = 0
        best_distance       = float("inf")
        passing_frames      = 0
        no_face_streak      = 0    # consecutive frames with no face detected
        last_guidance_beep  = 0.0  # last time we played the positioning beep
        GUIDANCE_BEEP_EVERY = 3.0  # seconds between repositioning audio cues
        deadline            = time.time() + self.WINDOW_SECONDS

        while time.time() < deadline and len(distances) < self.MAX_FRAMES:
            frame = camera_get_frame_fn()
            frames_tried += 1

            if frame is None:
                time.sleep(self.FRAME_INTERVAL)
                continue

            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Detect face locations — same 3-scale priority as face_detection.py
                # Pass 1: 50% scale (best for arm's-length, camera-below-face)
                small50 = cv2.resize(rgb, (0, 0), fx=0.50, fy=0.50)
                with _DLIB_LOCK:
                    locs = face_recognition.face_locations(
                        small50, model="hog", number_of_times_to_upsample=2)
                if locs:
                    locs = [(t*2, r*2, b*2, l*2) for t, r, b, l in locs]
                else:
                    # Pass 2: 25% scale (very close / large face)
                    small25 = cv2.resize(rgb, (0, 0), fx=0.25, fy=0.25)
                    with _DLIB_LOCK:
                        locs = face_recognition.face_locations(
                            small25, model="hog", number_of_times_to_upsample=2)
                    if locs:
                        locs = [(t*4, r*4, b*4, l*4) for t, r, b, l in locs]
                    else:
                        # Pass 3: 75% scale (small / distant face)
                        small75 = cv2.resize(rgb, (0, 0), fx=0.75, fy=0.75)
                        with _DLIB_LOCK:
                            locs = face_recognition.face_locations(
                                small75, model="hog", number_of_times_to_upsample=1)
                        if locs:
                            locs = [(int(t*4/3), int(r*4/3),
                                     int(b*4/3), int(l*4/3)) for t, r, b, l in locs]

                if not locs:
                    no_face_streak += 1
                    elapsed_no_face = no_face_streak * self.FRAME_INTERVAL
                    fn = len(distances) + 1
                    print(f"[VERIFY] Frame {fn}/{self.MAX_FRAMES} — no face — skip "
                          f"(no-face streak: {no_face_streak}x)")

                    # Choose guidance text based on streak length
                    if no_face_streak <= 4:
                        guidance_text = "AIM CAMERA AT YOUR FACE"
                    elif no_face_streak <= 8:
                        guidance_text = "MOVE CLOSER — ARM'S LENGTH AWAY"
                    else:
                        guidance_text = "FACE NOT FOUND — TILT CAMERA UP SLIGHTLY"

                    overlay_setter_fn({
                        'status':     f"VERIFYING... ({len(distances)}/{self.MAX_FRAMES})",
                        'guidance':   guidance_text,
                        'face_found': False,
                        'uid':        str(user_id),
                        'name':       '',
                        'confidence': 0,
                        'start_time': time.time()
                    })

                    # Play positioning audio cue every GUIDANCE_BEEP_EVERY seconds
                    now_t = time.time()
                    if guidance_fn and (now_t - last_guidance_beep) >= GUIDANCE_BEEP_EVERY:
                        try:
                            guidance_fn()
                        except Exception:
                            pass
                        last_guidance_beep = now_t

                    time.sleep(0.05)  # 50ms only — try next frame as fast as possible
                    continue

                # Face found — reset no-face streak
                no_face_streak = 0

                # Use LARGEST face (closest to camera)
                loc = max(locs, key=lambda l: (l[2]-l[0]) * (l[1]-l[3]))

                # Face size hint for positioning feedback
                t_f, r_f, b_f, l_f = loc
                face_h_px = b_f - t_f
                frame_h   = rgb.shape[0]
                face_ratio = face_h_px / frame_h
                if face_ratio < 0.10:
                    pos_hint = "MOVE CLOSER — HOLD CAMERA AT ARM'S LENGTH"
                elif face_ratio > 0.60:
                    pos_hint = "MOVE CAMERA BACK A LITTLE"
                else:
                    pos_hint = "HOLD STILL"

                with _DLIB_LOCK:
                    encs = face_recognition.face_encodings(
                        rgb, [loc], num_jitters=1, model="large")

                if not encs:
                    time.sleep(0.05)  # encoding failed — retry quickly
                    continue

                live_enc = np.array(encs[0], dtype=np.float64)

                # Euclidean distance (calibrated for dlib ResNet-34)
                dist = float(face_recognition.face_distance([stored_enc], live_enc)[0])
                distances.append(dist)
                if dist < best_distance:
                    best_distance = dist
                if dist < threshold:
                    passing_frames += 1

                status_icon = "✓ good" if dist < threshold else "✗ too far"
                fn = len(distances)
                print(f"[VERIFY] Frame {fn}/{self.MAX_FRAMES} — "
                      f"distance: {dist:.4f} — {status_icon} "
                      f"(passing: {passing_frames}/{self.MIN_PASSING_FRAMES}) "
                      f"face_size: {face_ratio:.0%} | hint: {pos_hint}")

                overlay_setter_fn({
                    'status':     f"VERIFYING... ({fn}/{self.MAX_FRAMES})",
                    'guidance':   pos_hint,
                    'face_found': True,
                    'uid':        str(user_id),
                    'name':       '',
                    'confidence': round(max(0.0, (1.0 - dist / 0.6)) * 100, 1),
                    'start_time': time.time()
                })

                # ── Early exit: triple-gate already satisfied ──────────────
                # No need to wait for all MAX_FRAMES if we already have enough
                # high-quality passing frames — grant immediately.
                if (passing_frames >= self.MIN_PASSING_FRAMES
                        and best_distance < threshold
                        and len(distances) >= self.MIN_PASSING_FRAMES):
                    avg_so_far = sum(distances) / len(distances)
                    if avg_so_far < threshold:
                        print(f"[VERIFY] Early exit — triple-gate satisfied after "
                              f"{fn} frames (avg {avg_so_far:.3f} < {threshold})")
                        break

            except Exception as e:
                print(f"[VERIFY] Frame error: {e}")

            time.sleep(self.FRAME_INTERVAL)

        # ── Decision ──────────────────────────────────────────────────────────
        if not distances:
            print(f"[VERIFY] TIMEOUT — no face detected in {self.WINDOW_SECONDS}s")
            result_callback_fn(self._make_result(
                verified=False, confidence=0.0, best_distance=9.99,
                frames_checked=0, reason="TIMEOUT", user_id=user_id))
            return

        best_distance = min(distances)
        avg_distance  = round(sum(distances) / len(distances), 4)

        # TRIPLE GATE — all three must pass for GRANTED:
        #
        #  Gate 1 — best single frame below threshold
        #            (enrolled person always has at least one clean frame)
        #
        #  Gate 2 — at least MIN_PASSING_FRAMES individually below threshold
        #            (stops a stranger who gets 1 lucky frame)
        #
        #  Gate 3 — AVERAGE of ALL frames below threshold
        #            (stops a stranger who flukes 2 frames at 0.49 but
        #             scores 0.65–0.80 on the rest → avg ≈ 0.60 → DENIED)
        #
        # Your enrolled face (log avg ≈ 0.43) passes all three easily.
        # A typical stranger (avg 0.65+) fails Gate 3 even if Gates 1&2 pass.
        gate1 = best_distance  < threshold
        gate2 = passing_frames >= self.MIN_PASSING_FRAMES
        gate3 = avg_distance   < threshold
        verified = gate1 and gate2 and gate3

        if verified:
            # Map [0, threshold] → [100%, 70%] — always clears main.py's 70% gate
            confidence = round(70.0 + 30.0 * (1.0 - best_distance / threshold), 1)
        else:
            confidence = round(max(0.0, (1.0 - best_distance / 0.6) * 100), 1)

        verdict = "GRANTED" if verified else "DENIED"
        deny_reason = ""
        if not verified:
            parts = []
            if not gate1:
                parts.append(f"best {best_distance:.3f} >= threshold {threshold}")
            if not gate2:
                parts.append(f"only {passing_frames}/{self.MIN_PASSING_FRAMES} passing frames")
            if not gate3:
                parts.append(f"avg {avg_distance:.3f} >= threshold {threshold} (inconsistent match)")
            deny_reason = f" ({' | '.join(parts)})"

        print(f"\n[VERIFY] ── Decision ─────────────────────────────────────────")
        print(f"[VERIFY] Frames checked  : {len(distances)} / {frames_tried} attempted")
        print(f"[VERIFY] Passing frames  : {passing_frames} / {self.MIN_PASSING_FRAMES} required")
        print(f"[VERIFY] All distances   : {[round(d,4) for d in distances]}")
        print(f"[VERIFY] Best distance   : {best_distance:.4f}  {'✓' if gate1 else '✗'}")
        print(f"[VERIFY] Avg distance    : {avg_distance:.4f}  {'✓' if gate3 else '✗'}")
        print(f"[VERIFY] Threshold       : {threshold}")
        print(f"[VERIFY] Confidence      : {confidence}%")
        print(f"[VERIFY] Result          : {verdict}{deny_reason}")
        print(f"[VERIFY] ════════════════════════════════════════════════════\n")

        reason = "MATCH" if verified else "NO_MATCH"
        result_callback_fn(self._make_result(
            verified=verified, confidence=confidence,
            best_distance=best_distance, frames_checked=len(distances),
            reason=reason, user_id=user_id))



    # =========================================================================
    # RESULT DICT BUILDER
    # =========================================================================
    def _make_result(self, verified, confidence, best_distance,
                     frames_checked, reason, user_id):
        return {
            "verified":       verified,
            "confidence":     confidence,   # 0–100 percent
            "best_distance":  round(best_distance, 4),
            "frames_checked": frames_checked,
            "message":        ("ACCESS GRANTED" if verified
                               else ("INSTALL face-recognition" if reason == "NO_LIBRARY"
                                     else f"FACE {reason.replace('_',' ')}")),
            "reason":         reason,       # MATCH | NO_MATCH | TIMEOUT | LOAD_ERROR | NO_LIBRARY
            "user_id":        user_id,
        }

    # =========================================================================
    # LEGACY SINGLE-FRAME VERIFY  (backward compat — biometric OFF path)
    # =========================================================================
    def verify_face(self, live_frame, stored_embedding_str, user_id=None):
        """Single-frame verify for backward compatibility (biometric-off path)."""
        stored_enc = load_embedding_from_db(stored_embedding_str)
        if stored_enc is None:
            return {"verified": False, "confidence": 0.0,
                    "message": "LOAD_ERROR", "reason": "LOAD_ERROR", "user_id": user_id}

        enc, _ = self.extract_encoding(live_frame, num_jitters=1)
        if enc is None:
            return {"verified": False, "confidence": 0.0,
                    "message": "NO FACE", "reason": "TIMEOUT", "user_id": user_id}

        dist     = float(face_recognition.face_distance([stored_enc], enc)[0])
        verified = dist < self.DISTANCE_THRESHOLD
        confidence = (round(70.0 + 30.0 * (1.0 - dist / self.DISTANCE_THRESHOLD), 1)
                      if verified
                      else round(max(0.0, (1.0 - dist / 0.6) * 100), 1))
        return self._make_result(verified=verified, confidence=confidence,
                                 best_distance=dist, frames_checked=1,
                                 reason="MATCH" if verified else "NO_MATCH",
                                 user_id=user_id)