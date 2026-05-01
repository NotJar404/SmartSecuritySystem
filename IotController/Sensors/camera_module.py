import cv2
import threading
import time
import platform
from flask import Flask, Response


# =========================
# CAMERA MODULE (UNIVERSAL)
# =========================
class CameraModule:
    """
    Supports:
    - Laptop webcam (Windows/Linux)
    - Raspberry Pi Camera Module
    - USB external cameras
    """

    def __init__(self, camera_id=0, width=640, height=480, fps=30):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.fps = fps

        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False

    def initialize(self):
        """Initialize camera with fallback support"""

        try:
            # =========================
            # AUTO DETECTION MODE
            # =========================
            system = platform.system().lower()

            # Raspberry Pi usually uses /dev/video0 or libcamera
            if system == "linux":
                print("Detected Linux system (likely Raspberry Pi)")

            # Open camera (works for both Pi + laptop)
            self.cap = cv2.VideoCapture(self.camera_id)

            if not self.cap.isOpened():
                print("Primary camera failed, trying fallback index 1...")
                self.cap = cv2.VideoCapture(1)

            if not self.cap.isOpened():
                raise Exception("Cannot open any camera device")

            # Optimize camera settings
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)

            print("Camera initialized successfully")
            return True

        except Exception as e:
            print("Camera init error:", e)
            return False

    def start(self):
        """Start camera capture thread"""
        if self.running:
            return

        self.running = True
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def _loop(self):
        """Continuous frame capture loop"""
        while self.running:
            try:
                ret, frame = self.cap.read()

                if ret:
                    with self.lock:
                        self.frame = frame

            except Exception as e:
                print("Camera loop error:", e)

            time.sleep(0.01)

    def get_frame(self):
        """Get latest frame safely"""
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        """Stop camera safely"""
        self.running = False
        if self.cap:
            self.cap.release()


# =========================
# FLASK STREAM SERVER
# =========================
app = Flask(__name__)
camera = CameraModule(camera_id=0)


def generate_frames():
    """
    MJPEG stream for ASP.NET <video> tag
    Works for:
    - Raspberry Pi stream
    - Laptop webcam stream
    - USB camera stream
    """

    while True:
        frame = camera.get_frame()

        if frame is None:
            continue

        # Encode frame to JPEG
        success, buffer = cv2.imencode('.jpg', frame)
        if not success:
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n'
        )


@app.route('/video')
def video_feed():
    """Streaming endpoint for ASP.NET"""
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
    print(" Supports: Laptop + Raspberry Pi")
    print(" Stream URL: http://<IP>:5000/video")
    print("===================================")

    if not camera.initialize():
        print("Failed to start camera")
        exit()

    camera.start()

    # IMPORTANT: 0.0.0.0 allows network access (Raspberry Pi / LAN)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)