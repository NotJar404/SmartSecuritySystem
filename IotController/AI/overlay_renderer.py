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
# TEXT SIZE CACHE (avoid repeated getTextSize calls)
# =========================
_text_size_cache = {}
_TEXT_CACHE_MAX = 200


def _cached_text_size(text, font, font_scale, thickness):
    """Cache cv2.getTextSize results to avoid recomputation every frame."""
    key = (text, font, round(font_scale, 2), thickness)
    if key not in _text_size_cache:
        if len(_text_size_cache) > _TEXT_CACHE_MAX:
            _text_size_cache.clear()  # Simple eviction
        _text_size_cache[key] = cv2.getTextSize(text, font, font_scale, thickness)[0]
    return _text_size_cache[key]


def _draw_confidence_bar(frame, x, y, w, confidence, color):
    """Draw a small horizontal confidence bar below a label."""
    bar_h = 3
    bar_w = min(w, 80)
    fill_w = int(bar_w * min(1.0, confidence))
    # Background
    cv2.rectangle(frame, (x, y + 2), (x + bar_w, y + 2 + bar_h), (60, 60, 60), -1)
    # Fill
    if fill_w > 0:
        cv2.rectangle(frame, (x, y + 2), (x + fill_w, y + 2 + bar_h), color, -1)


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
    'LOCKDOWN': (0, 0, 200),
    'EMERGENCY': (0, 0, 255),
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
    Uses cached text size computation for performance.
    
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
    label_size = _cached_text_size(text, font, font_scale, thickness)
    
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
    return label_y  # Return for confidence bar positioning


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

        # Label: ID + status icon + confidence (cleaner format)
        status_icon = {"authorized": "\u2713", "unauthorized": "\u2717", "unknown": "?"}.get(status, "?")
        conf_pct = int(confidence * 100) if confidence <= 1.0 else int(confidence)
        label = f"ID:{track_id} [{status.upper()}] {status_icon} {conf_pct}%"
        label_y = draw_label(frame, label, sx, sy, color)

        # Confidence bar below label (lightweight — single rectangle fill)
        conf_val = confidence if confidence <= 1.0 else confidence / 100.0
        if label_y is not None:
            _draw_confidence_bar(frame, sx, label_y, sw, conf_val, color)

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


