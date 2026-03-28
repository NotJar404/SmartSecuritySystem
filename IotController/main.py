import time
import threading
from datetime import datetime
from Sensors.camera_module import CameraModule
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier
from Sensors.rfid_reader import RFIDReader

class SmartSecuritySystem:
    """Main orchestration system for camera+RFID verification"""
    
    def __init__(self, use_simulated_rfid=False):
        self.camera = CameraModule(camera_id=0)
        self.face_detector = FaceDetector()
        self.face_verifier = FaceVerifier(storage_dir="face_data")
        self.rfid_reader = RFIDReader()
        self.use_simulated_rfid = use_simulated_rfid
        self.is_running = False
        self.detection_active = True
        
        # Access log
        self.access_log = []
    
    def initialize(self):
        """Initialize all system components"""
        print("Initializing Smart Security System...")
        
        # Initialize camera
        if not self.camera.initialize():
            print("Failed to initialize camera")
            return False
        
        # Initialize RFID reader
        if not self.use_simulated_rfid:
            if not self.rfid_reader.connect():
                print("Failed to connect RFID reader (will use simulation mode)")
                self.use_simulated_rfid = True
        
        print("System initialized successfully")
        return True
    
    def start(self):
        """Start the security system"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Start camera capture
        self.camera.start_capture()
        print("Camera capture started")
        
        # Start RFID reader with callback
        self.rfid_reader.start_reading(callback=self.on_rfid_tapped)
        print("RFID reader started")
        
        # Start face detection thread
        detection_thread = threading.Thread(target=self._face_detection_loop, daemon=True)
        detection_thread.start()
        print("Face detection started")
    
    def _face_detection_loop(self):
        """Continuous face detection loop"""
        while self.is_running and self.detection_active:
            try:
                frame = self.camera.get_latest_frame()
                
                if frame is None:
                    time.sleep(0.1)
                    continue
                
                # Detect faces
                faces, face_images = self.face_detector.detect_faces(frame)
                
                if faces:
                    # Store the first detected face
                    if len(face_images) > 0:
                        status = self.face_verifier.store_detected_face(face_images[0])
                        if status:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Face detected and stored - ready for RFID verification")
                else:
                    # Clear stored face if no detection
                    status = self.face_verifier.get_detection_status()
                    if status["detected"]:
                        time_diff = status["age_seconds"]
                        if time_diff > 5:
                            self.face_verifier.current_face_encoding = None
                
                time.sleep(0.1)
            except Exception as e:
                print(f"Face detection error: {e}")
                time.sleep(0.1)
    
    def on_rfid_tapped(self, user_id):
        """Callback when RFID is tapped"""
        print(f"\n['RFID TAPPED'] User {user_id} scanned")
        
        # Verify RFID with detected face
        verification_result = self.face_verifier.verify_rfid_with_face(user_id)
        
        print(f"Verification Result: {verification_result['message']}")
        print(f"Confidence: {verification_result['confidence']:.1f}%")
        
        # Log the access attempt
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "verified": verification_result["verified"],
            "confidence": verification_result["confidence"],
            "message": verification_result["message"]
        }
        self.access_log.append(log_entry)
        
        if verification_result["verified"]:
            print("✓ ACCESS GRANTED - Identity confirmed!")
            self.trigger_unlock()
        else:
            print("✗ ACCESS DENIED - Face does not match RFID!")
        
        print("-" * 50)
    
    def trigger_unlock(self):
        """Trigger door unlock or access permission"""
        print("[SYSTEM] Triggering unlock mechanism...")
        # TODO: Connect to lock_sensor.py to actually unlock door
        # For now just a notification
    
    def register_user(self, user_id, face_image_path):
        """Register a new user with face"
        
        Args:
            user_id: User identifier (e.g., RFID ID)
            face_image_path: Path to face image file
        """
        import cv2
        
        try:
            face_img = cv2.imread(face_image_path)
            if face_img is None:
                print(f"Could not load image: {face_image_path}")
                return False
            
            success = self.face_verifier.register_user_face(user_id, face_img)
            if success:
                print(f"User {user_id} registered successfully")
            return success
        except Exception as e:
            print(f"Registration error: {e}")
            return False
    
    def stop(self):
        """Stop the security system"""
        print("\nShutting down system...")
        self.is_running = False
        self.detection_active = False
        
        self.camera.stop_capture()
        self.rfid_reader.stop_reading()
        self.rfid_reader.disconnect()
        
        print("System stopped")
    
    def get_access_log(self):
        """Get access attempt log"""
        return self.access_log
    
    def print_status(self):
        """Print current system status"""
        print("\n=== System Status ===")
        print(f"Running: {self.is_running}")
        print(f"Face Detection: {self.face_verifier.get_detection_status()}")
        print(f"Access Attempts: {len(self.access_log)}")
        
        if self.access_log:
            print("\nRecent Access Attempts:")
            for log in self.access_log[-5:]:
                status = "✓ GRANTED" if log["verified"] else "✗ DENIED"
                print(f"  {log['timestamp']} - User {log['user_id']}: {status}")


def main():
    """Main entry point"""
    print("=" * 50)
    print("Smart Security System - Camera + RFID Verification")
    print("=" * 50)
    
    # Create system with simulated RFID for testing
    system = SmartSecuritySystem(use_simulated_rfid=True)
    
    if not system.initialize():
        print("Failed to initialize system")
        return
    
    system.start()
    
    print("\nSystem running. Commands:")
    print("  test <user_id>  - Simulate RFID tap with user_id")
    print("  status          - Show system status")
    print("  log             - Show access log")
    print("  register <id> <image_path> - Register user face")
    print("  quit            - Exit system")
    print()
    
    try:
        while True:
            cmd = input("Enter command: ").strip().lower().split()
            
            if not cmd:
                continue
            
            if cmd[0] == "quit":
                break
            
            elif cmd[0] == "test" and len(cmd) > 1:
                user_id = cmd[1]
                system.rfid_reader.simulate_rfid(user_id)
            
            elif cmd[0] == "status":
                system.print_status()
            
            elif cmd[0] == "log":
                log = system.get_access_log()
                if log:
                    print("\n=== Access Log ===")
                    for entry in log:
                        status = "✓" if entry["verified"] else "✗"
                        print(f"{status} {entry['timestamp']} - {entry['user_id']}: {entry['message']}")
                else:
                    print("No access attempts yet")
            
            elif cmd[0] == "register" and len(cmd) > 2:
                user_id = cmd[1]
                image_path = cmd[2]
                system.register_user(user_id, image_path)
            
            else:
                print("Unknown command")
    
    except KeyboardInterrupt:
        print("\nInterrupt received")
    
    finally:
        system.stop()
        print("Done")


if __name__ == "__main__":
    main()
