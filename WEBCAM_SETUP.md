# Webcam Integration Guide

## Overview

Your Smart Security System now has full webcam integration for both the **Cameras** and **Dashboard** pages. This allows you to test the AI detection system using your laptop's webcam.

## How to Enable Webcam in Cameras

### Option 1: Add a New Camera (Webcam Test Mode)
1. Go to **Cameras** page
2. Click **+ Add Camera** button
3. Fill in the form:
   - **Camera Name**: Any name (e.g., "Laptop Webcam Test")
   - **Location**: Any location (e.g., "Desk")
   - **Room**: Select a room
   - **Stream URL**: **Leave this EMPTY** to use your webcam
4. Click **Save**
5. Click on the camera in the grid view to open the focus view
6. Your webcam will activate and show a **WEBCAM** badge

### Option 2: Use Existing Stream URL
- If you provide a stream URL (RTSP, HTTP, HLS), the system will use that
- If the URL fails, it will automatically fall back to your webcam
- Both **Cameras** and **Dashboard** support this fallback

### Option 3: Check Permissions
If you see an error message:
- **"Webcam access denied"**: Check browser permissions in Settings
- **"No webcam found"**: Your device may not have a camera
- **"Webcam is in use"**: Another application has exclusive access

## How to Check if Webcam is Active

### Visual Indicators:
1. **WEBCAM badge** - Purple badge in top-right of camera card
2. **Purple border** - Camera cards with webcam have a subtle purple tint
3. **Source indicator** - Focus view shows "📱 Local Webcam (TEST MODE)" in overlay
4. **Detection status** - Browser-based AI detection activates automatically for webcam

### In the Grid View:
- Webcam cameras show the **WEBCAM** badge with a laptop icon
- Animation pulses gently to indicate active stream

### In the Focus View:
- Overlay text shows source: "📱 Local Webcam (TEST MODE — AI Detection Active)"
- Face detection bounding boxes appear in real-time
- People counter updates based on detected faces

## AI Detection with Webcam

When using your laptop's webcam, the following AI features are **automatically active**:

1. **Face Detection** - Detects human faces in the frame
2. **Face Counting** - Counts people present (occupancy)
3. **Confidence Scoring** - Shows detection confidence percentage
4. **Bounding Boxes** - Green boxes for confident detections, yellow for weak ones

### Detection Data:
- Detections are logged to the database
- Occupancy counts update in real-time
- Alerts trigger based on configured thresholds

## Dashboard Camera Feed

The Dashboard also displays camera feeds (grid view at top):

1. **Grid cards** show live feeds from all cameras
2. If a camera has no stream URL, it uses your webcam
3. Click a camera card to navigate to the full Cameras view
4. All webcam features work on the Dashboard as well

## Browser Permissions

### Required Permissions:
1. **Microphone/Webcam Access**: 
   - Chrome/Edge: Look for camera icon in address bar
   - Firefox: Browser menu → Permissions
   - Safari: System Preferences → Security & Privacy → Camera

### Grant Permissions:
1. When prompted, click **Allow** for camera access
2. If blocked, reset permissions:
   - Chrome: Settings → Privacy → Clear browsing data → All time
   - Or: Restart browser after resetting site permissions

## Testing Webcam Features

### Test the Detection System:
1. Add a camera with empty Stream URL
2. Open in focus view
3. Click the camera card to load your webcam
4. Verify you see:
   - Video stream from your webcam
   - "WEBCAM TEST MODE" indicator
   - Bounding boxes around faces
   - People count in AI status panel

### Verify Real-Time Updates:
1. Move in front of the webcam
2. Check that face detection responds
3. Verify occupancy count updates
4. Check that detection data is logged in the database

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Webcam won't load | Check browser permissions, restart browser |
| No detection boxes | Ensure face-api models are loaded (check console) |
| Black video screen | Try adding explicit camera permissions in OS settings |
| Stream works, want webcam | Edit camera and clear the Stream URL field |
| Want to use stream, not webcam | Add a valid Stream URL to camera settings |

## Stream URLs Supported

### Local Network (Recommended):
```
rtsp://192.168.1.100:554/stream
http://192.168.1.100:8080/stream
```

### Raspberry Pi with Camera Module:
```
http://raspberry-pi-ip:8081/stream
```

### OBS or Other Streaming Software:
```
http://localhost:8080/stream
rtmp://server:1935/stream
```

### HLS Streams (.m3u8):
```
http://server/playlist.m3u8
```

## Performance Notes

- **Webcam**: ~30 FPS, excellent for testing
- **Network Streams**: Depends on source and bandwidth
- **AI Detection**: Runs every 2 seconds for efficiency
- **Multi-Camera**: Each camera can use webcam or stream

## Security Notes

- Webcam access is **browser-based only** (runs on your machine)
- No video is sent to cloud unless configured
- Permission is required each session
- Disable webcam in browser settings if not in use

## Next Steps

1. ✅ Add a test camera with empty Stream URL
2. ✅ Grant webcam permission when prompted
3. ✅ Verify detection works in focus view
4. ✅ Replace with real stream URLs when ready
5. ✅ Deploy to Raspberry Pi cameras for production use