def render_lockdown_overlay(frame):
    """
    Render LOCKDOWN overlay — transparent blinking RED border + text.
    Lightweight: uses addWeighted for transparency, no expensive effects.
    """
    h, w = frame.shape[:2]
    sf = _scale_factor(frame)
    border = max(4, int(6 * sf))

    # Blinking red border (alternates every 0.5s)
    if int(time.time() * 2) % 2 == 0:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 200), border)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # LOCKDOWN text (center of frame)
    text = "LOCKDOWN ACTIVE"
    font_scale = 1.0 * sf
    thickness = max(2, int(3 * sf))
    text_size = _cached_text_size(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    tx = (w - text_size[0]) // 2
    ty = h // 2

    # Background for text readability
    cv2.rectangle(frame, (tx - 10, ty - text_size[1] - 10),
                  (tx + text_size[0] + 10, ty + 10), (0, 0, 0), -1)
    cv2.putText(frame, text, (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 255), thickness, cv2.LINE_AA)


def render_emergency_overlay(frame):
    """
    Render EMERGENCY overlay — alternating RED/YELLOW border + text.
    Lightweight: simple rectangle alternation.
    """
    h, w = frame.shape[:2]
    sf = _scale_factor(frame)
    border = max(4, int(6 * sf))

    # Alternating red/yellow border
    color = (0, 0, 255) if int(time.time() * 3) % 2 == 0 else (0, 200, 255)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), color, border)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

    # EMERGENCY text
    text = "EMERGENCY"
    font_scale = 1.2 * sf
    thickness = max(2, int(3 * sf))
    text_size = _cached_text_size(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    tx = (w - text_size[0]) // 2
    ty = h // 2

    cv2.rectangle(frame, (tx - 10, ty - text_size[1] - 10),
                  (tx + text_size[0] + 10, ty + 10), (0, 0, 0), -1)
    cv2.putText(frame, text, (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)


def render_verification_overlay(frame, overlay_data):
    """
    Render RFID face verification status overlay on camera stream.
    
    Shows: VERIFYING... → MATCH ✓ / NO MATCH ✗
    With person name, RFID UID, and confidence score.
    
    Args:
        frame: OpenCV frame (modified in-place)
        overlay_data: dict with {status, uid, name, confidence, start_time}
    """
    if not overlay_data:
        return

    h, w = frame.shape[:2]
    sf = _scale_factor(frame)
    status = overlay_data.get("status", "")
    uid = overlay_data.get("uid", "")
    name = overlay_data.get("name", "")
    confidence = overlay_data.get("confidence", 0)

    # ── Color by status ───────────────────────────────────────────────────
    # Granted outcomes → GREEN
    if status in ("ACCESS GRANTED", "RFID VERIFIED") or \
       ("MATCH" in status and "NO" not in status):
        bg_color = (0, 180, 0)        # Green
        text_color = (255, 255, 255)
    # Biometric bypass (RFID only, no face check) → BLUE
    elif status in ("RFID ONLY", "BIOMETRIC DISABLED"):
        bg_color = (200, 140, 0)      # Amber — granted but no face check
        text_color = (255, 255, 255)
    # In-progress → YELLOW
    elif "VERIFYING" in status or "CHECKING" in status:
        bg_color = (200, 200, 0)      # Yellow
        text_color = (0, 0, 0)
    # No face present → ORANGE (different from MISMATCH which is intentionally red)
    elif "NOT DETECTED" in status or "NO FACE" in status or "EXPIRED" in status:
        bg_color = (0, 140, 220)      # Orange-blue
        text_color = (255, 255, 255)
    # Denied / mismatch → RED
    else:
        bg_color = (0, 0, 200)        # Red (BGR)
        text_color = (255, 255, 255)
    # ─────────────────────────────────────────────────────────────────────

    is_final_result = status in (
        "ACCESS GRANTED", "RFID VERIFIED", "ACCESS DENIED",
        "NO MATCH", "CHECKED OUT", "TIMEOUT - NO FACE",
    ) or (("MATCH" in status or "DENIED" in status) and "VERIFYING" not in status)

    if is_final_result:
        # ── Full-frame color tint so result is IMPOSSIBLE to miss ──────────
        tint = frame.copy()
        cv2.rectangle(tint, (0, 0), (w, h), bg_color, -1)
        cv2.addWeighted(tint, 0.12, frame, 0.88, 0, frame)

        # ── Full-width tall banner ─────────────────────────────────────────
        banner_h = int(120 * sf)
        banner_y = h - banner_h - int(20 * sf)
        banner_x = 0
        banner_w = w

        overlay = frame.copy()
        cv2.rectangle(overlay, (banner_x, banner_y),
                      (banner_x + banner_w, banner_y + banner_h),
                      bg_color, -1)
        cv2.addWeighted(overlay, 0.92, frame, 0.08, 0, frame)

        # Border line at top of banner
        cv2.line(frame, (0, banner_y), (w, banner_y),
                 tuple(min(255, c + 80) for c in bg_color), max(3, int(3 * sf)))

        font = cv2.FONT_HERSHEY_SIMPLEX
        status_scale  = 1.2 * sf
        status_thick  = max(2, int(3 * sf))
        status_size   = _cached_text_size(status, font, status_scale, status_thick)
        sx = (w - status_size[0]) // 2
        sy = banner_y + int(50 * sf)
        cv2.putText(frame, status, (sx, sy), font, status_scale,
                    text_color, status_thick, cv2.LINE_AA)

        # Detail line
        detail_parts = []
        if name:
            detail_parts.append(name)
        if uid:
            detail_parts.append(f"UID: {uid[-8:]}")
        if confidence > 0:
            detail_parts.append(f"{confidence:.0f}% match")
        detail = "  |  ".join(detail_parts)

        if detail:
            detail_scale = 0.55 * sf
            detail_thick = max(1, int(1 * sf))
            detail_size  = _cached_text_size(detail, font, detail_scale, detail_thick)
            dx = (w - detail_size[0]) // 2
            dy = banner_y + int(95 * sf)
            cv2.putText(frame, detail, (dx, dy), font, detail_scale,
                        text_color, detail_thick, cv2.LINE_AA)

    else:
        # ── Compact banner for VERIFYING / in-progress states ─────────────
        face_found = overlay_data.get('face_found', None)
        guidance   = overlay_data.get('guidance', '')

        banner_h = int(90 * sf)   # slightly taller to fit guidance line
        banner_y = h - banner_h - int(30 * sf)
        banner_x = int(w * 0.05)
        banner_w = int(w * 0.90)

        overlay = frame.copy()
        cv2.rectangle(overlay, (banner_x, banner_y),
                      (banner_x + banner_w, banner_y + banner_h),
                      bg_color, -1)
        cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)

        font = cv2.FONT_HERSHEY_SIMPLEX

        # Face indicator dot (left side of banner)
        dot_cx = banner_x + int(20 * sf)
        dot_cy = banner_y + int(28 * sf)
        dot_r  = int(8 * sf)
        if face_found is True:
            cv2.circle(frame, (dot_cx, dot_cy), dot_r, (0, 255, 80), -1)   # green dot
        elif face_found is False:
            cv2.circle(frame, (dot_cx, dot_cy), dot_r, (0, 60, 220), -1)   # red dot

        # Status text
        status_scale = 0.8 * sf
        status_thick = max(2, int(2 * sf))
        status_size  = _cached_text_size(status, font, status_scale, status_thick)
        sx = banner_x + (banner_w - status_size[0]) // 2
        sy = banner_y + int(30 * sf)
        cv2.putText(frame, status, (sx, sy), font, status_scale,
                    text_color, status_thick, cv2.LINE_AA)

        # Guidance line (smaller, italic-style)
        guide_line_parts = []
        if guidance:
            guide_line_parts.append(guidance)
        if uid:
            guide_line_parts.append(f"UID: {uid}")
        if confidence > 0:
            guide_line_parts.append(f"{confidence:.0f}%")
        guide_line = "  |  ".join(guide_line_parts) if guide_line_parts else ""

        if guide_line:
            g_scale = 0.42 * sf
            g_thick = max(1, int(1 * sf))
            g_size  = _cached_text_size(guide_line, font, g_scale, g_thick)
            gx = banner_x + (banner_w - g_size[0]) // 2
            gy = banner_y + int(68 * sf)
            cv2.putText(frame, guide_line, (gx, gy), font, g_scale,
                        text_color, g_thick, cv2.LINE_AA)



def render_face_guide(frame, face_detected: bool, state: str = "ACCESS",
                      face_boxes=None, color_override=None):
    """
    Draw face bounding boxes in IDLE / ACCESS state.
    OVAL REMOVED — replaced with plain rectangles.

    Colors:
      IDLE  (monitoring, no RFID) → BLUE  (255, 100, 0)
      ACCESS (RFID tapped, verifying) → YELLOW (0, 255, 255)
      color_override: GREEN (0,200,0) = GRANTED | RED (0,0,200) = DENIED

    If face_boxes is provided, draws each box.
    If face_boxes is empty/None but face_detected, draws a centre placeholder.
    """
    if state not in ("IDLE", "ACCESS"):
        return

    h, w = frame.shape[:2]
    sf   = _scale_factor(frame)
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Determine box color: override takes priority (GRANTED=green, DENIED=red)
    if color_override is not None:
        box_color = color_override
        if color_override == (0, 200, 0):
            label = "ACCESS GRANTED ✓"
        elif color_override == (0, 0, 200):
            label = "ACCESS DENIED ✗"
        else:
            label = "VERIFYING..." if state == "ACCESS" else ("FACE DETECTED" if face_detected else "NO FACE")
    else:
        box_color  = (0, 255, 255) if state == "ACCESS" else (255, 100, 0)
        label      = "VERIFYING..." if state == "ACCESS" else ("FACE DETECTED" if face_detected else "NO FACE")
    label_color = box_color

    drawn = False
    if face_boxes:
        for (x, y, bw, bh) in face_boxes:
            if bw > 0 and bh > 0:
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), box_color, 2)
                # Corner accents for better visibility
                draw_corner_accents(frame, x, y, bw, bh, box_color)
                # Label above the box
                font_scale = 0.45 * sf
                thick = max(1, int(1.5 * sf))
                (tw, th), _ = cv2.getTextSize(label, font, font_scale, thick)
                lx = x
                ly = max(th + 6, y - 6)
                cv2.rectangle(frame, (lx - 2, ly - th - 4),
                              (lx + tw + 4, ly + 2), (0, 0, 0), -1)
                cv2.putText(frame, label, (lx, ly), font,
                            font_scale, label_color, thick, cv2.LINE_AA)
                drawn = True

    if not drawn:
        # No box available — show a simple text badge at the bottom-centre
        if color_override is not None:
            msg = label
            color = box_color
        else:
            msg = "FACE DETECTED - TAP RFID" if face_detected else "NO FACE - LOOK AT CAMERA"
            color = (0, 220, 80) if face_detected else (0, 165, 255)
        font_scale = 0.48 * sf
        thick = max(1, int(1.5 * sf))
        (tw, th), _ = cv2.getTextSize(msg, font, font_scale, thick)
        tx = (w - tw) // 2
        ty = int(h * 0.85)
        cv2.rectangle(frame, (tx - 5, ty - th - 5), (tx + tw + 5, ty + 5),
                      (0, 0, 0), -1)
        cv2.putText(frame, msg, (tx, ty), font, font_scale, color, thick, cv2.LINE_AA)



