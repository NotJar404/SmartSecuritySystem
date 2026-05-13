import time
import threading
import requests
import uuid
import os
import cv2
import numpy as np
import json
import queue
from datetime import datetime, timedelta
from collections import defaultdict, deque
from flask import Flask, Response

from Sensors.camera_module import CameraModule
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier
from AI.person_detector import PersonDetector
from AI.person_tracker import CentroidTracker
from AI.overlay_renderer import render_full_frame
from Sensors.rfid_reader import RFIDReader
from Sensors.pir_sensor import PIRSensor
from Sensors.lock_sensor import SolenoidLock
from Sensors.hardware import Buzzer, RGBLed, DoorSensor


# =========================
# FSM STATE CONSTANTS
# =========================
STATE_IDLE = "IDLE"
STATE_ACCESS = "ACCESS"
STATE_INSIDE = "INSIDE"
STATE_ALERT = "ALERT"
STATE_LOITERING = "LOITERING"
STATE_LOCKDOWN = "LOCKDOWN"
STATE_EMERGENCY = "EMERGENCY"


class SmartSecuritySystem:
    """
    State-Based Intelligent Security System

    Architecture:
    - FSM-driven (NOT frame-driven)
    - Session-based occupancy tracking
    - Anti-spam database writes
    - Hybrid: works on Raspberry Pi AND laptop webcam

    FSM States:
        IDLE â†’ ACCESS â†’ INSIDE â†’ LOITERING â†’ (EXIT â†’ IDLE)
                  â†“                    â†“
                ALERT              ALERT
    """

    def __init__(self, use_simulated_rfid=False,
                 api_url="http://localhost:5145/api/access/rfid",
                 base_url="http://localhost:5145",
                 camera_id=1,
                 room_id=1,
                 max_stay_minutes=20,
                 room_max_capacity=0,
                 operating_hours_start=None,
                 operating_hours_end=None):

        # =========================
        # HARDWARE MODULES
        # =========================
        self.camera = CameraModule(camera_id=0)
        self.face_detector = FaceDetector()
        self.face_verifier = FaceVerifier(storage_dir="face_data")
        self.person_detector = PersonDetector(
            confidence_threshold=0.5,
            model_dir=os.path.join(os.path.dirname(__file__), "models")
        )
        self.person_tracker = CentroidTracker(
            max_disappeared=30,
            max_distance=80
        )
        self.rfid_reader = RFIDReader()
        self.pir_sensor = PIRSensor()
        self.solenoid_lock = SolenoidLock()
        self.buzzer = Buzzer()
        self.rgb_led = RGBLed()
        self.door_sensor = DoorSensor()

        # =========================
        # TRACKED PERSONS (person detection state)
        # =========================
        self.tracked_persons = {}  # {track_id: TrackedPerson}
        self._person_session_map = {}  # {track_id: session_user_id}

        # =========================
        # CONFIGURATION
        # =========================
        self.use_simulated_rfid = use_simulated_rfid
        self.api_url = api_url
        self.base_url = base_url
        self.camera_id = camera_id
        self.room_id = room_id
        self.is_running = False

        # =========================
        # FSM STATE
        # =========================
        self.system_state = STATE_IDLE
        self.state_lock = threading.Lock()

        # =========================
        # SESSION-BASED OCCUPANCY TRACKING
        # Key: user_id (str)
        # Value: {
        #     "session_id": str (UUID),
        #     "entry_time": float (timestamp),
        #     "last_active": float (timestamp),
        #     "status": str (INSIDE / LOITERING),
        #     "rfid_uid": str
        # }
        # =========================
        self.active_sessions = {}
        self.session_lock = threading.Lock()

        # =========================
        # RFID COOLDOWN (prevent double-swipe spam)
        # =========================
        self.last_rfid_time = None
        self.rfid_cooldown = 10  # seconds
        self.rfid_active_window = 5

        # =========================
        # CAMERA ANTI-SPAM
        # =========================
        self.face_debounce_cooldown = 5.0   # seconds between same detection type pushes
        self.last_face_event_time = 0
        self.last_detection_state = None
        self.face_confidence_threshold = 0.70  # 70% minimum for verification
        self.current_occupancy = 0

        # =========================
        # OCCUPANCY SMOOTHING (BUG-9 FIX)
        # Median filter over N frames to reject single-frame flicker
        # =========================
        self._occupancy_buffer = []
        self._occupancy_buffer_size = 5

        # =========================
        # OCCUPANCY PUSH RATE LIMITING (existing behavior preserved)
        # =========================
        self.last_occupancy_push = 0
        self.occupancy_push_interval = 3

        # =========================
        # DETECTION PUSH RATE LIMITING (existing behavior preserved)
        # =========================
        self.last_detection_push = 0
        self.detection_push_interval = 2

        # =========================
        # ALERT COOLDOWN (existing behavior preserved)
        # =========================
        self.last_alert_push = 0
        self.alert_cooldown = 10

        # =========================
        # IDLE GRACE PERIOD (BUG-1 FIX)
        # Require sustained face detection before ALERT
        # =========================
        self._idle_face_counter = 0
        self._idle_grace_threshold = 5  # consecutive frames (~150ms)

        # =========================
        # ALERT AUTO-CLEAR (BUG-2 FIX)
        # Return to IDLE if presence clears
        # =========================
        self._alert_start_time = None
        self._alert_auto_clear_timeout = 30  # seconds

        # =========================
        # ENTRY WINDOW FOR TAILGATING (BUG-10 FIX)
        # =========================
        self._last_unlock_time = None
        self._entry_window_duration = 8  # seconds after door unlock
        self._tailgate_counter = 0

        # =========================
        # SUSTAINED EMPTY FRAME CHECK (BUG-11 FIX)
        # =========================
        self._empty_frame_counter = 0
        self._empty_frame_threshold = 10  # consecutive frames

        # =========================
        # LOITERING THRESHOLDS (REALISTIC HUMAN BEHAVIOR)
        # =========================
        self.loiter_suspicion_threshold = 600    # 10 minutes â€” suspicion phase
        self.loiter_critical_threshold = 1200    # 20 minutes â€” critical loitering
        self.pir_inactivity_threshold = 300      # 5 minutes PIR silence = suspicious

        # =========================
        # INDOOR MONITORING CONFIG (NO DB COLUMNS â€” all in Python config)
        # =========================
        self.max_stay_minutes = max_stay_minutes              # Per-room stay limit (default 20)
        self.extended_stay_threshold = (max_stay_minutes - 5) * 60  # Warning 5 min before limit
        self.suspicious_idle_threshold = 600                  # 10 min face + no PIR = suspicious

        # =========================
        # ENTRANCE LOITERING CONFIG
        # Graduated response: 5 min â†’ WARNING, 10 min â†’ CRITICAL
        # (Different from INTRUSION which is sustained-frame-based)
        # =========================
        self._entrance_face_start_time = None  # When face first appeared in IDLE
        self.entrance_loiter_warning = 300     # 5 minutes â†’ WARNING
        self.entrance_loiter_critical = 600    # 10 minutes â†’ CRITICAL
        self._entrance_warning_sent = False    # Track if 5-min warning already sent
        self._entrance_critical_sent = False   # Track if 10-min critical already sent

        # =========================
        # AFTER-HOURS CONFIG (operating hours)
        # Set to None to disable after-hours detection
        # =========================
        self.operating_hours_start = operating_hours_start  # e.g., 6 (6 AM)
        self.operating_hours_end = operating_hours_end      # e.g., 22 (10 PM)

        # =========================
        # IN-MEMORY EVENT COOLDOWN (ANTI-SPAM)
        # Key: "event_type:room_id" â†’ last push timestamp
        # Prevents duplicate API calls before they even reach the backend
        # =========================
        self._event_cooldowns = {}
        self._cooldown_durations = {
            "EXTENDED_STAY": 600,        # 10 min between extended stay alerts
            "OCCUPANCY_EXCEEDED": 300,   # 5 min between capacity alerts
            "SUSPICIOUS_IDLE": 900,      # 15 min between idle alerts
            "ENTRANCE_LOITERING": 300,   # 5 min between entrance loitering
            "AFTER_HOURS": 1800,         # 30 min between after-hours alerts
        }

        # =========================
        # OCCUPANCY EXCEEDED TRACKING
        # =========================
        self.room_max_capacity = room_max_capacity  # Max people allowed (0 = disabled)
        self._capacity_exceeded_sent = False

        # =========================
        # EXTENDED STAY TRACKING (per session)
        # =========================
        self._extended_stay_warned = set()  # session_ids that already got warning

        # =========================
        # EXIT INFERENCE (FALLBACK ONLY)
        # =========================
        self.exit_inference_timeout = 1800  # 30 minutes no activity = soft exit

        # =========================
        # RECORDING SYSTEM (MP4/H.264 + pre-buffer + async writer)
        # =========================
        self._is_recording = False
        self._recording_writer = None
        self._recording_path = None
        self._recording_start_time = None
        self._recording_alert_id = None
        self._recording_timeout = 60  # seconds max per recording
        self._recording_dir = "recordings"
        self._recording_post_buffer = 5  # seconds after event ends
        self._recording_post_deadline = None  # when to stop post-buffer
        os.makedirs(self._recording_dir, exist_ok=True)

        # Circular frame buffer for pre-buffer recording (3-5 seconds)
        self._frame_buffer_seconds = 3
        self._frame_buffer_fps = 15
        self._frame_buffer = deque(maxlen=self._frame_buffer_seconds * self._frame_buffer_fps)

        # Async recording writer queue (non-blocking frame writes)
        self._recording_queue = queue.Queue(maxsize=300)
        self._recording_writer_thread = None

        # Recording cleanup config
        self._recording_max_age_days = 7        # Normal recordings
        self._recording_critical_age_days = 30  # Critical alert recordings

        # =========================
        # PIR INTELLIGENCE (CPU optimization)
        # =========================
        self._pir_idle_skip_threshold = 30   # seconds of PIR inactivity before reducing FPS
        self._pir_reduced_fps_sleep = 0.2    # 5 FPS during PIR-idle mode
        self._pir_idle_mode = False           # Current PIR-idle state

        # =========================
        # UNKNOWN RFID ESCALATION TRACKER
        # =========================
        self._unknown_rfid_tracker = {}  # {uid: {count, last_tap, first_tap, locked_out_until}}
        self._unknown_rfid_cooldown = 3  # seconds between same UID taps
        self._unknown_rfid_lockout = 300  # 5 min lockout after alarm

        # =========================
        # PER-UID RFID COOLDOWN (anti-spam)
        # =========================
        self._rfid_per_uid_cooldown = {}  # {uid: last_tap_time}
        self._rfid_per_uid_cooldown_sec = 3  # seconds

        # =========================
        # FACE BUFFER (existing behavior preserved)
        # =========================
        self.last_face_update = 0

        # =========================
        # ALARM SETTINGS (polled from ASP.NET backend)
        # Controls whether buzzer/alerts actually fire
        # =========================
        self._alarm_settings = {
            "intrusion": True,
            "fire": True,
            "earthquake": True,
            "forcedentry": True
        }  # Defaults to all armed; updated by polling thread

        # =========================
        # SYSTEM CONFIG (polled from ASP.NET /api/system/config)
        # Maps 1:1 to UI card settings in System.cshtml
        # =========================
        self._master_armed = True              # Global Settings â†’ Master Arm
        self._hardware_siren_enabled = True    # Alert Protocols â†’ Hardware Siren
        self._gate_hold_open = 5               # Access Control â†’ Gate Hold-Open (seconds)
        self._biometric_lock_enabled = True    # Access Control â†’ Biometric Lock
        self._active_alarm_priority = 0        # Emergency trigger priority tracker

        # =========================
        # API RETRY QUEUE (guaranteed delivery for critical events)
        # =========================
        self._enable_api_retry = os.environ.get("ENABLE_API_RETRY", "true").lower() == "true"
        self._api_retry_queue = queue.Queue()
        self._api_retry_max_attempts = 3
        self._api_retry_delay = 5  # seconds between retries

    # =========================
    # INIT SYSTEM
    # =========================
    def initialize(self):
        print("=" * 50)
        print("[SYSTEM] Smart Security System â€” State-Based FSM")
        print("=" * 50)

        if not self.camera.initialize():
            print("[ERROR] Camera failed to initialize")
            return False

        self.pir_sensor.initialize()
        self.solenoid_lock.initialize()
        self.buzzer.initialize()
        self.rgb_led.initialize()
        self.door_sensor.initialize()

        # Set initial LED state
        self.rgb_led.status_idle()

        print(f"[FSM] Initial state: {self.system_state}")
        print("[SYSTEM] Initialization complete")
        return True

    # =========================
    # START SYSTEM
    # =========================
    def start(self):
        if self.is_running:
            return

        self.is_running = True

        # Start hardware modules
        self.camera.start()
        print("[SYSTEM] Camera started")

        self.pir_sensor.start(callback=self.on_pir_motion)
        print("[SYSTEM] PIR sensor started")

        if not self.use_simulated_rfid:
            self.rfid_reader.start_reading(callback=self.on_rfid_tapped)
            print("[SYSTEM] RFID reader started")

        # Start door sensor monitoring
        self.door_sensor.start(callback=self.on_door_change)
        print("[SYSTEM] Door sensor started")

        # Start FSM loops
        threading.Thread(target=self.main_loop, daemon=True).start()
        print("[SYSTEM] Main FSM loop started")

        threading.Thread(target=self.loitering_monitor, daemon=True).start()
        print("[SYSTEM] Loitering monitor started")

        # Start alarm settings polling (checks DB every 60s)
        threading.Thread(target=self._alarm_settings_poller, daemon=True).start()
        print("[SYSTEM] Alarm settings poller started")

        # Start API retry worker (guaranteed delivery for critical events)
        if self._enable_api_retry:
            threading.Thread(target=self._api_retry_worker, daemon=True).start()
            print("[SYSTEM] API retry worker started")

    # =========================
    # FSM STATE TRANSITION (THREAD-SAFE)
    # =========================
    def set_state(self, new_state):
        """
        Transition the global FSM state.
        Only logs when state actually CHANGES.
        Drives RGB LED on every transition.
        """
        with self.state_lock:
            if self.system_state != new_state:
                old_state = self.system_state
                self.system_state = new_state
                print(f"[FSM] {old_state} â†’ {new_state}")

                # Drive RGB LED based on new state
                if new_state == STATE_IDLE:
                    self.rgb_led.status_idle()
                elif new_state == STATE_ACCESS:
                    self.rgb_led.status_access()
                elif new_state == STATE_INSIDE:
                    self.rgb_led.status_monitoring()
                elif new_state == STATE_ALERT:
                    self.rgb_led.status_alert()
                elif new_state == STATE_LOITERING:
                    self.rgb_led.status_loitering()
                elif new_state == STATE_LOCKDOWN:
                    self.rgb_led.status_alert()  # Red blinking
                elif new_state == STATE_EMERGENCY:
                    self.rgb_led.status_alert()  # Red blinking

    def get_state(self):
        with self.state_lock:
            return self.system_state

    # =========================
    # IN-MEMORY EVENT COOLDOWN GATE
    # Prevents spam before even hitting the REST API
    # =========================
    def _can_push_event(self, event_type, now=None):
        """Check if enough time has passed since last push of this event type."""
        now = now or time.time()
        key = f"{event_type}:{self.room_id}"
        cooldown = self._cooldown_durations.get(event_type, 300)
        last_push = self._event_cooldowns.get(key, 0)

        if (now - last_push) >= cooldown:
            self._event_cooldowns[key] = now
            return True
        return False

    # =========================
    # AFTER-HOURS CHECK HELPER
    # =========================
    def _is_after_hours(self):
        """Check if current time is outside operating hours."""
        if self.operating_hours_start is None or self.operating_hours_end is None:
            return False  # No schedule configured = always operating

        current_hour = datetime.now().hour
        return current_hour < self.operating_hours_start or current_hour >= self.operating_hours_end

    # =========================
    # MAIN LOOP (STATE-DRIVEN, NOT FRAME-DRIVEN)
    # =========================
    def main_loop(self):
        # Render debug counters
        self._render_debug_time = 0
        self._render_box_total = 0
        self._render_frame_total = 0

        while self.is_running:
            try:
                frame = self.camera.get_frame()

                if frame is None:
                    if not hasattr(self, '_null_frame_warned'):
                        print("[DEBUG] Frame is None — camera not delivering frames yet")
                        self._null_frame_warned = True
                    time.sleep(0.05)
                    continue
                elif not hasattr(self, '_first_frame_logged'):
                    print(f"[DEBUG] First frame received! Shape: {frame.shape}")
                    self._first_frame_logged = True

                # =========================
                # POPULATE FRAME BUFFER (for pre-buffer recording)
                # O(1) deque append — zero CPU impact
                # =========================
                self._frame_buffer.append(frame.copy())

                # =========================
                # MASTER ARM CHECK — skip detection if disarmed
                # Still streams video but no AI processing
                # =========================
                if not self._master_armed:
                    frame, _ = render_full_frame(
                        frame, state='IDLE', occupancy=0, armed=False
                    )
                    self.camera.set_processed_frame(frame)
                    time.sleep(0.1)
                    continue

                # =========================
                # PIR-ASSISTED INFERENCE SKIPPING (CPU optimization)
                # In IDLE with no PIR motion for 30+s: reduce to ~5 FPS
                # Instant wake when PIR detects motion
                # =========================
                current_state_check = self.get_state()
                if current_state_check == STATE_IDLE and not self.pir_sensor.is_motion_detected():
                    if self.pir_sensor.get_inactivity_duration() > self._pir_idle_skip_threshold:
                        if not self._pir_idle_mode:
                            self._pir_idle_mode = True
                            print("[PIR] Idle mode — reducing inference to ~5 FPS")
                        # Still render HUD but skip heavy detection
                        frame, _ = render_full_frame(
                            frame, state='IDLE', occupancy=0, armed=self._master_armed
                        )
                        self.camera.set_processed_frame(frame)
                        time.sleep(self._pir_reduced_fps_sleep)
                        continue
                elif self._pir_idle_mode:
                    self._pir_idle_mode = False
                    print("[PIR] Motion detected — resuming full inference")

                # =========================
                # DUAL-MODE DETECTION
                # IDLE/ACCESS: Face detection (entrance monitoring + RFID verify)
                # INSIDE/LOITERING/ALERT: Person detection + tracking (room monitoring)
                # =========================
                now = time.time()
                current_state = self.get_state()
                faces = []
                face_images = []

                if current_state in (STATE_INSIDE, STATE_LOITERING, STATE_ALERT):
                    # =========================
                    # INSIDE/LOITERING/ALERT MODE: Person detection + tracking
                    # Keeps tracking during ALERT so bounding boxes don't vanish
                    # =========================
                    person_detections = self.person_detector.detect_persons(frame)
                    self.tracked_persons = self.person_tracker.update(person_detections, frame)

                    # Update authorization status for each tracked person
                    self._update_person_authorization()

                    raw_occupancy = self.person_tracker.get_active_count()

                    # Still run face detection at reduced rate for face buffer
                    # (needed if someone new taps RFID while in INSIDE state)
                    if now - self.last_face_update > 2:
                        faces, face_images = self.face_detector.detect_faces(frame)
                else:
                    # =========================
                    # IDLE/ACCESS MODE: Face detection
                    # =========================
                    faces, face_images = self.face_detector.detect_faces(frame)
                    raw_occupancy = len(faces)

                    # Debug: periodically log detection stats
                    if not hasattr(self, '_last_debug_log'):
                        self._last_debug_log = 0
                    if now - self._last_debug_log > 5:
                        blur = self.face_detector.last_blur_score
                        print(f"[DEBUG] Blur: {blur:.1f} | Faces: {len(faces)} | State: {current_state}")
                        self._last_debug_log = now

                # =========================
                # OCCUPANCY SMOOTHING (BUG-9 FIX)
                # Use median of last N frames to reject flicker
                # =========================
                self._occupancy_buffer.append(raw_occupancy)
                if len(self._occupancy_buffer) > self._occupancy_buffer_size:
                    self._occupancy_buffer.pop(0)
                self.current_occupancy = sorted(self._occupancy_buffer)[len(self._occupancy_buffer) // 2]

                # =========================
                # UPDATE PIR ACTIVITY ON DETECTION
                # (Camera supplements PIR for inactivity tracking)
                # =========================
                if self.current_occupancy > 0 and self.pir_sensor.simulated:
                    self.pir_sensor.simulate_motion()

                # =========================
                # UNIFIED OVERLAY RENDERING
                # Single call replaces ALL inline bounding box + HUD drawing.
                # render_full_frame handles: HUD, person boxes, face boxes,
                # corner accents, labels, REC indicator — everything.
                # =========================
                with self.session_lock:
                    session_count = len(self.active_sessions)

                frame, boxes_rendered = render_full_frame(
                    frame,
                    state=current_state,
                    occupancy=self.current_occupancy,
                    sessions=session_count,
                    tracked_persons=self.tracked_persons if current_state in (STATE_INSIDE, STATE_LOITERING, STATE_ALERT) else None,
                    faces=faces if current_state in (STATE_IDLE, STATE_ACCESS) else None,
                    is_recording=self._is_recording,
                    armed=self._master_armed
                )

                # === SET PROCESSED FRAME IMMEDIATELY after rendering ===
                # This is the CRITICAL fix: the processed frame with overlays
                # is set BEFORE any state processing to prevent the stream
                # from serving a raw frame.
                self.camera.set_processed_frame(frame)

                # Render debug logging (every 5 seconds)
                self._render_frame_total += 1
                self._render_box_total += boxes_rendered
                if now - self._render_debug_time > 5:
                    avg_boxes = self._render_box_total / max(1, self._render_frame_total)
                    tracked_count = len(self.tracked_persons)
                    print(f"[RENDER] State: {current_state} | "
                          f"Boxes/frame: {avg_boxes:.1f} | "
                          f"Tracked: {tracked_count} | "
                          f"Faces: {len(faces)} | "
                          f"FPS: {self._render_frame_total / 5:.1f}")
                    self._render_debug_time = now
                    self._render_box_total = 0
                    self._render_frame_total = 0

                # =========================
                # OCCUPANCY PUSH (rate-limited, preserves existing behavior)
                # =========================
                if now - self.last_occupancy_push > self.occupancy_push_interval:
                    self.push_occupancy()
                    self.last_occupancy_push = now

                # =========================
                # STATE-DRIVEN DETECTION LOGIC
                # =========================
                if current_state == STATE_IDLE:
                    self._handle_idle_detection(faces, face_images, now)

                elif current_state == STATE_INSIDE:
                    self._handle_inside_monitoring(faces, face_images, now)

                elif current_state == STATE_ALERT:
                    self._handle_alert_state(frame, now)

                # =========================
                # DETECTION STATE PUSH (ANTI-SPAM: state-change only)
                # =========================
                detection_state = self._compute_detection_state(faces, face_images)

                if detection_state != self.last_detection_state:
                    if now - self.last_face_event_time > self.face_debounce_cooldown:
                        self._push_detection_state(detection_state, faces, now)
                        self.last_detection_state = detection_state
                        self.last_face_event_time = now

                # =========================
                # FACE BUFFER (preserved from original)
                # =========================
                if face_images and (now - self.last_face_update > 1):
                    self.face_verifier.store_detected_face(face_images[0])
                    self.last_face_update = now

                # =========================
                # AUTO-EXIT: Update FSM if room is empty (BUG-11 FIX)
                # Require sustained empty frames, not single blurry frame
                # =========================
                if current_state in (STATE_INSIDE, STATE_LOITERING):
                    if self.current_occupancy == 0:
                        self._empty_frame_counter += 1
                        if self._empty_frame_counter >= self._empty_frame_threshold:
                            with self.session_lock:
                                if len(self.active_sessions) == 0:
                                    self.set_state(STATE_IDLE)
                                    self._empty_frame_counter = 0
                    else:
                        self._empty_frame_counter = 0

                time.sleep(0.03)

            except Exception as e:
                import traceback
                print(f"[MAIN LOOP ERROR] {e}")
                traceback.print_exc()
                time.sleep(0.1)

    # =========================
    # PERSON AUTHORIZATION LOGIC
    # Determines if tracked persons are authorized based on RFID sessions
    # =========================
    def _update_person_authorization(self):
        """
        Assign authorization status to each tracked person.

        Rules:
        1. If tracked_count <= session_count â†’ all persons are 'authorized'
        2. If tracked_count > session_count â†’ excess are 'unauthorized'
        3. New persons during entry window â†’ 'unknown' (grace period)
        """
        with self.session_lock:
            session_count = len(self.active_sessions)

        tracked_count = self.person_tracker.get_active_count()
        now = time.time()

        # Check if we're in the entry window (recent door unlock)
        in_entry_window = (
            self._last_unlock_time is not None
            and (now - self._last_unlock_time) < self._entry_window_duration
        )

        if tracked_count <= session_count:
            # Everyone accounted for â€” all authorized
            for person in self.tracked_persons.values():
                if person.disappeared == 0:
                    person.status = 'authorized'
        else:
            # More people than sessions â€” some are unauthorized
            authorized_count = 0
            for person in self.tracked_persons.values():
                if person.disappeared > 0:
                    continue

                if authorized_count < session_count:
                    person.status = 'authorized'
                    authorized_count += 1
                elif in_entry_window:
                    # During entry window: give benefit of doubt
                    person.status = 'unknown'
                else:
                    # Outside entry window: mark as unauthorized
                    person.status = 'unauthorized'

    def get_tracked_persons_info(self):
        """
        Return tracked person metadata for API/UI consumption.
        Used by Camera.cshtml tracked persons panel.
        """
        result = []
        with self.session_lock:
            sessions_list = list(self.active_sessions.values())

        for track_id, person in self.tracked_persons.items():
            if person.disappeared > 0:
                continue

            # Try to find associated session
            session = None
            person_name = "Unknown"
            entry_time = None
            session_id = None

            if person.status == 'authorized' and sessions_list:
                # Associate with first available session
                idx = min(track_id, len(sessions_list) - 1)
                if idx < len(sessions_list):
                    session = sessions_list[idx]
                    session_id = session.get("session_id")
                    entry_time = session.get("entry_time")
                    person_name = f"Session-{session.get('rfid_uid', 'Unknown')}"

            result.append({
                'trackId': track_id,
                'bbox': list(person.bbox),
                'status': person.status,
                'personName': person_name,
                'sessionId': session_id,
                'entryTime': entry_time,
                'confidence': round(person.confidence * 100, 1) if person.confidence else 0
            })

        return result

    # =========================
    # IDLE DETECTION: Graduated Entrance Response
    # Phase 1: Entrance Loitering (5 min WARNING, 10 min CRITICAL)
    # Phase 2: Intrusion (sustained frames without ANY RFID)
    # =========================
    def _handle_idle_detection(self, faces, face_images, now):
        """
        In IDLE mode (camera default = monitoring entrance area):

        When a face is detected without RFID:
        1. Track how long the face has been present
        2. After 5 min â†’ ENTRANCE_LOITERING (WARNING)
        3. After 10 min â†’ ENTRANCE_LOITERING (CRITICAL)
        4. Sustained frames without time check â†’ INTRUSION (existing behavior)

        This graduated response prevents false intrusion alerts from
        people simply walking past or briefly pausing near the entrance.
        """
        if self.current_occupancy > 0:
            # Check if any RFID was recently scanned
            if self.last_rfid_time is None or (now - self.last_rfid_time) > self.rfid_active_window:

                # ========================================
                # PHASE 1: Track entrance presence duration
                # ========================================
                if self._entrance_face_start_time is None:
                    self._entrance_face_start_time = now

                entrance_duration = now - self._entrance_face_start_time

                # 10 min â†’ CRITICAL entrance loitering
                if entrance_duration >= self.entrance_loiter_critical and not self._entrance_critical_sent:
                    if self._can_push_event("ENTRANCE_LOITERING", now):
                        self.push_state_transition(
                            event="ENTRANCE_LOITERING",
                            session_id=str(uuid.uuid4()),
                            description=f"Person lingering at entrance for {entrance_duration/60:.0f} min without RFID",
                            severity="HIGH"
                        )
                        self._entrance_critical_sent = True
                        print(f"[ENTRANCE] CRITICAL loitering: {entrance_duration/60:.1f} min")

                # 5 min â†’ WARNING entrance loitering
                elif entrance_duration >= self.entrance_loiter_warning and not self._entrance_warning_sent:
                    if self._can_push_event("ENTRANCE_LOITERING", now):
                        self.push_state_transition(
                            event="ENTRANCE_LOITERING",
                            session_id=str(uuid.uuid4()),
                            description=f"Person lingering at entrance for {entrance_duration/60:.0f} min without RFID",
                            severity="WARNING"
                        )
                        self._entrance_warning_sent = True
                        print(f"[ENTRANCE] WARNING loitering: {entrance_duration/60:.1f} min")

                # ========================================
                # PHASE 2: Sustained-frame intrusion check (existing behavior)
                # ========================================
                self._idle_face_counter += 1

                # Only alert after SUSTAINED detection
                if self._idle_face_counter >= self._idle_grace_threshold:
                    self.set_state(STATE_ALERT)
                    self._alert_start_time = now
                    self._idle_face_counter = 0

                    session_id = str(uuid.uuid4())
                    self.push_state_transition(
                        event="ALERT",
                        session_id=session_id,
                        alert_type="Intrusion",
                        description="Sustained presence detected without RFID authentication",
                        severity="HIGH"
                    )

                    # Start recording on intrusion
                    self._start_recording(session_id)

                    # Hardware feedback: alarm via emergency trigger system
                    self.trigger_emergency(
                        "intrusion", duration=10,
                        session_id=session_id,
                        description="Sustained presence detected without RFID authentication"
                    )

                    # Reset entrance tracking (escalated to full intrusion)
                    self._entrance_face_start_time = None
                    self._entrance_warning_sent = False
                    self._entrance_critical_sent = False
            else:
                self._idle_face_counter = 0  # RFID was recent, reset
                # Reset entrance tracking (RFID resolved the situation)
                self._entrance_face_start_time = None
                self._entrance_warning_sent = False
                self._entrance_critical_sent = False
        else:
            self._idle_face_counter = 0  # No face, reset
            # Reset entrance tracking (person left)
            self._entrance_face_start_time = None
            self._entrance_warning_sent = False
            self._entrance_critical_sent = False

    # =========================
    # ALERT STATE HANDLER (BUG-2 FIX)
    # Auto-clears + handles recording
    # =========================
    def _handle_alert_state(self, frame, now):
        """
        In ALERT mode:
        - Write frames to recording asynchronously if active
        - Auto-clear after timeout if no presence
        - DO NOT block main loop (overlays must render in real-time)
        """
        # Write to recording via async queue (non-blocking)
        if self._is_recording:
            try:
                self._recording_queue.put_nowait(frame.copy())
            except queue.Full:
                pass  # Drop frame rather than block main loop

            # Check recording timeout
            if (now - self._recording_start_time) > self._recording_timeout:
                self._stop_recording()

        # Auto-clear ALERT after timeout if no one is present
        if self._alert_start_time:
            elapsed = now - self._alert_start_time
            if elapsed > self._alert_auto_clear_timeout:
                if self.current_occupancy == 0:
                    self._stop_recording()
                    self.set_state(STATE_IDLE)
                    self._alert_start_time = None
                    print("[FSM] ALERT auto-cleared (no presence)")

    # =========================
    # INSIDE MONITORING: Full Indoor Surveillance
    # Tailgating + Occupancy + Extended Stay + Suspicious Idle + After-Hours
    # =========================
    def _handle_inside_monitoring(self, faces, face_images, now):
        """
        In INSIDE mode: Comprehensive indoor behavioral monitoring.

        Events detected:
        1. TAILGATING â€” occupancy > sessions (existing, preserved)
        2. OCCUPANCY EXCEEDED â€” people count > room max capacity
        3. EXTENDED STAY WARNING â€” approaching stay time limit
        4. SUSPICIOUS IDLE â€” face detected + PIR no motion for 10+ min
        5. AFTER-HOURS PRESENCE â€” person in room outside operating hours
        """
        with self.session_lock:
            expected_count = len(self.active_sessions)
            sessions_snapshot = dict(self.active_sessions)

        # ========================================
        # 1. TAILGATING DETECTION (existing â€” preserved exactly)
        # ========================================
        if self.current_occupancy > expected_count and expected_count > 0:
            # Determine if we're in the entry window
            in_entry_window = (
                self._last_unlock_time is not None
                and (now - self._last_unlock_time) < self._entry_window_duration
            )

            if in_entry_window:
                # During entry window: more likely real tailgating
                if now - self.last_alert_push > self.alert_cooldown:
                    session_id = str(uuid.uuid4())
                    self.push_state_transition(
                        event="ALERT",
                        session_id=session_id,
                        alert_type="SuspiciousActivity",
                        description=f"Tailgating suspected during entry: {self.current_occupancy} people, {expected_count} sessions",
                        severity="WARNING"
                    )
                    self.last_alert_push = now
                    self._start_recording(session_id)
            else:
                # Outside entry window: require sustained mismatch
                self._tailgate_counter += 1
                if self._tailgate_counter >= 3:
                    if now - self.last_alert_push > self.alert_cooldown:
                        session_id = str(uuid.uuid4())
                        self.push_state_transition(
                            event="ALERT",
                            session_id=session_id,
                            alert_type="SuspiciousActivity",
                            description=f"Sustained occupancy mismatch: {self.current_occupancy} people, {expected_count} sessions",
                            severity="INFO"
                        )
                        self.last_alert_push = now
                    self._tailgate_counter = 0
        else:
            self._tailgate_counter = 0

        # ========================================
        # 2. OCCUPANCY EXCEEDED (room over max capacity)
        # ========================================
        if self.room_max_capacity > 0 and self.current_occupancy > self.room_max_capacity:
            if not self._capacity_exceeded_sent:
                if self._can_push_event("OCCUPANCY_EXCEEDED", now):
                    self.push_state_transition(
                        event="OCCUPANCY_EXCEEDED",
                        session_id=str(uuid.uuid4()),
                        description=f"Room capacity exceeded: {self.current_occupancy}/{self.room_max_capacity} people"
                    )
                    self._capacity_exceeded_sent = True
                    print(f"[MONITOR] Occupancy exceeded: {self.current_occupancy}/{self.room_max_capacity}")
        else:
            # Reset when occupancy drops back below capacity
            self._capacity_exceeded_sent = False

        # ========================================
        # 3. EXTENDED STAY WARNING (per-session, 5 min before limit)
        # ========================================
        for user_id, session in sessions_snapshot.items():
            time_inside = now - session["entry_time"]
            sid = session["session_id"]

            if time_inside >= self.extended_stay_threshold and sid not in self._extended_stay_warned:
                if self._can_push_event("EXTENDED_STAY", now):
                    self.push_state_transition(
                        event="EXTENDED_STAY",
                        session_id=sid,
                        description=f"User {user_id} approaching stay limit: {time_inside/60:.0f}/{self.max_stay_minutes} min"
                    )
                    self._extended_stay_warned.add(sid)
                    print(f"[MONITOR] Extended stay warning: {user_id} at {time_inside/60:.1f} min")

        # ========================================
        # 4. SUSPICIOUS IDLE (face detected + PIR no motion)
        # ========================================
        if self.current_occupancy > 0:
            pir_inactivity = self.pir_sensor.get_inactivity_duration()
            if pir_inactivity >= self.suspicious_idle_threshold:
                if self._can_push_event("SUSPICIOUS_IDLE", now):
                    # Use first active session for context
                    first_session_id = next(iter(sessions_snapshot.values()), {}).get("session_id", str(uuid.uuid4()))
                    self.push_state_transition(
                        event="SUSPICIOUS_IDLE",
                        session_id=first_session_id,
                        description=f"Person detected but no movement for {pir_inactivity/60:.0f} min"
                    )
                    print(f"[MONITOR] Suspicious idle: {pir_inactivity/60:.1f} min no PIR motion")

        # ========================================
        # 5. AFTER-HOURS PRESENCE
        # ========================================
        if self._is_after_hours() and self.current_occupancy > 0:
            if self._can_push_event("AFTER_HOURS", now):
                current_hour = datetime.now().strftime("%H:%M")
                self.push_state_transition(
                    event="AFTER_HOURS",
                    session_id=next(iter(sessions_snapshot.values()), {}).get("session_id", str(uuid.uuid4())),
                    description=f"Person detected at {current_hour} (outside operating hours {self.operating_hours_start}:00-{self.operating_hours_end}:00)"
                )
                print(f"[MONITOR] After-hours presence detected at {current_hour}")

    # =========================
    # COMPUTE DETECTION STATE (for anti-spam push)
    # =========================
    def _compute_detection_state(self, faces, face_images):
        """Determine the current detection state â€” used for state-change-only pushes"""
        if self.current_occupancy > 0:
            if face_images:
                return "face_detected"
            else:
                return "face_obstruction"
        else:
            return "no_face"

    def _push_detection_state(self, detection_state, faces, now):
        """Push detection event ONLY on state change (anti-spam)"""
        if detection_state == "face_detected":
            self.push_detection("face_detected", len(faces), 0.85)
        elif detection_state == "face_obstruction":
            self.push_detection("face_obstruction", self.current_occupancy, 0.7, triggered_alert=True)
        elif detection_state == "no_face":
            self.push_detection("no_face", 0, 0.0)

    def on_rfid_tapped(self, user_id):
        """
        RFID tap handler with full FSM integration.

        Flow:
        1. Per-UID cooldown check (3s anti-spam)
        2. Global cooldown check (prevent double-swipe)
        3. Unknown RFID escalation (graduated response)
        4. Already-inside check (prevent duplicate session)
        5. Face verification with confidence threshold
        6. Session creation + state transition
        """
        now = time.time()
        uid_str = str(user_id)

        # =========================
        # PER-UID RFID COOLDOWN (3s anti-spam)
        # Same card tapped rapidly = ignore completely
        # =========================
        last_uid_tap = self._rfid_per_uid_cooldown.get(uid_str, 0)
        if (now - last_uid_tap) < self._rfid_per_uid_cooldown_sec:
            return  # Silent ignore
        self._rfid_per_uid_cooldown[uid_str] = now

        # =========================
        # GLOBAL RFID COOLDOWN (prevent double-swipe spam)
        # =========================
        if self.last_rfid_time and (now - self.last_rfid_time) < self.rfid_cooldown:
            print(f"[RFID] Cooldown active - ignoring tap for {user_id}")
            return

        self.last_rfid_time = now

        # Short buzzer feedback on every RFID tap
        self.buzzer.beep(duration=0.1)

        # =========================
        # UNKNOWN RFID CHECK + ROOM ACCESS CHECK
        # Query backend to see if UID is registered AND allowed in this room
        # =========================
        room_allowed = False
        person_id = None  # Resolved from backend for DB linkage
        try:
            resp = requests.get(
                f"{self.base_url}/api/access/rfid?uid={uid_str}&roomId={self.room_id}",
                timeout=2
            )
            data = resp.json() if resp.status_code == 200 else {}

            if resp.status_code == 404 or not data.get("found", False):
                self._handle_unknown_rfid(uid_str, now)
                return

            # Capture personId for database linkage
            person_id = data.get("personId")
            face_embedding_str = data.get("faceEmbedding")  # Base64 encoding from database

            # ROOM-BASED ACCESS CHECK (fail-secure)
            room_allowed = data.get("roomAllowed", False)
            room_name = data.get("roomName", "Unknown")

            if not room_allowed:
                print(f"[ACCESS] DENIED — {data.get('fullName', uid_str)} not authorized for {room_name}")
                # Yellow LED flash to indicate room denial
                self.rgb_led.status_access()
                time.sleep(0.3)
                self.buzzer.beep(duration=0.3)
                time.sleep(0.2)
                self.buzzer.beep(duration=0.3)
                self.rgb_led.off()

                # Log denied access via PushStateTransition (unified pipeline)
                try:
                    self.push_state_transition(
                        event="ALERT",
                        session_id=str(uuid.uuid4()),
                        rfid_uid=uid_str,
                        person_id=data.get("personId"),
                        alert_type="RoomAccessDenied",
                        description=f"Room access denied: {data.get('fullName', uid_str)} not assigned to {room_name}",
                        severity="WARNING"
                    )
                except Exception:
                    pass

                self.set_state(STATE_IDLE)
                return

        except requests.exceptions.ConnectionError:
            pass  # Backend offline - proceed with local logic
        except Exception as e:
            print(f"[RFID] Backend lookup failed: {e}")

        # =========================
        # ALREADY INSIDE CHECK (per-person session tracking)
        # =========================
        with self.session_lock:
            if uid_str in self.active_sessions:
                print(f"[FSM] User {user_id} already inside - ignoring RFID re-tap")
                return

        # =========================
        # TRANSITION: -> ACCESS MODE
        # =========================
        self.set_state(STATE_ACCESS)

        # =========================
        # FACE VERIFICATION (with confidence threshold)
        # Biometric Lock OFF = skip face check, grant access on RFID alone
        # Compares live camera face against face_embedding from the database.
        # The faceEmbedding is fetched from ASP.NET RFID lookup response.
        # Falls back to local .pkl file if database embedding unavailable.
        # =========================
        face_lookup_id = str(person_id) if person_id else uid_str
        if not self._biometric_lock_enabled:
            print(f"[ACCESS] Biometric Lock DISABLED â€” granting access on RFID alone for {user_id}")
            result = {"verified": True, "confidence": 100, "failure_type": None}
        else:
            result = self.face_verifier.verify_rfid_with_face(face_lookup_id, db_embedding_str=face_embedding_str)

        if result["verified"] and result["confidence"] >= self.face_confidence_threshold * 100:
            # =========================
            # ACCESS GRANTED â€” Create session
            # =========================
            session_id = str(uuid.uuid4())

            with self.session_lock:
                self.active_sessions[str(user_id)] = {
                    "session_id": session_id,
                    "entry_time": now,
                    "last_active": now,
                    "status": "INSIDE",
                    "rfid_uid": str(user_id),
                    "person_id": person_id
                }

            # =========================
            # TRANSITION: â†’ INSIDE MODE
            # =========================
            self.set_state(STATE_INSIDE)

            # Push to backend (single ENTRY event)
            # rfid_valid=True because RFID was verified by backend lookup
            # face_verified depends on whether biometric lock was enabled and passed
            self.push_state_transition(
                event="ENTRY",
                session_id=session_id,
                rfid_uid=str(user_id),
                person_id=person_id,
                confidence=result["confidence"] / 100.0,
                rfid_valid=True,
                face_verified=self._biometric_lock_enabled
            )

            # Unlock door + track entry window for tailgating
            self.solenoid_lock.unlock(duration=self._gate_hold_open)
            self._last_unlock_time = now

            # Hardware feedback: confirmation beep + green flash
            self.buzzer.beep(duration=0.2)
            self.rgb_led.status_granted()

            # Push detection event (preserves existing behavior)
            self.push_detection("face_verified", 1, result["confidence"] / 100.0)

            print(f"[ACCESS GRANTED] {user_id} â€” Session: {session_id[:8]}...")

        else:
            # =========================
            # ACCESS DENIED â€” Differentiated by failure type (BUG-4 FIX)
            # =========================
            failure_type = result.get("message", "")

            if failure_type == "FACE MISMATCH":
                # REAL THREAT: Face captured but doesn't match RFID owner
                self.set_state(STATE_ALERT)
                self._alert_start_time = time.time()

                session_id = str(uuid.uuid4())
                self.push_state_transition(
                    event="ALERT",
                    session_id=session_id,
                    rfid_uid=str(user_id),
                    person_id=person_id,
                    alert_type="UnauthorizedAccess",
                    description=f"RFID {user_id} face MISMATCH (confidence: {result['confidence']}%)",
                    severity="HIGH"
                )
                self.push_detection("unknown_face", 1, result["confidence"] / 100.0, triggered_alert=True)
                self._start_recording(session_id)

                # Hardware feedback: alarm via emergency trigger system
                self.rgb_led.status_denied()
                self.trigger_emergency(
                    "intrusion", duration=5,
                    session_id=session_id,
                    description=f"RFID {user_id} face MISMATCH (confidence: {result['confidence']}%)"
                )

                print(f"[ACCESS DENIED] {user_id} â€” Face MISMATCH")

                time.sleep(2)
                self.buzzer.stop()  # Ensure buzzer stops before state change
                self.set_state(STATE_IDLE)

            elif failure_type == "No face detected":
                # TEMPORARY: Camera didn't capture face â€” allow retry
                print(f"[ACCESS] {user_id} â€” No face captured, returning to IDLE")
                self.set_state(STATE_IDLE)
                # Do NOT push alert â€” camera issue, not security threat

            elif failure_type == "Face expired":
                # STALE: Encoding too old
                print(f"[ACCESS] {user_id} â€” Face encoding expired, returning to IDLE")
                self.set_state(STATE_IDLE)

            elif failure_type == "No registered face":
                # ADMIN ISSUE: User has no stored face data
                self.set_state(STATE_ALERT)
                self._alert_start_time = time.time()

                session_id = str(uuid.uuid4())
                self.push_state_transition(
                    event="ALERT",
                    session_id=session_id,
                    rfid_uid=str(user_id),
                    alert_type="SuspiciousActivity",
                    description=f"RFID {user_id} has no registered face data",
                    severity="WARNING"
                )
                print(f"[ACCESS DENIED] {user_id} â€” No registered face")

                # Warning beep (not full alarm â€” admin issue, not security threat)
                self.buzzer.pattern_beep(times=3, interval=0.3)

                time.sleep(2)
                self.set_state(STATE_IDLE)

            else:
                # Unknown failure â€” safe fallback
                print(f"[ACCESS] {user_id} â€” Verification failed: {failure_type}")
                self.set_state(STATE_IDLE)

    # =========================
    # PIR MOTION CALLBACK
    # =========================
    def on_pir_motion(self, motion_detected):
        """
        PIR state-change callback.
        Updates last_active for all active sessions.
        Does NOT generate database logs.
        """
        if motion_detected:
            with self.session_lock:
                for user_id, session in self.active_sessions.items():
                    session["last_active"] = time.time()

    # =========================
    # DOOR SENSOR CALLBACK
    # =========================
    def on_door_change(self, is_open):
        """
        Magnetic reed switch state-change callback.
        Detects forced entry when door opens without active session.
        """
        if is_open:
            with self.session_lock:
                has_active = len(self.active_sessions) > 0

            current_state = self.get_state()

            if not has_active and current_state == STATE_IDLE:
                # Door opened without any active session = FORCED ENTRY
                print("[DOOR] FORCED ENTRY â€” door opened without authorization")

                self.set_state(STATE_ALERT)
                self._alert_start_time = time.time()

                session_id = str(uuid.uuid4())
                self.push_state_transition(
                    event="ALERT",
                    session_id=session_id,
                    alert_type="ForcedEntry",
                    description="Door opened without any active RFID session",
                    severity="CRITICAL"
                )
                self._start_recording(session_id)

                # Hardware feedback: alarm via emergency trigger system
                self.trigger_emergency(
                    "forcedentry", duration=10,
                    session_id=session_id,
                    description="Door opened without any active RFID session"
                )

            elif has_active:
                print("[DOOR] Door opened â€” active session present (normal)")
        else:
            print("[DOOR] Door closed")

    # =========================
    # ALARM SETTINGS (DB-DRIVEN)
    # =========================
    def _is_alarm_enabled(self, alarm_type):
        """Check if a specific alarm protocol is armed in the DB."""
        return self._alarm_settings.get(alarm_type.lower(), True)

    def _fetch_alarm_settings(self):
        """Fetch alarm_settings from ASP.NET backend."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/system/alarm-settings",
                timeout=3
            )
            if resp.ok:
                settings = resp.json()
                self._alarm_settings = {
                    s["type"].lower(): s["isEnabled"]
                    for s in settings
                }
                print(f"[ALARM] Settings synced: {self._alarm_settings}")
        except Exception as e:
            print(f"[ALARM] Settings fetch failed (using last known): {e}")

    def _alarm_settings_poller(self):
        """Background thread: poll alarm + system settings every 10 seconds."""
        while self.is_running:
            self._fetch_alarm_settings()
            self._fetch_system_config()
            time.sleep(10)

    # =========================
    # SYSTEM CONFIG (DB-DRIVEN â€” ALL UI CARDS)
    # Maps each UI setting to the correct Python variable
    # =========================
    def _fetch_system_config(self):
        """Fetch system_config from ASP.NET backend (all UI card settings)."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/system/config",
                timeout=3
            )
            if resp.ok:
                config = resp.json()

                # === GLOBAL SETTINGS ===
                # Master Arm: controls whether detection runs at all
                arm_system = config.get("armSystem", True)
                if not arm_system and self.is_running:
                    print("[CONFIG] Master Arm DISABLED â€” detection paused")
                self._master_armed = arm_system

                # === AI INTELLIGENCE ===
                # Motion Sensitivity â†’ person_detector confidence_threshold
                sensitivity = config.get("motionSensitivity", 2)
                threshold_map = {1: 0.65, 2: 0.50, 3: 0.35}
                new_threshold = threshold_map.get(sensitivity, 0.50)
                if hasattr(self.person_detector, 'confidence_threshold'):
                    if self.person_detector.confidence_threshold != new_threshold:
                        self.person_detector.confidence_threshold = new_threshold
                        print(f"[CONFIG] Motion sensitivity â†’ {sensitivity} (threshold: {new_threshold})")

                # Face Accuracy â†’ face_confidence_threshold
                face_acc = config.get("faceAccuracy", 80)
                new_face_threshold = face_acc / 100.0
                if self.face_confidence_threshold != new_face_threshold:
                    self.face_confidence_threshold = new_face_threshold
                    print(f"[CONFIG] Face accuracy â†’ {face_acc}% (threshold: {new_face_threshold})")

                # === ALERT PROTOCOLS ===
                # Hardware Siren â†’ controls whether buzzer is allowed to fire
                self._hardware_siren_enabled = config.get("hardwareSiren", True)

                # === ACCESS CONTROL ===
                # Gate Hold-Open â†’ solenoid_lock unlock duration
                gate_duration = config.get("gateHoldOpen", 5)
                self._gate_hold_open = max(1, min(30, gate_duration))

                # Biometric Lock â†’ whether face verification is required
                self._biometric_lock_enabled = config.get("biometricLock", True)

        except Exception as e:
            # Silent fail â€” use last known config
            pass

    # =========================
    # EMERGENCY TRIGGER (PRIORITY-BASED)
    # Distinct hardware patterns per alarm type
    # =========================
    _ALARM_PRIORITY = {
        "fire": 4,
        "intrusion": 3,
        "forcedentry": 2,
        "earthquake": 1,
    }

    def trigger_emergency(self, alarm_type, duration=10, session_id=None, description=""):
        """
        Trigger an emergency alarm with type-specific hardware behavior.

        Only fires if the alarm_type is enabled in alarm_settings.
        Uses priority system: Fire > Intrusion > ForcedEntry > Earthquake.
        """
        alarm_key = alarm_type.lower()

        # Gate check: is this alarm armed?
        if not self._is_alarm_enabled(alarm_key):
            print(f"[ALARM] {alarm_type} is DISABLED in settings â€” skipping hardware")
            return False

        # Priority check: don't override a higher-priority alarm
        current_priority = getattr(self, '_active_alarm_priority', 0)
        new_priority = self._ALARM_PRIORITY.get(alarm_key, 0)

        if new_priority < current_priority:
            print(f"[ALARM] {alarm_type} (priority {new_priority}) blocked by active alarm (priority {current_priority})")
            return False

        self._active_alarm_priority = new_priority

        # Stop any current alarm before starting new one
        self.buzzer.stop()

        print(f"[ALARM] ðŸš¨ TRIGGERING: {alarm_type.upper()} (priority {new_priority})")

        # Type-specific hardware behavior
        # LED always fires; buzzer respects Hardware Siren setting
        if alarm_key == "fire":
            self.rgb_led.status_fire()
            if self._hardware_siren_enabled:
                self.buzzer.alarm_fire(duration=duration)
        elif alarm_key == "earthquake":
            self.rgb_led.status_earthquake()
            if self._hardware_siren_enabled:
                self.buzzer.alarm_earthquake(duration=duration)
        elif alarm_key == "forcedentry":
            self.rgb_led.status_medical()
            if self._hardware_siren_enabled:
                self.buzzer.alarm_medical(duration=duration)
        else:
            # Default: intrusion (continuous alarm + red blink)
            self.rgb_led.status_alert()
            if self._hardware_siren_enabled:
                self.buzzer.alarm(duration=duration)

        if not self._hardware_siren_enabled:
            print("[ALARM] Hardware siren DISABLED â€” LED only, no buzzer")

        # Push alarm status to ASP.NET for real-time UI
        self._push_alarm_status(alarm_key, True, session_id, description)

        # Schedule priority reset after alarm duration
        def _reset_priority():
            time.sleep(duration + 1)
            self._active_alarm_priority = 0
            self._push_alarm_status(alarm_key, False)
        threading.Thread(target=_reset_priority, daemon=True).start()

        return True

    def _push_alarm_status(self, alarm_type, is_active, session_id=None, description=""):
        """Push current alarm status to ASP.NET for UI display."""
        try:
            requests.post(
                f"{self.base_url}/api/system/alarm-status",
                json={
                    "type": alarm_type,
                    "isActive": is_active,
                    "sessionId": session_id or "",
                    "description": description,
                    "roomId": self.room_id,
                    "timestamp": datetime.now().isoformat()
                },
                timeout=2
            )
        except Exception as e:
            print(f"[ALARM] Status push failed: {e}")

    # =========================
    # LOITERING MONITOR (REALISTIC ALGORITHM)
    # =========================
    def loitering_monitor(self):
        """
        Background thread: checks for loitering conditions.
        Runs every 30 seconds (not per frame).

        Loitering = TIME + INACTIVITY + NO STATE CHANGE

        Conditions checked:
        1. Time inside > suspicion threshold (10 min)
        2. PIR inactivity > threshold (5 min no motion)
        3. No state change (still INSIDE, not ACCESS or exiting)
        4. Camera still sees them (confirming presence)
        """
        while self.is_running:
            try:
                now = time.time()

                with self.session_lock:
                    sessions_to_check = list(self.active_sessions.items())

                for user_id, session in sessions_to_check:
                    time_inside = now - session["entry_time"]
                    time_inactive = now - session["last_active"]
                    pir_inactivity = self.pir_sensor.get_inactivity_duration()

                    # =========================
                    # LOITERING CHECK (Combined Logic)
                    # =========================
                    if session["status"] == "INSIDE":
                        # Must be inside > suspicion threshold
                        # AND inactive for significant period
                        # AND PIR confirms no motion
                        if (time_inside > self.loiter_critical_threshold
                                and time_inactive > self.pir_inactivity_threshold
                                and pir_inactivity > self.pir_inactivity_threshold):

                            with self.session_lock:
                                session["status"] = "LOITERING"

                            self.set_state(STATE_LOITERING)

                            self.push_state_transition(
                                event="LOITERING",
                                session_id=session["session_id"],
                                description=f"User {user_id} loitering: {time_inside/60:.0f}min inside, {time_inactive/60:.0f}min inactive"
                            )

                            print(f"[LOITERING] User {user_id} â€” {time_inside/60:.1f}min inside, {time_inactive/60:.1f}min inactive")

                    # =========================
                    # EXIT INFERENCE (FALLBACK ONLY)
                    # Only if no door sensor available
                    # =========================
                    if time_inactive > self.exit_inference_timeout:
                        print(f"[EXIT INFERENCE] User {user_id} â€” {time_inactive/60:.0f}min inactive, assuming exit")

                        self.push_state_transition(
                            event="EXIT",
                            session_id=session["session_id"],
                            exit_reason="INFERENCE"
                        )

                        with self.session_lock:
                            self.active_sessions.pop(user_id, None)
                            # Clean up extended stay tracking for this session
                            self._extended_stay_warned.discard(session["session_id"])

                            if len(self.active_sessions) == 0:
                                self.set_state(STATE_IDLE)

            except Exception as e:
                print(f"[LOITERING MONITOR ERROR] {e}")

            # Check every 30 seconds (not per frame)
            time.sleep(30)

    # =========================
    # CENTRALIZED API POST (with retry queue for critical events)
    # =========================
    def post_to_dashboard(self, endpoint, payload, critical=False):
        """
        Centralized POST to ASP.NET backend.
        - critical=True: ENTRY, EXIT, ALERT -- queued for retry on failure
        - critical=False: occupancy, detection -- fire-and-forget
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.post(url, json=payload, timeout=3)
            return response
        except Exception as e:
            if critical and self._enable_api_retry:
                self._api_retry_queue.put({
                    "url": url,
                    "payload": payload,
                    "attempts": 0,
                    "timestamp": time.time()
                })
                print(f"[API RETRY] Queued critical POST to {endpoint} ({e})")
            else:
                print(f"[API] Non-critical POST failed: {endpoint} ({e})")
            return None

    def _api_retry_worker(self):
        """Background thread: retries failed critical API calls (max 3 attempts, 5s delay)."""
        print("[API RETRY] Worker started")
        while self.is_running:
            try:
                item = self._api_retry_queue.get(timeout=2)
            except queue.Empty:
                continue

            url = item["url"]
            payload = item["payload"]
            attempts = item["attempts"]

            if attempts >= self._api_retry_max_attempts:
                print(f"[API RETRY] GAVE UP after {attempts} attempts: {url}")
                print(f"[API RETRY] Lost payload: {json.dumps(payload)[:200]}")
                continue

            time.sleep(self._api_retry_delay)

            try:
                response = requests.post(url, json=payload, timeout=5)
                if response.status_code == 200:
                    print(f"[API RETRY] SUCCESS on attempt {attempts + 1}: {url}")
                else:
                    raise Exception(f"HTTP {response.status_code}")
            except Exception as e:
                item["attempts"] = attempts + 1
                self._api_retry_queue.put(item)
                print(f"[API RETRY] Attempt {attempts + 1}/{self._api_retry_max_attempts} failed: {e}")

    # =========================
    # STATE TRANSITION API (-> ASP.NET Backend)
    # =========================
    def push_state_transition(self, event, session_id,
                               rfid_uid=None, person_id=None, confidence=0,
                               exit_reason=None, alert_type=None,
                               description=None, severity=None,
                               rfid_valid=False, face_verified=False):
        """
        Push a state transition to the ASP.NET backend.
        This is the ONLY way the Python controller writes to the database.
        Each call represents a meaningful state change, NOT a frame event.
        Uses retry queue for guaranteed delivery (critical=True).
        """
        payload = {
            "SessionId": session_id,
            "Event": event,
            "CameraId": self.camera_id,
            "RoomId": self.room_id,
            "PersonId": person_id,
            "RfidUid": rfid_uid,
            "Confidence": confidence,
            "RfidValid": rfid_valid,
            "FaceVerified": face_verified,
            "ExitReason": exit_reason,
            "AlertType": alert_type,
            "Description": description,
            "Severity": severity
        }

        # ENTRY, EXIT, ALERT are critical -- must reach the database
        is_critical = event in ("ENTRY", "EXIT", "ALERT")

        response = self.post_to_dashboard(
            "/Cameras/PushStateTransition", payload, critical=is_critical
        )

        if response and response.status_code == 200:
            result = response.json()
            if result.get("duplicate"):
                print(f"[API] Duplicate prevented: {result.get('message')}")
            else:
                print(f"[API] State transition: {event} -> OK")
        elif response:
            print(f"[API] State transition failed: {response.status_code}")

    # =========================
    # OCCUPANCY PUSH (non-critical, fire-and-forget)
    # =========================
    def push_occupancy(self):
        self.post_to_dashboard(
            "/Cameras/UpdateOccupancy",
            {
                "CameraId": self.camera_id,
                "PeopleCount": self.current_occupancy
            },
            critical=False
        )

    # =========================
    # DETECTION PUSH (non-critical, fire-and-forget)
    # =========================
    def push_detection(self, detection_type, count, confidence, triggered_alert=False):
        self.post_to_dashboard(
            "/Cameras/PushDetection",
            {
                "CameraId": self.camera_id,
                "DetectionType": detection_type,
                "DetectedCount": count,
                "Confidence": confidence,
                "TriggeredAlert": triggered_alert
            },
            critical=False
        )

    # =========================
    # ALERT SYSTEM (critical, uses retry queue)
    # =========================
    def send_alert(self, alert_type, description, severity="WARNING"):
        now = time.time()

        if now - self.last_alert_push < self.alert_cooldown:
            return

        self.last_alert_push = now

        self.post_to_dashboard(
            "/Cameras/PushAlert",
            {
                "Type": alert_type,
                "Description": description,
                "Severity": severity,
                "RoomId": self.room_id
            },
            critical=True
        )

    # =========================
    # UNLOCK (preserved from original, now uses SolenoidLock module)
    # =========================
    def trigger_unlock(self):
        self.solenoid_lock.unlock(duration=self._gate_hold_open)
        self._last_unlock_time = time.time()
        print(f"[ACCESS GRANTED] Door unlocked for {self._gate_hold_open}s")

    # =========================
    # UNKNOWN RFID ESCALATION HANDLER
    # =========================
    def _handle_unknown_rfid(self, uid, now):
        """
        Graduated response for unknown RFID cards:
        1st tap: capture face, deny, log
        2nd tap: update face, deny
        3rd tap: mark suspicious, notify admin
        5th tap: trigger alarm, buzzer, RED LED, lockout
        """
        tracker = self._unknown_rfid_tracker.get(uid)

        # Check lockout
        if tracker and tracker.get("locked_out_until", 0) > now:
            print(f"[RFID] Unknown UID {uid} locked out for {tracker['locked_out_until'] - now:.0f}s")
            return

        # Initialize or update tracker
        if tracker is None:
            tracker = {"count": 0, "first_tap": now, "last_tap": now, "locked_out_until": 0}
            self._unknown_rfid_tracker[uid] = tracker

        tracker["count"] += 1
        tracker["last_tap"] = now
        count = tracker["count"]

        print(f"[RFID] Unknown UID {uid} - tap #{count}")

        # DENY ACCESS always for unknown UIDs
        self.rgb_led.status_denied()

        if count == 1:
            # 1st tap: capture + deny + log
            self.buzzer.beep(duration=0.3)
            self.push_state_transition(
                event="ALERT",
                session_id=str(uuid.uuid4()),
                rfid_uid=uid,
                alert_type="AccessDenied",
                description=f"Unknown RFID card detected (UID: {uid})",
                severity="WARNING"
            )

        elif count == 2:
            # 2nd tap: update face + deny
            self.buzzer.pattern_beep(times=2, interval=0.2)

        elif count == 3:
            # 3rd tap: suspicious - notify admin
            self.buzzer.pattern_beep(times=3, interval=0.2)
            self.push_state_transition(
                event="ALERT",
                session_id=str(uuid.uuid4()),
                rfid_uid=uid,
                alert_type="SuspiciousActivity",
                description=f"Suspicious RFID activity: unknown card {uid} tapped {count} times",
                severity="HIGH"
            )

        elif count >= 5:
            # 5th tap: ALARM + lockout
            session_id = str(uuid.uuid4())
            self.push_state_transition(
                event="ALERT",
                session_id=session_id,
                rfid_uid=uid,
                alert_type="BruteForceAttempt",
                description=f"Brute force RFID: unknown card {uid} tapped {count} times",
                severity="CRITICAL"
            )
            self._start_recording(session_id)
            self.trigger_emergency(
                "intrusion", duration=10,
                session_id=session_id,
                description=f"Brute force RFID: unknown card {uid} tapped {count} times"
            )
            # Lockout this UID for 5 minutes
            tracker["locked_out_until"] = now + self._unknown_rfid_lockout
            tracker["count"] = 0  # Reset count after lockout
            print(f"[RFID] UID {uid} LOCKED OUT for {self._unknown_rfid_lockout}s")

    # =========================
    # RECORDING SYSTEM (MP4/H.264 + pre-buffer + async writer)
    # =========================
    def _recording_writer_loop(self):
        """Async recording writer thread - drains frame queue without blocking main loop."""
        while self._is_recording or not self._recording_queue.empty():
            try:
                frame = self._recording_queue.get(timeout=1)
                if self._recording_writer is not None:
                    self._recording_writer.write(frame)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[RECORDING] Async write error: {e}")
                break

    def _start_recording(self, session_id):
        """
        Start recording video when ALERT is triggered.
        Uses MP4/H.264 for browser-compatible playback.
        Writes pre-buffer frames first (3-5 seconds before event).
        Uses async writer thread to prevent blocking the main loop.
        """
        if self._is_recording:
            return  # Already recording

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"alert_{timestamp}_{session_id[:8]}.mp4"
            self._recording_path = os.path.join(self._recording_dir, filename)
            self._recording_alert_id = session_id

            # Get frame dimensions from camera
            frame = self.camera.get_frame()
            if frame is None:
                print("[RECORDING] Cannot start - no frame available")
                return

            h, w = frame.shape[:2]
            # Use mp4v codec (H.264 compatible, works on Pi + browsers)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self._recording_writer = cv2.VideoWriter(
                self._recording_path, fourcc, 15.0, (w, h)
            )

            if not self._recording_writer.isOpened():
                print("[RECORDING] Failed to open writer")
                self._recording_writer = None
                return

            self._is_recording = True
            self._recording_start_time = time.time()
            self._recording_post_deadline = None

            # Clear queue and start async writer thread
            while not self._recording_queue.empty():
                try:
                    self._recording_queue.get_nowait()
                except queue.Empty:
                    break
            self._recording_writer_thread = threading.Thread(
                target=self._recording_writer_loop, daemon=True
            )
            self._recording_writer_thread.start()

            # Write pre-buffer frames (captured before the event)
            pre_frames = list(self._frame_buffer)
            for pf in pre_frames:
                try:
                    self._recording_queue.put_nowait(pf)
                except queue.Full:
                    break

            print(f"[RECORDING] Started: {filename} (pre-buffer: {len(pre_frames)} frames)")

        except Exception as e:
            print(f"[RECORDING ERROR] Start failed: {e}")
            self._is_recording = False
            self._recording_writer = None

    def _stop_recording(self):
        """
        Stop recording and push metadata to backend.
        Links recording to the alert via file_path.
        """
        if not self._is_recording:
            return

        try:
            if self._recording_writer is not None:
                self._recording_writer.release()
                self._recording_writer = None

            self._is_recording = False
            duration = time.time() - self._recording_start_time if self._recording_start_time else 0

            # Get file size
            file_size_mb = 0
            if self._recording_path and os.path.exists(self._recording_path):
                file_size_mb = round(os.path.getsize(self._recording_path) / (1024 * 1024), 2)

            print(f"[RECORDING] Stopped: {self._recording_path} ({file_size_mb}MB, {duration:.0f}s)")

            # Push recording metadata to backend
            if self._recording_path and file_size_mb > 0:
                try:
                    requests.post(
                        f"{self.base_url}/Cameras/PushRecording",
                        json={
                            "CameraId": self.camera_id,
                            "SessionId": self._recording_alert_id,
                            "FilePath": self._recording_path,
                            "FileSizeMb": file_size_mb
                        },
                        timeout=3
                    )
                except Exception as e:
                    print(f"[RECORDING] Backend push failed: {e}")

        except Exception as e:
            print(f"[RECORDING ERROR] Stop failed: {e}")
        finally:
            self._recording_writer = None
            self._is_recording = False
            self._recording_path = None
            self._recording_start_time = None
            self._recording_alert_id = None

    # =========================
    # STOP
    # =========================
    def stop(self):
        print("[SYSTEM] Shutting down...")
        self.is_running = False

        # Stop any active recording
        self._stop_recording()

        # Close all active sessions as INFERENCE exit
        with self.session_lock:
            for user_id, session in list(self.active_sessions.items()):
                self.push_state_transition(
                    event="EXIT",
                    session_id=session["session_id"],
                    exit_reason="INFERENCE"
                )
            self.active_sessions.clear()

        # Drain API retry queue before shutdown
        if self._enable_api_retry:
            remaining = self._api_retry_queue.qsize()
            if remaining > 0:
                print(f"[API RETRY] Draining {remaining} queued items before shutdown...")
                deadline = time.time() + 15  # Max 15s drain time
                while not self._api_retry_queue.empty() and time.time() < deadline:
                    try:
                        item = self._api_retry_queue.get_nowait()
                        requests.post(item["url"], json=item["payload"], timeout=3)
                        print(f"[API RETRY] Drained: {item['url']}")
                    except Exception:
                        pass
                print("[API RETRY] Queue drained")

        self.camera.stop()
        self.pir_sensor.cleanup()
        self.solenoid_lock.cleanup()
        self.buzzer.cleanup()
        self.rgb_led.cleanup()
        self.door_sensor.cleanup()

        if not self.use_simulated_rfid:
            self.rfid_reader.cleanup()
        else:
            self.rfid_reader.stop_reading()

        print("[SYSTEM] Shutdown complete")

    # =========================
    # STATUS (for debugging / dashboard)
    # =========================
    def get_system_status(self):
        with self.session_lock:
            sessions_info = {
                uid: {
                    "session_id": s["session_id"][:8] + "...",
                    "status": s["status"],
                    "minutes_inside": round((time.time() - s["entry_time"]) / 60, 1),
                    "minutes_inactive": round((time.time() - s["last_active"]) / 60, 1)
                }
                for uid, s in self.active_sessions.items()
            }

        return {
            "state": self.get_state(),
            "occupancy": self.current_occupancy,
            "active_sessions": sessions_info,
            "pir_motion": self.pir_sensor.is_motion_detected(),
            "pir_inactivity_seconds": round(self.pir_sensor.get_inactivity_duration(), 1),
            "lock_status": self.solenoid_lock.get_status(),
            "buzzer_active": self.buzzer.is_active,
            "led_color": self.rgb_led.get_status(),
            "door_open": self.door_sensor.is_door_open(),
            "alarm_settings": dict(self._alarm_settings)
        }



def main():
    import platform
    is_pi = platform.system().lower() == "linux"

    system = SmartSecuritySystem(
        use_simulated_rfid=not is_pi,  # Auto: real RFID on Pi, simulated on laptop
        base_url=os.environ.get("ASPNET_URL", "http://localhost:5145"),
        camera_id=1,
        room_id=1,
        # =============================================
        # ROOM-SPECIFIC CONFIG (no DB columns needed)
        # Change these per-room when deploying to Raspberry Pi
        # =============================================
        max_stay_minutes=20,          # Stay limit (20 min default, server room=30, lab=60)
        room_max_capacity=10,         # Max people allowed (0=disabled)
        operating_hours_start=6,      # Operating hours start (6 AM)
        operating_hours_end=22        # Operating hours end (10 PM)
    )

    if system.initialize():
        system.start()

        # Fetch alarm settings immediately on boot
        system._fetch_alarm_settings()

        # =========================
        # START MJPEG STREAM SERVER (shares FSM camera instance)
        # Also hosts /health (disk) and /archive (USB backup)
        # =========================
        stream_app = Flask(__name__)

        # =========================
        # CORS — Required for camera.cshtml on ASP.NET (different port)
        # Without this, browser blocks /status, /ready, /start fetch calls
        # =========================
        @stream_app.after_request
        def add_cors(response):
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            return response

        # =========================
        # UNIFIED /video — serves FSM-processed frames on BOTH Pi and Laptop
        # The FSM main_loop draws overlays → set_processed_frame() → get_stream_frame()
        # This is the ONLY /video route. No duplicate test-mode route needed.
        # HD 1280x720 frames with AI overlays burned in.
        # =========================
        @stream_app.route('/video')
        def video_feed():
            def generate():
                while True:
                    frame = system.camera.get_stream_frame()
                    if frame is None:
                        time.sleep(0.01)
                        continue
                    # JPEG quality 80 = sharp HD, good compression ratio
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

        @stream_app.route('/health')
        def pi_health():
            """Return REAL disk usage from the Pi's filesystem."""
            import shutil
            try:
                usage = shutil.disk_usage("/")
                total_gb = round(usage.total / (1024**3), 1)
                used_gb = round(usage.used / (1024**3), 1)
                free_gb = round(usage.free / (1024**3), 1)
                used_pct = round((usage.used / usage.total) * 100, 1)
                return json.dumps({
                    "diskUsedPercent": used_pct,
                    "diskTotalGb": total_gb,
                    "diskUsedGb": used_gb,
                    "diskFreeGb": free_gb,
                    "recordingsCount": len([f for f in os.listdir(system._recording_dir) if f.endswith('.mp4')]) if os.path.isdir(system._recording_dir) else 0
                }), 200, {'Content-Type': 'application/json'}
            except Exception as e:
                return json.dumps({"error": str(e)}), 500, {'Content-Type': 'application/json'}

        @stream_app.route('/archive', methods=['POST'])
        def archive_recordings():
            """Copy recordings from Pi to USB drive mount point."""
            import shutil as sh
            import glob

            # Common USB mount points on Raspberry Pi OS
            usb_paths = ["/media/usb", "/media/pi", "/mnt/usb"]
            # Also check for any mounted removable device
            if os.path.isdir("/media"):
                for user_dir in os.listdir("/media"):
                    full = os.path.join("/media", user_dir)
                    if os.path.isdir(full):
                        for dev in os.listdir(full):
                            candidate = os.path.join(full, dev)
                            if os.path.ismount(candidate):
                                usb_paths.insert(0, candidate)

            usb_mount = None
            for p in usb_paths:
                if os.path.ismount(p):
                    usb_mount = p
                    break

            if not usb_mount:
                return json.dumps({
                    "success": False,
                    "message": "No USB storage device detected. Please insert a USB drive into the Raspberry Pi."
                }), 200, {'Content-Type': 'application/json'}

            # Copy recordings
            rec_dir = system._recording_dir
            if not os.path.isdir(rec_dir):
                return json.dumps({
                    "success": False,
                    "message": "No recordings directory found."
                }), 200, {'Content-Type': 'application/json'}

            files = glob.glob(os.path.join(rec_dir, "*.mp4"))
            if not files:
                return json.dumps({
                    "success": True,
                    "message": "No recordings to archive.",
                    "copied": 0
                }), 200, {'Content-Type': 'application/json'}

            dest_dir = os.path.join(usb_mount, "SmartSecurity_Archive")
            os.makedirs(dest_dir, exist_ok=True)

            copied = 0
            for f in files:
                try:
                    sh.copy2(f, dest_dir)
                    copied += 1
                except Exception:
                    pass

            return json.dumps({
                "success": True,
                "message": f"Archived {copied}/{len(files)} recordings to {dest_dir}",
                "copied": copied,
                "total": len(files),
                "destination": dest_dir
            }), 200, {'Content-Type': 'application/json'}


        # =========================
        # COMPATIBILITY ROUTES
        # Camera is always running via CameraModule while main.py runs.
        # /start and /stop exist for frontend compatibility (sendBeacon).
        # CORS already applied by @after_request at line 1999.
        # =========================

        @stream_app.route('/start', methods=['POST', 'GET'])
        def stream_start():
            ready = system.camera._frame_ready.is_set() if hasattr(system.camera, '_frame_ready') else True
            return json.dumps({
                'success': True,
                'ready': ready,
                'message': 'Camera running via FSM pipeline'
            }), 200, {'Content-Type': 'application/json'}

        @stream_app.route('/ready', methods=['GET'])
        def stream_ready():
            """Instant health check — frontend pings this before loading /video."""
            ready = system.camera._frame_ready.is_set() if hasattr(system.camera, '_frame_ready') else True
            return json.dumps({
                'ready': ready,
                'state': system.get_state(),
                'armed': system._master_armed
            }), 200, {'Content-Type': 'application/json'}

        @stream_app.route('/stop', methods=['POST', 'GET'])
        def stream_stop():
            return json.dumps({'success': True, 'message': 'Camera managed by FSM lifecycle'}), 200, {'Content-Type': 'application/json'}

        @stream_app.route('/status', methods=['GET'])
        def stream_status():
            """Full FSM status for real-time AI panel updates."""
            status = system.get_system_status()
            tracked = len(system.tracked_persons)
            face_detected = system.current_occupancy > 0 and system.get_state() in (STATE_IDLE, STATE_ACCESS)
            
            # Determine threat level from state
            state = system.get_state()
            threat = 'SAFE'
            if state == STATE_ALERT:
                threat = 'ALERT'
            elif state == STATE_LOITERING:
                threat = 'WARNING'
            elif system.current_occupancy > system.room_max_capacity and system.room_max_capacity > 0:
                threat = 'WARNING'

            return json.dumps({
                'active': True,
                'mode': 'FSM',
                'state': state,
                'occupancy': system.current_occupancy,
                'sessions': len(system.active_sessions),
                'tracked_persons': tracked,
                'face_detected': face_detected,
                'threat_level': threat,
                'recording': system._is_recording,
                'pir_motion': system.pir_sensor.is_motion_detected(),
                'armed': system._master_armed
            }), 200, {'Content-Type': 'application/json'}


        stream_thread = threading.Thread(
            target=lambda: stream_app.run(host='0.0.0.0', port=5050, debug=False, threaded=True),
            daemon=True
        )
        stream_thread.start()
        print("[STREAM] MJPEG server started on port 5050 (overlays enabled)")

        mode = "RASPBERRY PI" if is_pi else "LAPTOP (SIMULATION)"
        print(f"\n{'=' * 50}")
        print(f" FSM Security System Running [{mode}]")
        print(f" Press Ctrl+C to stop")
        print(f"{'=' * 50}\n")

        try:
            while True:
                # Print status every 30 seconds for monitoring
                time.sleep(30)
                status = system.get_system_status()
                print(f"[STATUS] {status['state']} | "
                      f"Occupancy: {status['occupancy']} | "
                      f"Sessions: {len(status['active_sessions'])} | "
                      f"PIR: {'MOTION' if status['pir_motion'] else 'IDLE'} | "
                      f"Lock: {status['lock_status']} | "
                      f"Door: {'OPEN' if status['door_open'] else 'CLOSED'} | "
                      f"LED: {status['led_color']}")

        except KeyboardInterrupt:
            print("\n[SYSTEM] Interrupt received")
            system.stop()


if __name__ == "__main__":
    main()