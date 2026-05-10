/* 
=====================================================
WEBCAM FACE DETECTION (BROWSER-SIDE)

YOLO-STYLE OVERLAY ENGINE FOR TEST MODE:
- Draws bounding boxes matching Pi's overlay style
- Color-coded: GREEN (authorized), RED (unauthorized), YELLOW (unknown)
- Tracking ID labels with confidence percentage
- State-based push (anti-spam)
- Session-aware occupancy tracking
- Waits for face-api.js to load (handles defer timing)
=====================================================
*/

let faceDetectionActive = false;
let detectionCanvas = null;
let detectionInterval = null;
let modelsLoaded = false;
let detectionInitialized = false;  // Prevent double-init
let usingMJPEGStream = false;  // Track if using Python backend MJPEG

let activeCameraId = null;
let activeRoomId = null;

/* =========================
   STATE CONTROL (ANTI-SPAM)
========================= */
let lastFaceCount = -1;
let lastDetectionType = '';
let lastDetectionPush = 0;
let lastOccupancyPush = 0;
let lastOccupancyCount = -1;

const DETECTION_COOLDOWN = 10000;   // 10 seconds minimum between same-state pushes
const OCCUPANCY_COOLDOWN = 15000;   // 15 seconds minimum between occupancy pushes
const STABILITY_REQUIRED = 3;       // Require 3 stable frames before pushing

/* STABILITY FILTER (ANTI-FLICKER) */
let stableFaceCount = 0;
let stabilityFrames = 0;

/* =========================
   INIT (with defer-safe retry)
========================= */
async function initWebcamDetection(videoElement, cameraId, roomId, isMJPEGStream = false) {
    // Prevent double-init from both onSuccess and onWebcam callbacks
    if (detectionInitialized && activeCameraId === cameraId) {
        console.log('[DETECT] Already initialized for camera', cameraId);
        return;
    }

    activeCameraId = cameraId;
    activeRoomId = roomId;
    usingMJPEGStream = isMJPEGStream;
    
    console.log('[DETECT] Initializing for camera ID:', cameraId, '- MJPEG Stream:', isMJPEGStream);
    
    // Skip browser-side detection if using MJPEG stream from Python backend
    // The backend already renders the bounding boxes and the polling fetches detection data
    if (isMJPEGStream) {
        console.log('[DETECT] Using MJPEG stream from Python backend - skipping browser-side detection');
        console.log('[DETECT] Detection data will be fetched via polling and displayed in focus panel');
        detectionInitialized = true;
        // Clear canvas since backend handles overlays
        clearOverlayCanvas();
        return;
    }

    detectionInitialized = true;

    if (!detectionCanvas) {
        detectionCanvas = document.createElement('canvas');
    }

    // Wait for face-api.js to load (it uses defer attribute)
    await waitForFaceApi();

    if (!modelsLoaded && typeof faceapi !== 'undefined') {
        try {
            console.log('[DETECT] Loading face detection model...');
            const MODEL_URL =
                'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/model';

            await faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL);
            modelsLoaded = true;
            console.log('[DETECT] Model loaded successfully');
        } catch (e) {
            console.log('[DETECT] Model load failed:', e);
        }
    }

    startDetectionLoop(videoElement);
}

/**
 * Wait for face-api.js to be available (handles defer loading)
 */
function waitForFaceApi() {
    return new Promise((resolve) => {
        if (typeof faceapi !== 'undefined') {
            resolve();
            return;
        }
        let attempts = 0;
        const check = setInterval(() => {
            attempts++;
            if (typeof faceapi !== 'undefined' || attempts > 50) {
                clearInterval(check);
                if (typeof faceapi !== 'undefined') {
                    console.log('[DETECT] face-api.js loaded after', attempts * 100, 'ms');
                } else {
                    console.warn('[DETECT] face-api.js not available after 5s');
                }
                resolve();
            }
        }, 100);
    });
}

