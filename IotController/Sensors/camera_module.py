import cv2
import threading
import time
import platform
from flask import Flask, Response


# =========================
# CAMERA MODULE (AI-READY)
# =========================
class CameraModule:
    """
    Universal Camera Module
    Supports:
    - Laptop webcam
    - Raspberry Pi camera
    - USB cameras

    Now supports:
    - AI overlay frames
    - Safe multithreading
    """

    def __init__(self, camera_id=0, width=640, height=480, fps=30):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.fps = fps

        self.cap = None
        self.frame = None
        self.processed_frame = None  # NEW: for AI overlays

        self.lock = threading.Lock()
        self.running = False

    def initialize(self):
        """Initialize camera with Pi Camera Module 3 + fallback support"""
        try:
            system = platform.system().lower()

            if system == "linux":
                print("[CAMERA] Detected Linux — trying Pi Camera Module 3...")

                # =========================
                # PRIORITY 1: libcamera via GStreamer (Pi Camera Module 3)
                # =========================
                gst_pipeline = (
                    f"libcamerasrc ! "
                    f"video/x-raw,width={self.width},height={self.height},"
                    f"framerate={self.fps}/1 ! "
                    f"videoconvert ! appsink"
                )
                self.cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)

                if self.cap.isOpened():
                    print("[CAMERA] ✓ Pi Camera Module 3 via libcamera (GStreamer)")
                    return True

                # =========================
                # PRIORITY 2: picamera2 wrapper (if GStreamer unavailable)
                # =========================
                try:
                    from picamera2 import Picamera2
                    picam = Picamera2()
                    picam.configure(picam.create_preview_configuration(
                        main={"size": (self.width, self.height), "format": "RGB888"}
                    ))
                    picam.start()
                    self._picamera2 = picam
                    self._use_picamera2 = True
                    print("[CAMERA] ✓ Pi Camera Module 3 via picamera2")
                    return True
                except Exception as e:
                    print(f"[CAMERA] picamera2 not available: {e}")
                    self._use_picamera2 = False

                # =========================
                # PRIORITY 3: V4L2 USB camera on Pi
                # =========================
                self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
                if self.cap.isOpened():
                    print("[CAMERA] ✓ USB camera via V4L2")
                else:
                    raise Exception("No camera device found on Linux")

            else:
                # =========================
                # DESKTOP/LAPTOP — standard OpenCV
                # =========================
                print("[CAMERA] Detected Desktop — using webcam")
                self._use_picamera2 = False
                self.cap = cv2.VideoCapture(self.camera_id)

                if not self.cap.isOpened():
                    print("[CAMERA] Primary camera failed, trying index 1...")
                    self.cap = cv2.VideoCapture(1)

                if not self.cap.isOpened():
                    raise Exception("Cannot open any camera device")

            # Optimize settings (for OpenCV-based captures)
            if not getattr(self, '_use_picamera2', False):
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)

                # =========================
                # DISABLE AUTOFOCUS (CRITICAL FOR STABILITY)
                # =========================
                self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                self.cap.set(cv2.CAP_PROP_FOCUS, 40)

            print("[CAMERA] Initialized successfully")
            return True

        except Exception as e:
            print("[CAMERA] Init error:", e)
            return False

    def start(self):
        """Start camera capture thread"""
        if self.running:
            return

        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        """Continuous capture loop (OpenCV or picamera2)"""
        while self.running:
            try:
                if getattr(self, '_use_picamera2', False):
                    # Pi Camera Module 3 via picamera2
                    frame = self._picamera2.capture_array()
                    if frame is not None:
                        with self.lock:
                            self.frame = frame
                            if self.processed_frame is None:
                                self.processed_frame = frame
                else:
                    # Standard OpenCV capture
                    ret, frame = self.cap.read()
                    if ret:
                        with self.lock:
                            self.frame = frame
                            if self.processed_frame is None:
                                self.processed_frame = frame

            except Exception as e:
                print("[CAMERA] Loop error:", e)

            time.sleep(0.01)

    def get_frame(self):
        """Raw frame (for AI processing)"""
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def set_processed_frame(self, frame):
        """Set AI-processed frame (with overlays)"""
        with self.lock:
            self.processed_frame = frame

    def get_stream_frame(self):
        """Frame used for streaming (processed if available)"""
        with self.lock:
            if self.processed_frame is not None:
                return self.processed_frame.copy()
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        """Stop camera safely"""
        self.running = False
        if getattr(self, '_use_picamera2', False) and hasattr(self, '_picamera2'):
            try:
                self._picamera2.stop()
            except:
                pass
        elif self.cap:
            self.cap.release()


# =========================
# FLASK STREAM SERVER
# =========================
app = Flask(__name__)
camera = CameraModule(camera_id=0)


def generate_frames():
    """
    MJPEG stream for ASP.NET
    Shows AI overlays if available
    """
    while True:
        frame = camera.get_stream_frame()

        if frame is None:
            continue

        success, buffer = cv2.imencode('.jpg', frame)
        if not success:
            continue

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
        )


@app.route('/video')
def video_feed():
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


# =========================
# MAIN START
# =========================
if __name__ == "__main__":
    print("===================================")
    print(" Smart Camera Stream Starting...")
    print(" Hybrid Mode: Laptop + Raspberry Pi")
    print(" Stream URL: http://localhost:5000/video")
    print("===================================")

    if not camera.initialize():
        print("Failed to start camera")
        exit()

    camera.start()

    # Allow LAN access (important for ASP.NET)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)