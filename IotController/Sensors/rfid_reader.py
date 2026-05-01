import time
import threading
import requests
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522

class RFIDReader:
    """RC522 RFID Reader for Raspberry Pi 5 (White RFID Cards Supported)"""

    def __init__(self, api_url="http://localhost:5000/api/rfid/scan"):
        self.reader = SimpleMFRC522()
        self.api_url = api_url

        self.is_reading = False
        self.last_rfid = None
        self.rfid_callback = None
        self.lock = threading.Lock()

    # =========================
    # START READING LOOP
    # =========================
    def start_reading(self, callback=None):
        """
        Start RFID scanning loop

        callback: function(uid) optional
        """

        self.rfid_callback = callback
        self.is_reading = True

        thread = threading.Thread(target=self._read_loop, daemon=True)
        thread.start()

        print("[RFID] RC522 Reader Started...")
        return True

    # =========================
    # MAIN RFID LOOP
    # =========================
    def _read_loop(self):
        while self.is_reading:
            try:
                print("[RFID] Waiting for card...")

                uid, text = self.reader.read()

                # Convert UID to string
                rfid_uid = str(uid).strip()

                with self.lock:
                    self.last_rfid = rfid_uid

                print(f"[RFID] Card Detected UID: {rfid_uid}")

                # Send to API immediately
                self.send_to_server(rfid_uid)

                # Callback (optional local logic)
                if self.rfid_callback:
                    self.rfid_callback(rfid_uid)

                time.sleep(1)

            except Exception as e:
                print(f"[RFID ERROR] {e}")
                time.sleep(1)

    # =========================
    # SEND UID TO ASP.NET API
    # =========================
    def send_to_server(self, uid):
        try:
            response = requests.post(
                self.api_url,
                json={"uid": uid},
                timeout=3
            )

            print("[SERVER RESPONSE]", response.json())

        except Exception as e:
            print("[API ERROR]", e)

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
        GPIO.cleanup()
        print("[RFID] Cleaned up GPIO")