"""
MJPEG Stream Server for Desktop/Laptop Testing

UNIFIED PIPELINE: Same as main.py on the Pi
  Capture → Detection → Tracking → Overlay Rendering → MJPEG Stream

ON-DEMAND webcam lifecycle:
  /start  -> opens laptop webcam via OpenCV
  /video  -> serves PROCESSED MJPEG stream with bounding boxes
  /stop   -> releases webcam, turns off camera light
  /health -> real disk usage
  /status -> whether webcam is currently active

Camera.cshtml calls /start when page opens, /stop when page closes.
Webcam is NEVER held open permanently.

On Raspberry Pi, use main.py instead (full AI pipeline).
This script is for LAPTOP TESTING ONLY.

Usage:
    python stream_server.py
"""

import cv2
import numpy as np
import threading
import time
import shutil
import os
import json
from flask import Flask, Response, request
app = Flask(__name__)

# Manual CORS (no flask-cors dependency needed)
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

# =========================
# WEBCAM STATE (ON-DEMAND)
# =========================
cap = None
frame_lock = threading.Lock()
current_frame = None
capture_running = False
capture_thread_ref = None
active_viewers = 0
viewers_lock = threading.Lock()


# =========================
# DETECTION ENGINE (HOG + Tracking)
# Same pipeline as main.py on Pi
# =========================
class TestModeDetector:
    """
    Person detector + face identifier for test mode (laptop).
    
    Pipeline:
    1. HOG+SVM detects person bodies (always running)
    2. Haar cascade detects faces WITHIN person bounding boxes
    3. Once a face is seen for a tracked person, their status becomes PERMANENT
       (authorized/unauthorized/unknown) — even when face turns away
    4. Body tracking maintains the bounding box via centroid matching
    
    Status Rules (mirrors main.py _update_person_authorization):
    - Face detected + in session list -> 'authorized' (GREEN)
    - Face detected + NOT in session list -> 'unauthorized' (RED)
    - No face detected yet -> 'unknown' (YELLOW)
    - Status is STICKY: once set by face detection, it NEVER resets
      as long as the person remains tracked
    """

    def __init__(self, confidence=0.4):
        self.confidence = confidence

        # Person body detector (HOG+SVM, built into OpenCV)
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        # Face detector (Haar cascade, built into OpenCV)
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        # Centroid tracker with persistent status
        # tracked[id] = {cx, cy, bbox, smooth_bbox, conf, status, disappeared,
        #                face_seen, face_check_count}
        self.tracked = {}
        self.next_id = 1
        self.max_disappeared = 45   # ~4.5 sec @ 10fps (stable tracking)
        self.max_match_distance = 150

        # Bbox smoothing factor (0=no smoothing, 1=frozen)
        self.bbox_smooth = 0.6

        # Detection intervals
        self.frame_count = 0
        self.detect_every = 3       # HOG every 3rd frame
        self.face_detect_every = 6  # Face every 6th frame (lighter)
        self.last_detections = []

        print("[DETECT] HOG+SVM person detector initialized (test mode)")
        print("[DETECT] Haar cascade face detector loaded")
        print("[DETECT] Persistent status tracking enabled")

    def detect(self, frame):
        """Run person detection on frame."""
        self.frame_count += 1

        if self.frame_count % self.detect_every != 0:
            return self.last_detections

        try:
            small = cv2.resize(frame, (640, 480))
            scale_x = frame.shape[1] / 640
            scale_y = frame.shape[0] / 480

            boxes, weights = self.hog.detectMultiScale(
                small,
                winStride=(8, 8),
                padding=(4, 4),
                scale=1.05
            )

            detections = []
            for (x, y, w, h), weight in zip(boxes, weights):
                if weight < self.confidence:
                    continue
                ox = int(x * scale_x)
                oy = int(y * scale_y)
                ow = int(w * scale_x)
                oh = int(h * scale_y)
                detections.append((ox, oy, ow, oh, float(weight)))

            # NMS to remove duplicates
            if len(detections) > 1:
                boxes_nms = [[d[0], d[1], d[2], d[3]] for d in detections]
                scores = [d[4] for d in detections]
                indices = cv2.dnn.NMSBoxes(boxes_nms, scores, self.confidence, 0.4)
                if len(indices) > 0:
                    if isinstance(indices[0], (list, np.ndarray)):
                        indices = [i[0] for i in indices]
                    detections = [detections[i] for i in indices]

            self.last_detections = detections
            return detections

        except Exception as e:
            print(f"[DETECT ERROR] {e}")
            return self.last_detections

    def detect_faces_in_bbox(self, frame, bbox):
        """
        Detect faces within a person's bounding box.
        Returns True if at least one face is found.
        """
        x, y, w, h = bbox
        fh, fw = frame.shape[:2]

        # Clamp to frame bounds
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(fw, x + w)
        y2 = min(fh, y + h)

        if x2 - x1 < 30 or y2 - y1 < 30:
            return False

        # Crop the person region (upper portion where face would be)
        face_region_h = int((y2 - y1) * 0.5)  # Top 50% of person bbox
        roi = frame[y1:y1 + face_region_h, x1:x2]

        if roi.size == 0:
            return False

        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray_roi,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(20, 20)
        )

        return len(faces) > 0

    def update_tracking(self, detections):
        """
        Centroid tracking with PERSISTENT status.
        Once a person's face is detected, their status sticks forever
        (until they leave the room / disappear from tracking).
        """
        current_centroids = {}
        for (x, y, w, h, conf) in detections:
            cx = x + w // 2
            cy = y + h // 2
            current_centroids[(cx, cy)] = (x, y, w, h, conf)

        if len(current_centroids) == 0:
            for tid in list(self.tracked.keys()):
                self.tracked[tid]['disappeared'] += 1
                if self.tracked[tid]['disappeared'] > self.max_disappeared:
                    del self.tracked[tid]
            return self.tracked

        if len(self.tracked) == 0:
            for (cx, cy), (x, y, w, h, conf) in current_centroids.items():
                self.tracked[self.next_id] = {
                    'cx': cx, 'cy': cy,
                    'bbox': (x, y, w, h),
                    'smooth_bbox': [float(x), float(y), float(w), float(h)],
                    'conf': conf,
                    'status': 'unknown',
                    'disappeared': 0,
                    'face_seen': False,
                    'face_check_count': 0
                }
                self.next_id += 1
            return self.tracked

        # Match existing tracks to new detections
        track_ids = list(self.tracked.keys())
        track_centers = [(self.tracked[tid]['cx'], self.tracked[tid]['cy'])
                         for tid in track_ids]
        det_centers = list(current_centroids.keys())

        used_tracks = set()
        used_dets = set()

        pairs = []
        for di, dc in enumerate(det_centers):
            for ti, tc in enumerate(track_centers):
                dist = np.sqrt((dc[0] - tc[0])**2 + (dc[1] - tc[1])**2)
                pairs.append((dist, ti, di))
        pairs.sort()

        for dist, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue
            if dist > self.max_match_distance:
                continue

            tid = track_ids[ti]
            dc = det_centers[di]
            x, y, w, h, conf = current_centroids[dc]

            # Update centroid
            self.tracked[tid]['cx'] = dc[0]
            self.tracked[tid]['cy'] = dc[1]
            self.tracked[tid]['conf'] = conf
            self.tracked[tid]['disappeared'] = 0

            # Raw bbox update
            self.tracked[tid]['bbox'] = (x, y, w, h)

            # Smooth bbox (exponential moving average)
            sb = self.tracked[tid]['smooth_bbox']
            a = self.bbox_smooth
            sb[0] = a * sb[0] + (1 - a) * x
            sb[1] = a * sb[1] + (1 - a) * y
            sb[2] = a * sb[2] + (1 - a) * w
            sb[3] = a * sb[3] + (1 - a) * h

            used_tracks.add(ti)
            used_dets.add(di)

        # Register new detections
        for di, dc in enumerate(det_centers):
            if di not in used_dets:
                x, y, w, h, conf = current_centroids[dc]
                self.tracked[self.next_id] = {
                    'cx': dc[0], 'cy': dc[1],
                    'bbox': (x, y, w, h),
                    'smooth_bbox': [float(x), float(y), float(w), float(h)],
                    'conf': conf,
                    'status': 'unknown',
                    'disappeared': 0,
                    'face_seen': False,
                    'face_check_count': 0
                }
                self.next_id += 1

        # Increment disappeared for unmatched tracks
        for ti, tid in enumerate(track_ids):
            if ti not in used_tracks:
                self.tracked[tid]['disappeared'] += 1
                if self.tracked[tid]['disappeared'] > self.max_disappeared:
                    del self.tracked[tid]

        return self.tracked

    def update_face_status(self, frame):
        """
        Run face detection on tracked persons.
        PERSISTENT STATUS: once face is detected, status sticks.
        
        This mirrors main.py's _update_person_authorization():
        - If face is seen -> mark as 'unknown' (no RFID session in test mode)
        - In test mode, all detected faces default to 'unknown' since there's
          no RFID to verify. On Pi, main.py checks active_sessions.
        - The key is: the status NEVER resets to a worse state once set.
        """
        if self.frame_count % self.face_detect_every != 0:
            return

        for tid, info in self.tracked.items():
            if info['disappeared'] > 0:
                continue

            # Skip if face was already permanently identified
            if info['face_seen']:
                continue

            # Try to detect face inside this person's bounding box
            bbox = info['bbox']
            has_face = self.detect_faces_in_bbox(frame, bbox)

            info['face_check_count'] += 1

            if has_face:
                info['face_seen'] = True
                # In test mode (no RFID system), face detected = 'unknown'
                # On Pi, main.py would check RFID sessions to set authorized/unauthorized
                # Status is now PERMANENT for this track ID
                info['status'] = 'unknown'
                print(f"[FACE] Track ID:{tid} - Face detected, status locked: {info['status']}")
            elif info['face_check_count'] > 30:
                # After ~3 seconds without seeing a face (person facing away),
                # keep as 'unknown' - don't escalate in test mode
                pass

    def render_overlays(self, frame, tracked):
        """
        Draw bounding boxes + labels on frame.
        Uses smooth_bbox for stable, jitter-free rendering.
        MATCHES main.py overlay style exactly.
        """
        # Count only visible persons
        visible = sum(1 for t in tracked.values() if t['disappeared'] == 0)

        # State text (top-left)
        cv2.putText(frame, f"State: MONITORING | Persons: {visible}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 2)

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        for tid, info in tracked.items():
            if info['disappeared'] > 0:
                continue

            # Use smoothed bbox for stable rendering
            sb = info['smooth_bbox']
            x, y, w, h = int(sb[0]), int(sb[1]), int(sb[2]), int(sb[3])
            conf = info['conf']
            status = info.get('status', 'unknown')
            face_seen = info.get('face_seen', False)

            # Color coding (matches main.py exactly)
            color = {
                'authorized': (0, 200, 0),     # GREEN
                'unauthorized': (0, 0, 255),    # RED
                'unknown': (0, 220, 220),       # YELLOW
            }.get(status, (0, 220, 220))

            # === BOUNDING BOX ===
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

            # === CORNER ACCENTS (YOLO-style) ===
            corner_len = max(8, min(20, w // 5, h // 5))
            thickness = 3
            # Top-left
            cv2.line(frame, (x, y), (x + corner_len, y), color, thickness)
            cv2.line(frame, (x, y), (x, y + corner_len), color, thickness)
            # Top-right
            cv2.line(frame, (x + w, y), (x + w - corner_len, y), color, thickness)
            cv2.line(frame, (x + w, y), (x + w, y + corner_len), color, thickness)
            # Bottom-left
            cv2.line(frame, (x, y + h), (x + corner_len, y + h), color, thickness)
            cv2.line(frame, (x, y + h), (x, y + h - corner_len), color, thickness)
            # Bottom-right
            cv2.line(frame, (x + w, y + h), (x + w - corner_len, y + h), color, thickness)
            cv2.line(frame, (x + w, y + h), (x + w, y + h - corner_len), color, thickness)

            # === LABEL ===
            face_icon = "F" if face_seen else "?"
            label = f"ID:{tid} [{status.upper()}] ({face_icon}) {int(conf * 100)}%"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]

            # Label background
            cv2.rectangle(frame,
                          (x, y - label_size[1] - 10),
                          (x + label_size[0] + 8, y),
                          color, -1)

            # Label text
            cv2.putText(frame, label, (x + 4, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Pipeline indicator (bottom-left)
        cv2.putText(frame, "AI Pipeline Active (Test Mode)",
                    (10, frame.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

        return frame


# Global detector instance
detector = TestModeDetector()


_start_lock = threading.Lock()

def start_capture():
    """Open webcam and start capture loop (if not already running)."""
    global cap, capture_running, capture_thread_ref

    with _start_lock:
        if capture_running:
            return True

        capture_running = True
        capture_thread_ref = threading.Thread(target=_capture_loop, daemon=True)
        capture_thread_ref.start()

    for _ in range(20):
        if cap is not None and cap.isOpened():
            return True
        time.sleep(0.1)

    return cap is not None and cap.isOpened()


def stop_capture():
    """Release webcam and stop capture loop."""
    global cap, capture_running, current_frame, capture_thread_ref

    capture_running = False

    # Wait for capture thread to finish (ensures cap.release() in the thread)
    if capture_thread_ref is not None and capture_thread_ref.is_alive():
        capture_thread_ref.join(timeout=3.0)
        capture_thread_ref = None

    # Double-check: release camera if thread didn't
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
        cap = None
        print("[STREAM] Webcam released - camera OFF")

    with frame_lock:
        current_frame = None


def _capture_loop():
    """
    Background thread: capture -> detect -> track -> face ID -> overlay -> store frame.
    SAME pipeline as main.py on the Pi.
    """
    global cap, current_frame, capture_running

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[STREAM] Trying camera index 1...")
        cap = cv2.VideoCapture(1)

    if not cap.isOpened():
        print("[STREAM] ERROR: Cannot open any camera device!")
        capture_running = False
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    print("[STREAM] Webcam opened - camera ON")
    print("[STREAM] Pipeline: HOG+SVM -> Tracking -> Face ID -> Overlays -> MJPEG")

    while capture_running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.03)
            continue

        # === UNIFIED PIPELINE (matches main.py) ===
        # Step 1: Person Detection (HOG+SVM body detector)
        detections = detector.detect(frame)

        # Step 2: Centroid Tracking (persistent IDs)
        tracked = detector.update_tracking(detections)

        # Step 3: Face Detection + Status Lock
        # Detects face WITHIN person bbox, locks status permanently
        detector.update_face_status(frame)

        # Step 4: Overlay Rendering (bounding boxes, labels, tracking IDs)
        frame = detector.render_overlays(frame, tracked)

        # Step 5: Store processed frame for MJPEG streaming
        with frame_lock:
            current_frame = frame.copy()

    # === CLEANUP: Always release camera when loop ends ===
    if cap is not None and cap.isOpened():
        cap.release()
        cap = None
    print("[STREAM] Capture loop stopped, webcam released")


# =========================
# ROUTES
# =========================
@app.route('/start', methods=['POST', 'GET'])
def webcam_start():
    global active_viewers
    with viewers_lock:
        active_viewers += 1

    ok = start_capture()
    return json.dumps({
        "success": ok,
        "message": "Webcam started" if ok else "Failed to open webcam",
        "viewers": active_viewers
    }), 200, {'Content-Type': 'application/json'}


@app.route('/stop', methods=['POST', 'GET'])
def webcam_stop():
    global active_viewers
    with viewers_lock:
        active_viewers = max(0, active_viewers - 1)

    if active_viewers <= 0:
        stop_capture()
        msg = "Webcam stopped - no viewers"
    else:
        msg = f"Viewer disconnected, {active_viewers} still watching"

    return json.dumps({
        "success": True,
        "message": msg,
        "viewers": active_viewers
    }), 200, {'Content-Type': 'application/json'}


@app.route('/video')
def video_feed():
    """Serve MJPEG stream with bounding boxes. Auto-starts webcam if needed."""
    if not capture_running:
        start_capture()

    def generate():
        while capture_running:
            with frame_lock:
                frame = current_frame

            if frame is None:
                time.sleep(0.05)
                continue

            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                continue

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/status')
def webcam_status():
    return json.dumps({
        "active": capture_running,
        "viewers": active_viewers
    }), 200, {'Content-Type': 'application/json'}


@app.route('/health')
def health():
    try:
        usage = shutil.disk_usage("/") if os.name != 'nt' else shutil.disk_usage("C:\\")
        total_gb = round(usage.total / (1024**3), 1)
        used_gb = round(usage.used / (1024**3), 1)
        free_gb = round(usage.free / (1024**3), 1)
        used_pct = round((usage.used / usage.total) * 100, 1)
        return json.dumps({
            "diskUsedPercent": used_pct,
            "diskTotalGb": total_gb,
            "diskUsedGb": used_gb,
            "diskFreeGb": free_gb,
            "recordingsCount": 0
        }), 200, {'Content-Type': 'application/json'}
    except Exception as e:
        return json.dumps({"error": str(e)}), 500, {'Content-Type': 'application/json'}


@app.route('/archive', methods=['POST'])
def archive():
    return json.dumps({
        "success": False,
        "message": "Archive is only available on Raspberry Pi hardware."
    }), 200, {'Content-Type': 'application/json'}


# =========================
# MAIN
# =========================
if __name__ == '__main__':
    import atexit
    import signal

    def _cleanup_on_exit():
        """Ensure webcam is released when process exits."""
        print("[STREAM] Cleanup: releasing webcam...")
        stop_capture()

    atexit.register(_cleanup_on_exit)

    def _signal_handler(sig, frame):
        """Handle Ctrl+C gracefully."""
        print("\n[STREAM] Shutting down...")
        stop_capture()
        import sys
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print("=" * 55)
    print("  MJPEG Stream Server - Laptop Test Mode")
    print("  WITH Detection + Tracking + Face ID + Bounding Boxes")
    print("")
    print("  Stream:  http://localhost:5050/video")
    print("  Start:   http://localhost:5050/start")
    print("  Stop:    http://localhost:5050/stop")
    print("  Health:  http://localhost:5050/health")
    print("")
    print("  Pipeline: HOG -> Tracking -> Face ID -> Overlays -> MJPEG")
    print("  Webcam opens ON-DEMAND (not at startup)")
    print("=" * 55)

    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
