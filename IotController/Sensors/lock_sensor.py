import time
import threading
import platform


class SolenoidLock:
    """
    Solenoid Door Lock Actuator for Smart Security System

    Supports:
    - Real Raspberry Pi GPIO control
    - Simulated mode for laptop/desktop testing

    Role in FSM:
    - Actuator ONLY — unlocks door on verified access
    - Does NOT generate database logs
    - Controlled exclusively by the FSM state transitions
    """

    def __init__(self, pin=18, simulated=None):
        """
        Args:
            pin: BCM GPIO pin number for solenoid relay (default 18)
            simulated: Force simulation mode. None = auto-detect by platform.
        """
        self.pin = pin
        self.is_locked = True
        self.lock = threading.Lock()

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
            print("[LOCK] Running in SIMULATED mode (laptop fallback)")
            return True

        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setup(self.pin, GPIO.OUT)
            self._gpio.output(self.pin, GPIO.LOW)  # Start locked
            print(f"[LOCK] Initialized on GPIO pin {self.pin}")
            return True
        except Exception as e:
            print(f"[LOCK ERROR] GPIO init failed: {e}")
            print("[LOCK] Falling back to SIMULATED mode")
            self.simulated = True
            return True

    # =========================
    # UNLOCK (TIMED)
    # =========================
    def unlock(self, duration=5):
        """
        Unlock door for specified duration, then re-lock automatically.

        Args:
            duration: Seconds to keep door unlocked (default 5)
        """
        thread = threading.Thread(
            target=self._unlock_sequence,
            args=(duration,),
            daemon=True
        )
        thread.start()

    def _unlock_sequence(self, duration):
        """Internal: timed unlock then re-lock"""
        with self.lock:
            self.is_locked = False

            if self.simulated:
                print(f"[LOCK SIM] 🔓 Door UNLOCKED for {duration}s")
            else:
                self._gpio.output(self.pin, GPIO.HIGH)
                print(f"[LOCK] 🔓 Door UNLOCKED for {duration}s")

        time.sleep(duration)

        with self.lock:
            self.is_locked = True

            if self.simulated:
                print("[LOCK SIM] 🔒 Door RE-LOCKED")
            else:
                self._gpio.output(self.pin, GPIO.LOW)
                print("[LOCK] 🔒 Door RE-LOCKED")

    # =========================
    # EMERGENCY LOCK
    # =========================
    def emergency_lock(self):
        """Immediately lock the door (override any unlock sequence)"""
        with self.lock:
            self.is_locked = True

            if not self.simulated and self._gpio:
                self._gpio.output(self.pin, GPIO.LOW)

            print("[LOCK] 🚨 EMERGENCY LOCK ENGAGED")

    # =========================
    # STATUS
    # =========================
    def get_status(self):
        """Return current lock state"""
        with self.lock:
            return "LOCKED" if self.is_locked else "UNLOCKED"

    # =========================
    # CLEANUP
    # =========================
    def cleanup(self):
        """Safe shutdown — ensure door is locked"""
        with self.lock:
            self.is_locked = True

            if not self.simulated and self._gpio:
                try:
                    self._gpio.output(self.pin, GPIO.LOW)
                    self._gpio.cleanup(self.pin)
                except:
                    pass

        print("[LOCK] Cleaned up — door locked")
