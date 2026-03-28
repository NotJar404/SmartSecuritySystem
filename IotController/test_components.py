"""
Test utilities for Smart Security System
Run individual component tests without the full system
"""

import cv2
import sys
from Sensors.camera_module import CameraModule
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier


def test_camera():
    """Test camera connectivity and display live feed"""
    print("Testing Camera...")
    camera = CameraModule(camera_id=0)
    
    if not camera.initialize():
        print("✗ Camera failed to initialize")
        return False
    
    print("✓ Camera initialized")
    camera.start_capture()
    print("✓ Capture started")
    print("Press 'q' to exit camera test")
    
    try:
        while True:
            frame = camera.get_latest_frame()
            if frame is not None:
                cv2.imshow('Camera Test', frame)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print("Waiting for frames...")
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.stop_capture()
        cv2.destroyAllWindows()
        print("✓ Camera test completed")
    
    return True


def test_face_detection():
    """Test face detection on camera feed"""
    print("\nTesting Face Detection...")
    camera = CameraModule(camera_id=0)
    detector = FaceDetector()
    
    if not camera.initialize():
        print("✗ Camera failed to initialize")
        return False
    
    print("✓ Camera initialized")
    camera.start_capture()
    print("Press 'q' to exit face detection test")
    
    try:
        while True:
            frame = camera.get_latest_frame()
            if frame is not None:
                faces, face_images = detector.detect_faces(frame)
                
                if faces:
                    print(f"Detected {len(faces)} face(s)")
                
                # Draw detections
                display_frame = detector.draw_detections(frame, faces)
                cv2.imshow('Face Detection Test', display_frame)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print("Waiting for frames...")
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.stop_capture()
        cv2.destroyAllWindows()
        print("✓ Face detection test completed")
    
    return True


def test_face_registration():
    """Test registering a face"""
    print("\nTesting Face Registration...")
    camera = CameraModule(camera_id=0)
    detector = FaceDetector()
    verifier = FaceVerifier()
    
    if not camera.initialize():
        print("✗ Camera failed to initialize")
        return False
    
    user_id = input("Enter user ID to register: ").strip()
    if not user_id:
        print("✗ User ID required")
        return False
    
    print(f"Registering user: {user_id}")
    print("Position your face in the camera and press SPACE to capture")
    print("Press 'q' to exit without registering")
    
    camera.start_capture()
    
    try:
        while True:
            frame = camera.get_latest_frame()
            if frame is not None:
                faces, face_images = detector.detect_faces(frame)
                display_frame = detector.draw_detections(frame, faces)
                
                if faces:
                    cv2.putText(display_frame, "Face detected! Press SPACE to register", 
                               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                else:
                    cv2.putText(display_frame, "Position face in camera", 
                               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                
                cv2.imshow('Face Registration Test', display_frame)
                
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("✗ Registration cancelled")
                    break
                elif key == ord(' ') and faces:
                    # Register the user
                    if verifier.register_user_face(user_id, face_images[0]):
                        print(f"✓ User {user_id} registered successfully")
                        break
                    else:
                        print("✗ Failed to register user")
                        break
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.stop_capture()
        cv2.destroyAllWindows()
    
    return True


def test_face_matching():
    """Test face matching between two images"""
    print("\nTesting Face Matching...")
    verifier = FaceVerifier()
    
    image1_path = input("Enter path to first face image: ").strip()
    image2_path = input("Enter path to second face image: ").strip()
    
    try:
        face1 = cv2.imread(image1_path)
        face2 = cv2.imread(image2_path)
        
        if face1 is None or face2 is None:
            print("✗ Could not load images")
            return False
        
        # Extract encodings
        kp1, des1 = verifier.extract_face_encoding(face1)
        kp2, des2 = verifier.extract_face_encoding(face2)
        
        if des1 is None or des2 is None:
            print("✗ Could not extract features from images")
            return False
        
        # Match
        matches = verifier.bf.match(des1, des2)
        matches = sorted(matches, key=lambda x: x.distance)
        
        good_matches = len([m for m in matches if m.distance < 70])
        confidence = (good_matches / verifier.face_match_threshold) * 100
        
        print(f"\nMatching Results:")
        print(f"Total matches: {len(matches)}")
        print(f"Good matches (distance < 70): {good_matches}")
        print(f"Confidence: {confidence:.1f}%")
        print(f"Match threshold: {verifier.face_match_threshold}")
        
        if good_matches >= verifier.face_match_threshold:
            print("✓ FACES MATCH")
        else:
            print("✗ FACES DO NOT MATCH")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Smart Security System - Component Tests")
        print("\nUsage: python test_components.py <test>")
        print("\nAvailable tests:")
        print("  camera       - Test camera feed")
        print("  detection    - Test face detection on camera")
        print("  register     - Register a new user face")
        print("  match        - Test face matching between two images")
        return
    
    test = sys.argv[1].lower()
    
    if test == "camera":
        test_camera()
    elif test == "detection":
        test_face_detection()
    elif test == "register":
        test_face_registration()
    elif test == "match":
        test_face_matching()
    else:
        print(f"Unknown test: {test}")


if __name__ == "__main__":
    main()
