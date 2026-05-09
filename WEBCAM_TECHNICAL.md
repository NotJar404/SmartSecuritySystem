# Webcam Integration - Technical Implementation

## Architecture

### Files Modified/Created

1. **New File**: `wwwroot/js/webcam-stream-loader.js`
   - Centralized webcam/stream loading logic
   - Handles error cases gracefully
   - Provides callbacks for success/error scenarios

2. **Modified**: `Views/Cameras/Index.cshtml`
   - Added script reference to `webcam-stream-loader.js`
   - Updated grid initialization to use new loader
   - Updated `selectCamera()` to properly handle webcam vs. streams
   - Added camera source indicator in overlay

3. **Modified**: `Views/Dashboard/Index.cshtml`
   - Added script reference to `webcam-stream-loader.js`
   - Replaced inline camera loading with loader function
   - Added HLS support with fallback to webcam

4. **Modified**: `wwwroot/css/camera.css`
   - Added `.webcam-badge` styling
   - Added `.video-error-overlay` styling
   - Added `.is-webcam-stream` indicator class
   - Added `.webcam-loading` animation

## How It Works

### Cameras View (Focus View)

```
User clicks camera card
    ↓
selectCamera(cam) function called
    ↓
Check if StreamUrl exists?
    ├─ YES → loadVideoStream(url)
    │   ├─ URL is valid
    │   ├─ Load stream
    │   └─ Set overlay to "🎥 Network Stream"
    │
    └─ NO → loadWebcam()
        ├─ Request getUserMedia()
        ├─ Set overlay to "📱 Webcam (TEST MODE)"
        └─ Initialize face detection
```

### Cameras View (Grid View)

```
Page loads
    ↓
DOM ready event
    ↓
Find all .grid-preview video elements
    ↓
For each video element:
    ├─ Get data-src attribute
    ├─ If URL provided → loadStream()
    └─ If empty → loadWebcam()
    
Result: Each card shows live stream or webcam
```

### Dashboard View

```
Page loads
    ↓
DOM ready event
    ↓
Find all .cctv-video elements
    ↓
For each video:
    ├─ Get data-src attribute
    ├─ If HLS (.m3u8) → Load via Hls.js
    ├─ If URL → Direct src assignment
    └─ If empty → Request webcam
    
Result: Filmstrip shows live feeds
```

## Key Functions in webcam-stream-loader.js

### `loadVideoStream(videoElement, streamUrl, options)`
Main entry point for loading any video source.

**Parameters:**
- `videoElement`: HTMLVideoElement to load into
- `streamUrl`: Stream URL (empty string for webcam)
- `options`: Configuration object

**Options:**
```javascript
{
    onSuccess: (info) => {},      // Called when stream loads successfully
    onError: (error) => {},       // Called on error
    onWebcam: (info) => {},       // Called specifically for webcam
    fallbackToWebcam: true,       // Fallback to webcam if stream fails
    enableHLS: true               // Support HLS streams
}
```

**Returns:**
```javascript
// onSuccess callback receives:
{
    type: 'stream' | 'hls' | 'webcam',
    url: string,
    stream: MediaStream (webcam only)
}
```

### `loadWebcam(videoElement, options)`
Requests user's camera and loads stream.

**Behavior:**
- Requests permission (browser prompts user)
- Reuses stream if already granted
- Handles multiple video elements efficiently
- Adds CSS class `is-webcam-stream` for styling

### `stopAllWebcamStreams()`
Gracefully stops all active webcam streams and releases resources.

### `getVideoInfo(videoElement)`
Returns information about what's loaded in a video element.

**Returns:**
```javascript
{
    isWebcam: boolean,
    type: 'webcam' | 'stream',
    url: string,
    hasStream: boolean
}
```

## Error Handling

### Webcam Errors

| Error | Browser Name | Message | Fallback |
|-------|--------------|---------|----------|
| Permission denied | NotAllowedError | "Webcam access denied" | Show error |
| No camera | NotFoundError | "No webcam found" | Show error |
| In use | NotReadableError | "Webcam in use by another app" | Show error |

### Stream Errors

