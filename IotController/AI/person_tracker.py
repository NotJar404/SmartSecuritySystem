import numpy as np
from collections import OrderedDict


class TrackedPerson:
    """Represents a tracked person with persistent ID."""
    __slots__ = ['track_id', 'centroid', 'bbox', 'confidence',
                 'disappeared', 'first_seen', 'status']

    def __init__(self, track_id, centroid, bbox, confidence):
        self.track_id = track_id
        self.centroid = centroid          # (cx, cy)
        self.bbox = bbox                  # (x, y, w, h)
        self.confidence = confidence
        self.disappeared = 0
        self.first_seen = None           # Set by caller (time.time())
        self.status = 'unknown'          # 'authorized', 'unauthorized', 'unknown'


class CentroidTracker:
    """
    Lightweight object tracker using centroid distance matching.

    Algorithm:
    1. Compute centroid of each detection bounding box
    2. Match to existing tracked objects by minimum Euclidean distance
    3. Assign new ID if no match within max_distance
    4. Deregister if missing for max_disappeared consecutive frames

    Designed for indoor room monitoring:
    - Room-scale distances (~3-5m from camera)
    - 640x480 resolution
    - 10-30 FPS update rate

    Zero external dependencies beyond numpy.
    """

    def __init__(self, max_disappeared=30, max_distance=80):
        """
        Args:
            max_disappeared: Frames before a lost person is deregistered.
                             30 frames @ 10 FPS = 3 seconds tolerance.
            max_distance: Maximum pixel distance for centroid matching.
                          80px @ 640x480 ≈ 12% of frame width.
        """
        self.next_id = 0
        self.objects = OrderedDict()     # {track_id: TrackedPerson}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

    def register(self, centroid, bbox, confidence):
        """Register a new tracked person."""
        person = TrackedPerson(self.next_id, centroid, bbox, confidence)
        self.objects[self.next_id] = person
        self.next_id += 1
        return person

    def deregister(self, track_id):
        """Remove a tracked person."""
        del self.objects[track_id]

    def update(self, detections):
        """
        Update tracker with new detections.

        Args:
            detections: list of PersonDetection objects with .centroid and .bbox

        Returns:
            dict: {track_id: TrackedPerson} — all currently tracked persons
        """
        # =========================
        # NO DETECTIONS: increment disappeared for all
        # =========================
        if len(detections) == 0:
            for track_id in list(self.objects.keys()):
                self.objects[track_id].disappeared += 1
                if self.objects[track_id].disappeared > self.max_disappeared:
                    self.deregister(track_id)
            return dict(self.objects)

        # =========================
        # EXTRACT CENTROIDS FROM DETECTIONS
        # =========================
        input_centroids = np.array([d.centroid for d in detections])
        input_bboxes = [d.bbox for d in detections]
        input_confidences = [d.confidence for d in detections]

        # =========================
        # FIRST DETECTIONS: register all
        # =========================
        if len(self.objects) == 0:
            for i in range(len(detections)):
                self.register(
                    input_centroids[i],
                    input_bboxes[i],
                    input_confidences[i]
                )
            return dict(self.objects)

        # =========================
        # COMPUTE DISTANCE MATRIX
        # =========================
        object_ids = list(self.objects.keys())
        object_centroids = np.array([
            self.objects[oid].centroid for oid in object_ids
        ])

        # Euclidean distance between every existing object and every new detection
        D = np.linalg.norm(
            object_centroids[:, np.newaxis] - input_centroids[np.newaxis, :],
            axis=2
        )

        # =========================
        # HUNGARIAN MATCHING (greedy approximation)
        # =========================
        # Sort rows by smallest distance, then match greedily
        rows = D.min(axis=1).argsort()
        cols = D.argmin(axis=1)[rows]

        used_rows = set()
        used_cols = set()

        for (row, col) in zip(rows, cols):
            if row in used_rows or col in used_cols:
                continue

            # Only match if distance is within threshold
            if D[row, col] > self.max_distance:
                continue

            # Update existing object
            track_id = object_ids[row]
            self.objects[track_id].centroid = input_centroids[col]
            self.objects[track_id].bbox = input_bboxes[col]
            self.objects[track_id].confidence = input_confidences[col]
            self.objects[track_id].disappeared = 0

            used_rows.add(row)
            used_cols.add(col)

        # =========================
        # HANDLE UNMATCHED
        # =========================
        unused_rows = set(range(D.shape[0])) - used_rows
        unused_cols = set(range(D.shape[1])) - used_cols

        # Unmatched existing objects: increment disappeared
        for row in unused_rows:
            track_id = object_ids[row]
            self.objects[track_id].disappeared += 1
            if self.objects[track_id].disappeared > self.max_disappeared:
                self.deregister(track_id)

        # Unmatched new detections: register as new persons
        for col in unused_cols:
            self.register(
                input_centroids[col],
                input_bboxes[col],
                input_confidences[col]
            )

        return dict(self.objects)

    def get_active_count(self):
        """Return count of currently visible persons (not disappeared)."""
        return sum(1 for p in self.objects.values() if p.disappeared == 0)

    def get_all_count(self):
        """Return total tracked persons (including temporarily disappeared)."""
        return len(self.objects)

    def reset(self):
        """Clear all tracked persons (e.g., on state transition)."""
        self.objects.clear()
        # Don't reset next_id — keeps IDs unique across resets

    def get_status(self):
        """Return tracker status for debugging."""
        return {
            "tracked_count": len(self.objects),
            "active_count": self.get_active_count(),
            "next_id": self.next_id,
            "persons": {
                tid: {
                    "centroid": list(p.centroid),
                    "bbox": list(p.bbox),
                    "status": p.status,
                    "disappeared": p.disappeared
                }
                for tid, p in self.objects.items()
            }
        }
