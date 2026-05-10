"""
Enhanced Centroid Tracker with Robust Body Tracking

Features:
  - IoU (Intersection over Union) + centroid distance hybrid matching
  - Kalman-inspired velocity prediction for disappeared persons
  - EMA bounding box smoothing (anti-jitter)
  - Track confirmation (new tracks need N consecutive detections)
  - Re-identification: reconnect disappeared tracks to nearby new detections
  - Appearance descriptor (color histogram) for basic re-ID
  - Direction-aware tracking with velocity vectors
  - Face-seen persistence (locks authorization status)
  - Configurable smoothing and tolerance

Designed for:
  - Raspberry Pi 5 (lightweight, no GPU)
  - Single camera setup
  - Real-time FPS (10-30 FPS)
  - Indoor person tracking even when face is not visible

Zero external dependencies beyond numpy.
"""

import numpy as np
from collections import OrderedDict


class TrackedPerson:
    """Represents a tracked person with persistent ID, smooth rendering, and status memory."""
    __slots__ = ['track_id', 'centroid', 'bbox', 'smooth_bbox', 'confidence',
                 'disappeared', 'first_seen', 'status', 'face_seen',
                 'velocity', 'acceleration', 'prev_centroid', 'status_locked',
                 'consecutive_detections', 'confirmed',
                 'color_histogram', 'last_detection_time',
                 'total_visible_frames', 'age']

    def __init__(self, track_id, centroid, bbox, confidence):
        self.track_id = track_id
        self.centroid = centroid          # (cx, cy) — raw detection centroid
        self.bbox = bbox                  # (x, y, w, h) — raw detection box
        self.smooth_bbox = list(bbox)     # EMA-smoothed box for rendering
        self.confidence = confidence
        self.disappeared = 0
        self.first_seen = None           # Set by caller (time.time())
        self.status = 'unknown'          # 'authorized', 'unauthorized', 'unknown'
        self.face_seen = False           # Once True, status is permanently locked
        self.status_locked = False       # Prevents status from being overwritten

        # Motion prediction
        self.velocity = (0.0, 0.0)       # (vx, vy) pixels/frame
        self.acceleration = (0.0, 0.0)   # (ax, ay) for second-order prediction
        self.prev_centroid = centroid     # Previous centroid for velocity calc

        # Track confirmation (anti-phantom)
        self.consecutive_detections = 1  # Consecutive frames detected
        self.confirmed = False           # True after N consecutive detections

        # Appearance descriptor for re-identification
        self.color_histogram = None      # Cached color histogram

        # Timing
        self.last_detection_time = None  # time.time() of last detection
        self.total_visible_frames = 1    # Total frames this person was visible
        self.age = 0                     # Total frames since creation


