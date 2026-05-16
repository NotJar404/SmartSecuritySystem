"""
Unified Hardware Control Module for Smart Security System
Combines: Active Buzzer, RGB LED, Magnetic Door Sensor

All components use lgpio directly for Pi 5 compatibility.
No RPi.GPIO. No gpiozero default backend ambiguity.

GPIO Pin Mapping (BCM):
    Buzzer:         GPIO 24  (Pin 18) — Active buzzer, 3-24V
    RGB LED Red:    GPIO 5   (Pin 29) — With 220Ω resistor
    RGB LED Green:  GPIO 6   (Pin 31) — With 220Ω resistor
    RGB LED Blue:   GPIO 13  (Pin 33) — With 220Ω resistor
    Door Sensor:    GPIO 16  (Pin 36) — Magnetic reed switch, INPUT PULL_UP
"""

import time
import threading
import platform


# =========================
# LGPIO CHIP SINGLETON
# Prevents double-open of /dev/gpiochip4 across modules.
# =========================
_lgpio_chip = None
_lgpio_chip_lock = threading.Lock()


def _get_chip():
    """Get or create the shared lgpio chip handle (Pi 5 = gpiochip4)."""
    global _lgpio_chip
    with _lgpio_chip_lock:
        if _lgpio_chip is not None:
            return _lgpio_chip
        try:
            import lgpio
            _lgpio_chip = lgpio.gpiochip_open(4)
            print("[GPIO] lgpio chip 4 opened (Pi 5)")
            return _lgpio_chip
        except Exception:
            try:
                import lgpio
                _lgpio_chip = lgpio.gpiochip_open(0)
                print("[GPIO] lgpio chip 0 opened (Pi 4 / fallback)")
                return _lgpio_chip
            except Exception as e:
                print(f"[GPIO ERROR] Cannot open gpiochip: {e}")
                return None


def _cleanup_chip():
    """Close the shared lgpio chip handle on system shutdown."""
    global _lgpio_chip
    with _lgpio_chip_lock:
        if _lgpio_chip is not None:
            try:
                import lgpio
                lgpio.gpiochip_close(_lgpio_chip)
            except Exception:
                pass
            _lgpio_chip = None


