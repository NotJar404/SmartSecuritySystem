"""
Unified Overlay Renderer for Smart Security System

SINGLE SOURCE OF TRUTH for all visual overlays:
  - YOLO-style corner accent bounding boxes
  - Person tracking labels (ID, status, face indicator, confidence)
  - Face detection boxes (IDLE/ACCESS mode)
  - Status HUD (state, occupancy, sessions, timestamp)
  - REC indicator during ALERT
  - Anti-flicker grace period rendering
  - EMA-smoothed bounding boxes

Used by BOTH main.py (Pi) and stream_server.py (laptop test mode).
This is a STATELESS module — takes frame + data, returns drawn frame.
"""

import cv2
import time
import numpy as np


# =========================
# RESOLUTION SCALING
# =========================
def _scale_factor(frame):
    """Compute a scale factor relative to 640px base width."""
    if frame is None:
        return 1.0
    return max(0.8, frame.shape[1] / 640.0)


# =========================
# COLOR PALETTE
# =========================
COLOR_AUTHORIZED = (0, 200, 0)      # Green
COLOR_UNAUTHORIZED = (0, 0, 255)    # Red
COLOR_UNKNOWN = (0, 220, 220)       # Yellow
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (200, 200, 200)
COLOR_REC_RED = (0, 0, 255)

STATUS_COLORS = {
    'IDLE': (128, 128, 128),
    'ACCESS': (0, 255, 255),
    'INSIDE': (0, 255, 0),
    'ALERT': (0, 0, 255),
    'LOITERING': (0, 165, 255),
    'MONITORING': (128, 128, 128),
}

PERSON_COLORS = {
    'authorized': COLOR_AUTHORIZED,
    'unauthorized': COLOR_UNAUTHORIZED,
    'unknown': COLOR_UNKNOWN,
}


def _get_status_color(status):
    """Get color for a person's authorization status."""
    return PERSON_COLORS.get(status, COLOR_UNKNOWN)


def _fade_color(color, disappeared, max_frames=10):
    """Fade color based on disappeared frame count."""
    if disappeared <= 0:
        return color
    fade = max(0.3, 1.0 - (disappeared / max_frames))
    return tuple(int(c * fade) for c in color)


