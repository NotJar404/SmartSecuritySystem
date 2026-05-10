/**
 * Webcam Stream Loader
 * Handles loading video streams or webcam feeds with proper fallback and error handling
 * Provides visual feedback for webcam vs. stream usage
 */

let webcamStream = null;
let activeWebcamVideos = new Set();

/**
 * Load a video stream or webcam feed
 * @param {HTMLVideoElement} videoElement - The video element to load stream into
 * @param {string} streamUrl - The URL of the stream (leave empty for webcam)
 * @param {Object} options - Configuration options
 */
async function loadVideoStream(videoElement, streamUrl, options = {}) {
    const {
        onSuccess = null,
        onError = null,
        onWebcam = null,
        fallbackToWebcam = true,
        enableHLS = true
    } = options;

    try {
        // If URL provided, load stream
        if (streamUrl && streamUrl.trim() !== '') {
            return loadStream(videoElement, streamUrl, {
                enableHLS,
                onSuccess,
                onError,
                fallbackToWebcam
            });
        }

        // No URL provided - use Python backend webcam processing (NOT raw browser webcam)
        // This ensures overlays, detection, and FSM processing work correctly
        console.log('[StreamLoader] No stream URL provided - using Python backend at http://localhost:5050/video');
        return loadStream(videoElement, 'http://localhost:5050/video', {
            enableHLS: false,
            onSuccess: (info) => {
                if (onSuccess) onSuccess({ ...info, type: 'webcam', isBackendProcessed: true });
            },
            onError,
            fallbackToWebcam: false
        });

    } catch (error) {
        console.error('[StreamLoader] Error:', error);
        if (onError) onError(error);
    }
}

async function loadStream(videoElement, streamUrl, options = {}) {
    const { enableHLS = true, onSuccess = null, onError = null, fallbackToWebcam = true } = options;

    try {
        // Check if HLS stream
        if (enableHLS && streamUrl.includes('.m3u8') && window.Hls) {
            console.log('[StreamLoader] Loading HLS stream:', streamUrl);
            const hls = new Hls();
            hls.loadSource(streamUrl);
            hls.attachMedia(videoElement);
            hls.on(Hls.Events.MANIFEST_PARSED, () => {
                videoElement.play().catch(err => console.log('[StreamLoader] Play failed:', err));
                if (onSuccess) onSuccess({ type: 'hls', url: streamUrl });
            });
            hls.on(Hls.Events.ERROR, (event, data) => {
                console.warn('[StreamLoader] HLS Error:', data);
                if (fallbackToWebcam) {
                    console.log('[StreamLoader] Falling back to webcam');
                    loadWebcam(videoElement, { onSuccess, onError });
                }
            });
        } else {
            // Check if this is an MJPEG stream (from Python backend on port 5050)
            // MJPEG streams MUST use <img> tag, NOT <video> tag
            const isMJPEG = streamUrl.includes(':5050/video') || streamUrl.includes('/video');

            if (isMJPEG) {
                console.log('[StreamLoader] Detected MJPEG stream - using <img> tag:', streamUrl);

                // Create or reuse an <img> element for MJPEG
                let mjpegImg = videoElement.parentElement.querySelector('.mjpeg-stream-img');
                if (!mjpegImg) {
                    mjpegImg = document.createElement('img');
                    mjpegImg.className = 'mjpeg-stream-img';
                    mjpegImg.style.cssText = 'width:100%;height:100%;object-fit:contain;background:black;position:absolute;top:0;left:0;z-index:2;';
                    videoElement.parentElement.insertBefore(mjpegImg, videoElement);
                }

                // Hide <video>, show <img>
                videoElement.style.display = 'none';
                videoElement.removeAttribute('controls');
                mjpegImg.style.display = 'block';
                mjpegImg.src = streamUrl + (streamUrl.includes('?') ? '&' : '?') + 't=' + Date.now();

                let loadTimeout;
                mjpegImg.onload = function() {
                    clearTimeout(loadTimeout);
                    console.log('[StreamLoader] MJPEG stream loaded successfully');
                    if (onSuccess) onSuccess({ type: 'mjpeg', url: streamUrl, isBackendProcessed: true });
                };

                mjpegImg.onerror = function() {
                    clearTimeout(loadTimeout);
                    console.warn('[StreamLoader] MJPEG stream failed at:', streamUrl);
                    mjpegImg.style.display = 'none';
                    videoElement.style.display = 'block';
                    if (fallbackToWebcam) {
                        console.log('[StreamLoader] Falling back to webcam');
                        loadWebcam(videoElement, { onSuccess, onError });
                    } else if (onError) {
                        onError('MJPEG stream unavailable');
                    }
                };

                // Set timeout for MJPEG load (browser doesn't timeout MJPEG img automatically)
                loadTimeout = setTimeout(() => {
                    console.warn('[StreamLoader] MJPEG stream timeout at:', streamUrl);
                    mjpegImg.style.display = 'none';
                    videoElement.style.display = 'block';
                    if (fallbackToWebcam) {
                        loadWebcam(videoElement, { onSuccess, onError });
                    } else if (onError) {
                        onError('MJPEG stream timeout');
                    }
                }, 5000);

            } else {
                // Regular video stream (RTSP, HTTP, etc.)
                console.log('[StreamLoader] Loading stream:', streamUrl);
                videoElement.src = streamUrl;
                videoElement.play().catch(err => {
                    console.warn('[StreamLoader] Stream play failed:', err);
                    if (fallbackToWebcam) {
                        console.log('[StreamLoader] Falling back to webcam');
                        loadWebcam(videoElement, { onSuccess, onError });
                    }
                });
                if (onSuccess) onSuccess({ type: 'stream', url: streamUrl });
            }
        }

    } catch (error) {
        console.error('[StreamLoader] Stream load error:', error);
        if (onError) onError(error);
        if (fallbackToWebcam) {
            loadWebcam(videoElement, { onSuccess, onError });
        }
    }
}