# =========================
# ACTIVE BUZZER
# =========================
class Buzzer:
    """
    Active Buzzer Module for alarm/notification sounds.

    Uses lgpio directly — no RPi.GPIO, no gpiozero.

    Role in FSM:
    - Audible alarm on intrusion/denied access
    - Confirmation beep on access granted
    - Warning pattern on loitering
    - Controlled by alarm_settings (can be disabled from UI)
    """

    def __init__(self, pin=24, simulated=None):
        self.pin = pin
        self.is_active = False
        self.lock = threading.Lock()
        self._alarm_thread = None
        self._alarm_running = False
        self._initialized = False

        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

    def initialize(self):
        if self.simulated:
            print("[BUZZER] Running in SIMULATED mode")
            return True

        try:
            import lgpio
            chip = _get_chip()
            if chip is None:
                raise RuntimeError("No GPIO chip available")

            lgpio.gpio_claim_output(chip, self.pin, 0)
            self._initialized = True
            print(f"[BUZZER] Initialized on GPIO {self.pin}")
            return True
        except Exception as e:
            print(f"[BUZZER ERROR] GPIO init failed: {e}")
            print("[BUZZER] Falling back to SIMULATED mode")
            self.simulated = True
            return True

    def _gpio_write(self, value):
        """Safe GPIO write — never raises."""
        if self.simulated or not self._initialized:
            return
        try:
            import lgpio
            chip = _get_chip()
            if chip is not None:
                lgpio.gpio_write(chip, self.pin, value)
        except Exception:
            pass

    def beep(self, duration=0.2):
        """Short confirmation beep (access granted)."""
        thread = threading.Thread(
            target=self._beep_sequence,
            args=(duration,),
            daemon=True
        )
        thread.start()

    def _beep_sequence(self, duration):
        with self.lock:
            self.is_active = True
            if self.simulated:
                print(f"[BUZZER SIM] Beep ({duration}s)")
            else:
                self._gpio_write(1)

        time.sleep(duration)

        with self.lock:
            self.is_active = False
            self._gpio_write(0)

    def pattern_beep(self, times=3, interval=0.3):
        """Warning pattern beep (loitering, extended stay)."""
        thread = threading.Thread(
            target=self._pattern_sequence,
            args=(times, interval),
            daemon=True
        )
        thread.start()

    def _pattern_sequence(self, times, interval):
        for i in range(times):
            self._beep_sequence(interval)
            time.sleep(interval)
        if self.simulated:
            print(f"[BUZZER SIM] Pattern complete ({times}x)")

    def alarm(self, duration=10):
        """Continuous alarm (intrusion, forced entry)."""
        self._alarm_running = True
        self._alarm_thread = threading.Thread(
            target=self._alarm_sequence,
            args=(duration,),
            daemon=True
        )
        self._alarm_thread.start()

    def _alarm_sequence(self, duration):
        start = time.time()
        if self.simulated:
            print(f"[BUZZER SIM] ALARM ON ({duration}s)")

        with self.lock:
            self.is_active = True
            self._gpio_write(1)

        while self._alarm_running and (time.time() - start) < duration:
            time.sleep(0.1)

        with self.lock:
            self.is_active = False
            self._gpio_write(0)

        if self.simulated:
            print("[BUZZER SIM] ALARM OFF")

    def alarm_fire(self, duration=15):
        """Fast intermittent alarm for fire protocol."""
        self._alarm_running = True
        thread = threading.Thread(
            target=self._fire_sequence, args=(duration,), daemon=True
        )
        thread.start()

    def _fire_sequence(self, duration):
        start = time.time()
        if self.simulated:
            print(f"[BUZZER SIM] FIRE ALARM ({duration}s)")
        while self._alarm_running and (time.time() - start) < duration:
            with self.lock:
                self.is_active = True
                self._gpio_write(1)
            time.sleep(0.15)
            with self.lock:
                self.is_active = False
                self._gpio_write(0)
            time.sleep(0.1)
        if self.simulated:
            print("[BUZZER SIM] FIRE ALARM OFF")

    def alarm_earthquake(self, duration=20):
        """Slow pulsing alarm for earthquake mode."""
        self._alarm_running = True
        thread = threading.Thread(
            target=self._earthquake_sequence, args=(duration,), daemon=True
        )
        thread.start()

    def _earthquake_sequence(self, duration):
        start = time.time()
        if self.simulated:
            print(f"[BUZZER SIM] EARTHQUAKE ALARM ({duration}s)")
        while self._alarm_running and (time.time() - start) < duration:
            with self.lock:
                self.is_active = True
                self._gpio_write(1)
            time.sleep(0.8)
            with self.lock:
                self.is_active = False
                self._gpio_write(0)
            time.sleep(0.8)
        if self.simulated:
            print("[BUZZER SIM] EARTHQUAKE ALARM OFF")

    def alarm_medical(self, duration=15):
        """Urgent repeating pattern for medical emergency."""
        self._alarm_running = True
        thread = threading.Thread(
            target=self._medical_sequence, args=(duration,), daemon=True
        )
        thread.start()

    def _medical_sequence(self, duration):
        start = time.time()
        if self.simulated:
            print(f"[BUZZER SIM] MEDICAL ALARM ({duration}s)")
        while self._alarm_running and (time.time() - start) < duration:
            # 3 rapid beeps then pause
            for _ in range(3):
                if not self._alarm_running:
                    break
                with self.lock:
                    self.is_active = True
                    self._gpio_write(1)
                time.sleep(0.1)
                with self.lock:
                    self.is_active = False
                    self._gpio_write(0)
                time.sleep(0.1)
            time.sleep(0.5)
        if self.simulated:
            print("[BUZZER SIM] MEDICAL ALARM OFF")

    def stop(self):
        """Immediately silence the buzzer."""
        self._alarm_running = False
        with self.lock:
            self.is_active = False
            self._gpio_write(0)

    def cleanup(self):
        self.stop()
        # Pin is released when chip is closed at system shutdown.
        # No per-pin close needed with lgpio.
        self._initialized = False
        print("[BUZZER] Cleaned up")


