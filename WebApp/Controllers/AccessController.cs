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
        public string Room { get; set; }
    }
}