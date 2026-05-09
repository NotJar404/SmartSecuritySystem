import time
import threading
import requests
import uuid
import os
import cv2
import numpy as np
import json
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, Response

from Sensors.camera_module import CameraModule
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier
from AI.person_detector import PersonDetector
from AI.person_tracker import CentroidTracker
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
                 api_url="http://localhost:5000/api/access/rfid",
                 base_url="http://localhost:5000",
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
        # RECORDING SYSTEM
        # =========================
        self._is_recording = False
        self._recording_writer = None
        self._recording_path = None
        self._recording_start_time = None
        self._recording_alert_id = None
        self._recording_timeout = 60  # seconds max per recording
        self._recording_dir = "recordings"
        os.makedirs(self._recording_dir, exist_ok=True)

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
        while self.is_running:
            try:
                frame = self.camera.get_frame()

                if frame is None:
                    time.sleep(0.05)
                    continue

                # =========================
                # MASTER ARM CHECK â€” skip detection if disarmed
                # Still streams video but no AI processing
                # =========================
                if not self._master_armed:
                    cv2.putText(frame, "SYSTEM DISARMED", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    self.camera.set_processed_frame(frame)
                    time.sleep(0.1)
                    continue

                # =========================
                # DUAL-MODE DETECTION
                # IDLE/ACCESS: Face detection (entrance monitoring + RFID verify)
                # INSIDE/LOITERING: Person detection + tracking (room monitoring)
                # =========================
                now = time.time()
                current_state = self.get_state()
                faces = []
                face_images = []

                if current_state in (STATE_INSIDE, STATE_LOITERING):
                    # =========================
                    # INSIDE MODE: Person detection + tracking
                    # =========================
                    person_detections = self.person_detector.detect_persons(frame)
                    self.tracked_persons = self.person_tracker.update(person_detections)

                    # Update authorization status for each tracked person
                    self._update_person_authorization()

                    raw_occupancy = self.person_tracker.get_active_count()

                    # Still run face detection at reduced rate for face buffer
                    # (needed if someone new taps RFID while in INSIDE state)
                    if now - self.last_face_update > 2:
                        faces, face_images = self.face_detector.detect_faces(frame)
                else:
                    # =========================
                    # IDLE/ACCESS MODE: Face detection (unchanged)
                    # =========================
                    faces, face_images = self.face_detector.detect_faces(frame)
                    raw_occupancy = len(faces)

                    # Clear person tracker when not in INSIDE state
                    if len(self.tracked_persons) > 0:
                        self.person_tracker.reset()
                        self.tracked_persons = {}
                        self._person_session_map = {}

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
                # OVERLAY â€” STATE + OCCUPANCY TEXT
                # =========================
                status_color = {
                    STATE_IDLE: (128, 128, 128),
                    STATE_ACCESS: (0, 255, 255),
                    STATE_INSIDE: (0, 255, 0),
                    STATE_ALERT: (0, 0, 255),
                    STATE_LOITERING: (0, 165, 255),
                }.get(current_state, (255, 255, 255))

                with self.session_lock:
                    session_count = len(self.active_sessions)

                cv2.putText(
                    frame,
                    f"State: {current_state} | Occupancy: {self.current_occupancy}",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    status_color,
                    2
                )

                cv2.putText(
                    frame,
                    f"Sessions: {session_count}",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (200, 200, 200),
                    1
                )

                # =========================
                # BOUNDING BOX OVERLAY â€” COLOR-CODED
                # =========================
                if current_state in (STATE_INSIDE, STATE_LOITERING):
                    # INSIDE: Draw person detection boxes with authorization colors
                    for track_id, person in self.tracked_persons.items():
                        if person.disappeared > 0:
                            continue  # Don't draw disappeared persons

                        x, y, w, h = person.bbox
                        status = person.status

                        # Color coding: GREEN=authorized, RED=unauthorized, YELLOW=unknown
                        color = {
                            'authorized': (0, 200, 0),
                            'unauthorized': (0, 0, 255),
                            'unknown': (0, 220, 220),
                        }.get(status, (0, 220, 220))

                        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

                        # Label with tracking ID and status
                        label = f"ID:{track_id} [{status.upper()}]"
                        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]

                        # Background for label
                        cv2.rectangle(
                            frame,
                            (x, y - label_size[1] - 8),
                            (x + label_size[0] + 4, y),
                            color, -1
                        )
                        cv2.putText(
                            frame, label, (x + 2, y - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (255, 255, 255), 1
                        )
                else:
                    # IDLE/ACCESS: Draw face boxes (original behavior)
                    for (x, y, w, h) in faces:
                        cv2.rectangle(frame, (x, y), (x + w, y + h), status_color, 2)

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

                # =========================
                # SET PROCESSED FRAME (with all overlays)
                # This frame is served via /video endpoint at http://localhost:5050
                # =========================
                self.camera.set_processed_frame(frame)
                time.sleep(0.03)

            except Exception as e:
                print("[MAIN LOOP ERROR]", e)
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
        # Write to recording ASYNCHRONOUSLY to prevent blocking overlay rendering
        if self._is_recording and self._recording_writer is not None:
            # Non-blocking frame write to prevent main loop lag
            try:
                self._recording_writer.write(frame.copy())
            except Exception as e:
                print(f"[RECORDING] Write error: {e}")

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

    # =========================
    # RFID EVENT (FSM: IDLE â†’ ACCESS â†’ INSIDE)
    # =========================
    def on_rfid_tapped(self, user_id):
        """
        RFID tap handler with full FSM integration.

        Flow:
        1. Cooldown check (prevent double-swipe)
        2. Already-inside check (prevent duplicate session)
        3. Face verification with confidence threshold
        4. Session creation + state transition
        """
        now = time.time()

        # =========================
        # RFID COOLDOWN (prevent double-swipe spam)
        # =========================
        if self.last_rfid_time and (now - self.last_rfid_time) < self.rfid_cooldown:
            print(f"[RFID] Cooldown active â€” ignoring tap for {user_id}")
            return

        self.last_rfid_time = now

        # =========================
        # ALREADY INSIDE CHECK (per-person session tracking)
        # =========================
        with self.session_lock:
            if str(user_id) in self.active_sessions:
                print(f"[FSM] User {user_id} already inside â€” ignoring RFID re-tap")
                return

        # =========================
        # TRANSITION: â†’ ACCESS MODE
        # =========================
        self.set_state(STATE_ACCESS)

        # =========================
        # FACE VERIFICATION (with confidence threshold)
        # Biometric Lock OFF = skip face check, grant access on RFID alone
        # =========================
        if not self._biometric_lock_enabled:
            print(f"[ACCESS] Biometric Lock DISABLED â€” granting access on RFID alone for {user_id}")
            result = {"verified": True, "confidence": 100, "failure_type": None}
        else:
            result = self.face_verifier.verify_rfid_with_face(user_id)

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
                    "rfid_uid": str(user_id)
                }

            # =========================
            # TRANSITION: â†’ INSIDE MODE
            # =========================
            self.set_state(STATE_INSIDE)

            # Push to backend (single ENTRY event)
            self.push_state_transition(
                event="ENTRY",
                session_id=session_id,
                rfid_uid=str(user_id),
                confidence=result["confidence"] / 100.0
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
    # STATE TRANSITION API (â†’ ASP.NET Backend)
    # =========================
    def push_state_transition(self, event, session_id,
                               rfid_uid=None, confidence=0,
                               exit_reason=None, alert_type=None,
                               description=None, severity=None):
        """
        Push a state transition to the ASP.NET backend.
        This is the ONLY way the Python controller writes to the database.
        Each call represents a meaningful state change, NOT a frame event.
        """
        try:
            payload = {
                "SessionId": session_id,
                "Event": event,
                "CameraId": self.camera_id,
                "RoomId": self.room_id,
                "RfidUid": rfid_uid,
                "Confidence": confidence,
                "ExitReason": exit_reason,
                "AlertType": alert_type,
                "Description": description,
                "Severity": severity
            }

            response = requests.post(
                f"{self.base_url}/Cameras/PushStateTransition",
                json=payload,
                timeout=3
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("duplicate"):
                    print(f"[API] Duplicate prevented: {result.get('message')}")
                else:
                    print(f"[API] State transition: {event} â†’ OK")
            else:
                print(f"[API] State transition failed: {response.status_code}")

        except Exception as e:
            print(f"[API ERROR] State transition: {e}")

    # =========================
    # OCCUPANCY PUSH (preserved from original)
    # =========================
    def push_occupancy(self):
        try:
            requests.post(
                f"{self.base_url}/Cameras/UpdateOccupancy",
                json={
                    "CameraId": self.camera_id,
                    "PeopleCount": self.current_occupancy
                },
                timeout=2
            )
        except:
            pass

    # =========================
    # DETECTION PUSH (preserved from original, with debounce)
    # =========================
    def push_detection(self, detection_type, count, confidence, triggered_alert=False):
        try:
            requests.post(
                f"{self.base_url}/Cameras/PushDetection",
                json={
                    "CameraId": self.camera_id,
                    "DetectionType": detection_type,
                    "DetectedCount": count,
                    "Confidence": confidence,
                    "TriggeredAlert": triggered_alert
                },
                timeout=2
            )
        except:
            pass

    # =========================
    # ALERT SYSTEM (preserved from original)
    # =========================
    def send_alert(self, alert_type, description, severity="WARNING"):
        now = time.time()

        if now - self.last_alert_push < self.alert_cooldown:
            return

        self.last_alert_push = now

        try:
            requests.post(
                f"{self.base_url}/Cameras/PushAlert",
                json={
                    "Type": alert_type,
                    "Description": description,
                    "Severity": severity,
                    "RoomId": self.room_id
                },
                timeout=2
            )
        except:
            pass

    # =========================
    # UNLOCK (preserved from original, now uses SolenoidLock module)
    # =========================
    def trigger_unlock(self):
        self.solenoid_lock.unlock(duration=self._gate_hold_open)
        self._last_unlock_time = time.time()
        print(f"[ACCESS GRANTED] Door unlocked for {self._gate_hold_open}s")

    # =========================
    # RECORDING SYSTEM
    # =========================
    def _start_recording(self, session_id):
        """
        Start recording video when ALERT is triggered.
        Saves as .avi file linked to the alert session.
        """
        if self._is_recording:
            return  # Already recording

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"alert_{timestamp}_{session_id[:8]}.avi"
            self._recording_path = os.path.join(self._recording_dir, filename)
            self._recording_alert_id = session_id

            # Get frame dimensions from camera
            frame = self.camera.get_frame()
            if frame is None:
                print("[RECORDING] Cannot start â€” no frame available")
                return

            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            self._recording_writer = cv2.VideoWriter(
                self._recording_path, fourcc, 15.0, (w, h)
            )

            if not self._recording_writer.isOpened():
                print("[RECORDING] Failed to open writer")
                self._recording_writer = None
                return

            self._is_recording = True
            self._recording_start_time = time.time()
            print(f"[RECORDING] Started: {filename}")

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


class TestModeDetector:
    """
    Person detector + face identifier for test mode (laptop).
    Pipeline: HOG body detection -> Centroid tracking -> Face ID -> Persistent status
    """

    def __init__(self, confidence=0.4):
        self.confidence = confidence
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        self.tracked = {}
        self.next_id = 1
        self.max_disappeared = 45
        self.max_match_distance = 150
        self.bbox_smooth = 0.6
        self.frame_count = 0
        self.detect_every = 3
        self.face_detect_every = 6
        self.last_detections = []

    def detect(self, frame):
        self.frame_count += 1
        if self.frame_count % self.detect_every != 0:
            return self.last_detections
        try:
            small = cv2.resize(frame, (640, 480))
            scale_x = frame.shape[1] / 640
            scale_y = frame.shape[0] / 480
            boxes, weights = self.hog.detectMultiScale(
                small, winStride=(8, 8), padding=(4, 4), scale=1.05
            )
            detections = []
            for (x, y, w, h), weight in zip(boxes, weights):
                if weight < self.confidence:
                    continue
                detections.append((int(x * scale_x), int(y * scale_y),
                                   int(w * scale_x), int(h * scale_y), float(weight)))
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
        x, y, w, h = bbox
        fh, fw = frame.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(fw, x + w), min(fh, y + h)
        if x2 - x1 < 30 or y2 - y1 < 30:
            return False
        face_h = int((y2 - y1) * 0.5)
        roi = frame[y1:y1 + face_h, x1:x2]
        if roi.size == 0:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
        return len(faces) > 0

    def update_tracking(self, detections):
        current_centroids = {}
        for (x, y, w, h, conf) in detections:
            cx, cy = x + w // 2, y + h // 2
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
                    'cx': cx, 'cy': cy, 'bbox': (x, y, w, h),
                    'smooth_bbox': [float(x), float(y), float(w), float(h)],
                    'conf': conf, 'status': 'unknown', 'disappeared': 0,
                    'face_seen': False, 'face_check_count': 0
                }
                self.next_id += 1
            return self.tracked

        track_ids = list(self.tracked.keys())
        track_centers = [(self.tracked[tid]['cx'], self.tracked[tid]['cy']) for tid in track_ids]
        det_centers = list(current_centroids.keys())
        used_tracks, used_dets = set(), set()
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
            self.tracked[tid]['cx'] = dc[0]
            self.tracked[tid]['cy'] = dc[1]
            self.tracked[tid]['conf'] = conf
            self.tracked[tid]['disappeared'] = 0
            self.tracked[tid]['bbox'] = (x, y, w, h)
            sb = self.tracked[tid]['smooth_bbox']
            a = self.bbox_smooth
            sb[0] = a * sb[0] + (1 - a) * x
            sb[1] = a * sb[1] + (1 - a) * y
            sb[2] = a * sb[2] + (1 - a) * w
            sb[3] = a * sb[3] + (1 - a) * h
            used_tracks.add(ti)
            used_dets.add(di)
        for di, dc in enumerate(det_centers):
            if di not in used_dets:
                x, y, w, h, conf = current_centroids[dc]
                self.tracked[self.next_id] = {
                    'cx': dc[0], 'cy': dc[1], 'bbox': (x, y, w, h),
                    'smooth_bbox': [float(x), float(y), float(w), float(h)],
                    'conf': conf, 'status': 'unknown', 'disappeared': 0,
                    'face_seen': False, 'face_check_count': 0
                }
                self.next_id += 1
        for ti, tid in enumerate(track_ids):
            if ti not in used_tracks:
                self.tracked[tid]['disappeared'] += 1
                if self.tracked[tid]['disappeared'] > self.max_disappeared:
                    del self.tracked[tid]
        return self.tracked

    def update_face_status(self, frame):
        if self.frame_count % self.face_detect_every != 0:
            return
        for tid, info in self.tracked.items():
            if info['disappeared'] > 0 or info['face_seen']:
                continue
            has_face = self.detect_faces_in_bbox(frame, info['bbox'])
            info['face_check_count'] += 1
            if has_face:
                info['face_seen'] = True
                info['status'] = 'unknown'

    def render_overlays(self, frame, tracked):
        visible = sum(1 for t in tracked.values() if t['disappeared'] == 0)
        cv2.putText(frame, f"State: MONITORING | Persons: {visible}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 2)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        for tid, info in tracked.items():
            if info['disappeared'] > 0:
                continue
            sb = info['smooth_bbox']
            x, y, w, h = int(sb[0]), int(sb[1]), int(sb[2]), int(sb[3])
            conf = info['conf']
            status = info.get('status', 'unknown')
            face_seen = info.get('face_seen', False)
            color = {
                'authorized': (0, 200, 0),
                'unauthorized': (0, 0, 255),
                'unknown': (0, 220, 220),
            }.get(status, (0, 220, 220))
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            corner_len = max(8, min(20, w // 5, h // 5))
            thickness = 3
            cv2.line(frame, (x, y), (x + corner_len, y), color, thickness)
            cv2.line(frame, (x, y), (x, y + corner_len), color, thickness)
            cv2.line(frame, (x + w, y), (x + w - corner_len, y), color, thickness)
            cv2.line(frame, (x + w, y), (x + w, y + corner_len), color, thickness)
            cv2.line(frame, (x, y + h), (x + corner_len, y + h), color, thickness)
            cv2.line(frame, (x, y + h), (x, y + h - corner_len), color, thickness)
            cv2.line(frame, (x + w, y + h), (x + w - corner_len, y + h), color, thickness)
            cv2.line(frame, (x + w, y + h), (x + w, y + h - corner_len), color, thickness)
            face_icon = "F" if face_seen else "?"
            label = f"ID:{tid} [{status.upper()}] ({face_icon}) {int(conf * 100)}%"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(frame, (x, y - label_size[1] - 10),
                          (x + label_size[0] + 8, y), color, -1)
            cv2.putText(frame, label, (x + 4, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(frame, "AI Pipeline Active (Test Mode)",
                    (10, frame.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
        return frame


def main():
    import platform
    is_pi = platform.system().lower() == "linux"

    system = SmartSecuritySystem(
        use_simulated_rfid=not is_pi,  # Auto: real RFID on Pi, simulated on laptop
        base_url="http://localhost:5000",
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

        # Pi mode: /video serves processed frames from FSM pipeline
        # Laptop mode: /video is registered in test mode section below
        if is_pi:
            @stream_app.route('/video')
            def video_feed():
                def generate():
                    while True:
                        frame = system.camera.get_stream_frame()
                        if frame is None:
                            time.sleep(0.03)
                            continue
                        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if not ret:
                            continue
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

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
                    "recordingsCount": len([f for f in os.listdir(system._recording_dir) if f.endswith('.avi')]) if os.path.isdir(system._recording_dir) else 0
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

            files = glob.glob(os.path.join(rec_dir, "*.avi"))
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
        # TEST MODE ENDPOINTS (Laptop/Desktop Testing)
        # On-demand webcam activation with HOG detection & bounding boxes
        # Only active when NOT running on Raspberry Pi
        # =========================
        if not is_pi:
            # Global state for test mode capture
            test_mode_state = {
                'cap': None,
                'current_frame': None,
                'capture_running': False,
                'detector': TestModeDetector(),
                'frame_lock': threading.Lock(),
                'active_viewers': 0,
                'viewers_lock': threading.Lock(),
                'capture_thread_ref': None
            }

            def _test_mode_capture_loop():
                """Background thread: capture â†’ detect â†’ track â†’ overlay â†’ store frame."""
                state = test_mode_state
                cap = cv2.VideoCapture(0)
                
                if not cap.isOpened():
                    print("[STREAM] Trying camera index 1...")
                    cap = cv2.VideoCapture(1)

                if not cap.isOpened():
                    print("[STREAM] ERROR: Cannot open any camera device for test mode!")
                    state['capture_running'] = False
                    return

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)

                print("[STREAM] Test Mode Webcam opened - camera ON")
                print("[STREAM] Pipeline: Capture â†’ HOG Detection â†’ Tracking â†’ Overlays â†’ MJPEG")

                while state['capture_running']:
                    ret, frame = cap.read()
                    if not ret:
                        time.sleep(0.03)
                        continue

                    # === UNIFIED PIPELINE (matches Pi's main.py) ===
                    detections = state['detector'].detect(frame)
                    tracked = state['detector'].update_tracking(detections)
                    state['detector'].update_face_status(frame)
                    frame = state['detector'].render_overlays(frame, tracked)

                    with state['frame_lock']:
                        state['current_frame'] = frame.copy()

                if cap is not None and cap.isOpened():
                    cap.release()
                    cap = None
                
                state['cap'] = None
                print("[STREAM] Test mode capture loop stopped")

            def _test_mode_start_capture():
                """Open webcam and start capture loop."""
                state = test_mode_state
                
                if state['capture_running']:
                    return True

                state['capture_running'] = True
                state['capture_thread_ref'] = threading.Thread(target=_test_mode_capture_loop, daemon=True)
                state['capture_thread_ref'].start()

                # Wait up to 2 seconds for camera to open
                for _ in range(20):
                    if state['cap'] is not None and state['cap'].isOpened():
                        return True
                    time.sleep(0.1)

                return state['cap'] is not None and state['cap'].isOpened()

            def _test_mode_stop_capture():
                """Release webcam and stop capture loop."""
                state = test_mode_state
                state['capture_running'] = False
                time.sleep(0.2)

                if state['cap'] is not None:
                    state['cap'].release()
                    state['cap'] = None
                    print("[STREAM] Test mode webcam released - camera OFF")

                with state['frame_lock']:
                    state['current_frame'] = None

            @stream_app.after_request
            def add_test_mode_cors(response):
                """Enable CORS for test mode endpoints."""
                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
                return response

            @stream_app.route('/start', methods=['POST', 'GET'])
            def test_mode_webcam_start():
                """Start test mode webcam for camera.cshtml."""
                state = test_mode_state
                with state['viewers_lock']:
                    state['active_viewers'] += 1

                ok = _test_mode_start_capture()
                return json.dumps({
                    "success": ok,
                    "message": "Test mode webcam started" if ok else "Failed to open webcam",
                    "viewers": state['active_viewers'],
                    "mode": "TEST"
                }), 200, {'Content-Type': 'application/json'}

            @stream_app.route('/stop', methods=['POST', 'GET'])
            def test_mode_webcam_stop():
                """Stop test mode webcam."""
                state = test_mode_state
                with state['viewers_lock']:
                    state['active_viewers'] = max(0, state['active_viewers'] - 1)

                if state['active_viewers'] <= 0:
                    _test_mode_stop_capture()
                    msg = "Test mode webcam stopped - no viewers"
                else:
                    msg = f"Viewer disconnected, {state['active_viewers']} still watching"

                return json.dumps({
                    "success": True,
                    "message": msg,
                    "viewers": state['active_viewers']
                }), 200, {'Content-Type': 'application/json'}

            @stream_app.route('/status', methods=['GET'])
            def test_mode_status():
                """Get test mode capture status."""
                state = test_mode_state
                return json.dumps({
                    "active": state['capture_running'],
                    "viewers": state['active_viewers'],
                    "mode": "TEST"
                }), 200, {'Content-Type': 'application/json'}

            @stream_app.route('/video', methods=['GET'])
            def test_mode_video_feed():
                """Serve MJPEG stream with bounding boxes. Auto-starts webcam if needed."""
                state = test_mode_state
                
                if not state['capture_running']:
                    _test_mode_start_capture()

                def generate():
                    while state['capture_running']:
                        with state['frame_lock']:
                            frame = state['current_frame']

                        if frame is None:
                            time.sleep(0.05)
                            continue

                        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if not ret:
                            continue

                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

                return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

            print("[STREAM] Test mode endpoints enabled: /start, /stop, /status, /video")

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
