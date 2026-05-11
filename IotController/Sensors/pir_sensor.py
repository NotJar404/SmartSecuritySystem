import time
import threading
import platform


class PIRSensor:
    """
    PIR Motion Sensor Module for Smart Security System

    Supports:
    - Real Raspberry Pi GPIO (BCM pin)
    - Simulated mode for laptop/desktop testing

    Role in FSM:
    - Provides motion/inactivity data for loitering detection
    - Does NOT generate database logs directly
    - Updates last_motion_time used by the FSM
    """

    def __init__(self, pin=17, simulated=None):
        """
        Args:
            pin: BCM GPIO pin number for PIR sensor (default 17)
            simulated: Force simulation mode. None = auto-detect by platform.
        """
        self.pin = pin
        self.motion_detected = False
        self.last_motion_time = 0
        self.is_running = False
        self.lock = threading.Lock()
        self.callback = None

        # Auto-detect: simulate on non-Linux (laptop testing)
        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

        self._gpio = None

    # =========================
    # INITIALIZE
    # =========================
    def initialize(self):
        """Set up GPIO or simulation mode"""
        if self.simulated:
            print("[PIR] Running in SIMULATED mode (laptop fallback)")
            return True

        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setup(self.pin, GPIO.IN)
            print(f"[PIR] Initialized on GPIO pin {self.pin}")
            return True
        except Exception as e:
            print(f"[PIR ERROR] GPIO init failed: {e}")
            print("[PIR] Falling back to SIMULATED mode")
            self.simulated = True
            return True

    # =========================
    # START MONITORING
    # =========================
    def start(self, callback=None):
        """
        Start PIR monitoring loop

        callback: function(motion_detected: bool) — called on state change only
        """
        self.callback = callback
        self.is_running = True

        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()
        print("[PIR] Motion monitoring started")

    # =========================
    # MONITOR LOOP
    # =========================
    def _monitor_loop(self):
        """Continuously poll PIR state — only reports state CHANGES"""
        previous_state = False

        while self.is_running:
            try:
                if self.simulated:
                    # In simulation: no motion detected (idle by default)
                    # The FSM can call simulate_motion() to trigger motion
                    current_state = self.motion_detected
                else:
                    current_state = self._gpio.input(self.pin) == 1

                # Update last motion time on rising edge
                if current_state and not previous_state:
                    with self.lock:
                        self.last_motion_time = time.time()
                        self.motion_detected = True

                    if self.callback:
                        self.callback(True)

                elif not current_state and previous_state:
                    with self.lock:
                        self.motion_detected = False

                    if self.callback:
                        self.callback(False)

                previous_state = current_state

            except Exception as e:
                print(f"[PIR ERROR] {e}")

            time.sleep(0.2)  # 200ms polling — sufficient for PIR

    # =========================
    # STATE ACCESSORS (THREAD-SAFE)
    # =========================
    def is_motion_detected(self):
        """Current motion state"""
        with self.lock:
            return self.motion_detected

    def get_last_motion_time(self):
        """Timestamp of last detected motion"""
        with self.lock:
            return self.last_motion_time

    def get_inactivity_duration(self):
        """Seconds since last motion — used by loitering algorithm"""
        with self.lock:
            if self.last_motion_time == 0:
                # Return 0 on startup (no motion seen yet) so the FSM
                # does NOT skip detection.  float('inf') would trigger
                # PIR-idle mode immediately, producing a plain stream
                # with no bounding boxes until the first PIR event.
                return 0
            return time.time() - self.last_motion_time

    # =========================
    # SIMULATION HELPERS (LAPTOP TESTING)
    # =========================
    def simulate_motion(self):
        """Manually trigger motion event for testing"""
        if not self.simulated:
            return

        with self.lock:
            self.motion_detected = True
            self.last_motion_time = time.time()

        if self.callback:
            self.callback(True)

        print("[PIR SIM] Motion triggered")

    def simulate_idle(self):
        """Manually clear motion for testing"""
        if not self.simulated:
            return

        with self.lock:
            self.motion_detected = False

        if self.callback:
            self.callback(False)

        print("[PIR SIM] Motion cleared (idle)")

    # =========================
    # STOP & CLEANUP
    # =========================
    def stop(self):
        self.is_running = False
        print("[PIR] Stopped monitoring")

    def cleanup(self):
        self.is_running = False
        if not self.simulated and self._gpio:
            try:
                self._gpio.cleanup(self.pin)
            except:
                pass
        print("[PIR] Cleaned up")
