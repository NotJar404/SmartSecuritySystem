"""
MJPEG Stream Server for Desktop/Laptop Testing

UNIFIED PIPELINE: Uses the EXACT SAME AI modules as main.py on the Pi
  PersonDetector → CentroidTracker → FaceDetector → render_full_frame → MJPEG

ON-DEMAND webcam lifecycle:
  /start  -> opens laptop webcam via OpenCV
  /video  -> serves PROCESSED MJPEG stream with bounding boxes
  /stop   -> releases webcam, turns off camera light
  /health -> real disk usage
  /status -> whether webcam is currently active + FSM state

Camera.cshtml calls /start when page opens, /stop when page closes.
Webcam is NEVER held open permanently.

On Raspberry Pi, use main.py instead (full AI pipeline + real sensors).
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

# =========================
# SAME PRODUCTION AI MODULES AS main.py
# =========================
from AI.overlay_renderer import render_full_frame
from AI.face_detection import FaceDetector
from AI.person_detector import PersonDetector
from AI.person_tracker import CentroidTracker

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
# AI MODULE INSTANCES (SAME AS main.py)
# =========================
face_detector = FaceDetector()
person_detector = PersonDetector(
    confidence_threshold=0.5,
    model_dir=os.path.join(os.path.dirname(__file__), "models")
)
person_tracker = CentroidTracker(
    max_disappeared=30,
    max_distance=80
)

# =========================
# SIMULATED FSM STATE (mirrors main.py states for demo)
# =========================
STATE_IDLE = "IDLE"
STATE_ACCESS = "ACCESS"
STATE_INSIDE = "INSIDE"
STATE_ALERT = "ALERT"
STATE_LOITERING = "LOITERING"

demo_state = STATE_IDLE
demo_state_lock = threading.Lock()
tracked_persons_ref = {}       # Reference to current tracked persons
current_occupancy = 0
current_faces = []
face_images_ref = []
last_face_update = 0

# Face debounce for demo state transitions
_idle_face_counter = 0
_idle_grace_threshold = 5      # Same as main.py
_alert_start_time = None
_alert_auto_clear_timeout = 30  # Same as main.py
_empty_frame_counter = 0
_empty_frame_threshold = 10    # Same as main.py

# Occupancy smoothing (same as main.py BUG-9 fix)
_occupancy_buffer = []
_occupancy_buffer_size = 5


def _get_demo_state():
    with demo_state_lock:
        return demo_state


def _set_demo_state(new_state):
    global demo_state
    with demo_state_lock:
        if demo_state != new_state:
            old = demo_state
            demo_state = new_state
            print(f"[DEMO FSM] {old} → {new_state}")


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
    Background thread: capture → detect → track → face ID → overlay → store frame.
    Uses the EXACT SAME production AI modules as main.py on the Pi.
    """
    global cap, current_frame, capture_running
    global tracked_persons_ref, current_occupancy, current_faces, face_images_ref
    global last_face_update
    global _idle_face_counter, _alert_start_time, _empty_frame_counter
    global _occupancy_buffer
    import platform

    # Use DirectShow on Windows for faster init + lower latency
    if platform.system().lower() == 'windows':
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("[STREAM] Trying camera index 1...")
        cap = cv2.VideoCapture(1)

    if not cap.isOpened():
        print("[STREAM] ERROR: Cannot open any camera device!")
        capture_running = False
        return

    # HD resolution for sharp in-page stream
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Always get latest frame

    # Disable autofocus for stability
    try:
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        cap.set(cv2.CAP_PROP_FOCUS, 40)
    except Exception:
        pass

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[STREAM] Webcam opened - {actual_w}x{actual_h} (HD) - camera ON")
    print("[STREAM] Pipeline: PersonDetector → CentroidTracker → FaceDetector → Overlay → MJPEG")
    print("[STREAM] Using SAME AI modules as main.py (production parity)")

    # Reset demo state on capture start
    _set_demo_state(STATE_IDLE)
    _idle_face_counter = 0
    _alert_start_time = None
    _empty_frame_counter = 0
    _occupancy_buffer.clear()

    # Render debug counters
    _render_debug_time = 0
    _render_box_total = 0
    _render_frame_total = 0

    while capture_running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue

        # Mirror for selfie-view on webcam (matches camera_module.py behavior)
        frame = cv2.flip(frame, 1)

        now = time.time()
        current_state = _get_demo_state()
        faces = []
        face_imgs = []

        # =========================
        # DUAL-MODE DETECTION (SAME AS main.py)
        # IDLE/ACCESS: Face detection (entrance monitoring)
        # INSIDE/LOITERING/ALERT: Person detection + tracking (room monitoring)
        # =========================
        if current_state in (STATE_INSIDE, STATE_LOITERING, STATE_ALERT):
            # INSIDE/LOITERING/ALERT: Person detection + tracking
            person_detections = person_detector.detect_persons(frame)
            tracked_persons_ref = person_tracker.update(person_detections, frame)

            # Update authorization status (simplified for demo)
            for person in tracked_persons_ref.values():
                if person.disappeared == 0 and not person.status_locked:
                    person.status = 'authorized'  # Demo: all persons shown as authorized

            raw_occupancy = person_tracker.get_active_count()

            # Still run face detection at reduced rate (same as main.py line 534)
            if now - last_face_update > 2:
                faces, face_imgs = face_detector.detect_faces(frame)
                last_face_update = now
        else:
            # IDLE/ACCESS: Face detection
            faces, face_imgs = face_detector.detect_faces(frame)
            raw_occupancy = len(faces)

        # Store for status endpoint
        current_faces = faces
        face_images_ref = face_imgs

        # =========================
        # OCCUPANCY SMOOTHING (same as main.py BUG-9 fix)
        # =========================
        _occupancy_buffer.append(raw_occupancy)
        if len(_occupancy_buffer) > _occupancy_buffer_size:
            _occupancy_buffer.pop(0)
        current_occupancy = sorted(_occupancy_buffer)[len(_occupancy_buffer) // 2]

        # =========================
        # DEMO FSM STATE TRANSITIONS (mirrors main.py logic)
        # =========================
        if current_state == STATE_IDLE:
            if current_occupancy > 0:
                _idle_face_counter += 1
                if _idle_face_counter >= _idle_grace_threshold:
                    # Sustained face → simulate RFID tap → INSIDE
                    _set_demo_state(STATE_INSIDE)
                    _idle_face_counter = 0
                    print("[DEMO] Person detected → transitioning to INSIDE")
            else:
                _idle_face_counter = 0

        elif current_state == STATE_INSIDE:
            if current_occupancy == 0:
                _empty_frame_counter += 1
                if _empty_frame_counter >= _empty_frame_threshold:
                    _set_demo_state(STATE_IDLE)
                    _empty_frame_counter = 0
                    # Reset tracker for clean slate
                    person_tracker.objects = {}
                    tracked_persons_ref = {}
                    print("[DEMO] Room empty → transitioning to IDLE")
            else:
                _empty_frame_counter = 0

        elif current_state == STATE_ALERT:
            if _alert_start_time and (now - _alert_start_time) > _alert_auto_clear_timeout:
                if current_occupancy == 0:
                    _set_demo_state(STATE_IDLE)
                    _alert_start_time = None
                    print("[DEMO] ALERT auto-cleared (no presence)")

        # =========================
        # UNIFIED OVERLAY RENDERING (SAME render_full_frame as main.py)
        # =========================
        frame, boxes = render_full_frame(
            frame,
            state=current_state,
            occupancy=current_occupancy,
            sessions=0,
            tracked_persons=tracked_persons_ref if current_state in (STATE_INSIDE, STATE_LOITERING, STATE_ALERT) else None,
            faces=faces if current_state in (STATE_IDLE, STATE_ACCESS) else None,
            is_recording=False,
            armed=True,
            extra_info="AI Pipeline Active (Test Mode)"
        )

        # Render debug logging (every 5 seconds)
        _render_frame_total += 1
        _render_box_total += boxes
        if now - _render_debug_time > 5:
            avg_boxes = _render_box_total / max(1, _render_frame_total)
            tracked_count = len(tracked_persons_ref)
            print(f"[RENDER] State: {current_state} | "
                  f"Boxes/frame: {avg_boxes:.1f} | "
                  f"Tracked: {tracked_count} | "
                  f"Faces: {len(faces)} | "
                  f"FPS: {_render_frame_total / 5:.1f}")
            _render_debug_time = now
            _render_box_total = 0
            _render_frame_total = 0

        # Store processed frame for MJPEG streaming
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
                time.sleep(0.01)
                continue

            # JPEG quality 80 = sharp HD video
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                continue

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Access-Control-Allow-Origin': '*'
        }
    )