# =========================
# RGB LED STATUS INDICATOR
# =========================
class RGBLed:
    """
    RGB LED Module for visual system status indication.

    Uses lgpio directly — no RPi.GPIO, no gpiozero.

    Colors:
        IDLE:       Blue        (0, 0, 1)
        ACCESS:     Yellow      (1, 1, 0) — verifying
        INSIDE:     Green       (0, 1, 0) — monitoring
        ALERT:      Red         (1, 0, 0)
        LOITERING:  Orange      (1, 0.5, 0)
        GRANTED:    Green flash
        DENIED:     Red flash
    """

    def __init__(self, pin_r=5, pin_g=6, pin_b=13, simulated=None):
        self.pin_r = pin_r
        self.pin_g = pin_g
        self.pin_b = pin_b
        self.current_color = "OFF"
        self.lock = threading.Lock()
        self._blink_running = False
        self._initialized = False

        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

    def initialize(self):
        if self.simulated:
            print("[RGB LED] Running in SIMULATED mode")
            return True

        try:
            import lgpio
            chip = _get_chip()
            if chip is None:
                raise RuntimeError("No GPIO chip available")

            for pin in (self.pin_r, self.pin_g, self.pin_b):
                lgpio.gpio_claim_output(chip, pin, 0)

            self._initialized = True
            print(f"[RGB LED] Initialized on GPIO R={self.pin_r}, G={self.pin_g}, B={self.pin_b}")
            return True
        except Exception as e:
            print(f"[RGB LED ERROR] GPIO init failed: {e}")
            self.simulated = True
            return True

    def _gpio_write(self, pin, value):
        """Safe GPIO write — never raises."""
        if self.simulated or not self._initialized:
            return
        try:
            import lgpio
            chip = _get_chip()
            if chip is not None:
                lgpio.gpio_write(chip, pin, value)
        except Exception:
            pass

    def set_color(self, r, g, b, label="custom"):
        """Set LED color. Values: 0 (off) or 1 (on) per channel."""
        self._blink_running = False
        with self.lock:
            self.current_color = label
            if self.simulated:
                if r or g or b:
                    print(f"[RGB LED SIM] Color: {label} (R={r}, G={g}, B={b})")
            else:
                self._gpio_write(self.pin_r, int(r))
                self._gpio_write(self.pin_g, int(g))
                self._gpio_write(self.pin_b, int(b))

    def status_idle(self):
        """Blue — system idle, monitoring entrance."""
        self.set_color(0, 0, 1, "IDLE/Blue")

    def status_access(self):
        """Yellow — RFID tapped, verifying face."""
        self.set_color(1, 1, 0, "ACCESS/Yellow")

    def status_monitoring(self):
        """Green — authorized personnel inside, monitoring."""
        self.set_color(0, 1, 0, "MONITORING/Green")

    def status_granted(self):
        """Green flash — access granted confirmation."""
        thread = threading.Thread(target=self._flash, args=(0, 1, 0, 3, 0.2, "GRANTED"), daemon=True)
        thread.start()

    def status_denied(self):
        """Red flash — access denied."""
        thread = threading.Thread(target=self._flash, args=(1, 0, 0, 5, 0.15, "DENIED"), daemon=True)
        thread.start()

    def status_alert(self):
        """Red blinking — active alert/intrusion."""
        self._blink_running = True
        thread = threading.Thread(target=self._blink_loop, args=(1, 0, 0, "ALERT"), daemon=True)
        thread.start()

    def status_loitering(self):
        """Orange — loitering detected."""
        self.set_color(1, 0, 0, "LOITERING/Orange")
        # Note: true orange requires PWM. With digital GPIO, red approximates orange.

    def status_fire(self):
        """Fast red flashing — fire protocol."""
        self._blink_running = True
        thread = threading.Thread(target=self._blink_fast, args=(1, 0, 0, "FIRE"), daemon=True)
        thread.start()

    def status_earthquake(self):
        """Slow blue pulsing — earthquake mode."""
        self._blink_running = True
        thread = threading.Thread(target=self._blink_slow, args=(0, 0, 1, "EARTHQUAKE"), daemon=True)
        thread.start()

    def status_medical(self):
        """Red-blue alternating — medical emergency."""
        self._blink_running = True
        thread = threading.Thread(target=self._blink_alternate, daemon=True)
        thread.start()

    def _blink_fast(self, r, g, b, label):
        """Fast flashing pattern (fire protocol)."""
        if self.simulated:
            print(f"[RGB LED SIM] Fast blink: {label}")
        while self._blink_running:
            self.set_color(r, g, b, label)
            time.sleep(0.15)
            if not self._blink_running:
                break
            self.off()
            time.sleep(0.15)

    def _blink_slow(self, r, g, b, label):
        """Slow pulsing pattern (earthquake)."""
        if self.simulated:
            print(f"[RGB LED SIM] Slow pulse: {label}")
        while self._blink_running:
            self.set_color(r, g, b, label)
            time.sleep(1.0)
            if not self._blink_running:
                break
            self.off()
            time.sleep(1.0)

    def _blink_alternate(self):
        """Red-blue alternating pattern (medical emergency)."""
        if self.simulated:
            print("[RGB LED SIM] Alternate: MEDICAL (Red / Blue)")
        while self._blink_running:
            self.set_color(1, 0, 0, "MEDICAL/Red")
            time.sleep(0.3)
            if not self._blink_running:
                break
            self.set_color(0, 0, 1, "MEDICAL/Blue")
            time.sleep(0.3)

    def _flash(self, r, g, b, times, interval, label):
        if self.simulated:
            print(f"[RGB LED SIM] Flash: {label} ({times}x)")
        for _ in range(times):
            self.set_color(r, g, b, label)
            time.sleep(interval)
            self.off()
            time.sleep(interval)

    def _blink_loop(self, r, g, b, label):
        while self._blink_running:
            self.set_color(r, g, b, label)
            time.sleep(0.5)
            if not self._blink_running:
                break
            self.off()
            time.sleep(0.5)

    def off(self):
        with self.lock:
            self.current_color = "OFF"
            if not self.simulated and self._initialized:
                self._gpio_write(self.pin_r, 0)
                self._gpio_write(self.pin_g, 0)
                self._gpio_write(self.pin_b, 0)

    def get_status(self):
        with self.lock:
            return self.current_color

    def cleanup(self):
        self._blink_running = False
        self.off()
        self._initialized = False
        print("[RGB LED] Cleaned up")


