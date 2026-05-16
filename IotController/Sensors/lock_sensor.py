"""
Solenoid Door Lock Actuator for Smart Security System

Uses lgpio directly for Pi 5 compatibility.
No RPi.GPIO. No gpiozero.

GPIO: BCM 18 (Pin 12) — Relay module controlling solenoid lock
    VCC: 5V (Pin 4)
    GND: Pin 14
    IN:  GPIO 18 — HIGH = unlock relay (energize solenoid), LOW = locked

Role in FSM:
- Actuator ONLY — unlocks door on verified access
- Does NOT generate database logs
- Controlled exclusively by the FSM state transitions

Safety:
- Fail-secure: GPIO LOW on init = door locked
- Emergency lock overrides any active unlock sequence
- Cleanup ensures door is locked on shutdown
"""

import time
import threading
import platform


class SolenoidLock:
    """
    Solenoid Door Lock Actuator with timed unlock.

    Uses lgpio directly — no RPi.GPIO, no gpiozero.
    Fail-secure design: door defaults to LOCKED.
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
        self._initialized = False
        self._unlock_cancelled = False

        # Auto-detect: simulate on non-Linux (laptop testing)
        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

    # =========================
    # INITIALIZE
    # =========================
    def initialize(self):
        """Set up GPIO or simulation mode."""
        if self.simulated:
            print("[LOCK] Running in SIMULATED mode (laptop fallback)")
            return True

        try:
            import lgpio
            from Sensors.hardware import _get_chip

            chip = _get_chip()
            if chip is None:
                raise RuntimeError("No GPIO chip available")

            # Claim as output, initial LOW = door locked (fail-secure)
            lgpio.gpio_claim_output(chip, self.pin, 0)
            self._initialized = True
            print(f"[LOCK] Initialized on GPIO {self.pin} (fail-secure: LOCKED)")
            return True
        except Exception as e:
            print(f"[LOCK ERROR] GPIO init failed: {e}")
            print("[LOCK] Falling back to SIMULATED mode")
            self.simulated = True
            return True

    def _gpio_write(self, value):
        """Safe GPIO write — never raises."""
        if self.simulated or not self._initialized:
            return
        try:
            import lgpio
            from Sensors.hardware import _get_chip

            chip = _get_chip()
            if chip is not None:
                lgpio.gpio_write(chip, self.pin, value)
        except Exception:
            pass

    # =========================
    # UNLOCK (TIMED)
    # =========================
    def unlock(self, duration=5):
        """
        Unlock door for specified duration, then re-lock automatically.

        Args:
            duration: Seconds to keep door unlocked (default 5)
        """
        self._unlock_cancelled = False
        thread = threading.Thread(
            target=self._unlock_sequence,
            args=(duration,),
            daemon=True
        )
        thread.start()

    def _unlock_sequence(self, duration):
        """Internal: timed unlock then re-lock."""
        with self.lock:
            self.is_locked = False
            self._gpio_write(1)

            if self.simulated:
                print(f"[LOCK SIM] Door UNLOCKED for {duration}s")
            else:
                print(f"[LOCK] Door UNLOCKED for {duration}s")

        # Wait in small increments so emergency_lock can interrupt
        elapsed = 0.0
        while elapsed < duration and not self._unlock_cancelled:
            time.sleep(0.1)
            elapsed += 0.1

        with self.lock:
            self.is_locked = True
            self._gpio_write(0)

            if self._unlock_cancelled:
                pass  # emergency_lock already logged
            elif self.simulated:
                print("[LOCK SIM] Door RE-LOCKED")
            else:
                print("[LOCK] Door RE-LOCKED")

    # =========================
    # EMERGENCY LOCK
    # =========================
    def emergency_lock(self):
        """Immediately lock the door (override any unlock sequence)."""
        self._unlock_cancelled = True
        with self.lock:
            self.is_locked = True
            self._gpio_write(0)
            print("[LOCK] EMERGENCY LOCK ENGAGED")

    # =========================
    # STATUS
    # =========================
    def get_status(self):
        """Return current lock state."""
        with self.lock:
            return "LOCKED" if self.is_locked else "UNLOCKED"

    # =========================
    # CLEANUP
    # =========================
    def cleanup(self):
        """Safe shutdown — ensure door is locked."""
        self._unlock_cancelled = True
        with self.lock:
            self.is_locked = True
            self._gpio_write(0)
        self._initialized = False
        print("[LOCK] Cleaned up — door locked")