/* =========================
   DETECTION LOOP (YOLO-STYLE)
========================= */
function startDetectionLoop(videoElement) {
    if (detectionInterval) clearInterval(detectionInterval);
    faceDetectionActive = true;

    detectionInterval = setInterval(async () => {
        if (!faceDetectionActive || videoElement.paused || videoElement.ended) return;
        if (videoElement.videoWidth === 0) return;

        let faceCount = 0;
        let detectionType = 'no_face';
        let confidence = 0;

        /* =========================
           FACE DETECTION + OVERLAY RENDERING
        ========================= */
        if (modelsLoaded && typeof faceapi !== 'undefined') {
            try {
                const detections = await faceapi.detectAllFaces(
                    videoElement,
                    new faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.5 })
                );

                faceCount = detections.length;

                // Draw YOLO-style bounding box overlays on canvas
                drawDetectionOverlays(videoElement, detections);

                if (faceCount > 0) {
                    confidence = detections[0].score;

                    if (confidence >= 0.6) {
                        detectionType = 'face_detected';
                    } else {
                        faceCount = 0;
                        detectionType = 'no_face';
                    }
                }

            } catch (e) {
                console.log('[DETECT ERROR]', e);
            }
        } else {
            // Model not loaded yet — clear any stale overlays
            clearOverlayCanvas();
        }

        /* =========================
           STABILITY FILTER (ANTI-FLICKER)
        ========================= */
        if (faceCount === stableFaceCount) {
            stabilityFrames++;
        } else {
            stabilityFrames = 0;
        }

        stableFaceCount = faceCount;

        if (stabilityFrames < STABILITY_REQUIRED) {
            updateLocalDetectionUI(faceCount, detectionType, confidence);
            return;
        }

        const now = Date.now();

        /* =========================
           DETECTION PUSH (STATE-CHANGE ONLY)
        ========================= */
        const detectionChanged = detectionType !== lastDetectionType;
        const detectionCooldownPassed = (now - lastDetectionPush) > DETECTION_COOLDOWN;

        if (activeCameraId && detectionChanged && detectionCooldownPassed) {
            pushDetection(activeCameraId, detectionType, faceCount, confidence);
            lastDetectionType = detectionType;
            lastFaceCount = faceCount;
            lastDetectionPush = now;
            console.log(`[DETECT] State change: ${detectionType} (${faceCount} faces)`);
        }

        /* =========================
           OCCUPANCY PUSH (CHANGE-ONLY)
        ========================= */
        const occupancyChanged = faceCount !== lastOccupancyCount;
        const occupancyCooldownPassed = (now - lastOccupancyPush) > OCCUPANCY_COOLDOWN;

        if (activeCameraId && occupancyChanged && occupancyCooldownPassed) {
            pushOccupancy(activeCameraId, faceCount);
            lastOccupancyCount = faceCount;
            lastOccupancyPush = now;
            console.log(`[OCCUPANCY] Count changed: ${faceCount}`);
        }

        updateLocalDetectionUI(faceCount, detectionType, confidence);

    }, 2000);
}

