import cv2
import threading
import time
import platform


# =========================
# CAMERA MODULE (AI-READY)
# =========================
class CameraModule:
    """
    Universal Camera Module
    Supports:
    - Laptop webcam (HD 1280x720, mirrored)
    - Raspberry Pi camera (libcamera, picamera2, V4L2)
    - USB cameras

    Architecture:
    - Capture thread writes ONLY to self._raw_frame
    - Main loop reads raw frame via get_frame()
    - Main loop draws overlays and writes via set_processed_frame()
    - Stream reads via get_stream_frame() → processed if available, else raw
    - NO RACE CONDITION: capture thread NEVER touches processed_frame

    Performance:
    - HD resolution (1280x720) for sharp video on ASP.NET frontend
    - Webcam mirroring for natural selfie-view on laptop
    - Warm-up ensures first frame is available before stream starts
    - MJPEG buffer optimization for minimal latency
    """

    def __init__(self, camera_id=0, width=1280, height=720, fps=30, mirror=None):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.fps = fps

        # Auto-detect mirror: True for laptop webcam, False for Pi camera
        if mirror is None:
            self._mirror = platform.system().lower() != "linux"
        else:
            self._mirror = mirror

        self.cap = None
        self._raw_frame = None           # Written ONLY by capture thread
        self._processed_frame = None     # Written ONLY by set_processed_frame()
        self._has_processed = False      # True once main loop has set at least one processed frame
        self._frame_ready = threading.Event()  # Signals when first frame is captured

        self._lock = threading.Lock()
        self.running = False

        # Compatibility aliases
        self.frame = None
        self.processed_frame = None
        self.lock = self._lock

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
                # DESKTOP/LAPTOP — DirectShow backend (more reliable on Windows)
                # =========================
                print("[CAMERA] Detected Desktop -- using webcam (DirectShow)")
                self._use_picamera2 = False
                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)

                if not self.cap.isOpened():
                    print("[CAMERA] DirectShow failed, trying default backend...")
                    self.cap = cv2.VideoCapture(self.camera_id)

                if not self.cap.isOpened():
                    print("[CAMERA] Primary camera failed, trying index 1...")
                    self.cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)

                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(1)

                if not self.cap.isOpened():
                    raise Exception("Cannot open any camera device")

            # Optimize settings (for OpenCV-based captures)
            if not getattr(self, '_use_picamera2', False):
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)

                # =========================
                # BUFFER SIZE = 1: Ensures we always get the LATEST frame
                # Prevents stale frames from accumulating in the driver buffer
                # =========================
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                # =========================
                # DISABLE AUTOFOCUS (CRITICAL FOR STABILITY)
                # Not all cameras support this — ignore failures
                # =========================
                try:
                    self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                    self.cap.set(cv2.CAP_PROP_FOCUS, 40)
                except Exception:
                    print("[CAMERA] Autofocus control not supported — skipping")

                # Report actual resolution
                actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = int(self.cap.get(cv2.CAP_PROP_FPS))
                mirror_status = "ON (selfie mode)" if self._mirror else "OFF"
                print(f"[CAMERA] Resolution: {actual_w}x{actual_h} @ {actual_fps}fps | Mirror: {mirror_status}")

            print("[CAMERA] Initialized successfully")
            return True

        except Exception as e:
            print("[CAMERA] Init error:", e)
            return False

    def start(self):
        """Start camera capture thread and wait for first frame (warm-up)."""
        if self.running:
            return

        self.running = True

        # =========================
        # DRAIN STALE FRAMES: Camera drivers (DirectShow, V4L2) buffer
        # 3-5 old frames internally. If we don't drain them, the first
        # /video frame will be stale/delayed. Read and discard a few.
        # =========================
        if self.cap is not None and not getattr(self, '_use_picamera2', False):
            for _ in range(5):
                self.cap.read()  # Discard stale buffered frames

        threading.Thread(target=self._loop, daemon=True).start()

        # =========================
        # WARM-UP: Wait for first LIVE frame to be captured
        # Webcam typically delivers first frame in <0.5s
        # Pi Camera Module 3 typically within 1-2s
        # =========================
        print("[CAMERA] Warming up...")
        if self._frame_ready.wait(timeout=2.0):
            print("[CAMERA] ✓ Stream ready — first frame captured")
        else:
            print("[CAMERA] ⚠ Warm-up timeout — stream may start with delay")

    def _loop(self):
        """
        Continuous capture loop (OpenCV or picamera2).

        CRITICAL: This loop writes ONLY to self._raw_frame.
        It NEVER writes to self._processed_frame.
        This eliminates the race condition that caused bounding boxes to disappear.

        WATCHDOG: Detects consecutive frame failures and auto-restarts camera.
        """
        _frame_count = 0
        _consecutive_failures = 0
        _max_failures = 30  # ~3 seconds of failures at 10ms/frame

        while self.running:
            try:
                if getattr(self, '_use_picamera2', False):
                    # Pi Camera Module 3 via picamera2
                    frame = self._picamera2.capture_array()
                    if frame is not None:
                        with self._lock:
                            self._raw_frame = frame
                            self.frame = frame
                        self._frame_ready.set()
                        _consecutive_failures = 0
                    else:
                        _consecutive_failures += 1
                else:
                    # Standard OpenCV capture
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        # Apply mirror for webcam mode (selfie view)
                        if self._mirror:
                            frame = cv2.flip(frame, 1)

                        with self._lock:
                            self._raw_frame = frame
                            self.frame = frame
                        self._frame_ready.set()
                        _consecutive_failures = 0
                    else:
                        _consecutive_failures += 1

                # =========================
                # WATCHDOG: Auto-restart on sustained failure
                # =========================
                if _consecutive_failures >= _max_failures:
                    print(f"[CAMERA WATCHDOG] {_consecutive_failures} consecutive failures — attempting restart...")
                    _consecutive_failures = 0
                    self._restart_capture()

            except Exception as e:
                print("[CAMERA] Loop error:", e)
                _consecutive_failures += 1

            _frame_count += 1
            # No sleep for first 10 frames to fill pipeline fast,
            # then 10ms (~100fps cap) to prevent CPU spin
            if _frame_count > 10:
                time.sleep(0.01)

    def _restart_capture(self):
        """Watchdog restart: release and re-initialize camera capture."""
        try:
            if getattr(self, '_use_picamera2', False):
                try:
                    self._picamera2.stop()
                except:
                    pass
                time.sleep(1)
                self._picamera2.start()
                print("[CAMERA WATCHDOG] picamera2 restarted")
            elif self.cap is not None:
                self.cap.release()
                time.sleep(1)
                # Re-open with same settings
                self.cap = cv2.VideoCapture(self.camera_id)
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    print("[CAMERA WATCHDOG] OpenCV capture restarted")
                else:
                    print("[CAMERA WATCHDOG] Failed to reopen camera")
        except Exception as e:
            print(f"[CAMERA WATCHDOG] Restart failed: {e}")

    def get_frame(self):
        """
        Get raw frame for AI processing.
        Returns a COPY so the caller can draw on it without affecting the capture thread.
        """
        with self._lock:
            if self._raw_frame is None:
                return None
            return self._raw_frame.copy()

    def set_processed_frame(self, frame):
        """
        Set the AI-processed frame (with overlays drawn on it).
        This is the ONLY way to update the processed frame.
        Called by the main loop after drawing all overlays.
        """
        if frame is None:
            return
        with self._lock:
            self._processed_frame = frame
            self._has_processed = True
            self.processed_frame = frame

    def get_stream_frame(self):
        """
        Get frame for MJPEG streaming.
        Returns the PROCESSED frame (with overlays) if available,
        otherwise returns the raw frame.

        IMPORTANT: Returns a COPY to prevent the stream encoder
        from interfering with the main loop's frame.
        """
        with self._lock:
            if self._has_processed and self._processed_frame is not None:
                return self._processed_frame.copy()
            if self._raw_frame is not None:
                return self._raw_frame.copy()
            return None

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