class CentroidTracker:
    """
    Enhanced centroid tracker with:
    - IoU + centroid hybrid matching (robust for overlapping/size-varying persons)
    - Kalman-inspired velocity + acceleration prediction
    - EMA bounding box smoothing (anti-jitter)
    - Track confirmation (requires N consecutive detections to confirm)
    - Re-identification for disappeared tracks
    - Appearance descriptors for basic re-ID
    - Direction-aware tracking with velocity vectors

    Algorithm:
    1. Compute IoU between every existing track and every new detection
    2. Fallback to centroid distance if IoU is zero (non-overlapping)
    3. Match using combined score (IoU preferred, distance as tiebreaker)
    4. For disappeared objects, predict position using velocity + acceleration
    5. Apply EMA smoothing to bounding boxes for stable rendering
    6. Assign new ID if no match within threshold
    7. Deregister if missing for max_disappeared consecutive frames
    8. New tracks require confirmation_frames consecutive detections

    Zero external dependencies beyond numpy.
    """

    # Tuning parameters
    BBOX_SMOOTH = 0.55          # EMA factor: higher = smoother (more lag)
    VELOCITY_SMOOTH = 0.4       # Velocity averaging factor
    ACCEL_SMOOTH = 0.3          # Acceleration averaging factor
    IOU_THRESHOLD = 0.15        # Minimum IoU to consider a match
    CONFIRMATION_FRAMES = 2     # Consecutive detections to confirm a track
    PREDICTION_FRAMES = 15      # How many frames to predict position after disappearance
    HISTOGRAM_WEIGHT = 0.2      # Weight of appearance similarity in matching

    def __init__(self, max_disappeared=50, max_distance=100):
        """
        Args:
            max_disappeared: Frames before a lost person is deregistered.
                             50 frames @ 10 FPS = 5 seconds tolerance.
            max_distance: Maximum pixel distance for centroid matching.
                          100px @ 640x480 = generous matching range.
        """
        self.next_id = 0
        self.objects = OrderedDict()     # {track_id: TrackedPerson}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

        # Recently deregistered tracks for re-identification
        self._recently_lost = OrderedDict()  # {track_id: TrackedPerson}
        self._max_lost_memory = 100          # Max frames to remember lost tracks

    def register(self, centroid, bbox, confidence, frame=None):
        """Register a new tracked person."""
        person = TrackedPerson(self.next_id, centroid, bbox, confidence)

        # Compute appearance descriptor if frame provided
        if frame is not None:
            person.color_histogram = self._compute_histogram(frame, bbox)

        self.objects[self.next_id] = person
        self.next_id += 1
        return person

    def deregister(self, track_id):
        """Remove a tracked person and save to recently-lost for re-ID."""
        if track_id in self.objects:
            person = self.objects[track_id]
            self._recently_lost[track_id] = person
            del self.objects[track_id]

            # Trim lost memory
            while len(self._recently_lost) > 20:
                self._recently_lost.popitem(last=False)

    def _compute_iou(self, bbox1, bbox2):
        """Compute Intersection over Union between two bounding boxes (x,y,w,h)."""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2

        # Convert to (x1, y1, x2, y2) format
        ax1, ay1, ax2, ay2 = x1, y1, x1 + w1, y1 + h1
        bx1, by1, bx2, by2 = x2, y2, x2 + w2, y2 + h2

        # Intersection
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0

        intersection = (ix2 - ix1) * (iy2 - iy1)
        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - intersection

        if union <= 0:
            return 0.0

        return intersection / union

    def _predict_position(self, person):
        """Predict next position using velocity + acceleration (Kalman-inspired)."""
        vx, vy = person.velocity
        ax, ay = person.acceleration
        cx, cy = person.centroid

        # Second-order prediction: pos + vel + 0.5*accel
        predicted_cx = cx + vx + 0.5 * ax
        predicted_cy = cy + vy + 0.5 * ay

        return (predicted_cx, predicted_cy)

    def _predict_bbox(self, person):
        """Predict bounding box position based on velocity."""
        vx, vy = person.velocity
        x, y, w, h = person.smooth_bbox
        return (x + vx, y + vy, w, h)

    def _smooth_bbox(self, person, new_bbox):
        """Apply EMA smoothing to bounding box coordinates."""
        alpha = self.BBOX_SMOOTH
        for i in range(4):
            person.smooth_bbox[i] = alpha * person.smooth_bbox[i] + (1 - alpha) * new_bbox[i]

    def _update_velocity(self, person, new_centroid):
        """Update velocity and acceleration estimates from centroid movement."""
        old_cx, old_cy = person.prev_centroid
        new_cx, new_cy = new_centroid

        raw_vx = new_cx - old_cx
        raw_vy = new_cy - old_cy

        # Smooth velocity
        alpha_v = self.VELOCITY_SMOOTH
        old_vx, old_vy = person.velocity
        new_vx = alpha_v * old_vx + (1 - alpha_v) * raw_vx
        new_vy = alpha_v * old_vy + (1 - alpha_v) * raw_vy

        # Compute and smooth acceleration
        raw_ax = new_vx - old_vx
        raw_ay = new_vy - old_vy
        alpha_a = self.ACCEL_SMOOTH
        old_ax, old_ay = person.acceleration
        person.acceleration = (
            alpha_a * old_ax + (1 - alpha_a) * raw_ax,
            alpha_a * old_ay + (1 - alpha_a) * raw_ay
        )

        person.velocity = (new_vx, new_vy)
        person.prev_centroid = new_centroid

    def _compute_histogram(self, frame, bbox):
        """Compute a color histogram for appearance matching."""
        try:
            x, y, w, h = [int(v) for v in bbox]
            fh, fw = frame.shape[:2]
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(fw, x + w), min(fh, y + h)

            if x2 - x1 < 10 or y2 - y1 < 10:
                return None

            roi = frame[y1:y2, x1:x2]
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

            # Hue + Saturation histogram (16x16 bins)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            return hist.flatten()
        except Exception:
            return None

    def _compare_histograms(self, hist1, hist2):
        """Compare two histograms. Returns similarity score (0-1)."""
        if hist1 is None or hist2 is None:
            return 0.0
        try:
            h1 = hist1.reshape(16, 16).astype(np.float32)
            h2 = hist2.reshape(16, 16).astype(np.float32)
            return cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL)
        except Exception:
            return 0.0

    def _try_reidentify(self, centroid, bbox, confidence, frame=None):
        """
        Try to match a new detection to a recently-lost track.
        Returns the track_id if a match is found, None otherwise.
        """
        if not self._recently_lost:
            return None

        best_id = None
        best_score = 0.0

        for track_id, person in self._recently_lost.items():
            # Distance check
            pred_pos = self._predict_position(person)
            dist = np.sqrt((centroid[0] - pred_pos[0])**2 + (centroid[1] - pred_pos[1])**2)

            if dist > self.max_distance * 1.5:
                continue

            # Combined score: distance + appearance
            dist_score = max(0, 1.0 - dist / (self.max_distance * 1.5))

            # Appearance similarity
            appearance_score = 0.0
            if frame is not None and person.color_histogram is not None:
                new_hist = self._compute_histogram(frame, bbox)
                appearance_score = self._compare_histograms(person.color_histogram, new_hist)

            score = dist_score * (1 - self.HISTOGRAM_WEIGHT) + appearance_score * self.HISTOGRAM_WEIGHT

            if score > best_score and score > 0.3:
                best_score = score
                best_id = track_id

        if best_id is not None:
            # Recover the lost track
            person = self._recently_lost.pop(best_id)
            person.centroid = centroid
            person.bbox = bbox
            person.confidence = confidence
            person.disappeared = 0
            person.consecutive_detections = 1
            self._smooth_bbox(person, bbox)
            self._update_velocity(person, centroid)

            if frame is not None:
                person.color_histogram = self._compute_histogram(frame, bbox)

            self.objects[best_id] = person
            return best_id

        return None

    def update(self, detections, frame=None):
        """
        Update tracker with new detections.

        Args:
            detections: list of PersonDetection objects with .centroid and .bbox
            frame: Optional frame for appearance descriptor computation

        Returns:
            dict: {track_id: TrackedPerson} — all currently tracked persons
        """
        # Age all tracks
        for person in self.objects.values():
            person.age += 1

        # Age recently-lost tracks and clean up old ones
        for track_id in list(self._recently_lost.keys()):
            self._recently_lost[track_id].age += 1
            if self._recently_lost[track_id].age - self._recently_lost[track_id].total_visible_frames > self._max_lost_memory:
                del self._recently_lost[track_id]

        # =========================
        # NO DETECTIONS: increment disappeared, predict positions
        # =========================
        if len(detections) == 0:
            for track_id in list(self.objects.keys()):
                person = self.objects[track_id]
                person.disappeared += 1
                person.consecutive_detections = 0

                # Predict position using velocity (keeps box moving naturally)
                if person.disappeared <= self.PREDICTION_FRAMES:
                    predicted = self._predict_position(person)
                    person.centroid = predicted
                    # Update smooth_bbox position based on velocity
                    vx, vy = person.velocity
                    person.smooth_bbox[0] += vx
                    person.smooth_bbox[1] += vy

                if person.disappeared > self.max_disappeared:
                    self.deregister(track_id)

            return dict(self.objects)

        # =========================
        # EXTRACT CENTROIDS FROM DETECTIONS
        # =========================
        input_centroids = np.array([d.centroid for d in detections])
        input_bboxes = [d.bbox for d in detections]
        input_confidences = [d.confidence for d in detections]

        # =========================
        # FIRST DETECTIONS: try re-identification, then register new
        # =========================
        if len(self.objects) == 0:
            for i in range(len(detections)):
                # Try to re-identify from recently lost
                recovered = self._try_reidentify(
                    input_centroids[i], input_bboxes[i],
                    input_confidences[i], frame
                )
                if recovered is None:
                    self.register(
                        input_centroids[i], input_bboxes[i],
                        input_confidences[i], frame
                    )
            return dict(self.objects)

        # =========================
        # COMPUTE COST MATRIX: IoU (primary) + centroid distance (fallback)
        # =========================
        object_ids = list(self.objects.keys())
        num_objects = len(object_ids)
        num_detections = len(detections)

        # Get predicted positions for disappeared objects
        object_centroids = np.array([
            self._predict_position(self.objects[oid])
            if self.objects[oid].disappeared > 0
            else self.objects[oid].centroid
            for oid in object_ids
        ])

        # Get predicted bboxes
        object_bboxes = [
            self._predict_bbox(self.objects[oid])
            if self.objects[oid].disappeared > 0
            else tuple(self.objects[oid].smooth_bbox)
            for oid in object_ids
        ]

        # Combined cost matrix (lower = better match)
        cost_matrix = np.full((num_objects, num_detections), 1e6)

        for i in range(num_objects):
            for j in range(num_detections):
                # IoU score (higher = better, invert for cost)
                iou = self._compute_iou(object_bboxes[i], input_bboxes[j])

                # Centroid distance
                dist = np.sqrt(
                    (object_centroids[i][0] - input_centroids[j][0])**2 +
                    (object_centroids[i][1] - input_centroids[j][1])**2
                )

                if dist > self.max_distance and iou < self.IOU_THRESHOLD:
                    continue  # Too far and no overlap — skip

                # Combined cost: prefer IoU, fall back to distance
                if iou >= self.IOU_THRESHOLD:
                    # Good IoU: cost is inverse IoU (lower cost = better)
                    cost = (1.0 - iou) * 100
                else:
                    # No IoU: use distance directly
                    cost = dist

                cost_matrix[i, j] = cost

        # =========================
        # GREEDY MATCHING (sorted by cost, lowest first)
        # =========================
        # Find all valid (cost < threshold) pairs and sort
        pairs = []
        for i in range(num_objects):
            for j in range(num_detections):
                if cost_matrix[i, j] < 1e5:
                    pairs.append((cost_matrix[i, j], i, j))
        pairs.sort()

        used_rows = set()
        used_cols = set()

        for cost, row, col in pairs:
            if row in used_rows or col in used_cols:
                continue

            # Update existing object
            track_id = object_ids[row]
            person = self.objects[track_id]

            # Update velocity before changing centroid
            self._update_velocity(person, input_centroids[col])

            person.centroid = input_centroids[col]
            person.bbox = input_bboxes[col]
            person.confidence = input_confidences[col]
            person.disappeared = 0
            person.consecutive_detections += 1
            person.total_visible_frames += 1

            # Confirm track after N consecutive detections
            if person.consecutive_detections >= self.CONFIRMATION_FRAMES:
                person.confirmed = True

            # Apply EMA smoothing to bbox
            self._smooth_bbox(person, input_bboxes[col])

            # Update appearance descriptor periodically
            if frame is not None and person.age % 10 == 0:
                person.color_histogram = self._compute_histogram(frame, input_bboxes[col])

            used_rows.add(row)
            used_cols.add(col)

        # =========================
        # HANDLE UNMATCHED
        # =========================
        unused_rows = set(range(num_objects)) - used_rows
        unused_cols = set(range(num_detections)) - used_cols

        # Unmatched existing objects: increment disappeared
        for row in unused_rows:
            track_id = object_ids[row]
            person = self.objects[track_id]
            person.disappeared += 1
            person.consecutive_detections = 0

            # Predict position using velocity
            if person.disappeared <= self.PREDICTION_FRAMES:
                predicted = self._predict_position(person)
                person.centroid = predicted
                vx, vy = person.velocity
                person.smooth_bbox[0] += vx
                person.smooth_bbox[1] += vy

            if person.disappeared > self.max_disappeared:
                self.deregister(track_id)

        # Unmatched new detections: try re-ID, then register as new
        for col in unused_cols:
            recovered = self._try_reidentify(
                input_centroids[col], input_bboxes[col],
                input_confidences[col], frame
            )
            if recovered is None:
                self.register(
                    input_centroids[col], input_bboxes[col],
                    input_confidences[col], frame
                )

        return dict(self.objects)

    def set_person_status(self, track_id, status, face_seen=False):
        """
        Set authorization status for a tracked person.
        Once face_seen is True, status is PERMANENTLY locked.
        """
        if track_id not in self.objects:
            return

        person = self.objects[track_id]

        # Once face is seen and status locked, it can NEVER change back
        if person.status_locked:
            return

        person.status = status

        if face_seen:
            person.face_seen = True
            person.status_locked = True

    def get_active_count(self):
        """Return count of currently visible (confirmed) persons."""
        return sum(
            1 for p in self.objects.values()
            if p.disappeared == 0 and p.confirmed
        )

    def get_visible_count(self):
        """Return count of all visible persons (including unconfirmed)."""
        return sum(1 for p in self.objects.values() if p.disappeared == 0)

    def get_all_count(self):
        """Return total tracked persons (including temporarily disappeared)."""
        return len(self.objects)

    def reset(self):
        """Clear all tracked persons (e.g., on state transition)."""
        # Move all to recently-lost for potential re-ID
        for track_id, person in self.objects.items():
            self._recently_lost[track_id] = person
        self.objects.clear()
        # Don't reset next_id — keeps IDs unique across resets

    def get_status(self):
        """Return tracker status for debugging."""
        return {
            "tracked_count": len(self.objects),
            "active_count": self.get_active_count(),
            "visible_count": self.get_visible_count(),
            "next_id": self.next_id,
            "recently_lost": len(self._recently_lost),
            "persons": {
                tid: {
                    "centroid": list(p.centroid),
                    "bbox": list(p.bbox),
                    "smooth_bbox": list(p.smooth_bbox),
                    "status": p.status,
                    "face_seen": p.face_seen,
                    "disappeared": p.disappeared,
                    "velocity": list(p.velocity),
                    "confirmed": p.confirmed,
                    "consecutive_detections": p.consecutive_detections,
                    "age": p.age
                }
                for tid, p in self.objects.items()
            }
        }


# Need cv2 for histogram computation
try:
    import cv2
except ImportError:
    # If cv2 is not available, disable histogram features
    cv2 = None
