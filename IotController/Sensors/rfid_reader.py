"""
RC522 RFID Reader Module for Smart Security System

Supports:
- Real Raspberry Pi 5 GPIO via mfrc522/SimpleMFRC522
- Simulated mode for laptop/desktop testing

CRITICAL DESIGN:
- Reads ALL RFID cards, even unregistered/unknown ones
- Always passes UID to callback — FSM + backend decide what to do
- Unknown UIDs are logged and can be enrolled from the admin dashboard

GPIO (SPI0):
    SDA:   GPIO 8  (CE0) — Pin 24
    SCK:   GPIO 11       — Pin 23
    MOSI:  GPIO 10       — Pin 19
    MISO:  GPIO 9        — Pin 21
    RST:   GPIO 25       — Pin 22
    3.3V:                — Pin 1
    GND:                 — Pin 6
"""

import time
import threading
import platform


class RFIDReader:
    """RC522 RFID Reader with simulation fallback for laptop testing."""

    def __init__(self, simulated=None):
        """
        Args:
            simulated: Force simulation mode. None = auto-detect by platform.
        """
        self.is_reading = False
        self.last_rfid = None
        self.rfid_callback = None
        self.lock = threading.Lock()
        self.reader = None

        # Auto-detect: simulate on non-Linux (laptop testing)
        if simulated is None:
            self.simulated = platform.system().lower() != "linux"
        else:
            self.simulated = simulated

        # Simulation queue for testing
        self._sim_queue = []
        self._sim_lock = threading.Lock()

    # =========================
    # START READING LOOP
    # =========================
    def start_reading(self, callback=None):
        """
        Start RFID scanning loop.

        callback: function(uid: str) — called for EVERY card tap (known or unknown)
        """
        self.rfid_callback = callback
        self.is_reading = True

        if not self.simulated:
            # Initialize hardware reader ONLY on Pi
            try:
                from mfrc522 import SimpleMFRC522
                self.reader = SimpleMFRC522()
            except ImportError:
                print("[RFID ERROR] mfrc522 module not installed. Install: pip install mfrc522")
                print("[RFID] Falling back to SIMULATED mode")
                self.simulated = True
            except Exception as e:
                print(f"[RFID ERROR] Hardware init failed: {e}")
                print("[RFID] Falling back to SIMULATED mode")
                self.simulated = True

        thread = threading.Thread(target=self._read_loop, daemon=True)
        thread.start()

        mode = "SIMULATED" if self.simulated else "RC522 HARDWARE"
        print(f"[RFID] Reader started ({mode})")
        return True

    # =========================
    # MAIN RFID LOOP
    # =========================
    def _read_loop(self):
        while self.is_reading:
            try:
                if self.simulated:
                    # SIMULATION: Check queue for test UIDs
                    uid = None
                    with self._sim_lock:
                        if self._sim_queue:
                            uid = self._sim_queue.pop(0)

                    if uid:
                        self._handle_card(uid)

                    time.sleep(0.5)  # Poll sim queue every 500ms
                else:
                    # REAL HARDWARE: Blocks until card is present
                    print("[RFID] Waiting for card...")
                    uid_raw, text = self.reader.read()

                    # Convert UID to clean string
                    rfid_uid = str(uid_raw).strip()

                    self._handle_card(rfid_uid)

                    # Debounce: wait before reading next card
                    time.sleep(1)

            except Exception as e:
                print(f"[RFID ERROR] {e}")
                time.sleep(1)

    # =========================
    # HANDLE CARD (ALL CARDS — known or unknown)
    # =========================
    def _handle_card(self, uid):
        """Process any RFID card tap — known or unknown."""
        with self.lock:
            self.last_rfid = uid

        print(f"[RFID] Card detected UID: {uid}")

        # ALWAYS fire callback — FSM decides what to do with the UID
        if self.rfid_callback:
            self.rfid_callback(uid)

    # =========================
    # SIMULATION HELPERS (LAPTOP TESTING)
    # =========================
    def simulate_tap(self, uid):
        """Queue a simulated RFID tap for testing."""
        if not self.simulated:
            print("[RFID] Cannot simulate on real hardware")
            return

        with self._sim_lock:
            self._sim_queue.append(str(uid))

        print(f"[RFID SIM] Card queued: {uid}")

    # =========================
    # GET LAST RFID
    # =========================
    def get_last_rfid(self):
        with self.lock:
            return self.last_rfid

    # =========================
    # STOP READING
    # =========================
    def stop_reading(self):
        self.is_reading = False
        print("[RFID] Stopped reading")

    # =========================
    # CLEAN EXIT
    # =========================
    def cleanup(self):
        self.is_reading = False
        if not self.simulated:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
            except:
                pass
        print("[RFID] Cleaned up")