def draw_corner_accents(frame, x, y, w, h, color, corner_len=None, thickness=None):
    """
    Draw YOLO-style corner accent brackets on a bounding box.
    
    Args:
        frame: OpenCV frame (modified in-place)
        x, y, w, h: Bounding box (top-left x, y, width, height)
        color: BGR tuple
        corner_len: Length of corner lines (auto-calculated if None)
        thickness: Line thickness (auto-calculated if None)
    """
    sf = _scale_factor(frame)
    if corner_len is None:
        corner_len = max(int(14 * sf), min(w, h) // 5)
    if thickness is None:
        thickness = max(2, int(3 * sf))

    x2, y2 = x + w, y + h

    # Top-left
    cv2.line(frame, (x, y), (x + corner_len, y), color, thickness)
    cv2.line(frame, (x, y), (x, y + corner_len), color, thickness)
    # Top-right
    cv2.line(frame, (x2, y), (x2 - corner_len, y), color, thickness)
    cv2.line(frame, (x2, y), (x2, y + corner_len), color, thickness)
    # Bottom-left
    cv2.line(frame, (x, y2), (x + corner_len, y2), color, thickness)
    cv2.line(frame, (x, y2), (x, y2 - corner_len), color, thickness)
    # Bottom-right
    cv2.line(frame, (x2, y2), (x2 - corner_len, y2), color, thickness)
    cv2.line(frame, (x2, y2), (x2, y2 - corner_len), color, thickness)


def draw_label(frame, text, x, y, bg_color, text_color=COLOR_WHITE, font_scale=None):
    """
    Draw a label with background above a bounding box.
    Auto-scales based on frame resolution.
    
    Args:
        frame: OpenCV frame (modified in-place)
        text: Label string
        x, y: Top-left corner of the bounding box
        bg_color: Background color (BGR)
        text_color: Text color (BGR)
        font_scale: Font scale (auto-calculated if None)
    """
    sf = _scale_factor(frame)
    if font_scale is None:
        font_scale = 0.45 * sf
    thickness = max(1, int(1 * sf))
    font = cv2.FONT_HERSHEY_SIMPLEX
    label_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    
    # Ensure label doesn't go above frame
    label_y = max(label_size[1] + 10, y)
    
    # Background rectangle
    cv2.rectangle(
        frame,
        (x, label_y - label_size[1] - 8),
        (x + label_size[0] + 6, label_y),
        bg_color, -1
    )
    # Text
    cv2.putText(
        frame, text,
        (x + 3, label_y - 4),
        font, font_scale,
        text_color, thickness, cv2.LINE_AA
    )


def render_person_boxes(frame, tracked_persons, max_disappeared_render=15):
    """
    Render person bounding boxes with corner accents and labels.
    Used in INSIDE, LOITERING, and ALERT states.
    
    Args:
        frame: OpenCV frame (modified in-place)
        tracked_persons: dict {track_id: TrackedPerson} or dict {track_id: dict}
        max_disappeared_render: Max disappeared frames to still render (fade out)
    
    Returns:
        int: Number of boxes rendered
    """
    rendered = 0
    
    for track_id, person in tracked_persons.items():
        # Support both TrackedPerson objects and dict format (stream_server.py)
        if hasattr(person, 'disappeared'):
            disappeared = person.disappeared
            smooth_bbox = person.smooth_bbox
            status = person.status
            face_seen = person.face_seen
            confidence = person.confidence
        else:
            disappeared = person.get('disappeared', 0)
            smooth_bbox = person.get('smooth_bbox', person.get('bbox', [0, 0, 0, 0]))
            status = person.get('status', 'unknown')
            face_seen = person.get('face_seen', False)
            confidence = person.get('conf', person.get('confidence', 0))

        # Skip persons that have been gone too long
        if disappeared > max_disappeared_render:
            continue

        # Extract smoothed bbox coordinates
        sx, sy, sw, sh = [int(v) for v in smooth_bbox]
        
        # Skip invalid boxes
        if sw <= 0 or sh <= 0:
            continue

        # Color based on authorization status
        color = _get_status_color(status)

        # Fade for disappeared persons
        if disappeared > 0:
            color = _fade_color(color, disappeared, max_disappeared_render)

        # Main rectangle (scaled thickness)
        sf = _scale_factor(frame)
        rect_thick = max(2, int(2 * sf))
        cv2.rectangle(frame, (sx, sy), (sx + sw, sy + sh), color, rect_thick)

        # Corner accents (thick, YOLO-style — auto-scaled)
        draw_corner_accents(frame, sx, sy, sw, sh, color)

        # Label: ID + status + face indicator + confidence (auto-scaled)
        face_flag = "F" if face_seen else "?"
        conf_pct = int(confidence * 100) if confidence <= 1.0 else int(confidence)
        label = f"ID:{track_id} [{status.upper()}] ({face_flag}) {conf_pct}%"
        draw_label(frame, label, sx, sy, color)

        rendered += 1

    return rendered


def render_face_boxes(frame, faces, state_color, state_name="IDLE"):
    """
    Render face detection bounding boxes with corner accents.
    Used in IDLE and ACCESS states.
    
    Args:
        frame: OpenCV frame (modified in-place)
        faces: list of (x, y, w, h) tuples
        state_color: BGR color for the current state
        state_name: Current state name for label
    
    Returns:
        int: Number of boxes rendered
    """
    rendered = 0

    for idx, (x, y, w, h) in enumerate(faces):
        # Main rectangle (scaled)
        sf = _scale_factor(frame)
        rect_thick = max(2, int(2 * sf))
        cv2.rectangle(frame, (x, y), (x + w, y + h), state_color, rect_thick)

        # Corner accents (auto-scaled)
        draw_corner_accents(frame, x, y, w, h, state_color)

        # Face label (auto-scaled)
        face_label = f"Face #{idx+1}"
        draw_label(frame, face_label, x, y, state_color)

        rendered += 1

    return rendered


def render_hud(frame, state, occupancy, sessions=0, timestamp=None,
               extra_info=None, armed=True):
    """
    Render the heads-up display: state, occupancy, sessions, timestamp.
    
    Args:
        frame: OpenCV frame (modified in-place)
        state: Current FSM state string
        occupancy: Current occupancy count
        sessions: Active session count
        timestamp: Optional timestamp string (auto-generated if None)
        extra_info: Optional extra info string for bottom-left
        armed: Whether the system is armed
    """
    h, w = frame.shape[:2]
    sf = _scale_factor(frame)
    state_color = STATUS_COLORS.get(state, (255, 255, 255))

    # Disarmed banner
    if not armed:
        cv2.putText(frame, "SYSTEM DISARMED", (10, int(35 * sf)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7 * sf, (0, 0, 255),
                    max(2, int(2 * sf)), cv2.LINE_AA)
        return

    # State + Occupancy (top-left)
    cv2.putText(
        frame,
        f"State: {state} | Occupancy: {occupancy}",
        (10, int(35 * sf)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7 * sf,
        state_color, max(2, int(2 * sf)), cv2.LINE_AA
    )

    # Sessions (below state)
    cv2.putText(
        frame,
        f"Sessions: {sessions}",
        (10, int(70 * sf)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55 * sf,
        COLOR_GRAY, max(1, int(1 * sf)), cv2.LINE_AA
    )

    # Timestamp (bottom-right)
    if timestamp is None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    ts_scale = 0.45 * sf
    ts_thick = max(1, int(1 * sf))
    ts_size = cv2.getTextSize(timestamp, cv2.FONT_HERSHEY_SIMPLEX, ts_scale, ts_thick)[0]
    cv2.putText(
        frame,
        timestamp,
        (w - ts_size[0] - 10, h - int(15 * sf)),
        cv2.FONT_HERSHEY_SIMPLEX, ts_scale,
        COLOR_GRAY, ts_thick, cv2.LINE_AA
    )

    # Extra info (bottom-left)
    if extra_info:
        cv2.putText(
            frame,
            extra_info,
            (10, h - int(15 * sf)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45 * sf,
            (0, 200, 255), max(1, int(1 * sf)), cv2.LINE_AA
        )


def render_rec_indicator(frame, is_recording):
    """
    Render REC indicator in top-right corner during recording.
    
    Args:
        frame: OpenCV frame (modified in-place)
        is_recording: Whether recording is active
    """
    if not is_recording:
        return

    h, w = frame.shape[:2]
    # Blinking effect (on/off every 0.5s)
    if int(time.time() * 2) % 2 == 0:
        cv2.circle(frame, (w - 30, 30), 10, COLOR_REC_RED, -1)
    cv2.putText(frame, "REC", (w - 70, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_REC_RED, 2, cv2.LINE_AA)


def render_full_frame(frame, state, occupancy, sessions=0,
                      tracked_persons=None, faces=None,
                      is_recording=False, armed=True,
                      extra_info=None):
    """
    MASTER RENDER FUNCTION — Draws ALL overlays on a frame.
    
    This is the single entry point for ALL overlay rendering.
    Call this from main.py and stream_server.py for identical output.
    
    Args:
        frame: OpenCV frame (MODIFIED IN-PLACE and returned)
        state: Current FSM state string ('IDLE', 'INSIDE', etc.)
        occupancy: Current occupancy count
        sessions: Active session count
        tracked_persons: dict of tracked persons (for INSIDE/LOITERING/ALERT)
        faces: list of (x, y, w, h) face detections (for IDLE/ACCESS)
        is_recording: Whether recording is active
        armed: Whether the system is armed
        extra_info: Optional bottom-left info string
    
    Returns:
        tuple: (frame, boxes_rendered) — the drawn frame and count of boxes
    """
    if frame is None:
        return frame, 0

    boxes_rendered = 0

    # 1. HUD (always drawn)
    render_hud(frame, state, occupancy, sessions,
               extra_info=extra_info, armed=armed)

    # 2. Bounding boxes (state-dependent)
    if state in ('INSIDE', 'LOITERING', 'ALERT', 'MONITORING'):
        if tracked_persons:
            boxes_rendered = render_person_boxes(frame, tracked_persons)
    else:
        # IDLE / ACCESS: face detection boxes
        if faces:
            state_color = STATUS_COLORS.get(state, (128, 128, 128))
            boxes_rendered = render_face_boxes(frame, faces, state_color, state)

    # 3. REC indicator (ALERT state)
    if state == 'ALERT' or is_recording:
        render_rec_indicator(frame, is_recording)

    return frame, boxes_rendered
