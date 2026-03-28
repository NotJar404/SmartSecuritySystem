# Smart Security System - Camera + RFID Verification

## Overview
This system integrates camera-based face detection with RFID verification to create a secure access control system. When a person is detected by the camera, their face is captured. When the person taps their RFID, the system verifies if the RFID belongs to the detected person.

## System Flow

```
1. Camera continuously monitors for faces
   ↓
2. When a person is detected, face encoding is extracted and stored (30-second window)
   ↓
3. Person taps RFID card/tag
   ↓
4. System compares face detected by camera with the registered face for that RFID user
   ↓
5. If match: ACCESS GRANTED ✓
   If no match: ACCESS DENIED ✗
```

## Architecture

### Components

#### 1. **camera_module.py** - Camera Hardware Interface
- Initializes and manages camera capture
- Runs continuous frame capture in background thread
- Provides thread-safe access to latest frames
- Maintains frame buffer for processing

#### 2. **face_detection.py** - Face Detection Engine
- Uses OpenCV's Haar Cascade classifier
- Detects faces in video frames
- Extracts face regions from detected faces
- Draws bounding boxes for visualization

#### 3. **face_verfication.py** - Face Verification & Recognition
- Extracts feature encodings from faces using ORB (Oriented FAST and Rotated BRIEF)
- Stores detected face encoding when camera detects a person (max 30 seconds)
- When RFID is tapped, compares stored face with registered user face
- Returns verification result with confidence score
- Manages user registration and face data persistence

#### 4. **rfid_reader.py** - RFID Input Module
- Connects to RFID reader via serial port
- Runs background thread for continuous RFID reading
- Provides simulated RFID mode for testing without hardware
- Triggers callback when RFID is read

#### 5. **main.py** - System Orchestration
- Initializes all components
- Runs continuous face detection loop
- Handles RFID tap events and triggers verification
- Maintains access log
- Provides command-line interface for testing

## Setup & Installation

### Prerequisites
- Python 3.8+
- USB Camera (or any OpenCV-compatible camera)
- RFID Reader (optional - system has simulation mode)

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure RFID reader port (if using hardware):
   - Edit `rfid_reader.py` line with `port='COM3'` to match your RFID reader port
   - On Windows: COM3, COM4, etc.
   - On Linux/Mac: /dev/ttyUSB0, /dev/ttyACM0, etc.

## Usage

### Running the System

```bash
python main.py
```

The system starts in simulated RFID mode for easy testing.

### Commands

**Test RFID Tap** (Simulate RFID without hardware):
```
test USER123
```
The system will:
1. Check if a face was recently detected by camera
2. Compare the detected face with USER123's registered face
3. Grant or deny access based on match

**Register a New User**:
```
register USER123 /path/to/face-image.jpg
```
This registers USER123 with their face image. Later, when they stand in front of camera and tap RFID, the system will verify them.

**Show System Status**:
```
status
```
Displays current system state and recent access attempts.

**View Access Log**:
```
log
```
Shows all access attempts with timestamps, results, and confidence scores.

**Exit**:
```
quit
```

## Face Verification Algorithm

1. **Feature Extraction**: Uses ORB (Oriented FAST and Rotated BRIEF) algorithm
   - Fast and rotation-invariant feature detection
   - Extracts keypoints and binary descriptors from face image

2. **Matching**: BFMatcher (Brute Force Matcher)
   - Matches features between detected face and registered face
   - Counts good matches (distance < 70)

3. **Threshold**: Requires minimum 50 good matches to verify
   - Adjustable via `face_match_threshold` in `face_verfication.py`
   - Higher threshold = stricter verification
   - Lower threshold = more lenient

4. **Confidence Score**: (good_matches / threshold) × 100%
   - Indicates how strong the face match is

5. **Timeout**: Detected face is valid for 30 seconds
   - User must tap RFID within 30 seconds of being detected
   - Prevents verification of wrong person if multiple people in frame

## File Structure

```
IotController/
├── main.py ......................... System orchestration & CLI
├── requirements.txt ................ Python dependencies
│
├── AI/
│   ├── face_detection.py ........... Face detector using Haar Cascade
│   └── face_verfication.py ........ Face verification & matching
│
└── Sensors/
    ├── camera_module.py ........... Camera interface & capture
    ├── rfid_reader.py ............. RFID reader interface
    ├── pir_sensor.py .............. (Motion sensor - future)
    └── lock_sensor.py ............. (Door lock - future)
```

## Example Workflow

1. **Start System**:
   ```
   python main.py
   ```

2. **Register User**:
   ```
   register USER123 ./user_photo.jpg
   ```

3. **Verify User**:
   - User stands in front of camera (faces camera)
   - User taps RFID card
   - System detects face, compares with USER123's face
   - If match: "✓ ACCESS GRANTED - Identity confirmed!"
   - If no match: "✗ ACCESS DENIED - Face does not match RFID!"

## Advanced Configuration

### Adjust Face Matching Sensitivity

In `face_verfication.py`, modify:

```python
self.face_match_threshold = 50  # Minimum matches required

# Lower = More lenient:
self.face_match_threshold = 30  # More people match

# Higher = Stricter:
self.face_match_threshold = 80  # Fewer false positives
```

### Adjust Face Detection

In `face_detection.py`, modify:

```python
self.scale_factor = 1.1      # How much image size is reduced per scale (1.05-1.4)
self.min_neighbors = 5       # Detections required to detect face (4-6)
self.min_face_size = (30, 30) # Minimum face size to detect
```

### Change Face Timeout

In `face_verfication.py`, modify:

```python
time_diff > 30  # Change from 30 seconds to desired timeout
```

## Performance Tips

1. **Better Lighting**: More reliable face detection in good lighting
2. **Face Position**: Ensure face is centered and clear in camera view
3. **Camera Resolution**: Higher resolution = better accuracy (currently 640x480)
4. **Multiple Registration**: Register faces in different lighting/angles for better robustness

## Integration with WebApp

The IoT system can send verification results to the WebApp via:
- HTTP REST API endpoints
- WebSocket for real-time updates
- Database logging

See `WebApp/` for the C# backend integration points.

## Troubleshooting

**No face detected?**
- Ensure good lighting
- Check camera is connected
- Verify camera works (test with `test_camera.py`)
- Adjust `min_neighbors` and `scale_factor` in face_detection.py

**RFID not reading?**
- Check RFID reader serial port (adjust `port='COMx'`)
- Verify RFID device is connected
- Test with `test rfid <user_id>` command

**Face verification always fails?**
- Lower `face_match_threshold` for more lenient matching
- Re-register user with better quality front-facing photo
- Check face is not obscured or partially off-camera

## Future Enhancements

- [ ] Multi-face detection (handle multiple people)
- [ ] Temperature sensor integration
- [ ] Better face encoding (use deep learning like face_recognition library)
- [ ] Database integration for user management
- [ ] Event notifications via WebApp
- [ ] Logging to SQL Server
- [ ] Two-factor authentication