| Error | Response | Fallback |
|-------|----------|----------|
| Invalid URL | Stream fails to play | Fallback to webcam |
| Network unavailable | HLS error event | Fallback to webcam |
| Permissions blocked | getUserMedia fails | Show error |

## CSS Classes Added

### `.webcam-badge`
Purple pulsing badge showing webcam is in use.

```html
<span class="webcam-badge">
    <i class="fas fa-laptop"></i> WEBCAM
</span>
```

### `.is-webcam-stream`
Applied to video elements using webcam.

```css
.is-webcam-stream {
    border: 2px solid rgba(102, 126, 234, 0.3);
}
```

### `.video-error-overlay`
Overlay shown when video fails to load.

```html
<div class="video-error-overlay">
    <div class="video-error-content">
        <i class="fas fa-exclamation-circle"></i>
        <p>Error message here</p>
    </div>
</div>
```

## Integration with AI Detection

When webcam is loaded in focus view:

```javascript
// In selectCamera():
if (info.type === 'webcam') {
    // Start browser-based face detection
    initWebcamDetection(video, cam.Id, cam.RoomId);
}
```

This triggers the existing `camera-detect.js` which:
- Loads face-api models
- Detects faces every 2 seconds
- Updates occupancy count
- Sends detection logs to backend
- Draws bounding boxes on canvas overlay

## Performance Considerations

### Webcam Stream
- Uses hardware acceleration (browser native)
- ~30 FPS typical
- Minimal CPU usage
- Battery efficient (mobile)

### AI Detection Loop
- Runs every 2 seconds (not every frame)
- Processes full video resolution
- Face detection: ~100-200ms per frame
- Results cached for stability

### Grid Preview Video Elements
- All use single shared webcam stream (if needed)
- Reuses MediaStream for efficiency
- Auto-pauses when focus view opens

## Browser Compatibility

### Supported Browsers
- ✅ Chrome 50+
- ✅ Edge 79+
- ✅ Firefox 55+
- ✅ Safari 11+
- ✅ Opera 37+

### Required Features
- `getUserMedia()` API
- `MediaStream` support
- `WebGL` for face detection

### Feature Detection
```javascript
const hasUserMedia = navigator.mediaDevices?.getUserMedia;
const hasFaceAPI = typeof faceapi !== 'undefined';
```

## Logging

Detailed console logs help with debugging:

```
[StreamLoader] Initializing 4 video elements
[StreamLoader] Loading stream: http://192.168.1.100:8080
[StreamLoader] Stream loaded: {type: 'stream', url: ...}
[StreamLoader] Requesting webcam access
[StreamLoader] Webcam access granted
[StreamLoader] All webcam streams stopped
```

## Database Integration

When using webcam in focus view:

1. **Occupancy Updates**: Pushed every 15s if count changes
   - Endpoint: `/Cameras/UpdateOccupancy`
   - Data: `{CameraId, PeopleCount}`

2. **Detection Logs**: Pushed on state change
   - Endpoint: `/Cameras/PushDetection`
   - Data: `{CameraId, DetectionType, DetectedCount, Confidence}`

3. **Detection Types**: 
   - `face_detected` - Face with >60% confidence
   - `no_face` - No faces or <60% confidence
   - `unknown_face`, `verified_face` - Classified faces

## Configuration

### Enable/Disable Features

To disable webcam fallback:
```javascript
loadVideoStream(video, url, { fallbackToWebcam: false });
```

To require authentication for webcam:
```javascript
// Modify selectCamera() to prompt
if (User.IsInRole("Admin") || User.IsInRole("Security")) {
    loadWebcam(...);
}
```

To auto-start webcam on page load:
```javascript
// In initializeVideoElements
loadVideoStream(video, '', { /* force webcam */ });
```

## Testing Checklist

- [ ] Webcam loads when StreamUrl is empty
- [ ] Face detection activates for webcam in focus view
- [ ] Detection overlays show bounding boxes
- [ ] Occupancy counter updates in real-time
- [ ] Dashboard shows webcam in grid cards
- [ ] Browser permissions prompt appears
- [ ] Error messages show if permission denied
- [ ] System falls back to webcam if stream fails
- [ ] Multiple cameras can use different sources
- [ ] Page unload properly cleans up webcam stream