@app.route('/ready', methods=['GET'])
def stream_ready():
    """Instant health check — frontend pings this before loading /video."""
    return json.dumps({
        'ready': capture_running and cap is not None and cap.isOpened(),
        'state': _get_demo_state(),
        'armed': True
    }), 200, {'Content-Type': 'application/json'}


@app.route('/status')
def webcam_status():
    """Return stream status with tracked person info for AI panel.
    SAME format as main.py /status — camera.cshtml polls this."""
    state = _get_demo_state()
    visible = sum(1 for p in tracked_persons_ref.values()
                  if hasattr(p, 'disappeared') and p.disappeared == 0) if tracked_persons_ref else 0
    face_detected = current_occupancy > 0 and state in (STATE_IDLE, STATE_ACCESS)

    # Threat level (same logic as main.py)
    threat = 'SAFE'
    if state == STATE_ALERT:
        threat = 'ALERT'
    elif state == STATE_LOITERING:
        threat = 'WARNING'

    return json.dumps({
        "active": capture_running,
        "mode": "TEST",
        "state": state,
        "occupancy": current_occupancy,
        "sessions": 0,
        "tracked_persons": visible,
        "face_detected": face_detected,
        "threat_level": threat,
        "recording": False,
        "pir_motion": False,
        "armed": True
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

    print("=" * 60)
    print("  MJPEG Stream Server - Laptop Test Mode")
    print("  PRODUCTION PARITY: Same AI modules as main.py")
    print("")
    print("  Modules: PersonDetector + CentroidTracker + FaceDetector")
    print("  Renderer: render_full_frame (shared with main.py)")
    print("")
    print("  Stream:  http://localhost:5050/video")
    print("  Start:   http://localhost:5050/start")
    print("  Stop:    http://localhost:5050/stop")
    print("  Status:  http://localhost:5050/status")
    print("  Health:  http://localhost:5050/health")
    print("")
    print("  Pipeline: PersonDetector → CentroidTracker → FaceDetector → Overlay → MJPEG")
    print("  Webcam opens ON-DEMAND (not at startup)")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
