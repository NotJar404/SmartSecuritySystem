"""
Test utilities for Smart Security System
Run individual component tests without the full system.

Usage:
  python test_components.py camera       -- live camera feed
  python test_components.py detection    -- face detection on camera
  python test_components.py register     -- enroll a new user face
  python test_components.py match        -- compare two image files
  python test_components.py verify <image> <base64_embed>  -- offline DB-match check
"""

import cv2
import sys
from AI.face_detection import FaceDetector
from AI.face_verfication import FaceVerifier


def test_camera():
    """Test camera connectivity and display live feed."""
    from Sensors.camera_module import CameraModule
    print("Testing Camera...")
    camera = CameraModule(camera_id=0)

    if not camera.initialize():
        print("X Camera failed to initialize")
        return False

    print("OK Camera initialized")
    camera.start_capture()
    print("OK Capture started -- press Q to exit")

    try:
        while True:
            frame = camera.get_frame()
            if frame is not None:
                cv2.imshow('Camera Test', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.stop_capture()
        cv2.destroyAllWindows()
        print("OK Camera test completed")

    return True


def test_face_detection():
    """Test face detection on live camera feed."""
    from Sensors.camera_module import CameraModule
    print("\nTesting Face Detection...")
    camera   = CameraModule(camera_id=0)
    detector = FaceDetector()

    if not camera.initialize():
        print("X Camera failed to initialize")
        return False

    camera.start_capture()
    print("OK Press Q to exit")

    try:
        while True:
            frame = camera.get_frame()
            if frame is not None:
                faces, _ = detector.detect_faces(frame)
                if faces:
                    print(f"Detected {len(faces)} face(s)")
                display = detector.draw_detections(frame, faces)
                cv2.imshow('Face Detection Test', display)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.stop_capture()
        cv2.destroyAllWindows()
        print("OK Face detection test completed")

    return True


def test_face_registration():
    """Enroll a new user face from the live camera (SPACE to capture)."""
    from Sensors.camera_module import CameraModule
    print("\nTesting Face Registration...")
    camera   = CameraModule(camera_id=0)
    detector = FaceDetector()
    verifier = FaceVerifier()

    if not camera.initialize():
        print("X Camera failed to initialize")
        return False

    user_id = input("Enter user ID to register: ").strip()
    if not user_id:
        print("X User ID required")
        return False

    print(f"Registering user: {user_id}")
    print("Position your face -- press SPACE to capture, Q to cancel")
    camera.start_capture()

    try:
        while True:
            frame = camera.get_frame()
            if frame is not None:
                faces, face_images = detector.detect_faces(frame)
                display = detector.draw_detections(frame, faces)

                label = "Face detected! Press SPACE to register" if faces else "Position face in camera"
                color = (0, 255, 0) if faces else (0, 0, 255)
                cv2.putText(display, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                cv2.imshow('Face Registration Test', display)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("X Registration cancelled")
                    break
                elif key == ord(' ') and faces:
                    result = verifier.register_user_face(user_id, face_images[0])
                    if result['success']:
                        print(f"OK User {user_id} registered -- encoding_b64 prefix: {result['encoding_b64'][:40]}...")
                    else:
                        print(f"X Registration failed: {result['message']}")
                    break
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.stop_capture()
        cv2.destroyAllWindows()

    return True


def test_face_matching():
    """Compare two image files using dlib ResNet 128-dim embeddings.

    Usage: python test_components.py match
    Then enter paths to two images when prompted.
    """
    print("\nTesting Face Matching (dlib ResNet)...")
    verifier = FaceVerifier()

    image1_path = input("Path to image 1 (enrolled): ").strip()
    image2_path = input("Path to image 2 (live/test): ").strip()

    try:
        img1 = cv2.imread(image1_path)
        img2 = cv2.imread(image2_path)

        if img1 is None or img2 is None:
            print("X Could not load one or both images")
            return False

        enc1, _ = verifier.extract_encoding(img1, num_jitters=5)
        enc2, _ = verifier.extract_encoding(img2, num_jitters=1)

        if enc1 is None:
            print("X No face found in image 1")
            return False
        if enc2 is None:
            print("X No face found in image 2")
            return False

        try:
            import face_recognition
            distance   = face_recognition.face_distance([enc1], enc2)[0]
            confidence = (1.0 - distance) * 100
            threshold  = (1.0 - verifier.tolerance) * 100

            print(f"\nMatching Results:")
            print(f"  Euclidean distance : {distance:.4f}")
            print(f"  Confidence         : {confidence:.1f}%")
            print(f"  Threshold          : {threshold:.1f}%  (tolerance={verifier.tolerance})")
            print(f"  Result             : {'MATCH - would GRANT' if distance < verifier.tolerance else 'NO MATCH - would DENY'}")
        except ImportError:
            print("X face_recognition not installed -- pip install face-recognition")
            return False

        return True
    except Exception as e:
        print(f"X Error: {e}")
        return False


def test_verify_embedding():
    """Offline check: compare an image against a base64 embedding from the database.
    Simulates exactly what multi-frame verification does on each frame.

    Usage:
        python test_components.py verify <image_path> <base64_embedding>

    Example (Pi):
        python test_components.py verify recordings/snapshots/debug_UID_timestamp.jpg "AAEC..."
    """
    print("\nTesting Face vs DB Embedding (offline)...")

    if len(sys.argv) < 4:
        print("Usage: python test_components.py verify <image_path> <base64_embedding>")
        print("Tip:   paste the faceEmbedding value from the ASP.NET API response")
        return False

    image_path    = sys.argv[2]
    embedding_b64 = sys.argv[3]

    verifier = FaceVerifier()

    img = cv2.imread(image_path)
    if img is None:
        print(f"X Cannot open image: {image_path}")
        return False

    enc, bbox = verifier.extract_encoding(img)
    if enc is None:
        print("X No face detected in image -- ensure face is clearly visible")
        return False
    print(f"OK Face detected  bbox={bbox}")

    stored = verifier._decode_embedding(embedding_b64)
    if stored is None:
        print("X Could not decode the embedding string -- check format (base64/JSON/JPEG)")
        return False
    print(f"OK DB embedding decoded  shape={stored.shape}")

    try:
        import face_recognition
        distance   = face_recognition.face_distance([stored], enc)[0]
        confidence = (1.0 - distance) * 100
        threshold  = (1.0 - verifier.tolerance) * 100

        print(f"\nVerification Result:")
        print(f"  Distance   : {distance:.4f}")
        print(f"  Confidence : {confidence:.1f}%  (need >= {threshold:.1f}% to GRANT)")
        print(f"  Tolerance  : {verifier.tolerance}  (edit TOLERANCE in face_verfication.py to tune)")
        verdict = "ACCESS GRANTED" if distance < verifier.tolerance else "FACE MISMATCH / DENIED"
        print(f"  Decision   : {verdict}")

        if distance >= verifier.tolerance:
            gap = distance - verifier.tolerance
            print(f"\n  Tip: distance is {gap:.4f} above threshold.")
            print(f"       Raise TOLERANCE to {verifier.tolerance + round(gap + 0.02, 2):.2f} to grant this face,")
            print(f"       or re-enroll with a clearer, well-lit photo.")

    except ImportError:
        print("X face_recognition not installed -- pip install face-recognition")
        return False

    return True


def main():
    if len(sys.argv) < 2:
        print("Smart Security System - Component Tests")
        print("\nUsage: python test_components.py <test>")
        print("\nAvailable tests:")
        print("  camera       - Live camera feed")
        print("  detection    - Face detection on camera")
        print("  register     - Enroll a new user face")
        print("  match        - Compare two image files")
        print("  verify       - Offline: image vs base64 DB embedding")
        print("                 Usage: verify <image_path> <base64_embedding>")
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
    elif test == "verify":
        test_verify_embedding()
    else:
        print(f"Unknown test: {test}")
        print("Run without arguments to see available tests.")


if __name__ == "__main__":
    main()
