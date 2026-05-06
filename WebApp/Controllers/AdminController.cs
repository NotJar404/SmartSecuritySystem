using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using SmartSecuritySystem.Models;
using SmartSecuritySystem.ViewModels;
using WebApp.Models;
using System;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class AdminController : Controller
    {
        private readonly AppDbContext _context;

        public AdminController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // DASHBOARD
        // =========================
        public async Task<IActionResult> Index()
        {
            var model = await BuildDashboardModel(isAdmin: User.IsInRole("Admin"));
            ViewBag.Rooms = await _context.Rooms.ToListAsync();
            ViewBag.IsAdmin = User.IsInRole("Admin");
            return View(model);
        }

        // =========================
        // ANALYTICS
        // =========================
        public async Task<IActionResult> Analytics(DateTime? startDate, DateTime? endDate, string? locationFilter, string? eventFilter)
        {
            bool isAdmin = User.IsInRole("Admin");
            var model = await BuildDashboardModel(startDate, endDate, locationFilter, eventFilter, isAdmin);
            
            ViewBag.StartDate = startDate?.ToString("yyyy-MM-dd");
            ViewBag.EndDate = endDate?.ToString("yyyy-MM-dd");
            ViewBag.LocationFilter = locationFilter;
            ViewBag.EventFilter = eventFilter;
            ViewBag.IsAdmin = isAdmin;

            return View(model);
        }

        // =========================
        // CORE DASHBOARD BUILDER (SAFE - NO PARALLEL EF)
        // =========================
        private async Task<AdminDashboardViewModel> BuildDashboardModel(DateTime? startDate = null, DateTime? endDate = null, string? locationFilter = null, string? eventFilter = null, bool isAdmin = true)
        {
            var now = DateTime.UtcNow;

            // =========================
            // METRICS (SEQUENTIAL SAFE QUERIES)
            // =========================
            var users = await _context.Users
                .Where(u => u.Status == "Active")
                .CountAsync();

            var cameras = await _context.CameraDevices
                .Where(c => c.Status == "active")
                .CountAsync();

            var alertsActive = await _context.Alerts
                .Where(a =>
                    a.Status == AlertStatus.New ||
                    a.Status == AlertStatus.Acknowledged)
                .CountAsync();

            var detectionToday = await _context.DetectionLogs
                .Where(d => d.Timestamp.Date == now.Date)
                .CountAsync();

            // =========================
            // TIME SERIES DATA
            // =========================
            var alertQ = _context.Alerts.AsQueryable();
            var accessQ = _context.AccessLogs.AsQueryable();
            var motionQ = _context.DetectionLogs.AsQueryable();

            if (startDate.HasValue)
            {
                alertQ = alertQ.Where(x => x.Timestamp >= startDate.Value);
                accessQ = accessQ.Where(x => x.Timestamp >= startDate.Value);
                motionQ = motionQ.Where(x => x.Timestamp >= startDate.Value);
            }
            if (endDate.HasValue)
            {
                var end = endDate.Value.AddDays(1).AddTicks(-1);
                alertQ = alertQ.Where(x => x.Timestamp <= end);
                accessQ = accessQ.Where(x => x.Timestamp <= end);
                motionQ = motionQ.Where(x => x.Timestamp <= end);
            }

            // Optional: location filter could apply if room matches (simplistic string match for demonstration)
            if (!string.IsNullOrEmpty(locationFilter))
            {
                // In a real app, map location to RoomId. For now, we leave as is or apply if property exists.
            }

            var alertDates = await alertQ.Select(a => a.Timestamp).ToListAsync();
            var accessDates = await accessQ.Select(a => a.Timestamp).ToListAsync();
            var motionDates = await motionQ.Select(d => d.Timestamp).ToListAsync();

            var occupancy = await SafeLoadRoomOccupancy();

            // =========================
            // ACTIVE INTERVENTIONS (Unresolved Alerts)
            // =========================
            var activeInterventions = await _context.Alerts
                .Where(a => a.Status != AlertStatus.Resolved)
                .OrderByDescending(a => a.Timestamp)
                .Take(15)
                .ToListAsync();

            // =========================
            // ROLE-BASED AUDIT LOGS
            // =========================
            var auditLogs = new List<AuditLogViewModel>();
            
            // Add Alerts and Detections for both roles
            var recentAlerts = await _context.Alerts
                .OrderByDescending(a => a.Timestamp)
                .Take(10)
                .ToListAsync();
                
            var recentDetections = await _context.DetectionLogs
                .OrderByDescending(a => a.Timestamp)
                .Take(10)
                .ToListAsync();
                
            var recentAccess = await _context.AccessLogs
                .OrderByDescending(a => a.Timestamp)
                .Take(10)
                .ToListAsync();

            auditLogs.AddRange(recentAlerts.Select(a => new AuditLogViewModel { Action = a.Type.ToString(), Description = $"Severity: {a.Severity} | {a.Status}", Timestamp = a.Timestamp }));
            auditLogs.AddRange(recentDetections.Select(d => new AuditLogViewModel { Action = "Detection", Description = $"Detected: {d.DetectedCount} at {d.Confidence}%", Timestamp = d.Timestamp }));
            auditLogs.AddRange(recentAccess.Select(a => new AuditLogViewModel { Action = a.AccessResult == "granted" ? "Access Granted" : "Access Denied", Description = $"RFID/Face check via Local Device", Timestamp = a.Timestamp }));

            // Add Admin-only logs
            if (isAdmin)
            {
                var recentLogins = await _context.Users
                    .Where(u => u.LastLogin != null)
                    .OrderByDescending(u => u.LastLogin)
                    .Take(10)
                    .ToListAsync();
                    
                auditLogs.AddRange(recentLogins.Select(u => new AuditLogViewModel { Action = "User Login", Description = $"{u.Username} signed in securely", Timestamp = u.LastLogin ?? DateTime.UtcNow }));
            }

            // Final sort and take top 15
            var criticalAuditStream = auditLogs
                .OrderByDescending(a => a.Timestamp)
                .Take(15)
                .ToList();

            // =========================
            // RETURN VIEW MODEL
            // =========================
            return new AdminDashboardViewModel
            {
                ActivePersonnelCount = users,
                ActiveCameraCount = cameras,
                ActiveIncidentCount = alertsActive,
                TodayDetectionCount = detectionToday,

                AlertWeekly = GroupByWeek(alertDates),
                AccessWeekly = GroupByWeek(accessDates),
                MotionWeekly = GroupByWeek(motionDates),
                OccupancyWeekly = GroupByWeek(occupancy.Select(o => o.Timestamp)),

                ActiveInterventions = activeInterventions,
                AuditLogs = criticalAuditStream,

                // Optional safety fallback (if your view uses labels)
                Labels = new List<string>
                {
                    "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
                }
            };
        }

        // =========================
        // SAFE OCCUPANCY LOADER
        // =========================
        private async Task<List<RoomOccupancy>> SafeLoadRoomOccupancy()
        {
            try
            {
                return await _context.RoomOccupancy
                    .AsNoTracking()
                    .ToListAsync();
            }
            catch
            {
                return new List<RoomOccupancy>();
            }
        }

        // =========================
        // WEEK GROUPING (MON - SUN)
        // =========================
        private List<int> GroupByWeek(IEnumerable<DateTime> dates)
        {
            var grouped = dates
                .GroupBy(d => d.DayOfWeek)
                .ToDictionary(g => g.Key, g => g.Count());

            return new List<int>
            {
                grouped.GetValueOrDefault(DayOfWeek.Monday),
                grouped.GetValueOrDefault(DayOfWeek.Tuesday),
                grouped.GetValueOrDefault(DayOfWeek.Wednesday),
                grouped.GetValueOrDefault(DayOfWeek.Thursday),
                grouped.GetValueOrDefault(DayOfWeek.Friday),
                grouped.GetValueOrDefault(DayOfWeek.Saturday),
                grouped.GetValueOrDefault(DayOfWeek.Sunday)
            };
        }

        // =========================
        // PERSONNEL
        // =========================
        [Authorize(Roles = "Admin")]
        public async Task<IActionResult> Personnel(string? search)
        {
            var users = _context.Users.AsQueryable();
            var members = _context.AuthorizedPersonnel.AsQueryable();

            if (!string.IsNullOrWhiteSpace(search))
            {
                users = users.Where(u =>
                    (u.FullName ?? "").Contains(search) ||
                    (u.Username ?? "").Contains(search) ||
                    (u.Email ?? "").Contains(search));

                members = members.Where(m =>
                    (m.FullName ?? "").Contains(search) ||
                    (m.Email ?? "").Contains(search) ||
                    (m.Department ?? "").Contains(search));
            }

            var userList = await users.ToListAsync();
            var memberList = await members.ToListAsync();

            var campusMembers = memberList.Select(m => new AuthorizedMember
            {
                Id = m.PersonId,
                FullName = m.FullName,
                Email = m.Email ?? "",
                Phone = m.Phone ?? "",
                Department = m.Department ?? "",
                RfidTag = m.RfidTag ?? "",
                Status = m.Status,
                SecurityLevel = m.SecurityLevel,
                HasFaceData = !string.IsNullOrEmpty(m.FaceEmbedding),
                CreatedAt = m.CreatedAt,
                LastAccess = null
            }).ToList();

            var viewModel = new PersonnelManagementViewModel
            {
                SystemUsers = userList,
                CampusMembers = campusMembers
            };

            return View("~/Views/Admin/Personnel.cshtml", viewModel);
        }

        // =========================
        // ADD USER
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        [Authorize(Roles = "Admin")]
        public async Task<IActionResult> Add(User user)
        {
            if (!ModelState.IsValid)
                return RedirectToAction(nameof(Personnel));

            user.Role = string.IsNullOrWhiteSpace(user.Role) ? "Security" : user.Role;
            user.Status = "Active";

            if (string.IsNullOrWhiteSpace(user.PasswordHash))
                user.PasswordHash = "1234";

            _context.Users.Add(user);
            await _context.SaveChangesAsync();

            return RedirectToAction(nameof(Personnel));
        }

        // =========================
        // DELETE USER
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        [Authorize(Roles = "Admin")]
        public async Task<IActionResult> Delete(int id)
        {
            var user = await _context.Users.FindAsync(id);

            if (user == null)
                return NotFound();

            _context.Users.Remove(user);
            await _context.SaveChangesAsync();

            return RedirectToAction(nameof(Personnel));
        }

        // =========================
        // SYSTEM SETTINGS
        // =========================
        private static SystemStatus systemStatus = new SystemStatus();

        [Authorize(Roles = "Admin")]
        public IActionResult System()
        {
            return View(systemStatus);
        }

        [HttpPost]
        [Authorize(Roles = "Admin")]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            if (string.IsNullOrWhiteSpace(setting))
                return BadRequest();

            switch (setting)
            {
                case "Notifications":
                    systemStatus.NotificationsEnabled = value;
                    break;

                case "Recording":
                    systemStatus.RecordingEnabled = value;
                    break;

                case "AI":
                    systemStatus.AiDetectionEnabled = value;
                    break;

                default:
                    return BadRequest();
            }

            return Ok(new { success = true });
        }
    }
}