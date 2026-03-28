import cv2
import numpy as np

class FaceDetector:
    """Detects faces in frames using OpenCV"""
    
    def __init__(self):
        # Load pre-trained face detector cascade
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        self.min_face_size = (30, 30)
        self.scale_factor = 1.1
        self.min_neighbors = 5
    
    def detect_faces(self, frame):
        """
        Detect faces in a frame
        
        Args:
            frame: Input image/frame
            
        Returns:
            List of detected face rectangles [(x, y, w, h), ...]
            List of face images extracted from frame
        """
        if frame is None:
            return [], []
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=self.min_face_size
        )
        
        # Extract face regions
        face_images = []
        for (x, y, w, h) in faces:
            face_region = frame[y:y+h, x:x+w]
            face_images.append(face_region)
        
        return list(faces), face_images
    
    def draw_detections(self, frame, faces):
        """Draw bounding boxes around detected faces"""
        frame_copy = frame.copy()
        for (x, y, w, h) in faces:
            cv2.rectangle(frame_copy, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame_copy, 'Face Detected', (x, y-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        return frame_copy