# =========================
# MAGNETIC DOOR SENSOR
# =========================
class DoorSensor:
    """
    Magnetic Reed Switch Door Sensor Module.

    Uses lgpio directly — no RPi.GPIO, no gpiozero.

    Detects door open/close state changes.
    Reed switch connects GPIO to GND:
        - Door CLOSED: switch closed -> GPIO reads LOW (0)
        - Door OPEN:   switch open  -> GPIO reads HIGH (1, pulled up)

    Role in FSM:
    - Detect unauthorized door openings (ForcedEntry alert)
    - Assist EXIT inference when door closes after session
    - Does NOT generate database logs directly — FSM handles events
    """

    def __init__(self, pin=16, simulated=None):
        self.pin = pin
        self.is_open = False
        self.is_running = False
        self.lock = threading.Lock()
        self.callback = None
        self._initialized = False
        self._error_logged = False

        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

    def initialize(self):
        if self.simulated:
            print("[DOOR] Running in SIMULATED mode (door closed)")
            return True

        try:
            import lgpio
            chip = _get_chip()
            if chip is None:
                raise RuntimeError("No GPIO chip available")

            lgpio.gpio_claim_input(chip, self.pin, lgpio.SET_PULL_UP)
            self._initialized = True

            # Read initial state: HIGH = door open (pull-up, switch open)
            val = lgpio.gpio_read(chip, self.pin)
            self.is_open = bool(val)

            print(f"[DOOR] Initialized on GPIO {self.pin} — {'OPEN' if self.is_open else 'CLOSED'}")
            return True
        except Exception as e:
            print(f"[DOOR ERROR] GPIO init failed: {e}")
            self.simulated = True
            return True

    def start(self, callback=None):
        """Start door monitoring. callback(is_open: bool) fires on state change."""
        self.callback = callback
        self.is_running = True
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()
        print("[DOOR] Monitoring started")

    def _monitor_loop(self):
        previous_state = self.is_open

        while self.is_running:
            try:
                if self.simulated:
                    current_state = self.is_open
                else:
                    import lgpio
                    chip = _get_chip()
                    if chip is None:
                        time.sleep(1)
                        continue
                    val = lgpio.gpio_read(chip, self.pin)
                    current_state = bool(val)

                if current_state != previous_state:
                    with self.lock:
                        self.is_open = current_state

                    state_str = "OPEN" if current_state else "CLOSED"
                    print(f"[DOOR] State changed: {state_str}")

                    if self.callback:
                        self.callback(current_state)

                    previous_state = current_state

                self._error_logged = False

            except Exception as e:
                if not self._error_logged:
                    print(f"[DOOR ERROR] {e}")
                    self._error_logged = True

            time.sleep(0.2)

    def is_door_open(self):
        with self.lock:
            return self.is_open

    # Simulation helpers
    def simulate_open(self):
        if not self.simulated:
            return
        with self.lock:
            self.is_open = True
        if self.callback:
            self.callback(True)
        print("[DOOR SIM] Door OPENED")

    def simulate_close(self):
        if not self.simulated:
            return
        with self.lock:
            self.is_open = False
        if self.callback:
            self.callback(False)
        print("[DOOR SIM] Door CLOSED")

    def cleanup(self):
        self.is_running = False
        self._initialized = False
        print("[DOOR] Cleaned up")
