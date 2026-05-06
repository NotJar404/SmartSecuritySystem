using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class CamerasController : Controller
    {
        private readonly AppDbContext _context;

        public CamerasController(AppDbContext context)
        {
            _context = context;
        }

        // ===============================
        // LIVE MONITORING
        // ===============================
        public IActionResult Index(int? selectedId)
        {
            LoadRooms();

            ViewBag.SelectedCameraId = selectedId;

            // OCCUPANCY
            var occupancyCounts = _context.Set<RoomOccupancy>()
                .GroupBy(o => o.CameraId)
                .ToDictionary(
                    g => g.Key,
                    g => g.OrderByDescending(o => o.Timestamp)
                          .FirstOrDefault()!.PeopleCount
                );

            ViewBag.OccupancyCounts = occupancyCounts;

            // ACTIVE ALERT ROOMS (ENUM SAFE)
            var alertRoomIds = _context.Alerts
                .Where(a => a.Status == AlertStatus.New ||
                            a.Status == AlertStatus.Acknowledged)
                .Where(a => a.RoomId != null)
                .Select(a => a.RoomId!.Value)
                .ToHashSet();

            ViewBag.CameraAlerts = alertRoomIds;

            // ROOM MAX CAPACITIES (for capacity bar)
            var roomCapacities = _context.Rooms
                .Where(r => r.MaxCapacity != null)
                .ToDictionary(r => r.RoomId, r => r.MaxCapacity!.Value);

            ViewBag.RoomCapacities = roomCapacities;

            // LATEST DETECTION PER CAMERA (for face status)
            var latestDetections = _context.DetectionLogs
                .GroupBy(d => d.CameraId)
                .ToDictionary(
                    g => g.Key,
                    g => g.OrderByDescending(d => d.Timestamp).FirstOrDefault()
                );

            ViewBag.LatestDetections = latestDetections;

            // ACTIVE ALERT SEVERITY PER ROOM (for tri-state badge)
            var alertSeverities = _context.Alerts
                .Where(a => a.Status == AlertStatus.New ||
                            a.Status == AlertStatus.Acknowledged)
                .Where(a => a.RoomId != null)
                .GroupBy(a => a.RoomId!.Value)
                .ToDictionary(
                    g => g.Key,
                    g => g.Max(a => a.Severity)
                );

            ViewBag.AlertSeverities = alertSeverities;

            return View(GetCameras());
        }

        // ===============================
        // SELECT CAMERA
        // ===============================
        public IActionResult Select(int id)
        {
            return RedirectToAction(nameof(Index), new { selectedId = id });
        }

        // ===============================
        // ADD CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(Camera camera)
        {
            LoadRooms();

            if (!User.IsInRole("Admin"))
                return Unauthorized();

            if (!ModelState.IsValid)
                return View("Index", GetCameras());

            NormalizeStream(camera);

            if (!IsValidRoom(camera.RoomId))
            {
                ModelState.AddModelError("", "Invalid room selected.");
                return View("Index", GetCameras());
            }

            if (IsDuplicate(camera))
            {
                ModelState.AddModelError("", "Camera already exists in this room.");
                return View("Index", GetCameras());
            }

            camera.Status = string.IsNullOrEmpty(camera.Status)
                ? "active"
                : camera.Status;

            _context.CameraDevices.Add(camera);
            _context.SaveChanges();

            return RedirectToAction(nameof(Index));
        }

        // ===============================
        // EDIT CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Edit(Camera camera)
        {
            LoadRooms();

            if (!User.IsInRole("Admin"))
                return Unauthorized();

            if (!ModelState.IsValid)
                return View("Index", GetCameras());

            var existing = _context.CameraDevices.FirstOrDefault(c => c.Id == camera.Id);

            if (existing == null)
                return RedirectToAction(nameof(Index));

            if (!IsValidRoom(camera.RoomId))
            {
                ModelState.AddModelError("", "Invalid room.");
                return View("Index", GetCameras());
            }

            NormalizeStream(camera);

            if (IsDuplicate(camera, true))
            {
                ModelState.AddModelError("", "Duplicate camera found.");
                return View("Index", GetCameras());
            }

            existing.Name = camera.Name;
            existing.RoomId = camera.RoomId;
            existing.StreamUrl = camera.StreamUrl;
            existing.Location = camera.Location;
            existing.Status = string.IsNullOrEmpty(camera.Status)
                ? "active"
                : camera.Status;

            _context.SaveChanges();

            return RedirectToAction(nameof(Index));
        }

        // ===============================
        // DELETE CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(int id)
        {
            if (!User.IsInRole("Admin"))
                return Unauthorized();

            var cam = _context.CameraDevices.FirstOrDefault(c => c.Id == id);

            if (cam != null)
            {
                _context.CameraDevices.Remove(cam);
                _context.SaveChanges();
            }

            return RedirectToAction(nameof(Index));
        }

        // ===============================
        // REAL-TIME STATUS API (AJAX POLLING)
        // ===============================
        // Called every 5 seconds from Camera.cshtml
        // Returns per-camera real-time security state
        [HttpGet]
        [AllowAnonymous]
        public IActionResult Status()
        {
            var cameras = _context.CameraDevices
                .Include(c => c.Room)
                .ToList();

            // Latest occupancy per camera
            var occupancyCounts = _context.Set<RoomOccupancy>()
                .GroupBy(o => o.CameraId)
                .ToDictionary(
                    g => g.Key,
                    g => g.OrderByDescending(o => o.Timestamp)
                          .FirstOrDefault()!.PeopleCount
                );

            // Active alerts per room
            var activeAlerts = _context.Alerts
                .Where(a => a.Status == AlertStatus.New ||
                            a.Status == AlertStatus.Acknowledged)
                .Where(a => a.RoomId != null)
                .OrderByDescending(a => a.Timestamp)
                .ToList();

            // Latest detection per camera
            var latestDetections = _context.DetectionLogs
                .GroupBy(d => d.CameraId)
                .ToDictionary(
                    g => g.Key,
                    g => g.OrderByDescending(d => d.Timestamp).FirstOrDefault()
                );

            // Room capacities
            var roomCapacities = _context.Rooms
                .Where(r => r.MaxCapacity != null)
                .ToDictionary(r => r.RoomId, r => r.MaxCapacity!.Value);

            var result = cameras.Select(cam =>
            {
                var peopleCount = occupancyCounts.ContainsKey(cam.Id)
                    ? occupancyCounts[cam.Id] : 0;

                var roomAlerts = activeAlerts
                    .Where(a => a.RoomId == cam.RoomId)
                    .ToList();

                var maxSeverity = roomAlerts.Any()
                    ? roomAlerts.Max(a => a.Severity)
                    : (SeverityLevel?)null;

                // Compute tri-state security status
                var securityStatus = "SAFE";
                if (maxSeverity == SeverityLevel.CRITICAL)
                    securityStatus = "ALERT";
                else if (maxSeverity == SeverityLevel.WARNING || maxSeverity == SeverityLevel.INFO)
                    securityStatus = "WARNING";

                // Compute face recognition status
                var faceStatus = "none";
                if (latestDetections.ContainsKey(cam.Id))
                {
                    var det = latestDetections[cam.Id]!;
                    var timeSinceDetection = (DateTime.UtcNow - det.Timestamp).TotalSeconds;

                    // Only show recent detections (within 30 seconds)
                    if (timeSinceDetection < 30)
                    {
                        faceStatus = det.DetectionType?.ToLower() switch
                        {
                            "face_verified" => "verified",
                            "face_detected" => "detected",
                            "unknown_face" => "unknown",
                            "face_obstruction" => "obstructed",
                            _ => "none"
                        };
                    }
                }

                var maxCapacity = roomCapacities.ContainsKey(cam.RoomId)
                    ? roomCapacities[cam.RoomId] : 0;

                return new
                {
                    cameraId = cam.Id,
                    roomId = cam.RoomId,
                    roomName = cam.Room?.RoomName ?? "",
                    cameraName = cam.Name,
                    peopleCount,
                    maxCapacity,
                    securityStatus,
                    faceStatus,
                    alertCount = roomAlerts.Count,
                    latestAlert = roomAlerts.FirstOrDefault() != null ? new
                    {
                        alertId = roomAlerts.First().AlertId,
                        type = roomAlerts.First().Type.ToString(),
                        severity = roomAlerts.First().Severity.ToString(),
                        description = roomAlerts.First().Description ?? "",
                        minutesAgo = roomAlerts.First().MinutesAgo
                    } : null,
                    lastUpdated = DateTime.UtcNow
                };
            });

            return Json(result);
        }

        // ===============================
        // HYBRID IOT ENDPOINTS
        // ===============================

        // OCCUPANCY SYNC (RASPBERRY PI / LAPTOP AI)
        // Auto-resolves RoomId from CameraId
        [HttpPost]
        [AllowAnonymous]
        public IActionResult UpdateOccupancy([FromBody] OccupancyUpdateDto data)
        {
            if (data == null)
                return BadRequest();

            // Resolve RoomId from CameraId
            var camera = _context.CameraDevices
                .FirstOrDefault(c => c.Id == data.CameraId);

            var roomId = camera?.RoomId ?? 0;

            // Get latest record for this camera
            var latest = _context.Set<RoomOccupancy>()
                .Where(o => o.CameraId == data.CameraId)
                .OrderByDescending(o => o.Timestamp)
                .FirstOrDefault();

            // Insert ONLY if needed
            if (latest == null ||
                latest.PeopleCount != data.PeopleCount ||
                (DateTime.UtcNow - latest.Timestamp).TotalSeconds > 10)
            {
                _context.Add(new RoomOccupancy
                {
                    CameraId = data.CameraId,
                    RoomId = roomId,
                    PeopleCount = data.PeopleCount,
                    Timestamp = DateTime.UtcNow
                });

                _context.SaveChanges();
            }

            return Ok(new { message = "Occupancy updated", roomId });
        }

        // DETECTION EVENT SYNC (RASPBERRY PI AI)
        // Records face detection, obstruction, unknown face, loitering events
        [HttpPost]
        [AllowAnonymous]
        public IActionResult PushDetection([FromBody] DetectionDto data)
        {
            if (data == null)
                return BadRequest();

            var detection = new DetectionLog
            {
                CameraId = data.CameraId,
                DetectionType = data.DetectionType ?? "unknown",
                DetectedCount = data.DetectedCount,
                Confidence = data.Confidence,
                ImagePath = data.ImagePath,
                TriggeredAlert = data.TriggeredAlert,
                Timestamp = DateTime.UtcNow
            };

            _context.DetectionLogs.Add(detection);

            // Auto-create alert if detection triggered one
            if (data.TriggeredAlert)
            {
                var camera = _context.CameraDevices
                    .FirstOrDefault(c => c.Id == data.CameraId);

                var alertType = MapDetectionToAlertType(data.DetectionType);
                var severity = MapDetectionToSeverity(data.DetectionType);

                _context.Alerts.Add(new Alert
                {
                    Type = alertType,
                    Description = $"{FormatDetectionType(data.DetectionType)} — Camera: {camera?.Name ?? "Unknown"}, Confidence: {data.Confidence:P0}",
                    Severity = severity,
                    RoomId = camera?.RoomId,
                    Status = AlertStatus.New,
                    Timestamp = DateTime.UtcNow
                });
            }

            _context.SaveChanges();

            return Ok(new { message = "Detection logged" });
        }

        // ALERT SYNC (FIXED TO MATCH Alert.cs)
        [HttpPost]
        [AllowAnonymous]
        public IActionResult PushAlert([FromBody] AlertDto data)
        {
            if (data == null)
                return BadRequest();

            var alert = new Alert
            {
                Type = ParseAlertType(data.Type),
                Description = data.Description,
                Severity = ParseSeverity(data.Severity),
                RoomId = data.RoomId,
                Status = AlertStatus.New,
                Timestamp = DateTime.UtcNow
            };

            _context.Alerts.Add(alert);
            _context.SaveChanges();

            return Ok(new { message = "Alert received" });
        }

        // ===============================
        // STATE TRANSITION API (FSM CORE)
        // ===============================
        // Receives discrete state transitions from the Python edge controller.
        // ONLY processes meaningful state changes — NOT frame-level events.
        // This is the primary anti-spam database gate.
        [HttpPost]
        [AllowAnonymous]
        public IActionResult PushStateTransition([FromBody] StateTransitionDto data)
        {
            if (data == null || string.IsNullOrEmpty(data.SessionId))
                return BadRequest(new { error = "SessionId is required" });

            switch (data.Event?.ToUpper())
            {
                // =========================
                // ENTRY — Create new session
                // =========================
                case "ENTRY":
                {
                    // ANTI-SPAM: Check if this session already exists
                    var existingSession = _context.OccupancySessions
                        .FirstOrDefault(s => s.SessionId == data.SessionId);

                    if (existingSession != null)
                        return Ok(new { message = "Session already exists", duplicate = true });

                    // ANTI-SPAM: Check if person already has an active session
                    if (data.PersonId.HasValue)
                    {
                        var activeSession = _context.OccupancySessions
                            .FirstOrDefault(s => s.PersonId == data.PersonId
                                              && s.ExitTime == null);

                        if (activeSession != null)
                            return Ok(new { message = "Person already inside", duplicate = true });
                    }

                    // Resolve room from camera
                    int? roomId = data.RoomId;
                    if (roomId == null && data.CameraId > 0)
                    {
                        var camera = _context.CameraDevices
                            .FirstOrDefault(c => c.Id == data.CameraId);
                        roomId = camera?.RoomId;
                    }

                    var session = new OccupancySession
                    {
                        SessionId = data.SessionId,
                        PersonId = data.PersonId,
                        RoomId = roomId,
                        EntryTime = DateTime.UtcNow,
                        Status = "INSIDE",
                        FaceConfidence = data.Confidence,
                        RfidUid = data.RfidUid
                    };

                    _context.OccupancySessions.Add(session);

                    // Single access log for the entry event
                    _context.AccessLogs.Add(new AccessLog
                    {
                        PersonId = data.PersonId,
                        RoomId = roomId,
                        RfidValid = true,
                        FaceVerified = true,
                        AccessResult = "granted",
                        Timestamp = DateTime.UtcNow
                    });

                    _context.SaveChanges();

                    return Ok(new { message = "Entry session created", sessionId = data.SessionId });
                }

                // =========================
                // LOITERING — Update session status
                // =========================
                case "LOITERING":
                {
                    var session = _context.OccupancySessions
                        .FirstOrDefault(s => s.SessionId == data.SessionId && s.ExitTime == null);

                    if (session == null)
                        return NotFound(new { error = "No active session found" });

                    // ANTI-SPAM: Only update if not already in LOITERING state
                    if (session.Status == "LOITERING")
                        return Ok(new { message = "Already in loitering state", duplicate = true });

                    session.Status = "LOITERING";

                    // Create alert (ONE per loitering event)
                    _context.Alerts.Add(new Alert
                    {
                        Type = AlertType.SuspiciousActivity,
                        Description = $"Loitering detected — Session {data.SessionId}",
                        Severity = SeverityLevel.WARNING,
                        RoomId = session.RoomId,
                        Status = AlertStatus.New,
                        Timestamp = DateTime.UtcNow
                    });

                    _context.Notifications.Add(new Notification
                    {
                        UserId = null,
                        TargetRole = "Security",
                        Message = $"🚶 Loitering detected in {(session.Room?.RoomName ?? "Room")}",
                        IsRead = false,
                        Timestamp = DateTime.UtcNow
                    });

                    _context.SaveChanges();

                    return Ok(new { message = "Loitering state recorded" });
                }

                // =========================
                // EXIT — Close session
                // =========================
                case "EXIT":
                {
                    var session = _context.OccupancySessions
                        .FirstOrDefault(s => s.SessionId == data.SessionId && s.ExitTime == null);

                    if (session == null)
                        return NotFound(new { error = "No active session to close" });

                    session.ExitTime = DateTime.UtcNow;
                    session.Status = data.ExitReason == "INFERENCE" ? "EXPIRED" : "COMPLETED";
                    session.ExitReason = data.ExitReason ?? "INFERENCE";

                    _context.SaveChanges();

                    return Ok(new { message = "Session closed", exitReason = session.ExitReason });
                }

                // =========================
                // ALERT — Security event (intrusion, face mismatch, tailgating)
                // =========================
                case "ALERT":
                {
                    var alertType = ParseAlertType(data.AlertType ?? "Intrusion");
                    var severity = ParseSeverity(data.Severity ?? "HIGH");

                    int? roomId = data.RoomId;
                    if (roomId == null && data.CameraId > 0)
                    {
                        var camera = _context.CameraDevices
                            .FirstOrDefault(c => c.Id == data.CameraId);
                        roomId = camera?.RoomId;
                    }

                    // ANTI-SPAM: Check for recent identical alert
                    var recentAlert = _context.Alerts.Any(a =>
                        a.RoomId == roomId &&
                        a.Type == alertType &&
                        a.Timestamp > DateTime.UtcNow.AddMinutes(-2));

                    if (recentAlert)
                        return Ok(new { message = "Similar alert already exists", duplicate = true });

                    _context.Alerts.Add(new Alert
                    {
                        Type = alertType,
                        Description = data.Description ?? "Security event detected",
                        Severity = severity,
                        RoomId = roomId,
                        Status = AlertStatus.New,
                        Timestamp = DateTime.UtcNow
                    });

                    _context.Notifications.Add(new Notification
                    {
                        UserId = null,
                        TargetRole = "Security",
                        Message = $"🚨 {data.AlertType}: {data.Description}",
                        IsRead = false,
                        Timestamp = DateTime.UtcNow
                    });

                    // Log as denied access if person info available
                    if (data.PersonId.HasValue || !string.IsNullOrEmpty(data.RfidUid))
                    {
                        _context.AccessLogs.Add(new AccessLog
                        {
                            PersonId = data.PersonId,
                            RoomId = roomId,
                            RfidValid = !string.IsNullOrEmpty(data.RfidUid),
                            FaceVerified = false,
                            AccessResult = "denied",
                            Timestamp = DateTime.UtcNow
                        });
                    }

                    _context.SaveChanges();

                    return Ok(new { message = "Alert recorded" });
                }

                default:
                    return BadRequest(new { error = $"Unknown event type: {data.Event}" });
            }
        }

        // ===============================
        // ACTIVE SESSIONS API (DASHBOARD)
        // ===============================
        [HttpGet]
        [AllowAnonymous]
        public IActionResult GetActiveSessions()
        {
            var sessions = _context.OccupancySessions
                .Where(s => s.ExitTime == null)
                .Include(s => s.Person)
                .Include(s => s.Room)
                .OrderByDescending(s => s.EntryTime)
                .Select(s => new
                {
                    sessionId = s.SessionId,
                    personName = s.Person != null ? s.Person.FullName : "Unknown",
                    roomName = s.Room != null ? s.Room.RoomName : "Unknown",
                    entryTime = s.EntryTime,
                    status = s.Status,
                    minutesInside = (DateTime.UtcNow - s.EntryTime).TotalMinutes,
                    rfidUid = s.RfidUid
                })
                .ToList();

            return Json(sessions);
        }

        // ===============================
        // RECORDING API (FROM PYTHON EDGE)
        // ===============================
        [HttpPost]
        [AllowAnonymous]
        public IActionResult PushRecording([FromBody] RecordingDto data)
        {
            if (data == null || string.IsNullOrEmpty(data.FilePath))
                return BadRequest(new { error = "FilePath is required" });

            try
            {
                // Find the most recent alert for this session to link
                int? alertId = null;
                if (!string.IsNullOrEmpty(data.SessionId))
                {
                    // Try to find alert via session's room context
                    var session = _context.OccupancySessions
                        .FirstOrDefault(s => s.SessionId == data.SessionId);

                    if (session != null)
                    {
                        var recentAlert = _context.Alerts
                            .Where(a => a.RoomId == session.RoomId
                                     && a.Timestamp > DateTime.UtcNow.AddMinutes(-5))
                            .OrderByDescending(a => a.Timestamp)
                            .FirstOrDefault();

                        if (recentAlert != null)
                        {
                            alertId = recentAlert.AlertId;
                            // Link video path to alert record
                            recentAlert.VideoPath = data.FilePath;
                        }
                    }
                }

                // Insert into recordings table
                _context.Database.ExecuteSqlRaw(
                    @"INSERT INTO recordings (camera_id, alert_id, file_path, file_size_mb, is_archived, timestamp)
                      VALUES ({0}, {1}, {2}, {3}, false, NOW())",
                    data.CameraId,
                    alertId.HasValue ? (object)alertId.Value : DBNull.Value,
                    data.FilePath,
                    data.FileSizeMb
                );

                _context.SaveChanges();

                return Ok(new { message = "Recording saved", alertId = alertId });
            }
            catch (Exception ex)
            {
                return StatusCode(500, new { error = ex.Message });
            }
        }

        // ===============================
        // HELPERS
        // ===============================
        private List<Camera> GetCameras()
        {
            return _context.CameraDevices
                .Include(c => c.Room)
                .ToList();
        }

        private void LoadRooms()
        {
            ViewBag.Rooms = _context.Rooms.ToList();
        }

        private void NormalizeStream(Camera camera)
        {
            if (string.IsNullOrWhiteSpace(camera.StreamUrl))
            {
                camera.StreamUrl = null;
                camera.Status = "local";
            }
        }

        private bool IsValidRoom(int roomId)
        {
            return _context.Rooms.Any(r => r.RoomId == roomId);
        }

        private bool IsDuplicate(Camera camera, bool isEdit = false)
        {
            return _context.CameraDevices.Any(c =>
                (!isEdit || c.Id != camera.Id) &&
                c.RoomId == camera.RoomId &&
                !string.IsNullOrEmpty(camera.StreamUrl) &&
                c.StreamUrl == camera.StreamUrl
            );
        }

        // ENUM PARSERS (IMPORTANT FOR PYTHON HYBRID)
        private AlertType ParseAlertType(string type)
        {
            return type?.ToLower() switch
            {
                "intrusion" => AlertType.Intrusion,
                "unauthorizedaccess" => AlertType.UnauthorizedAccess,
                "suspiciousactivity" => AlertType.SuspiciousActivity,
                "accessdenied" => AlertType.AccessDenied,
                "forcedentry" => AlertType.ForcedEntry,
                "door" => AlertType.DoorEvent,
                _ => AlertType.Intrusion
            };
        }

        private SeverityLevel ParseSeverity(string severity)
        {
            return severity?.ToUpper() switch
            {
                "LOW" => SeverityLevel.INFO,
                "INFO" => SeverityLevel.INFO,
                "WARNING" => SeverityLevel.WARNING,
                "HIGH" => SeverityLevel.CRITICAL,
                "CRITICAL" => SeverityLevel.CRITICAL,
                _ => SeverityLevel.WARNING
            };
        }

        // DETECTION → ALERT TYPE MAPPING
        private AlertType MapDetectionToAlertType(string? detectionType)
        {
            return detectionType?.ToLower() switch
            {
                "face_obstruction" => AlertType.SuspiciousActivity,
                "unknown_face" => AlertType.UnauthorizedAccess,
                "loitering" => AlertType.SuspiciousActivity,
                "intrusion" => AlertType.Intrusion,
                "no_face" => AlertType.SuspiciousActivity,
                _ => AlertType.SuspiciousActivity
            };
        }

        // DETECTION → SEVERITY MAPPING
        private SeverityLevel MapDetectionToSeverity(string? detectionType)
        {
            return detectionType?.ToLower() switch
            {
                "intrusion" => SeverityLevel.CRITICAL,
                "face_obstruction" => SeverityLevel.WARNING,
                "unknown_face" => SeverityLevel.WARNING,
                "loitering" => SeverityLevel.INFO,
                "no_face" => SeverityLevel.INFO,
                _ => SeverityLevel.WARNING
            };
        }

        // HUMAN-READABLE DETECTION NAMES
        private string FormatDetectionType(string? detectionType)
        {
            return detectionType?.ToLower() switch
            {
                "face_obstruction" => "Face obstruction detected",
                "unknown_face" => "Unknown person detected",
                "loitering" => "Loitering behavior detected",
                "intrusion" => "Intrusion detected",
                "no_face" => "Body detected without visible face",
                "face_verified" => "Face verified successfully",
                "face_detected" => "Face detected",
                _ => "Detection event"
            };
        }
    }

    // ===============================
    // DTOs (Python / Raspberry Pi)
    // ===============================
    public class OccupancyUpdateDto
    {
        public int CameraId { get; set; }
        public int PeopleCount { get; set; }
    }

    public class AlertDto
    {
        public string Type { get; set; } = "Intrusion";
        public string Description { get; set; } = "";
        public string Severity { get; set; } = "WARNING";
        public int? RoomId { get; set; }
    }

    public class DetectionDto
    {
        public int CameraId { get; set; }
        public string? DetectionType { get; set; }
        public int DetectedCount { get; set; }
        public float Confidence { get; set; }
        public string? ImagePath { get; set; }
        public bool TriggeredAlert { get; set; }
    }

    // ===============================
    // STATE TRANSITION DTO (FSM)
    // ===============================
    // Used by Python edge controller to send state changes
    public class StateTransitionDto
    {
        // Core identity
        public string SessionId { get; set; } = string.Empty;
        public string? Event { get; set; }       // ENTRY, LOITERING, EXIT, ALERT

        // Person info
        public int? PersonId { get; set; }
        public string? RfidUid { get; set; }

        // Location
        public int CameraId { get; set; }
        public int? RoomId { get; set; }

        // Verification data
        public float Confidence { get; set; }

        // Exit info
        public string? ExitReason { get; set; }  // DOOR_SENSOR, RFID_EXIT, INFERENCE

        // Alert info
        public string? AlertType { get; set; }
        public string? Severity { get; set; }
        public string? Description { get; set; }
    }

    // ===============================
    // RECORDING DTO (FROM PYTHON EDGE)
    // ===============================
    public class RecordingDto
    {
        public int CameraId { get; set; }
        public string? SessionId { get; set; }
        public string FilePath { get; set; } = string.Empty;
        public float FileSizeMb { get; set; }
    }
}