/* =========================
   YOLO-STYLE BOUNDING BOX RENDERER
   Matches Pi main.py overlay style:
   - Green boxes for high confidence
   - Yellow boxes for low confidence
   - Label with ID + confidence %
   - Filled label background
========================= */
function drawDetectionOverlays(videoElement, detections) {
    const overlayCanvas = document.getElementById('detectOverlay');
    if (!overlayCanvas) return;

    // Match canvas internal resolution to video dimensions
    overlayCanvas.width = videoElement.videoWidth;
    overlayCanvas.height = videoElement.videoHeight;
    const ctx = overlayCanvas.getContext('2d');
    ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    if (detections.length === 0) return;

    detections.forEach((det, i) => {
        const box = det.box;
        const score = det.score;
        const pct = Math.round(score * 100);
        const isReliable = score >= 0.6;

        // Color coding matching Pi pipeline:
        // GREEN = reliable detection (authorized equivalent)
        // YELLOW = weak detection (unknown equivalent)
        const boxColor = isReliable ? '#10b981' : '#f59e0b';
        const bgColor = isReliable ? 'rgba(16,185,129,0.85)' : 'rgba(245,158,11,0.85)';

        // === BOUNDING BOX ===
        ctx.strokeStyle = boxColor;
        ctx.lineWidth = 2;
        ctx.strokeRect(box.x, box.y, box.width, box.height);

        // === CORNER ACCENTS (YOLO-style) ===
        const cornerLen = Math.min(20, box.width * 0.2, box.height * 0.2);
        ctx.strokeStyle = boxColor;
        ctx.lineWidth = 3;

        // Top-left corner
        ctx.beginPath();
        ctx.moveTo(box.x, box.y + cornerLen);
        ctx.lineTo(box.x, box.y);
        ctx.lineTo(box.x + cornerLen, box.y);
        ctx.stroke();

        // Top-right corner
        ctx.beginPath();
        ctx.moveTo(box.x + box.width - cornerLen, box.y);
        ctx.lineTo(box.x + box.width, box.y);
        ctx.lineTo(box.x + box.width, box.y + cornerLen);
        ctx.stroke();

        // Bottom-left corner
        ctx.beginPath();
        ctx.moveTo(box.x, box.y + box.height - cornerLen);
        ctx.lineTo(box.x, box.y + box.height);
        ctx.lineTo(box.x + cornerLen, box.y + box.height);
        ctx.stroke();

        // Bottom-right corner
        ctx.beginPath();
        ctx.moveTo(box.x + box.width - cornerLen, box.y + box.height);
        ctx.lineTo(box.x + box.width, box.y + box.height);
        ctx.lineTo(box.x + box.width, box.y + box.height - cornerLen);
        ctx.stroke();

        // === LABEL BACKGROUND ===
        const label = `ID:${i + 1} [${pct}%]`;
        ctx.font = 'bold 13px Inter, system-ui, sans-serif';
        const textWidth = ctx.measureText(label).width;
        const labelH = 22;

        ctx.fillStyle = bgColor;
        ctx.fillRect(box.x, box.y - labelH, textWidth + 12, labelH);

        // === LABEL TEXT ===
        ctx.fillStyle = '#fff';
        ctx.fillText(label, box.x + 6, box.y - 6);

        // === STATUS INDICATOR (bottom of box) ===
        const statusLabel = isReliable ? 'DETECTED' : 'WEAK';
        const statusW = ctx.measureText(statusLabel).width;
        ctx.fillStyle = bgColor;
        ctx.fillRect(box.x, box.y + box.height, statusW + 12, 20);
        ctx.fillStyle = '#fff';
        ctx.font = '11px Inter, system-ui, sans-serif';
        ctx.fillText(statusLabel, box.x + 6, box.y + box.height + 14);
    });

    // === DETECTION COUNT OVERLAY (top-right) ===
    const reliableCount = detections.filter(d => d.score >= 0.6).length;
    if (reliableCount > 0) {
        const countLabel = `${reliableCount} Person${reliableCount > 1 ? 's' : ''} Detected`;
        ctx.font = 'bold 14px Inter, system-ui, sans-serif';
        const cw = ctx.measureText(countLabel).width;

        ctx.fillStyle = 'rgba(16,185,129,0.9)';
        ctx.fillRect(overlayCanvas.width - cw - 20, 8, cw + 16, 26);

        ctx.fillStyle = '#fff';
        ctx.fillText(countLabel, overlayCanvas.width - cw - 12, 26);
    }
}

/* =========================
   CLEAR OVERLAY CANVAS
========================= */
function clearOverlayCanvas() {
    const overlayCanvas = document.getElementById('detectOverlay');
    if (overlayCanvas) {
        const ctx = overlayCanvas.getContext('2d');
        ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    }
}

