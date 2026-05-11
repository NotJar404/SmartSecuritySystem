using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class AccessController : Controller
    {
        private readonly AppDbContext _context;

        public AccessController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // MAIN PAGE (SESSION-AWARE)
        // =========================
        public async Task<IActionResult> Index()
        {
            var logs = await _context.AccessLogs
                .Include(x => x.Person)
                .Include(x => x.RoomEntity)
                .OrderByDescending(x => x.Timestamp)
                .Take(50)
                .ToListAsync();

            // =========================
            // ACTIVE SESSIONS (for UI status context)
            // =========================
            var activeSessions = await _context.OccupancySessions
                .Where(s => s.ExitTime == null)
                .Include(s => s.Person)
                .ToListAsync();

            var activePersonIds = activeSessions
                .Where(s => s.PersonId.HasValue)
                .Select(s => s.PersonId!.Value)
                .ToHashSet();

            ViewBag.ActivePersonIds = activePersonIds;
            ViewBag.ActiveSessions = activeSessions;

            foreach (var log in logs)
            {
                // =========================
                // PERSON MAPPING
                // =========================
                log.FullName = log.Person?.FullName ?? "Unknown User";
                log.PersonnelId = log.PersonId?.ToString() ?? "N/A";
                log.Department = log.Person?.Department ?? "-";
                log.Email = log.Person?.Email ?? "-";
                log.Phone = log.Person?.Phone ?? "-";
                log.ImageUrl = "/images/default-user.png";

                // =========================
                // ROOM MAPPING
                // =========================
                log.Room = log.RoomEntity?.RoomName ?? "Unknown Room";
                log.Location = "Unknown Location";
            }

            // =========================
            // RISK ENGINE (MOVED TO SESSION-AWARE)
            // Only creates alerts for DENIED access logs
            // that are fresh AND don't already have alerts.
            // AUTHORIZED entries handled by FSM — no alerts needed.
            // =========================
            var alertCutoff = DateTime.UtcNow.AddMinutes(-2);
            var deniedLogs = logs.Where(l =>
                l.Timestamp > alertCutoff &&
                l.AccessResult == "denied");

            foreach (var log in deniedLogs)
            {
                var riskLevel = EvaluateRisk(log);
                if (riskLevel != "LOW")
                {
                    CreateAlertFromLog(log, riskLevel);
                }
            }

            await _context.SaveChangesAsync();

            return View(logs);
        }

        // =========================
        // RFID UID LOOKUP (for Python edge controller)
        // Returns whether a scanned RFID UID belongs to a registered person
        // + ROOM-BASED ACCESS CONTROL (fail-secure)
        // =========================
        [HttpGet]
        [AllowAnonymous]
        [Route("/api/access/rfid")]
        public IActionResult RfidLookup([FromQuery] string uid, [FromQuery] int? roomId)
        {
            if (string.IsNullOrEmpty(uid))
                return BadRequest(new { error = "UID is required" });

            var person = _context.AuthorizedPersonnel
                .FirstOrDefault(p => p.RfidTag == uid);

            if (person == null)
                return Ok(new { found = false, uid, roomAllowed = false });

            // ROOM-BASED ACCESS CHECK (fail-secure: deny if no mapping exists)
            bool roomAllowed = false;
            string roomName = "Unknown";

            if (roomId.HasValue)
            {
                var roomAccess = _context.PersonRoomAccess
                    .Include(pra => pra.Room)
                    .FirstOrDefault(pra => pra.PersonId == person.PersonId && pra.RoomId == roomId.Value);

                if (roomAccess != null && roomAccess.AccessLevel == "allowed")
                {
                    roomAllowed = true;
                    roomName = roomAccess.Room?.RoomName ?? "Unknown";
                }
                else
                {
                    // Get room name for logging even on deny
                    var room = _context.Rooms.FirstOrDefault(r => r.RoomId == roomId.Value);
                    roomName = room?.RoomName ?? "Unknown";
                }
            }
            else
            {
                // No roomId sent — legacy behavior, but still fail-secure
                roomAllowed = false;
            }

            return Ok(new
            {
                found = true,
                uid,
                personId = person.PersonId,
                fullName = person.FullName,
                department = person.Department,
                roomAllowed,
                roomName,
                roomId = roomId ?? 0,
                // Face embedding for Python edge controller verification
                // Returns the stored encoding so verify can compare against live camera face
                faceEmbedding = person.FaceEmbedding
            });
        }

        // =========================
        // REALTIME AJAX: Get Latest Logs (for polling from Access.cshtml)
        // =========================
        [HttpGet]
        public IActionResult GetLatestLogs(int count = 50)
        {
            var logs = _context.AccessLogs
                .Include(x => x.Person)
                .Include(x => x.RoomEntity)
                .OrderByDescending(x => x.Timestamp)
                .Take(count)
                .ToList();

            var activeSessions = _context.OccupancySessions
                .Where(s => s.ExitTime == null)
                .ToList();

            var activePersonIds = activeSessions
                .Where(s => s.PersonId.HasValue)
                .Select(s => s.PersonId!.Value)
                .ToList();

            var result = logs.Select(log => new
            {
                fullName = log.Person?.FullName ?? "Unknown User",
                personnelId = log.PersonId?.ToString() ?? "N/A",
                department = log.Person?.Department ?? "-",
                email = log.Person?.Email ?? "-",
                phone = log.Person?.Phone ?? "-",
                room = log.RoomEntity?.RoomName ?? "Unknown Room",
                location = "Unknown Location",
                imageUrl = "/images/default-user.png",
                time = log.Timestamp.ToString("hh:mm tt"),
                videoPath = log.VideoPath ?? "",
                hasVideo = !string.IsNullOrEmpty(log.VideoPath),
                riskLevel = log.ComputedRiskLevel,
                rfidValid = log.RfidValid,
                faceVerified = log.FaceVerified,
                personId = log.PersonId ?? 0
            });

            return Json(new
            {
                logs = result,
                activeSessionCount = activeSessions.Count,
                activePersonIds
            });
        }

        // =========================
        // RISK ENGINE (SESSION-AWARE)
        // =========================
        private string EvaluateRisk(AccessLog log)
        {
            // If person is currently inside with an active session,
            // this is NOT a risk — it's a re-detection (ignore it)
            if (log.PersonId.HasValue)
            {
                var hasActiveSession = _context.OccupancySessions
                    .Any(s => s.PersonId == log.PersonId && s.ExitTime == null);

                if (hasActiveSession && log.AccessResult == "granted")
                    return "LOW";
            }

            if (!log.RfidValid && !log.FaceVerified)
                return "CRITICAL";

            if (log.AccessResult == "denied")
                return "HIGH";

            // Granted access with valid RFID = normal operation
            if (log.RfidValid && log.AccessResult == "granted")
                return "LOW";

            if (!log.RfidValid || !log.FaceVerified)
                return "MEDIUM";

            return "LOW";
        }

        // =========================
        // ALERT CREATION (ANTI-SPAM)
        // =========================
        private void CreateAlertFromLog(AccessLog log, string riskLevel)
        {
            // ANTI-SPAM: Check for recent alert for same person + room
            var exists = _context.Alerts.Any(a =>
                a.RoomId == log.RoomId &&
                a.Description != null &&
                a.Description.Contains(log.FullName) &&
                a.Timestamp > DateTime.UtcNow.AddMinutes(-5));

            if (exists) return;

            var alert = new Alert
            {
                Type = AlertType.AccessDenied,
                Description = $"Access anomaly detected for {log.FullName}",
                Severity = riskLevel switch
                {
                    "CRITICAL" => SeverityLevel.CRITICAL,
                    "HIGH" => SeverityLevel.CRITICAL,
                    "MEDIUM" => SeverityLevel.WARNING,
                    _ => SeverityLevel.INFO
                },
                RoomId = log.RoomId,
                Timestamp = DateTime.UtcNow,
                Status = AlertStatus.New
            };

            _context.Alerts.Add(alert);

            _context.Notifications.Add(new Notification
            {
                UserId = null,
                TargetRole = "Security",
                Message = $"🚨 {riskLevel} Alert: {log.FullName} in {log.Room}",
                IsRead = false,
                Timestamp = DateTime.UtcNow
            });
        }

        // =========================
        // API: FLAG FOR ADMIN (ANTI-SPAM)
        // =========================
        [HttpPost("api/flag")]
        [AllowAnonymous]
        public IActionResult FlagForAdmin([FromBody] FlagRequest req)
        {
            // ANTI-SPAM: Check if same flag already exists within 5 minutes
            var recentFlag = _context.Notifications.Any(n =>
                n.TargetRole == "Admin" &&
                n.Message.Contains(req.Name ?? "") &&
                n.Timestamp > DateTime.UtcNow.AddMinutes(-5));

            if (recentFlag)
                return Ok(new { message = "Flag already raised recently", duplicate = true });

            _context.Notifications.Add(new Notification
            {
                UserId = null,
                TargetRole = "Admin",
                Message = $"🚩 Manual flag raised: {req.Name} ({req.Room})",
                IsRead = false,
                Timestamp = DateTime.UtcNow
            });

            _context.SaveChanges();
            return Ok(new { message = "Flag sent" });
        }

        // =========================
        // API: LOCKDOWN ROOM (ANTI-SPAM)
        // =========================
        [HttpPost("api/security/lockdown")]
        [AllowAnonymous]
        public IActionResult LockdownRoom([FromBody] LockdownRequest req)
        {
            // ANTI-SPAM: Prevent duplicate lockdown notifications
            var recentLockdown = _context.Notifications.Any(n =>
                n.Message.Contains("lockdown") &&
                n.Message.Contains(req.Room ?? "") &&
                n.Timestamp > DateTime.UtcNow.AddMinutes(-5));

            if (recentLockdown)
                return Ok(new { message = "Lockdown already active", duplicate = true });

            _context.Notifications.Add(new Notification
            {
                UserId = null,
                TargetRole = "Security",
                Message = $"🔒 Room lockdown triggered: {req.Room}",
                IsRead = false,
                Timestamp = DateTime.UtcNow
            });

            // Also create a CRITICAL alert for the lockdown
            _context.Alerts.Add(new Alert
            {
                Type = AlertType.Intrusion,
                Description = $"Room lockdown triggered: {req.Room}",
                Severity = SeverityLevel.CRITICAL,
                Status = AlertStatus.New,
                Timestamp = DateTime.UtcNow
            });

            _context.SaveChanges();
            return Ok(new { message = "Lockdown triggered" });
        }

        // =========================
        // API: TRIGGER ALARM (ANTI-SPAM)
        // =========================
        [HttpPost("api/security/alarm")]
        [AllowAnonymous]
        public IActionResult TriggerAlarm()
        {
            // ANTI-SPAM: Prevent rapid alarm spam
            var recentAlarm = _context.Notifications.Any(n =>
                n.Message.Contains("EMERGENCY ALARM") &&
                n.Timestamp > DateTime.UtcNow.AddMinutes(-2));

            if (recentAlarm)
                return Ok(new { message = "Alarm already active", duplicate = true });

            _context.Notifications.Add(new Notification
            {
                UserId = null,
                TargetRole = "Security",
                Message = $"🚨 EMERGENCY ALARM TRIGGERED",
                IsRead = false,
                Timestamp = DateTime.UtcNow
            });

            _context.SaveChanges();
            return Ok(new { message = "Alarm triggered" });
        }

        // =========================
        // UNLOCK DOOR (existing)
        // =========================
        [HttpPost]
        public IActionResult UnlockDoor()
        {
            TempData["Message"] = "Door unlocked successfully.";
            return RedirectToAction(nameof(Index));
        }

        // =========================
        // API: LOG FEED (SESSION-AWARE + VIDEO EVIDENCE)
        // =========================
        [HttpGet]
        public async Task<IActionResult> GetLatestLogs()
        {
            var logs = await _context.AccessLogs
                .Include(x => x.Person)
                .Include(x => x.RoomEntity)
                .OrderByDescending(x => x.Timestamp)
                .Take(20)
                .ToListAsync();

            // Get active person IDs for session-aware status
            var activePersonIds = await _context.OccupancySessions
                .Where(s => s.ExitTime == null && s.PersonId != null)
                .Select(s => s.PersonId!.Value)
                .ToListAsync();

            var activeSet = new HashSet<int>(activePersonIds);

            var result = logs.Select(log => new
            {
                FullName = log.Person?.FullName ?? "Unknown User",
                StudentId = log.PersonId?.ToString() ?? "N/A",
                Department = log.Person?.Department ?? "-",
                Email = log.Person?.Email ?? "-",
                Phone = log.Person?.Phone ?? "-",
                Room = log.RoomEntity?.RoomName ?? "Unknown Room",
                Location = "Unknown Location",
                Time = log.Timestamp.ToString("hh:mm tt"),
                ImageUrl = "/images/default-user.png",
                Status = log.AccessResult,
                // SESSION-AWARE: Tell the UI if this person is currently inside
                IsCurrentlyInside = log.PersonId.HasValue && activeSet.Contains(log.PersonId.Value),
                // VIDEO EVIDENCE: Tell the UI if recording exists for this event
                HasVideo = !string.IsNullOrEmpty(log.VideoPath),
                VideoPath = log.VideoPath ?? ""
            });

            return Json(result);
        }

        // =========================
        // ROOM ACCESS MANAGEMENT API
        // =========================

        /// <summary>Get rooms assigned to a specific person</summary>
        [HttpGet]
        [Route("/api/access/room-list")]
        public async Task<IActionResult> GetRoomAccess([FromQuery] int personId)
        {
            var access = await _context.PersonRoomAccess
                .Where(pra => pra.PersonId == personId)
                .Include(pra => pra.Room)
                .Select(pra => new
                {
                    pra.AccessId,
                    pra.RoomId,
                    roomName = pra.Room!.RoomName,
                    pra.AccessLevel,
                    createdAt = pra.CreatedAt.ToString("MMM dd, yyyy")
                })
                .ToListAsync();

            return Json(access);
        }

        /// <summary>Assign a person to a room</summary>
        [HttpPost]
        [Route("/api/access/room-assign")]
        public async Task<IActionResult> AssignRoom([FromBody] RoomAssignRequest req)
        {
            if (req.PersonId <= 0 || req.RoomId <= 0)
                return BadRequest(new { success = false, message = "Invalid person or room ID" });

            // Check if already assigned
            var existing = await _context.PersonRoomAccess
                .FirstOrDefaultAsync(pra => pra.PersonId == req.PersonId && pra.RoomId == req.RoomId);

            if (existing != null)
                return Ok(new { success = false, message = "Already assigned to this room" });

            var entry = new PersonRoomAccess
            {
                PersonId = req.PersonId,
                RoomId = req.RoomId,
                AccessLevel = "allowed",
                CreatedAt = DateTime.UtcNow
            };

            _context.PersonRoomAccess.Add(entry);
            await _context.SaveChangesAsync();

            var room = await _context.Rooms.FindAsync(req.RoomId);
            return Ok(new { success = true, message = $"Assigned to {room?.RoomName ?? "room"}" });
        }

        /// <summary>Revoke a person's access to a room</summary>
        [HttpPost]
        [Route("/api/access/room-revoke")]
        public async Task<IActionResult> RevokeRoom([FromBody] RoomAssignRequest req)
        {
            var entry = await _context.PersonRoomAccess
                .FirstOrDefaultAsync(pra => pra.PersonId == req.PersonId && pra.RoomId == req.RoomId);

            if (entry == null)
                return Ok(new { success = false, message = "No access record found" });

            _context.PersonRoomAccess.Remove(entry);
            await _context.SaveChangesAsync();

            return Ok(new { success = true, message = "Access revoked" });
        }

        /// <summary>Get all rooms for dropdown selection</summary>
        [HttpGet]
        [Route("/api/access/rooms")]
        public async Task<IActionResult> GetAllRooms()
        {
            var rooms = await _context.Rooms
                .Select(r => new { r.RoomId, r.RoomName })
                .OrderBy(r => r.RoomName)
                .ToListAsync();

            return Json(rooms);
        }
    }

    // =========================
    // REQUEST MODELS
    // =========================
    public class FlagRequest
    {
        public string Name { get; set; }
        public string Room { get; set; }
    }

    public class LockdownRequest
    {
        public string Room { get; set; } = string.Empty;
        public string Reason { get; set; } = string.Empty;
    }

    public class RoomAssignRequest
    {
        public int PersonId { get; set; }
        public int RoomId { get; set; }
    }
}