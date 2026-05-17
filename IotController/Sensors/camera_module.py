"""
Camera Module for Smart Security System

Universal camera with Pi Camera Module 3 + USB/webcam fallback.
No GPIO dependency. Thread-safe dual-frame architecture.

Supports:
- Raspberry Pi Camera Module 3 via picamera2 (primary)
- USB cameras via V4L2 (secondary)
- GStreamer libcamera pipeline (tertiary)
- Laptop webcam via DirectShow/default backend (desktop testing)
- Auto-initialization from ASP.NET-detected network camera IP

Architecture:
- Capture thread writes ONLY to self._raw_frame
- Main loop reads raw frame via get_frame()
- Main loop draws overlays and writes via set_processed_frame()
- Stream reads via get_stream_frame() -> processed if available, else raw
- NO RACE CONDITION: capture thread NEVER touches processed_frame

Safety:
- Watchdog auto-restarts camera on sustained frame failure
- Fallback escalation: picamera2 -> V4L2 on sustained watchdog failures
- No blocking initialization loops
- Safe cleanup prevents segfaults on picamera2/OpenCV release
- picamera2.close() on stop() ensures /dev/video* is fully released
- Error spam suppression (logs once per failure episode)

Auto-Init from ASP.NET:
- auto_initialize_from_network(detected_ip) matches 192.168.100.* subnet
- Triggers full initialize() + start() if camera is not already running
- Tolerates minor IP variations (e.g., .101 vs .2) via subnet matching
"""

import cv2
import threading
import time
import platform


