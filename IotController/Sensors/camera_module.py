import cv2
import threading
from collections import deque
from datetime import datetime

class CameraModule:
    """Handles camera capture and frame management"""
    
    def __init__(self, camera_id=0, frame_buffer_size=10):
        self.camera_id = camera_id
        self.cap = None
        self.frame_buffer = deque(maxlen=frame_buffer_size)
        self.latest_frame = None
        self.is_running = False
        self.lock = threading.Lock()
        
    def initialize(self):
        """Initialize camera"""
        try:
            self.cap = cv2.VideoCapture(self.camera_id)
            if not self.cap.isOpened():
                raise Exception(f"Failed to open camera {self.camera_id}")
            # Set camera properties for better performance
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            return True
        except Exception as e:
            print(f"Camera initialization error: {e}")
            return False
    
    def start_capture(self):
        """Start camera capture in background thread"""
        if self.is_running:
            return
        self.is_running = True
        capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        capture_thread.start()
    
    def _capture_loop(self):
        """Continuous frame capture loop"""
        while self.is_running:
            try:
                ret, frame = self.cap.read()
                if ret:
                    with self.lock:
                        self.latest_frame = frame
                        self.frame_buffer.append(frame)
            except Exception as e:
                print(f"Capture error: {e}")
    
    def get_latest_frame(self):
        """Get the most recent frame"""
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None
    
    def get_frame_buffer(self):
        """Get all frames in buffer"""
        with self.lock:
            return list(self.frame_buffer)
    
    def stop_capture(self):
        """Stop camera capture"""
        self.is_running = False
        if self.cap:
            self.cap.release()
    
    def save_frame(self, filename):
        """Save current frame to file"""
        frame = self.get_latest_frame()
        if frame is not None:
            cv2.imwrite(filename, frame)
            return True
        return False