def render_countdown_overlay(frame, seconds_remaining):
    """
    Render silent countdown timer during IDLE detection.
    Shows how many seconds remain before alert triggers.
    
    Args:
        frame: OpenCV frame (modified in-place)
        seconds_remaining: int, seconds left in countdown
    """
    if seconds_remaining is None or seconds_remaining <= 0:
        return

    h, w = frame.shape[:2]
    sf = _scale_factor(frame)

    # Small countdown badge in top-right area
    text = f"RFID: {int(seconds_remaining)}s"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55 * sf
    thickness = max(1, int(2 * sf))
    text_size = _cached_text_size(text, font, font_scale, thickness)

    # Position: top-right, below REC indicator area
    tx = w - text_size[0] - 15
    ty = int(65 * sf)

    # Background pill
    pad = 6
    cv2.rectangle(frame, (tx - pad, ty - text_size[1] - pad),
                  (tx + text_size[0] + pad, ty + pad),
                  (0, 120, 200), -1)
    cv2.putText(frame, text, (tx, ty), font, font_scale,
                (255, 255, 255), thickness, cv2.LINE_AA)


def render_full_frame(frame, state, occupancy, sessions=0,
                      tracked_persons=None, faces=None,
                      is_recording=False, armed=True,
                      extra_info=None, verification_overlay=None,
                      countdown_seconds=None, face_detected=None):
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
        verification_overlay: dict {status, uid, name, confidence, start_time}
        countdown_seconds: float, seconds remaining in IDLE countdown (None=hidden)
    
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
    if state in ('INSIDE', 'LOITERING', 'ALERT', 'MONITORING', 'LOCKDOWN', 'EMERGENCY'):
        # MONITORING STATES: show tracking boxes only — no oval
        if tracked_persons:
            boxes_rendered = render_person_boxes(frame, tracked_persons)
    else:
        # IDLE / ACCESS: draw face bounding boxes
        # Derive box colour from the current verification result:
        #   GRANTED / MATCH  → green   (confirmation)
        #   DENIED  / errors → red     (rejection)
        #   VERIFYING        → default state colour (yellow)
        _box_color_override = None
        if verification_overlay:
            _vstatus = verification_overlay.get('status', '')
            if ('GRANTED' in _vstatus or
                    ('MATCH' in _vstatus and 'NO' not in _vstatus
                     and 'VERIFYING' not in _vstatus)):
                _box_color_override = (0, 200, 0)   # Green — access granted
            elif any(x in _vstatus for x in
                     ('DENIED', 'NO MATCH', 'TIMEOUT', 'LIBRARY',
                      'INSTALL', 'MISSING', 'LOAD ERROR')):
                _box_color_override = (0, 0, 200)   # Red — denied / error

        if face_detected is not None:
            render_face_guide(frame, face_detected, state,
                              face_boxes=faces, color_override=_box_color_override)

    # 3. REC indicator (ALERT state or active recording)
    if state == 'ALERT' or is_recording:
        render_rec_indicator(frame, is_recording)

    # 4. Lockdown / Emergency overlays (transparent, lightweight)
    if state == 'LOCKDOWN':
        render_lockdown_overlay(frame)
    elif state == 'EMERGENCY':
        render_emergency_overlay(frame)

    # 5. RFID verification overlay (FIX-7: VERIFYING/MATCH/NO MATCH banner)
    if verification_overlay:
        render_verification_overlay(frame, verification_overlay)

    # 6. IDLE countdown timer (FIX-1: shows seconds until buzzer)
    if countdown_seconds is not None and countdown_seconds > 0:
        render_countdown_overlay(frame, countdown_seconds)

    return frame, boxes_rendered