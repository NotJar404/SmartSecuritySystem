"""
Unified Hardware Control Module for Smart Security System
Combines: Active Buzzer, RGB LED, Magnetic Door Sensor

All components follow the same pattern as pir_sensor.py and lock_sensor.py:
- Auto-detect Raspberry Pi vs laptop (simulation mode)
- Thread-safe state access
- Clean GPIO shutdown

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
# ACTIVE BUZZER
# =========================
class Buzzer:
    """
    Active Buzzer Module for alarm/notification sounds.

    Supports:
    - Real Raspberry Pi GPIO (BCM pin)
    - Simulated mode for laptop/desktop testing

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

        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

        self._gpio = None

    def initialize(self):
        if self.simulated:
            print("[BUZZER] Running in SIMULATED mode")
            return True

        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setup(self.pin, GPIO.OUT)
            self._gpio.output(self.pin, GPIO.LOW)  # Start silent
            print(f"[BUZZER] Initialized on GPIO pin {self.pin}")
            return True
        except Exception as e:
            print(f"[BUZZER ERROR] GPIO init failed: {e}")
            self.simulated = True
            return True

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
                print(f"[BUZZER SIM] 🔊 Beep ({duration}s)")
            else:
                self._gpio.output(self.pin, GPIO.HIGH)

        time.sleep(duration)

        with self.lock:
            self.is_active = False
            if not self.simulated:
                self._gpio.output(self.pin, GPIO.LOW)

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
            print(f"[BUZZER SIM] 🚨 ALARM ON ({duration}s)")

        with self.lock:
            self.is_active = True
            if not self.simulated:
                self._gpio.output(self.pin, GPIO.HIGH)

        while self._alarm_running and (time.time() - start) < duration:
            time.sleep(0.1)

        with self.lock:
            self.is_active = False
            if not self.simulated:
                self._gpio.output(self.pin, GPIO.LOW)

        if self.simulated:
            print("[BUZZER SIM] 🔇 ALARM OFF")

    def stop(self):
        """Immediately silence the buzzer."""
        self._alarm_running = False
        with self.lock:
            self.is_active = False
            if not self.simulated and self._gpio:
                self._gpio.output(self.pin, GPIO.LOW)

    def cleanup(self):
        self.stop()
        if not self.simulated and self._gpio:
            try:
                self._gpio.cleanup(self.pin)
            except:
                pass
        print("[BUZZER] Cleaned up")


# =========================
# RGB LED STATUS INDICATOR
# =========================
class RGBLed:
    """
    RGB LED Module for visual system status indication.

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

        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

        self._gpio = None

    def initialize(self):
        if self.simulated:
            print("[RGB LED] Running in SIMULATED mode")
            return True

        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            for pin in [self.pin_r, self.pin_g, self.pin_b]:
                self._gpio.setup(pin, GPIO.OUT)
                self._gpio.output(pin, GPIO.LOW)
            print(f"[RGB LED] Initialized on GPIO pins R={self.pin_r}, G={self.pin_g}, B={self.pin_b}")
            return True
        except Exception as e:
            print(f"[RGB LED ERROR] GPIO init failed: {e}")
            self.simulated = True
            return True

    def set_color(self, r, g, b, label="custom"):
        """Set LED color. Values: 0 (off) or 1 (on) per channel."""
        self._blink_running = False
        with self.lock:
            self.current_color = label
            if self.simulated:
                if r or g or b:
                    print(f"[RGB LED SIM] Color: {label} (R={r}, G={g}, B={b})")
            else:
                self._gpio.output(self.pin_r, GPIO.HIGH if r else GPIO.LOW)
                self._gpio.output(self.pin_g, GPIO.HIGH if g else GPIO.LOW)
                self._gpio.output(self.pin_b, GPIO.HIGH if b else GPIO.LOW)

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
            if not self.simulated and self._gpio:
                for pin in [self.pin_r, self.pin_g, self.pin_b]:
                    self._gpio.output(pin, GPIO.LOW)

    def get_status(self):
        with self.lock:
            return self.current_color

    def cleanup(self):
        self._blink_running = False
        self.off()
        if not self.simulated and self._gpio:
            try:
                for pin in [self.pin_r, self.pin_g, self.pin_b]:
                    self._gpio.cleanup(pin)
            except:
                pass
        print("[RGB LED] Cleaned up")


# =========================
# MAGNETIC DOOR SENSOR
# =========================
class DoorSensor:
    """
    Magnetic Reed Switch Door Sensor Module.

    Detects door open/close state changes.
    Uses INPUT with PULL_UP — reed switch connects GPIO to GND.
        - Door CLOSED: switch closed → GPIO reads LOW
        - Door OPEN:   switch open  → GPIO reads HIGH (pulled up)

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

        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

        self._gpio = None

    def initialize(self):
        if self.simulated:
            print("[DOOR] Running in SIMULATED mode (door closed)")
            return True

        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            # Read initial state
            self.is_open = self._gpio.input(self.pin) == 1
            print(f"[DOOR] Initialized on GPIO pin {self.pin} — {'OPEN' if self.is_open else 'CLOSED'}")
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
                    current_state = self._gpio.input(self.pin) == 1

                if current_state != previous_state:
                    with self.lock:
                        self.is_open = current_state

                    state_str = "OPEN" if current_state else "CLOSED"
                    print(f"[DOOR] State changed: {state_str}")

                    if self.callback:
                        self.callback(current_state)

                    previous_state = current_state

            except Exception as e:
                print(f"[DOOR ERROR] {e}")

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
        if not self.simulated and self._gpio:
            try:
                self._gpio.cleanup(self.pin)
            except:
                pass
        print("[DOOR] Cleaned up")
