import time
import threading
import requests
from datetime import datetime

from Sensors.camera_module import CameraModule
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier
from Sensors.rfid_reader import RFIDReader


class SmartSecuritySystem:
    """Main orchestration system for RFID + Face Verification + Backend Sync"""

    def __init__(self, use_simulated_rfid=False, api_url="http://localhost:5000/api/access/rfid"):
        self.camera = CameraModule(camera_id=0)
        self.face_detector = FaceDetector()
        self.face_verifier = FaceVerifier(storage_dir="face_data")

        self.rfid_reader = RFIDReader()

        self.use_simulated_rfid = use_simulated_rfid
        self.api_url = api_url

        self.is_running = False
        self.detection_active = True

        self.access_log = []

    # =========================
    # INITIALIZATION
    # =========================
    def initialize(self):
        print("[SYSTEM] Initializing Smart Security System...")

        if not self.camera.initialize():
            print("[ERROR] Camera initialization failed")
            return False

        print("[SYSTEM] Initialization complete")
        return True

    # =========================
    # START SYSTEM
    # =========================
    def start(self):
        if self.is_running:
            return

        self.is_running = True

        self.camera.start_capture()
        print("[SYSTEM] Camera started")

        # RFID MODE SWITCH
        if self.use_simulated_rfid:
            print("[SYSTEM] Running in SIMULATION mode")
        else:
            self.rfid_reader.start_reading(callback=self.on_rfid_tapped)
            print("[SYSTEM] RC522 RFID Reader started")

        threading.Thread(target=self._face_detection_loop, daemon=True).start()
        print("[SYSTEM] Face detection started")

    # =========================
    # FACE DETECTION LOOP
    # =========================
    def _face_detection_loop(self):
        while self.is_running and self.detection_active:
            try:
                frame = self.camera.get_latest_frame()

                if frame is None:
                    time.sleep(0.1)
                    continue

                faces, face_images = self.face_detector.detect_faces(frame)

                if faces and len(face_images) > 0:
                    self.face_verifier.store_detected_face(face_images[0])

                else:
                    status = self.face_verifier.get_detection_status()
                    if status["detected"] and status["age_seconds"] > 10:
                        self.face_verifier.current_face_encoding = None

                time.sleep(0.1)

            except Exception as e:
                print("[FACE ERROR]", e)
                time.sleep(0.2)

    # =========================
    # RFID CALLBACK
    # =========================
    def on_rfid_tapped(self, user_id):
        print("\n[RFID] Card Detected:", user_id)

        result = self.face_verifier.verify_rfid_with_face(user_id)

        print("[RESULT]", result["message"])
        print("[CONFIDENCE]", result["confidence"])

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "verified": result["verified"],
            "confidence": result["confidence"],
            "message": result["message"]
        }

        self.access_log.append(log_entry)

        # =========================
        # SEND TO ASP.NET BACKEND
        # =========================
        try:
            requests.post(
                self.api_url,
                json={
                    "rfid": user_id,
                    "verified": result["verified"],
                    "confidence": result["confidence"],
                    "timestamp": log_entry["timestamp"]
                },
                timeout=3
            )
        except Exception as e:
            print("[API ERROR]", e)

        # =========================
        # ACCESS DECISION
        # =========================
        if result["verified"]:
            print("[ACCESS GRANTED]")
            self.trigger_unlock()
        else:
            print("[ACCESS DENIED]")

        print("-" * 50)

    # =========================
    # UNLOCK SYSTEM
    # =========================
    def trigger_unlock(self):
        print("[SYSTEM] Unlock triggered (relay/door integration here)")

    # =========================
    # USER REGISTRATION
    # =========================
    def register_user(self, user_id, image_path):
        import cv2

        try:
            img = cv2.imread(image_path)

            if img is None:
                print("[ERROR] Image not found")
                return False

            success = self.face_verifier.register_user_face(user_id, img)

            if success:
                print(f"[REGISTERED] User {user_id}")

            return success

        except Exception as e:
            print("[REGISTER ERROR]", e)
            return False

    # =========================
    # STOP SYSTEM
    # =========================
    def stop(self):
        print("[SYSTEM] Stopping...")

        self.is_running = False
        self.detection_active = False

        self.camera.stop_capture()
        self.rfid_reader.stop_reading()
        self.rfid_reader.disconnect()

        print("[SYSTEM] Shutdown complete")

    # =========================
    # STATUS
    # =========================
    def print_status(self):
        print("\n=== SYSTEM STATUS ===")
        print("Running:", self.is_running)
        print("Logs:", len(self.access_log))


# =========================
# MAIN ENTRY POINT
# =========================
def main():
    print("=" * 50)
    print("SMART SECURITY SYSTEM (RFID + FACE + AI)")
    print("=" * 50)

    system = SmartSecuritySystem(
        use_simulated_rfid=False,  # 🔥 CHANGE TO FALSE FOR RASPBERRY PI
        api_url="http://YOUR_SERVER_IP/api/access/rfid"
    )

    if not system.initialize():
        return

    system.start()

    print("\nCommands:")
    print("status | log | register <id> <img> | quit")

    try:
        while True:
            cmd = input("> ").split()

            if not cmd:
                continue

            if cmd[0] == "quit":
                break

            elif cmd[0] == "status":
                system.print_status()

            elif cmd[0] == "log":
                for l in system.access_log:
                    print(l)

            elif cmd[0] == "register" and len(cmd) == 3:
                system.register_user(cmd[1], cmd[2])

    except KeyboardInterrupt:
        pass

    finally:
        system.stop()
        print("Exited")


if __name__ == "__main__":
    main()