/* =========================
   STOP DETECTION
========================= */
function stopDetection() {
    faceDetectionActive = false;
    detectionInitialized = false;

    if (detectionInterval) {
        clearInterval(detectionInterval);
        detectionInterval = null;
    }

    clearOverlayCanvas();
    
    // Stop Python backend webcam if it's running
    if (usingMJPEGStream && activeCameraId) {
        fetch('http://localhost:5050/stop', { method: 'POST' }).catch(() => {});
    }

    // Reset state for next camera
    lastDetectionType = '';
    lastFaceCount = -1;
    stableFaceCount = 0;
    stabilityFrames = 0;
    usingMJPEGStream = false;
    activeCameraId = null;
}

/* =========================
   BACKEND PUSH (UNCHANGED ENDPOINTS)
========================= */
function pushOccupancy(cameraId, peopleCount) {
    fetch('/Cameras/UpdateOccupancy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ CameraId: cameraId, PeopleCount: peopleCount })
    }).catch(() => {});
}

function pushDetection(cameraId, detectionType, count, confidence) {
    fetch('/Cameras/PushDetection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            CameraId: cameraId,
            DetectionType: detectionType,
            DetectedCount: count,
            Confidence: confidence,
            TriggeredAlert: false
        })
    }).catch(() => {});
}

/* =========================
   MOTION FALLBACK (REDUCED NOISE)
========================= */
let previousFrameData = null;

function analyzeFrame(imageData) {
    const data = imageData.data;
    let totalBrightness = 0;
    const pixelCount = data.length / 4;

    for (let i = 0; i < data.length; i += 4) {
        totalBrightness += (data[i] + data[i + 1] + data[i + 2]) / 3;
    }

    const avgBrightness = totalBrightness / pixelCount;

    let changeRatio = 0;
    let motionDetected = false;

    if (previousFrameData) {
        let diff = 0;

        for (let i = 0; i < data.length; i += 32) {
            diff += Math.abs(data[i] - previousFrameData[i]);
        }

        changeRatio = diff / (data.length / 32) / 255;
        motionDetected = changeRatio > 0.06;
    }

    previousFrameData = new Uint8Array(data);

    return { avgBrightness, changeRatio, motionDetected };
}

/* =========================
   UI UPDATE
========================= */
function updateLocalDetectionUI(faceCount, detectionType, confidence) {

    const cards = document.querySelectorAll('.grid-card');

    cards.forEach(card => {
        if (parseInt(card.dataset.cameraId) === activeCameraId) {

            const countEl = card.querySelector('[data-field="peopleCount"]');

            if (countEl && countEl.textContent !== String(faceCount)) {
                countEl.textContent = faceCount;
                countEl.classList.add('count-flip');

                setTimeout(() => {
                    countEl.classList.remove('count-flip');
                }, 400);
            }
        }
    });

    const pc = document.getElementById('focusPeopleCount');
    if (pc) pc.textContent = faceCount;

    const fs = document.getElementById('focusFaceStatus');
    if (fs) {
        const labels = {
            face_detected: 'Detected',
            face_verified: 'Verified',
            unknown_face: 'Unknown',
            no_face: 'No Face'
        };
        fs.textContent = labels[detectionType] || 'No Face';
    }

    let badge = document.getElementById('webcamDetectBadge');

    if (!badge) {
        badge = document.createElement('div');
        badge.id = 'webcamDetectBadge';
        badge.className = 'webcam-detect-badge';

        const viewerBody = document.querySelector('.viewer-body');
        if (viewerBody) viewerBody.appendChild(badge);
    }

    if (faceCount > 0) {
        badge.className = 'webcam-detect-badge detecting';
        badge.innerHTML =
            `<i class="fas fa-user-check"></i> ${faceCount} face${faceCount > 1 ? 's' : ''} detected`;
    } else {
        badge.className = 'webcam-detect-badge';
        badge.innerHTML = '<i class="fas fa-search"></i> Scanning...';
    }
}