/**
 * Load webcam feed into video element
 */
async function loadWebcam(videoElement, options = {}) {
    const { onSuccess = null, onError = null, onWebcam = null } = options;

    try {
        console.log('[StreamLoader] Requesting webcam access');

        // Reuse existing webcam stream if available
        if (!webcamStream) {
            webcamStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    facingMode: 'user'
                },
                audio: false
            });
            console.log('[StreamLoader] Webcam access granted');
        }

        videoElement.srcObject = webcamStream;
        videoElement.play().catch(err => console.log('[StreamLoader] Webcam play failed:', err));

        // Track active webcam videos
        activeWebcamVideos.add(videoElement);

        // Mark as webcam element
        videoElement.dataset.isWebcam = 'true';
        videoElement.classList.add('is-webcam-stream');

        if (onSuccess) onSuccess({ type: 'webcam', stream: webcamStream });
        if (onWebcam) onWebcam({ stream: webcamStream });

    } catch (error) {
        console.error('[StreamLoader] Webcam error:', error);

        // Provide helpful error messages
        let userMessage = 'Unable to access webcam';
        if (error.name === 'NotAllowedError') {
            userMessage = 'Webcam access denied. Please check browser permissions.';
        } else if (error.name === 'NotFoundError') {
            userMessage = 'No webcam found on this device.';
        } else if (error.name === 'NotReadableError') {
            userMessage = 'Webcam is in use by another application.';
        }

        console.warn('[StreamLoader] ' + userMessage);
        if (onError) onError(new Error(userMessage));

        // Show error in video element
        showVideoError(videoElement, userMessage);
    }
}

/**
 * Display error message in video element
 */
function showVideoError(videoElement, message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'video-error-overlay';
    errorDiv.innerHTML = `
        <div class="video-error-content">
            <i class="fas fa-exclamation-circle"></i>
            <p>${message}</p>
            <small>Try adding a camera with a stream URL, or check system permissions</small>
        </div>
    `;

    if (videoElement.parentElement) {
        videoElement.parentElement.style.position = 'relative';
        videoElement.parentElement.appendChild(errorDiv);
    }
}

/**
 * Stop all active webcam streams
 */
function stopAllWebcamStreams() {
    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
        activeWebcamVideos.clear();
        console.log('[StreamLoader] All webcam streams stopped');
    }
}

/**
 * Stop a specific webcam video
 */
function stopWebcamVideo(videoElement) {
    if (activeWebcamVideos.has(videoElement)) {
        videoElement.srcObject = null;
        activeWebcamVideos.delete(videoElement);

        // Stop main stream if no more active videos
        if (activeWebcamVideos.size === 0) {
            stopAllWebcamStreams();
        }
    }
}

/**
 * Get information about video type
 */
function getVideoInfo(videoElement) {
    const isWebcam = videoElement.dataset.isWebcam === 'true';
    return {
        isWebcam,
        type: isWebcam ? 'webcam' : 'stream',
        url: videoElement.src || 'webcam',
        hasStream: !!videoElement.srcObject || !!videoElement.src
    };
}

/**
 * Initialize all video elements on page load
 */
function initializeVideoElements(selector = '.grid-preview, .cctv-video') {
    const videos = document.querySelectorAll(selector);
    console.log(`[StreamLoader] Initializing ${videos.length} video elements`);

    videos.forEach((video) => {
        const url = video.getAttribute('data-src');
        loadVideoStream(video, url, {
            // IMPORTANT: Card previews must NOT grab the webcam via getUserMedia.
            // If they do, main.py's OpenCV can't access the webcam → black stream in focus view.
            // Cards show camera icon placeholder if MJPEG isn't available.
            fallbackToWebcam: false,
            onSuccess: (info) => {
                console.log('[StreamLoader] Video loaded:', info);
            },
            onError: (error) => {
                console.log('[StreamLoader] Card preview not available (normal if main.py not running)');
            }
        });
    });
}

/**
 * Webcam indicator - disabled (badge removed per design requirement)
 */
function addWebcamIndicator(videoElement) {
    // Badge removed — webcam test mode should look identical to production
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initializeVideoElements();
    });
} else {
    initializeVideoElements();
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    stopAllWebcamStreams();
});
