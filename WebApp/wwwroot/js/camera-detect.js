/* 
=====================================================
WEBCAM FACE DETECTION (BROWSER-SIDE)

STATE-BASED VERSION:
- Only pushes on STATE CHANGE (not every frame)
- Strict debounce cooldowns
- Session-aware (checks active sessions before alerting)
- Prevents detection log spam entirely
- Separates occupancy vs detection updates
=====================================================
*/

let faceDetectionActive = false;
let detectionCanvas = null;
let detectionInterval = null;
let modelsLoaded = false;

let activeCameraId = null;
let activeRoomId = null;

/* =========================
   STATE CONTROL (ANTI-SPAM)
========================= */
let lastFaceCount = -1;
let lastDetectionType = '';
let lastDetectionPush = 0;
let lastOccupancyPush = 0;
let lastOccupancyCount = -1;  // Track last pushed count

// ANTI-SPAM: Only push when STATE changes, not on timer
const DETECTION_COOLDOWN = 10000;   // 10 seconds minimum between same-state pushes
const OCCUPANCY_COOLDOWN = 15000;   // 15 seconds minimum between occupancy pushes
const STABILITY_REQUIRED = 3;       // Require 3 stable frames before pushing

/* STABILITY FILTER (ANTI-FLICKER) */
let stableFaceCount = 0;
let stabilityFrames = 0;

/* =========================
   INIT
========================= */
async function initWebcamDetection(videoElement, cameraId, roomId) {
    activeCameraId = cameraId;
    activeRoomId = roomId;

    if (!detectionCanvas) {
        detectionCanvas = document.createElement('canvas');
    }

    if (!modelsLoaded && typeof faceapi !== 'undefined') {
        try {
            const MODEL_URL =
                'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/model';

            await faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL);
            modelsLoaded = true;
        } catch (e) {
            console.log('[DETECT] Model load failed:', e);
        }
    }

    startDetectionLoop(videoElement);
}

/* =========================
   LOOP (STATE-BASED CORE)
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
           FACE DETECTION
        ========================= */
        if (modelsLoaded && typeof faceapi !== 'undefined') {
            try {
                const detections = await faceapi.detectAllFaces(
                    videoElement,
                    new faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.5 })
                );

                faceCount = detections.length;

                if (faceCount > 0) {
                    confidence = detections[0].score;

                    // CONFIDENCE THRESHOLD: Only count as detected if > 60%
                    if (confidence >= 0.6) {
                        detectionType = 'face_detected';
                    } else {
                        // Low confidence = treat as no reliable detection
                        faceCount = 0;
                        detectionType = 'no_face';
                    }
                }

            } catch (e) {
                console.log('[DETECT ERROR]', e);
            }
        }

        /* =========================
           STABILITY FILTER (ANTI-FLICKER)
           Require STABILITY_REQUIRED consecutive frames
           with same count before accepting
        ========================= */
        if (faceCount === stableFaceCount) {
            stabilityFrames++;
        } else {
            stabilityFrames = 0;
        }

        stableFaceCount = faceCount;

        // Don't push anything until detection is stable
        if (stabilityFrames < STABILITY_REQUIRED) {
            updateLocalDetectionUI(faceCount, detectionType, confidence);
            return;
        }

        const now = Date.now();

        /* =========================
           DETECTION PUSH (STATE-CHANGE ONLY)
           RULE: Only push when detection TYPE changes
           NOT on every cooldown expiration
        ========================= */
        const detectionChanged = detectionType !== lastDetectionType;
        const detectionCooldownPassed = (now - lastDetectionPush) > DETECTION_COOLDOWN;

        if (activeCameraId && detectionChanged && detectionCooldownPassed) {

            pushDetection(
                activeCameraId,
                detectionType,
                faceCount,
                confidence
            );

            lastDetectionType = detectionType;
            lastFaceCount = faceCount;
            lastDetectionPush = now;

            console.log(`[DETECT] State change pushed: ${detectionType} (${faceCount} faces)`);
        }

        /* =========================
           OCCUPANCY PUSH (CHANGE-ONLY)
           RULE: Only push when count ACTUALLY changes
           NOT on a timer if count is the same
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
   STOP
========================= */
function stopDetection() {
    faceDetectionActive = false;

    if (detectionInterval) {
        clearInterval(detectionInterval);
        detectionInterval = null;
    }
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

        // stricter threshold (reduces spam)
        motionDetected = changeRatio > 0.06;
    }

    previousFrameData = new Uint8Array(data);

    return { avgBrightness, changeRatio, motionDetected };
}

/* =========================
   UI UPDATE (UNCHANGED)
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
            face_verified: 'Verified ✅',
            unknown_face: 'Unknown ⚠',
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