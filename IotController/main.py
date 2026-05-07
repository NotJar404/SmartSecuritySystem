import time
import threading
import requests
import uuid
import os
import cv2
from datetime import datetime

from Sensors.camera_module import CameraModule
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier
from Sensors.rfid_reader import RFIDReader
from Sensors.pir_sensor import PIRSensor
from Sensors.lock_sensor import SolenoidLock


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
        IDLE → ACCESS → INSIDE → LOITERING → (EXIT → IDLE)
                  ↓                    ↓
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
        self.rfid_reader = RFIDReader()
        self.pir_sensor = PIRSensor()
        self.solenoid_lock = SolenoidLock()

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
        self.loiter_suspicion_threshold = 600    # 10 minutes — suspicion phase
        self.loiter_critical_threshold = 1200    # 20 minutes — critical loitering
        self.pir_inactivity_threshold = 300      # 5 minutes PIR silence = suspicious

        # =========================
        # INDOOR MONITORING CONFIG (NO DB COLUMNS — all in Python config)
        # =========================
        self.max_stay_minutes = max_stay_minutes              # Per-room stay limit (default 20)
        self.extended_stay_threshold = (max_stay_minutes - 5) * 60  # Warning 5 min before limit
        self.suspicious_idle_threshold = 600                  # 10 min face + no PIR = suspicious

        # =========================
        # ENTRANCE LOITERING CONFIG
        # Graduated response: 5 min → WARNING, 10 min → CRITICAL
        # (Different from INTRUSION which is sustained-frame-based)
        # =========================
        self._entrance_face_start_time = None  # When face first appeared in IDLE
        self.entrance_loiter_warning = 300     # 5 minutes → WARNING
        self.entrance_loiter_critical = 600    # 10 minutes → CRITICAL
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
        # Key: "event_type:room_id" → last push timestamp
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
    # INIT SYSTEM
    # =========================
    def initialize(self):
        print("=" * 50)
        print("[SYSTEM] Smart Security System — State-Based FSM")
        print("=" * 50)

        if not self.camera.initialize():
            print("[ERROR] Camera failed to initialize")
            return False

        self.pir_sensor.initialize()
        self.solenoid_lock.initialize()

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

        # Start FSM loops
        threading.Thread(target=self.main_loop, daemon=True).start()
        print("[SYSTEM] Main FSM loop started")

        threading.Thread(target=self.loitering_monitor, daemon=True).start()
        print("[SYSTEM] Loitering monitor started")

    # =========================
    # FSM STATE TRANSITION (THREAD-SAFE)
    # =========================
    def set_state(self, new_state):
        """
        Transition the global FSM state.
        Only logs when state actually CHANGES.
        """
        with self.state_lock:
            if self.system_state != new_state:
                old_state = self.system_state
                self.system_state = new_state
                print(f"[FSM] {old_state} → {new_state}")

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
                # FACE DETECTION (always runs for camera overlay)
                # =========================
                faces, face_images = self.face_detector.detect_faces(frame)

                # =========================
                # OCCUPANCY SMOOTHING (BUG-9 FIX)
                # Use median of last N frames to reject flicker
                # =========================
                raw_occupancy = len(faces)
                self._occupancy_buffer.append(raw_occupancy)
                if len(self._occupancy_buffer) > self._occupancy_buffer_size:
                    self._occupancy_buffer.pop(0)
                self.current_occupancy = sorted(self._occupancy_buffer)[len(self._occupancy_buffer) // 2]

                now = time.time()
                current_state = self.get_state()

                # =========================
                # UPDATE PIR ACTIVITY ON FACE DETECTION
                # (Camera supplements PIR for inactivity tracking)
                # =========================
                if self.current_occupancy > 0 and self.pir_sensor.simulated:
                    # In simulation mode, camera detection counts as activity
                    self.pir_sensor.simulate_motion()

                # =========================
                # OVERLAY (preserved from original)
                # =========================
                status_color = {
                    STATE_IDLE: (128, 128, 128),
                    STATE_ACCESS: (0, 255, 255),
                    STATE_INSIDE: (0, 255, 0),
                    STATE_ALERT: (0, 0, 255),
                    STATE_LOITERING: (0, 165, 255),
                }.get(current_state, (255, 255, 255))

                cv2.putText(
                    frame,
                    f"State: {current_state} | Occupancy: {self.current_occupancy}",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    status_color,
                    2
                )

                # Draw face boxes
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x + w, y + h), status_color, 2)

                # =========================
                # SESSION COUNT OVERLAY
                # =========================
                with self.session_lock:
                    session_count = len(self.active_sessions)

                cv2.putText(
                    frame,
                    f"Active Sessions: {session_count}",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (200, 200, 200),
                    1
                )

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

                self.camera.frame = frame
                time.sleep(0.03)

            except Exception as e:
                print("[MAIN LOOP ERROR]", e)
                time.sleep(0.1)

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
        2. After 5 min → ENTRANCE_LOITERING (WARNING)
        3. After 10 min → ENTRANCE_LOITERING (CRITICAL)
        4. Sustained frames without time check → INTRUSION (existing behavior)

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

                # 10 min → CRITICAL entrance loitering
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

                # 5 min → WARNING entrance loitering
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
        - Write frames to recording if active
        - Auto-clear after timeout if no presence
        - Do NOT generate new alerts (already alerted)
        """
        # Write to recording
        if self._is_recording and self._recording_writer is not None:
            self._recording_writer.write(frame)

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
        1. TAILGATING — occupancy > sessions (existing, preserved)
        2. OCCUPANCY EXCEEDED — people count > room max capacity
        3. EXTENDED STAY WARNING — approaching stay time limit
        4. SUSPICIOUS IDLE — face detected + PIR no motion for 10+ min
        5. AFTER-HOURS PRESENCE — person in room outside operating hours
        """
        with self.session_lock:
            expected_count = len(self.active_sessions)
            sessions_snapshot = dict(self.active_sessions)

        # ========================================
        # 1. TAILGATING DETECTION (existing — preserved exactly)
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
        """Determine the current detection state — used for state-change-only pushes"""
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
    # RFID EVENT (FSM: IDLE → ACCESS → INSIDE)
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
            print(f"[RFID] Cooldown active — ignoring tap for {user_id}")
            return

        self.last_rfid_time = now

        # =========================
        # ALREADY INSIDE CHECK (per-person session tracking)
        # =========================
        with self.session_lock:
            if str(user_id) in self.active_sessions:
                print(f"[FSM] User {user_id} already inside — ignoring RFID re-tap")
                return

        # =========================
        # TRANSITION: → ACCESS MODE
        # =========================
        self.set_state(STATE_ACCESS)

        # =========================
        # FACE VERIFICATION (with confidence threshold)
        # =========================
        result = self.face_verifier.verify_rfid_with_face(user_id)

        if result["verified"] and result["confidence"] >= self.face_confidence_threshold * 100:
            # =========================
            # ACCESS GRANTED — Create session
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
            # TRANSITION: → INSIDE MODE
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
            self.solenoid_lock.unlock(duration=5)
            self._last_unlock_time = now

            # Push detection event (preserves existing behavior)
            self.push_detection("face_verified", 1, result["confidence"] / 100.0)

            print(f"[ACCESS GRANTED] {user_id} — Session: {session_id[:8]}...")

        else:
            # =========================
            # ACCESS DENIED — Differentiated by failure type (BUG-4 FIX)
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
                print(f"[ACCESS DENIED] {user_id} — Face MISMATCH")

                time.sleep(2)
                self.set_state(STATE_IDLE)

            elif failure_type == "No face detected":
                # TEMPORARY: Camera didn't capture face — allow retry
                print(f"[ACCESS] {user_id} — No face captured, returning to IDLE")
                self.set_state(STATE_IDLE)
                # Do NOT push alert — camera issue, not security threat

            elif failure_type == "Face expired":
                # STALE: Encoding too old
                print(f"[ACCESS] {user_id} — Face encoding expired, returning to IDLE")
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
                print(f"[ACCESS DENIED] {user_id} — No registered face")

                time.sleep(2)
                self.set_state(STATE_IDLE)

            else:
                # Unknown failure — safe fallback
                print(f"[ACCESS] {user_id} — Verification failed: {failure_type}")
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

                            print(f"[LOITERING] User {user_id} — {time_inside/60:.1f}min inside, {time_inactive/60:.1f}min inactive")

                    # =========================
                    # EXIT INFERENCE (FALLBACK ONLY)
                    # Only if no door sensor available
                    # =========================
                    if time_inactive > self.exit_inference_timeout:
                        print(f"[EXIT INFERENCE] User {user_id} — {time_inactive/60:.0f}min inactive, assuming exit")

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
    # STATE TRANSITION API (→ ASP.NET Backend)
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
                    print(f"[API] State transition: {event} → OK")
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
        self.solenoid_lock.unlock(duration=5)
        self._last_unlock_time = time.time()
        print("[ACCESS GRANTED] Door unlocked")

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
                print("[RECORDING] Cannot start — no frame available")
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

        if not self.use_simulated_rfid:
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
            "lock_status": self.solenoid_lock.get_status()
        }


def main():
    system = SmartSecuritySystem(
        use_simulated_rfid=True,
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

        print("\n" + "=" * 50)
        print(" FSM Security System Running")
        print(" Press Ctrl+C to stop")
        print("=" * 50 + "\n")

        try:
            while True:
                # Print status every 30 seconds for monitoring
                time.sleep(30)
                status = system.get_system_status()
                print(f"[STATUS] {status['state']} | "
                      f"Occupancy: {status['occupancy']} | "
                      f"Sessions: {len(status['active_sessions'])} | "
                      f"PIR: {'MOTION' if status['pir_motion'] else 'IDLE'} | "
                      f"Lock: {status['lock_status']}")

        except KeyboardInterrupt:
            print("\n[SYSTEM] Interrupt received")
            system.stop()


if __name__ == "__main__":
    main()