import cv2
import numpy as np
import pickle
import os
from datetime import datetime
from pathlib import Path

class FaceVerifier:
    """Verifies if detected faces match RFID identity"""
    
    def __init__(self, storage_dir="face_data"):
        self.storage_dir = storage_dir
        self.orb = cv2.ORB_create(nfeatures=500)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.current_face_encoding = None
        self.current_face_timestamp = None
        self.face_match_threshold = 50  # Min matches required
        
        # Create storage directory if it doesn't exist
        Path(self.storage_dir).mkdir(parents=True, exist_ok=True)
    
    def extract_face_encoding(self, face_image):
        """
        Extract feature encoding from a face image using ORB
        
        Args:
            face_image: Face ROI extracted from frame
            
        Returns:
            Tuple of (keypoints, descriptors)
        """
        if face_image is None or face_image.size == 0:
            return None, None
        
        # Convert to grayscale if needed
        if len(face_image.shape) == 3:
            gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = face_image
        
        # Detect keypoints and compute descriptors
        kp, des = self.orb.detectAndCompute(gray, None)
        
        return kp, des
    
    def store_detected_face(self, face_image):
        """
        Store the current detected face encoding
        Called when camera detects a face
        
        Args:
            face_image: Face image from camera
            
        Returns:
            Boolean indicating success
        """
        try:
            kp, des = self.extract_face_encoding(face_image)
            
            if des is None:
                print("Could not extract features from face")
                return False
            
            self.current_face_encoding = des
            self.current_face_timestamp = datetime.now()
            print(f"Face stored at {self.current_face_timestamp}")
            return True
        except Exception as e:
            print(f"Error storing face: {e}")
            return False
    
    def verify_rfid_with_face(self, user_id):
        """
        Verify if RFID user matches the currently detected face
        Called when RFID is tapped
        
        Args:
            user_id: RFID user ID
            
        Returns:
            Dictionary with verification result and confidence
        """
        result = {
            "verified": False,
            "confidence": 0,
            "message": "",
            "user_id": user_id
        }
        
        # Check if face was recently detected
        if self.current_face_encoding is None:
            result["message"] = "No face detected in camera. Please stand in front of camera."
            return result
        
        # Check face freshness (30 seconds timeout)
        time_diff = (datetime.now() - self.current_face_timestamp).total_seconds()
        if time_diff > 30:
            result["message"] = "Face detection expired. Please stand in front of camera again."
            self.current_face_encoding = None
            return result
        
        # Get stored face encoding for this user
        stored_encoding = self.load_user_face(user_id)
        if stored_encoding is None:
            result["message"] = f"No registered face data for user {user_id}"
            return result
        
        # Compare encodings
        matches = self.bf.match(self.current_face_encoding, stored_encoding)
        matches = sorted(matches, key=lambda x: x.distance)
        
        good_matches = len([m for m in matches if m.distance < 70])
        
        if good_matches >= self.face_match_threshold:
            result["verified"] = True
            result["confidence"] = min(100, (good_matches / self.face_match_threshold) * 100)
            result["message"] = f"Identity verified! Welcome {user_id}."
        else:
            result["confidence"] = (good_matches / self.face_match_threshold) * 100
            result["message"] = f"Face does not match RFID user {user_id}. Access denied."
        
        # Clear face after verification
        self.current_face_encoding = None
        
        return result
    
    def register_user_face(self, user_id, face_image):
        """
        Register a face encoding for a user
        
        Args:
            user_id: User identifier
            face_image: Face image for registration
            
        Returns:
            Boolean indicating success
        """
        try:
            kp, des = self.extract_face_encoding(face_image)
            
            if des is None:
                print(f"Could not extract features from {user_id}'s face")
                return False
            
            # Save face encoding
            file_path = os.path.join(self.storage_dir, f"{user_id}_face.pkl")
            with open(file_path, 'wb') as f:
                pickle.dump(des, f)
            
            print(f"Face registered for user {user_id}")
            return True
        except Exception as e:
            print(f"Error registering face: {e}")
            return False
    
    def load_user_face(self, user_id):
        """
        Load stored face encoding for a user
        
        Args:
            user_id: User identifier
            
        Returns:
            Face encoding (descriptors) or None if not found
        """
        file_path = os.path.join(self.storage_dir, f"{user_id}_face.pkl")
        
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"Error loading face for user {user_id}: {e}")
            return None
    
    def get_detection_status(self):
        """Get current face detection status"""
        if self.current_face_encoding is None:
            return {"detected": False, "message": "No face detected"}
        
        time_diff = (datetime.now() - self.current_face_timestamp).total_seconds()
        return {
            "detected": True,
            "timestamp": self.current_face_timestamp.isoformat(),
            "age_seconds": time_diff
        }