class CameraModule:
    """
    Universal Camera Module — AI-ready, production-hardened.

    Public API:
        initialize()                      -> bool
        start()                           -> None
        get_frame()                       -> numpy.ndarray or None
        set_processed_frame()             -> None
        get_stream_frame()                -> numpy.ndarray or None
        stop()                            -> None
        auto_initialize_from_network(ip)  -> bool
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
        self._picamera2 = None
        self._use_picamera2 = False
        self._use_v4l2 = False
        self._use_gstreamer = False

        self._raw_frame = None           # Written ONLY by capture thread
        self._processed_frame = None     # Written ONLY by set_processed_frame()
        self._has_processed = False
        self._frame_ready = threading.Event()

        self._lock = threading.RLock()   # RLock: allows re-entrant locking during restart
        self.running = False
        self._initialized = False        # Tracks whether initialize() succeeded

        # Compatibility aliases (used by some callers)
        self.frame = None
        self.processed_frame = None
        self.lock = self._lock

        # Error spam suppression
        self._last_error_msg = None
        self._error_count = 0

        # Watchdog escalation: track consecutive watchdog restart failures
        self._watchdog_restart_failures = 0
        self._watchdog_max_before_fallback = 3  # After 3 failed restarts, try V4L2

        # Auto-init tracking: prevent concurrent initialization
        self._auto_init_lock = threading.Lock()
        self._auto_init_in_progress = False

        # Network subnet for camera detection (configurable)
        self._camera_subnet = "192.168.100"

    def initialize(self):
        """Initialize camera with Pi Camera Module 3 + fallback support."""
        try:
            system = platform.system().lower()
            self._use_picamera2 = False
            self._use_v4l2 = False
            self._use_gstreamer = False

            if system == "linux":
                print("[CAMERA] Detected Linux — trying Pi Camera Module 3...")

                # =========================
                # PRIORITY 1: picamera2 (Pi Camera Module 3)
                # =========================
                if self._try_picamera2():
                    self._initialized = True
                    return True

                # =========================
                # PRIORITY 2: V4L2 USB camera
                # =========================
                if self._try_v4l2():
                    self._initialized = True
                    return True

                # =========================
                # PRIORITY 3: GStreamer libcamera
                # =========================
                if self._try_gstreamer():
                    self._initialized = True
                    return True

                raise Exception("No camera device found on Linux")

            else:
                # =========================
                # DESKTOP/LAPTOP — DirectShow + fallback
                # =========================
                print("[CAMERA] Detected Desktop — using webcam")

                for cam_id in (self.camera_id, 1):
                    for backend in (cv2.CAP_DSHOW, cv2.CAP_ANY):
                        try:
                            self.cap = cv2.VideoCapture(cam_id, backend)
                            if self.cap is not None and self.cap.isOpened():
                                break
                            self._safe_release_cap()
                        except Exception:
                            self._safe_release_cap()
                    if self.cap is not None and self.cap.isOpened():
                        break

                if self.cap is None or not self.cap.isOpened():
                    raise Exception("Cannot open any camera device")

                self._configure_opencv_cap()
                self._log_opencv_resolution("DirectShow/OpenCV", "PRIMARY")

            print("[CAMERA] Initialized successfully")
            self._initialized = True
            return True

        except Exception as e:
            print(f"[CAMERA] Init error: {e}")
            self._initialized = False
            return False

    def _try_picamera2(self):
        """Attempt to initialize Pi Camera Module 3 via picamera2."""
        try:
            from picamera2 import Picamera2

            # Kill any stale libcamera processes that may hold the pipeline
            self._release_stale_libcamera()

            picam = Picamera2()

            config = picam.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            picam.configure(config)

            # Set manual focus for stability
            try:
                picam.set_controls({"AfMode": 0})
            except Exception:
                pass

            picam.start()

            # Verify we can actually capture a frame (catches pipeline-busy)
            time.sleep(0.3)
            test_frame = picam.capture_array()
            if test_frame is None or test_frame.size == 0:
                raise Exception("picamera2 started but no frame captured")

            self._picamera2 = picam
            self._use_picamera2 = True
            print(f"[CAMERA] Pi Camera Module 3 via picamera2 (PRIMARY)")
            print(f"[CAMERA] Resolution: {self.width}x{self.height} @ {self.fps}fps | Mirror: {'ON' if self._mirror else 'OFF'}")
            return True

        except Exception as e:
            print(f"[CAMERA] picamera2 failed: {e}")
            self._use_picamera2 = False
            # Clean up partial picamera2 init
            self._safe_release_picamera2()
            return False

    def _try_v4l2(self):
        """Attempt to initialize USB camera via V4L2."""
        try:
            self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
            if self.cap is not None and self.cap.isOpened():
                self._configure_opencv_cap()
                self._use_v4l2 = True
                self._log_opencv_resolution("V4L2", "SECONDARY")
                return True
            else:
                self._safe_release_cap()
                return False
        except Exception as e:
            print(f"[CAMERA] V4L2 failed: {e}")
            return False

    def _try_gstreamer(self):
        """Attempt to initialize camera via GStreamer libcamera pipeline."""
        try:
            gst_pipeline = (
                f"libcamerasrc ! "
                f"video/x-raw,width={self.width},height={self.height},"
                f"framerate={self.fps}/1 ! "
                f"videoconvert ! appsink"
            )
            self.cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)

            if self.cap is not None and self.cap.isOpened():
                self._use_gstreamer = True
                print(f"[CAMERA] Pi Camera via GStreamer (FALLBACK)")
                print(f"[CAMERA] Resolution: {self.width}x{self.height} @ {self.fps}fps")
                return True
            else:
                self._safe_release_cap()
                return False
        except Exception as e:
            print(f"[CAMERA] GStreamer failed: {e}")
            return False

    def _release_stale_libcamera(self):
        """
        Kill stale libcamera processes that may hold /dev/video* busy.
        This prevents 'Pipeline handler in use by another process' errors.
        Only runs on Linux.
        """
        if platform.system().lower() != "linux":
            return

        try:
            import subprocess
            # Find any orphaned libcamera/picamera2 processes (not our PID)
            import os
            our_pid = os.getpid()

            result = subprocess.run(
                ["pgrep", "-f", "libcamera"],
                capture_output=True, text=True, timeout=3
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid_str in pids:
                    pid = int(pid_str.strip())
                    if pid != our_pid:
                        try:
                            os.kill(pid, 9)
                            print(f"[CAMERA] Killed stale libcamera process {pid}")
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            pass
                time.sleep(0.5)  # Allow kernel to release device
        except Exception:
            pass  # Best-effort cleanup

    def _configure_opencv_cap(self):
        """Apply standard settings to an OpenCV VideoCapture."""
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        try:
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            self.cap.set(cv2.CAP_PROP_FOCUS, 40)
        except Exception:
            pass

    def _log_opencv_resolution(self, backend_name, priority):
        """Log actual resolved camera resolution."""
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = int(self.cap.get(cv2.CAP_PROP_FPS))
        mirror_str = "ON (selfie mode)" if self._mirror else "OFF"
        print(f"[CAMERA] {backend_name} camera ({priority})")
        print(f"[CAMERA] Resolution: {actual_w}x{actual_h} @ {actual_fps}fps | Mirror: {mirror_str}")

    def _safe_release_cap(self):
        """Release OpenCV capture without raising."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _safe_release_picamera2(self):
        """
        Fully release picamera2 resources.
        CRITICAL: Must call both stop() AND close() to release /dev/video*.
        Without close(), the camera device stays locked and rpicam-hello fails.
        """
        if self._picamera2 is not None:
            try:
                self._picamera2.stop()
            except Exception:
                pass
            try:
                self._picamera2.close()
            except Exception:
                pass
            self._picamera2 = None
        self._use_picamera2 = False

    # =========================
    # AUTO-INITIALIZE FROM NETWORK
    # =========================
    def auto_initialize_from_network(self, detected_ip):
        """
        Auto-initialize camera when ASP.NET detects camera at a network IP.

        Called by the ASP.NET integration layer when a camera is detected
        at an IP like 192.168.100.101 or 192.168.100.2.

        The method matches the IP against the configured camera subnet
        (default: 192.168.100.*) and triggers initialization if:
        1. The IP matches the subnet
        2. The camera is not already running
        3. No other auto-init is in progress

        Args:
            detected_ip: IP address string (e.g., "192.168.100.101")

        Returns:
            True if camera was successfully initialized, False otherwise
        """
        if not detected_ip:
            return False

        # Match against subnet (e.g., "192.168.100.*")
        if not self._ip_matches_camera_subnet(detected_ip):
            print(f"[CAMERA AUTO] IP {detected_ip} does not match camera subnet {self._camera_subnet}.*")
            return False

        # Already running — no need to reinitialize
        if self.running and self._initialized:
            print(f"[CAMERA AUTO] Already running — ignoring detection at {detected_ip}")
            return True

        # Prevent concurrent initialization
        if not self._auto_init_lock.acquire(blocking=False):
            print(f"[CAMERA AUTO] Initialization already in progress")
            return False

        try:
            self._auto_init_in_progress = True
            print(f"[CAMERA AUTO] Camera detected at {detected_ip} — initializing...")

            # Stop existing capture if partially initialized
            if self._initialized or self.running:
                self.stop()
                time.sleep(0.5)

            # Initialize and start
            if self.initialize():
                self.start()
                print(f"[CAMERA AUTO] Successfully started from network detection at {detected_ip}")
                return True
            else:
                print(f"[CAMERA AUTO] Failed to initialize camera from {detected_ip}")
                return False

        except Exception as e:
            print(f"[CAMERA AUTO] Error during auto-init: {e}")
            return False

        finally:
            self._auto_init_in_progress = False
            self._auto_init_lock.release()

    def _ip_matches_camera_subnet(self, ip):
        """
        Check if an IP address matches the camera subnet.
        Supports exact subnet prefix matching.
        e.g., "192.168.100.101" matches subnet "192.168.100"
        """
        if not ip:
            return False

        # Clean the IP string
        ip = ip.strip()

        # Simple prefix match: "192.168.100.X" starts with "192.168.100."
        return ip.startswith(self._camera_subnet + ".")

    def set_camera_subnet(self, subnet):
        """
        Configure the subnet used for auto-detection matching.
        e.g., set_camera_subnet("192.168.1") for 192.168.1.* range
        """
        self._camera_subnet = subnet
        print(f"[CAMERA] Camera subnet set to {subnet}.*")

    def start(self):
        """Start camera capture thread and wait for first frame (warm-up)."""
        if self.running:
            return

        self.running = True

        # Drain stale buffered frames from camera driver
        if self.cap is not None and not self._use_picamera2:
            for _ in range(5):
                try:
                    self.cap.read()
                except Exception:
                    break

        threading.Thread(target=self._loop, daemon=True).start()

        # Warm-up: wait for first live frame
        print("[CAMERA] Warming up...")
        if self._frame_ready.wait(timeout=3.0):
            print("[CAMERA] Stream ready — first frame captured")
        else:
            print("[CAMERA] Warm-up timeout — stream may start with delay")

    def _loop(self):
        """
        Continuous capture loop.

        CRITICAL: Writes ONLY to self._raw_frame. NEVER writes to _processed_frame.
        WATCHDOG: Auto-restarts camera on sustained frame failure.
        FALLBACK ESCALATION: If picamera2 watchdog fails repeatedly, switch to V4L2.
        """
        _frame_count = 0
        _consecutive_failures = 0
        _max_failures = 30       # ~3 seconds at 10ms/frame
        _warmup_frames = 10

        while self.running:
            try:
                frame = None

                if self._use_picamera2 and self._picamera2 is not None:
                    frame = self._capture_picamera2()
                elif self.cap is not None:
                    frame = self._capture_opencv()
                else:
                    _consecutive_failures += 1

                # Store valid frames
                if frame is not None:
                    with self._lock:
                        self._raw_frame = frame
                        self.frame = frame
                    self._frame_ready.set()
                    _consecutive_failures = 0
                    self._watchdog_restart_failures = 0  # Reset on success
                else:
                    if _frame_count >= _warmup_frames:
                        _consecutive_failures += 1

                # Watchdog: auto-restart on sustained failure
                if _consecutive_failures >= _max_failures:
                    print(f"[CAMERA WATCHDOG] {_consecutive_failures} consecutive failures — restarting...")
                    _consecutive_failures = 0
                    self._restart_capture()

            except Exception as e:
                self._log_error(f"Loop critical error: {e}")
                _consecutive_failures += 1

            _frame_count += 1

            # Fast fill for first frames, then cap at ~100fps
            if _frame_count > _warmup_frames:
                time.sleep(0.01)

    def _capture_picamera2(self):
        """Capture from Pi Camera Module 3. Returns BGR frame or None."""
        try:
            frame = self._picamera2.capture_array()
            if frame is None or frame.size == 0:
                return None
            # picamera2 returns RGB, convert to BGR for OpenCV
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        except Exception as e:
            self._log_error(f"picamera2 capture: {e}")
            return None

    def _capture_opencv(self):
        """Capture from OpenCV (V4L2/GStreamer/DirectShow). Returns BGR frame or None."""
        try:
            ret, frame = self.cap.read()
            if not ret or frame is None or frame.size == 0:
                return None
            if self._mirror:
                frame = cv2.flip(frame, 1)
            return frame
        except Exception as e:
            self._log_error(f"OpenCV capture: {e}")
            return None

    def _log_error(self, msg):
        """Log error once per unique message to prevent spam."""
        if msg != self._last_error_msg:
            print(f"[CAMERA] {msg}")
            self._last_error_msg = msg
            self._error_count = 1
        else:
            self._error_count += 1
            # Log every 100th repeat
            if self._error_count % 100 == 0:
                print(f"[CAMERA] {msg} (x{self._error_count})")

    def _restart_capture(self):
        """
        Watchdog restart: release and re-initialize camera capture.
        Handles safe cleanup for picamera2, V4L2, and GStreamer.
        Escalates from picamera2 to V4L2 after repeated failures.
        """
        try:
            if self._use_picamera2:
                self._watchdog_restart_failures += 1

                if self._watchdog_restart_failures >= self._watchdog_max_before_fallback:
                    # Escalate: picamera2 is consistently failing, try V4L2
                    print(f"[CAMERA WATCHDOG] picamera2 failed {self._watchdog_restart_failures} restarts — escalating to V4L2")
                    self._safe_release_picamera2()

                    if self._try_v4l2():
                        print("[CAMERA WATCHDOG] Successfully fell back to V4L2")
                        self._watchdog_restart_failures = 0
                        return
                    elif self._try_gstreamer():
                        print("[CAMERA WATCHDOG] Successfully fell back to GStreamer")
                        self._watchdog_restart_failures = 0
                        return
                    else:
                        print("[CAMERA WATCHDOG] All fallbacks failed")
                else:
                    self._restart_picamera2()
            else:
                self._restart_opencv()
        except Exception as e:
            print(f"[CAMERA WATCHDOG] Restart failed: {e}")

    def _restart_picamera2(self):
        """Safe restart for picamera2."""
        try:
            if self._picamera2 is not None:
                self._picamera2.stop()
                time.sleep(0.5)
        except Exception as e:
            print(f"[CAMERA WATCHDOG] Error stopping picamera2: {e}")

        try:
            if self._picamera2 is not None:
                self._picamera2.start()
                print("[CAMERA WATCHDOG] picamera2 restarted")
            else:
                print("[CAMERA WATCHDOG] picamera2 instance lost")
                self._use_picamera2 = False
        except Exception as e:
            print(f"[CAMERA WATCHDOG] Failed to restart picamera2: {e}")
            self._use_picamera2 = False

    def _restart_opencv(self):
        """Safe restart for OpenCV capture."""
        self._safe_release_cap()
        time.sleep(0.5)

        backend = "OpenCV"
        if self._use_v4l2:
            self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
            backend = "V4L2"
        elif self._use_gstreamer:
            gst_pipeline = (
                f"libcamerasrc ! "
                f"video/x-raw,width={self.width},height={self.height},"
                f"framerate={self.fps}/1 ! "
                f"videoconvert ! appsink"
            )
            self.cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
            backend = "GStreamer"
        else:
            self.cap = cv2.VideoCapture(self.camera_id)
            backend = "OpenCV"

        if self.cap is not None and self.cap.isOpened():
            self._configure_opencv_cap()
            print(f"[CAMERA WATCHDOG] {backend} capture restarted")
        else:
            print(f"[CAMERA WATCHDOG] Failed to reopen {backend} camera")

    # =========================
    # FRAME ACCESS (THREAD-SAFE)
    # =========================
    def get_frame(self):
        """
        Get raw frame for AI processing.
        Returns a COPY so the caller can draw on it without affecting capture.
        """
        with self._lock:
            if self._raw_frame is None:
                return None
            return self._raw_frame.copy()

    def set_processed_frame(self, frame):
        """
        Set the AI-processed frame (with overlays).
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
        Returns processed frame (with overlays) if available, else raw.
        Returns a COPY to prevent encoder interference.
        """
        with self._lock:
            if self._has_processed and self._processed_frame is not None:
                return self._processed_frame.copy()
            if self._raw_frame is not None:
                return self._raw_frame.copy()
            return None

    # =========================
    # STOP
    # =========================
    def stop(self):
        """
        Stop camera safely — prevents segmentation faults.

        CRITICAL for Raspberry Pi 5:
        - picamera2.stop() halts the capture pipeline
        - picamera2.close() releases /dev/video* file descriptors
        - Without close(), rpicam-hello will fail with "Pipeline handler in use"
        - Small sleep allows capture loop thread to exit before releasing hardware
        """
        self.running = False
        time.sleep(0.2)  # Allow capture loop to exit cleanly

        # Release picamera2 fully (stop + close)
        if self._use_picamera2 and self._picamera2 is not None:
            try:
                self._picamera2.stop()
                print("[CAMERA] picamera2 stopped")
            except Exception as e:
                print(f"[CAMERA] Error stopping picamera2: {e}")

            try:
                self._picamera2.close()
                print("[CAMERA] picamera2 closed (device released)")
            except Exception as e:
                print(f"[CAMERA] Error closing picamera2: {e}")

            self._picamera2 = None

        # Release OpenCV capture
        self._safe_release_cap()
        if self.cap is None:
            print("[CAMERA] Capture released")

        # Reset state
        self._initialized = False
        self._use_picamera2 = False
        self._use_v4l2 = False
        self._use_gstreamer = False
        self._frame_ready.clear()
        self._watchdog_restart_failures = 0