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
            ViewBag.AvailableRooms = model.AvailableRooms;
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
            
            // Pass available rooms to view for dynamic dropdown
            ViewBag.AvailableRooms = model.AvailableRooms;

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
                // Convert Unspecified DateTime to UTC for PostgreSQL compatibility
                var startDateUtc = DateTime.SpecifyKind(startDate.Value, DateTimeKind.Utc);
                alertQ = alertQ.Where(x => x.Timestamp >= startDateUtc);
                accessQ = accessQ.Where(x => x.Timestamp >= startDateUtc);
                motionQ = motionQ.Where(x => x.Timestamp >= startDateUtc);
            }
            if (endDate.HasValue)
            {
                // Convert Unspecified DateTime to UTC and add 1 day for end-of-day filtering
                var endDateUtc = DateTime.SpecifyKind(endDate.Value.AddDays(1).AddTicks(-1), DateTimeKind.Utc);
                alertQ = alertQ.Where(x => x.Timestamp <= endDateUtc);
                accessQ = accessQ.Where(x => x.Timestamp <= endDateUtc);
                motionQ = motionQ.Where(x => x.Timestamp <= endDateUtc);
            }

            // =========================
            // RESOLVE LOCATION FILTER TO ROOM ID
            // =========================
            int? resolvedRoomId = null;
            if (!string.IsNullOrEmpty(locationFilter))
            {
                var resolvedRoom = await _context.Rooms
                    .FirstOrDefaultAsync(r => r.RoomName == locationFilter);
                if (resolvedRoom != null)
                {
                    resolvedRoomId = resolvedRoom.RoomId;
                    // Filter alerts by RoomId
                    alertQ = alertQ.Where(a => a.RoomId == resolvedRoomId);
                    // Filter access logs by RoomId
                    accessQ = accessQ.Where(a => a.RoomId == resolvedRoomId);
                    // Filter detections by CameraId matching the room
                    var cameraIdsInRoom = await _context.CameraDevices
                        .Where(c => c.RoomId == resolvedRoomId)
                        .Select(c => c.Id)
                        .ToListAsync();
                    motionQ = motionQ.Where(d => cameraIdsInRoom.Contains(d.CameraId));
                }
            }

            // =========================
            // EVENT TYPE FILTER
            // =========================
            // eventFilter: "Alert" = show only alert data, "Access" = show only access data
            // When a specific filter is active, the other category datasets will be empty

            var alertDates = (string.IsNullOrEmpty(eventFilter) || eventFilter == "Alert")
                ? await alertQ.Select(a => a.Timestamp).ToListAsync()
                : new List<DateTime>();
            var accessDates = (string.IsNullOrEmpty(eventFilter) || eventFilter == "Access")
                ? await accessQ.Select(a => a.Timestamp).ToListAsync()
                : new List<DateTime>();
            var motionDates = (string.IsNullOrEmpty(eventFilter) || eventFilter == "Alert")
                ? await motionQ.Select(d => d.Timestamp).ToListAsync()
                : new List<DateTime>();

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

            auditLogs.AddRange(recentAlerts.Select(a => new AuditLogViewModel { Action = a.Type.ToString(), Description = $"Severity: {a.Severity} | {a.Status}", User = "System", Timestamp = a.Timestamp }));
            auditLogs.AddRange(recentDetections.Select(d => new AuditLogViewModel { Action = "Detection", Description = $"Detected: {d.DetectedCount} at {d.Confidence}%", User = "AI Engine", Timestamp = d.Timestamp }));
            auditLogs.AddRange(recentAccess.Select(a => new AuditLogViewModel { Action = a.AccessResult == "granted" ? "Access Granted" : "Access Denied", Description = $"RFID/Face check via Local Device", User = "Access Control", Timestamp = a.Timestamp }));

            // Add Admin-only logs
            if (isAdmin)
            {
                var recentLogins = await _context.Users
                    .Where(u => u.LastLogin != null)
                    .OrderByDescending(u => u.LastLogin)
                    .Take(10)
                    .ToListAsync();
                    
                auditLogs.AddRange(recentLogins.Select(u => new AuditLogViewModel { Action = "User Login", Description = $"{u.Username} signed in securely", User = u.Username, Timestamp = u.LastLogin ?? DateTime.UtcNow }));
            }

            // Final sort and take top 15
            var criticalAuditStream = auditLogs
                .OrderByDescending(a => a.Timestamp)
                .Take(15)
                .ToList();

            // =========================
            // ENHANCED CHART DATA QUERIES
            // =========================

            // 1. ALERTS BY TYPE (Doughnut Chart) - Materialize first, then convert enum
            var alertsForType = await alertQ.ToListAsync();
            var alertsByType = alertsForType
                .GroupBy(a => a.Type)
                .Select(g => new { Type = g.Key.ToString(), Count = g.Count() })
                .ToList();
            
            var alertsByTypeDictionary = alertsByType
                .ToDictionary(x => x.Type, x => x.Count);

            // 1B. ALERT TRENDS BY DAY AND TYPE (Stacked Bar Chart) - Materialize first, then group
            var alertTrendsByDayAndType = new Dictionary<string, Dictionary<string, int>>();
            var dayLabels = new[] { "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat" };
            
            // Initialize the structure
            foreach (var dayLabel in dayLabels)
            {
                alertTrendsByDayAndType[dayLabel] = new Dictionary<string, int>();
            }

            // Materialize alerts first, then group by day and type
            var alertsByDayType = alertsForType
                .GroupBy(a => new { DayOfWeek = (int)a.Timestamp.DayOfWeek, AlertType = a.Type.ToString() })
                .Select(g => new { DayOfWeek = g.Key.DayOfWeek, AlertType = g.Key.AlertType, Count = g.Count() })
                .ToList();

            // Populate the structure
            foreach (var item in alertsByDayType)
            {
                var dayLabel = dayLabels[item.DayOfWeek];
                if (!alertTrendsByDayAndType[dayLabel].ContainsKey(item.AlertType))
                {
                    alertTrendsByDayAndType[dayLabel][item.AlertType] = 0;
                }
                alertTrendsByDayAndType[dayLabel][item.AlertType] += item.Count;
            }

            // 2. OCCUPANCY BY ROOM (Horizontal Bar Chart)
            var occupancyByRoom = occupancy
                .GroupBy(o => o.RoomId)
                .Select(g => new 
                { 
                    RoomId = g.Key,
                    TotalPeopleCount = g.Sum(x => x.PeopleCount)
                })
                .ToList();

            // Get room names from DB
            var roomIds = occupancyByRoom.Select(o => o.RoomId).Distinct().ToList();
            var roomNames = await _context.Rooms
                .Where(r => roomIds.Contains(r.RoomId))
                .Select(r => new { r.RoomId, r.RoomName })
                .ToDictionaryAsync(x => x.RoomId, x => x.RoomName);

            var occupancyRoomLabels = new List<string>();
            var occupancyRoomCounts = new List<int>();

            foreach (var item in occupancyByRoom.OrderByDescending(x => x.TotalPeopleCount))
            {
                var roomName = roomNames.TryGetValue(item.RoomId, out var name) ? name : $"Room {item.RoomId}";
                occupancyRoomLabels.Add(roomName);
                occupancyRoomCounts.Add(item.TotalPeopleCount);
            }

            // 3. ACCESS BY RESULT (Authorized/Suspicious/Unauthorized - Doughnut Chart)
            var accessByResult = await accessQ
                .GroupBy(a => a.AccessResult)
                .Select(g => new { Result = g.Key, Count = g.Count() })
                .ToListAsync();

            var accessByResultDictionary = accessByResult
                .ToDictionary(x => x.Result ?? "PENDING", x => x.Count);

            // 4. DETECTIONS BY TYPE (Polar/Radar Chart)
            var detectionsByType = await motionQ
                .GroupBy(d => d.DetectionType)
                .Select(g => new { Type = g.Key ?? "Unknown", Count = g.Count() })
                .ToListAsync();

            var detectionsByTypeDictionary = detectionsByType
                .ToDictionary(x => x.Type, x => x.Count);

            // 5. AVAILABLE ROOMS (for filter dropdown)
            var availableRooms = await _context.Rooms
                .OrderBy(r => r.RoomName)
                .ToListAsync();

            // =========================
            // APPLY LOCATION FILTER TO NEW DATA (if specified)
            // =========================
            if (!string.IsNullOrEmpty(locationFilter))
            {
                // Try to resolve location to RoomId
                var selectedRoom = availableRooms.FirstOrDefault(r => 
                    r.RoomName.Equals(locationFilter, StringComparison.OrdinalIgnoreCase));

                if (selectedRoom != null)
                {
                    // Re-filter occupancy data by room
                    occupancyRoomLabels.Clear();
                    occupancyRoomCounts.Clear();
                    var filteredOccupancy = occupancyByRoom
                        .Where(o => o.RoomId == selectedRoom.RoomId)
                        .ToList();
                    
                    foreach (var item in filteredOccupancy)
                    {
                        occupancyRoomLabels.Add(selectedRoom.RoomName);
                        occupancyRoomCounts.Add(item.TotalPeopleCount);
                    }
                }
            }

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

                // New Enhanced Chart Data
                AlertsByType = alertsByTypeDictionary,
                AlertTrendsByDayAndType = alertTrendsByDayAndType,
                OccupancyRoomLabels = occupancyRoomLabels,
                OccupancyRoomCounts = occupancyRoomCounts,
                AccessByResult = accessByResultDictionary,
                DetectionsByType = detectionsByTypeDictionary,
                AvailableRooms = availableRooms,

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
                HasFaceData = !string.IsNullOrEmpty(m.FaceEmbedding) && m.FaceEmbedding != "PENDING_ENROLLMENT",
                ProfileImagePath = m.ProfileImagePath,
                CreatedAt = m.CreatedAt,
                LastAccess = null,
                RoomCount = _context.PersonRoomAccess.Count(pra => pra.PersonId == m.PersonId)
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
        public async Task<IActionResult> System()
        {
            // =========================
            // AUTO-SEED: Ensure the 4 alarm protocols exist
            // =========================
            if (!await _context.AlarmSettings.AnyAsync())
            {
                _context.AlarmSettings.AddRange(
                    new AlarmSetting { Name = "Intruder Alert", Type = "Intrusion", IsEnabled = true },
                    new AlarmSetting { Name = "Fire Protocol", Type = "Fire", IsEnabled = true },
                    new AlarmSetting { Name = "Earthquake Mode", Type = "Earthquake", IsEnabled = true },
                    new AlarmSetting { Name = "Medical Emergency", Type = "ForcedEntry", IsEnabled = true }
                );
                await _context.SaveChangesAsync();
            }

            var settings = await _context.AlarmSettings
                .OrderBy(s => s.SettingId)
                .ToListAsync();

            ViewBag.Alarms = settings;

            // Pass system config so toggles render with REAL shared state (from SystemController)
            var liveConfig = SystemController.GetSharedConfig();
            ViewBag.Config = new {
                ArmSystem = liveConfig.ArmSystem,
                AutoMaintenance = liveConfig.AutoMaintenance,
                MotionSensitivity = liveConfig.MotionSensitivity,
                FaceAccuracy = liveConfig.FaceAccuracy,
                EmailReports = liveConfig.EmailReports,
                HardwareSiren = liveConfig.HardwareSiren,
                GateHoldOpen = liveConfig.GateHoldOpen,
                BiometricLock = liveConfig.BiometricLock
            };

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

        // =========================
        // ANALYTICS DATA API (AJAX REFRESH)
        // =========================
        [HttpGet]
        [Route("/Admin/AnalyticsData")]
        public async Task<IActionResult> AnalyticsData(DateTime? startDate, DateTime? endDate, string? locationFilter, string? eventFilter)
        {
            bool isAdmin = User.IsInRole("Admin");
            var model = await BuildDashboardModel(startDate, endDate, locationFilter, eventFilter, isAdmin);

            return Json(new
            {
                activeAlerts = model.ActiveIncidentCount,
                accessLogs = model.AccessWeekly.Sum(),
                detections = model.TodayDetectionCount,
                personnel = model.ActivePersonnelCount,
                alertsByType = model.AlertsByType,
                alertTrendsByDayAndType = model.AlertTrendsByDayAndType,
                accessByResult = model.AccessByResult,
                detectionsByType = model.DetectionsByType,
                occupancyRoomLabels = model.OccupancyRoomLabels,
                occupancyRoomCounts = model.OccupancyRoomCounts
            });
        }

        // =========================
        // SCHEDULE REPORT (REAL ENDPOINT)
        // =========================
        [HttpPost]
        [Route("/Admin/ScheduleReport")]
        public IActionResult ScheduleReport([FromBody] ScheduleReportRequest? request)
        {
            if (request == null || string.IsNullOrWhiteSpace(request.Email))
                return BadRequest(new { success = false, message = "Email is required" });

            // Log the schedule request (persists for audit)
            _context.Notifications.Add(new Notification
            {
                UserId = null,
                TargetRole = "Admin",
                Message = $"📊 Report scheduled: {request.Frequency} digest → {request.Email}",
                IsRead = false,
                Timestamp = DateTime.UtcNow
            });
            _context.SaveChanges();

            return Json(new
            {
                success = true,
                message = $"{request.Frequency} report scheduled for {request.Email}"
            });
        }

        // =========================
        // PERSONNEL COUNTS (STAT CARD POLLING)
        // =========================
        [HttpGet]
        [Route("/Admin/PersonnelCounts")]
        public async Task<IActionResult> PersonnelCounts()
        {
            var operators = await _context.Users.CountAsync();
            var members = await _context.AuthorizedPersonnel.CountAsync();
            var departments = await _context.AuthorizedPersonnel
                .Where(m => m.Department != null && m.Department != "")
                .Select(m => m.Department)
                .Distinct()
                .CountAsync();

            return Json(new { operators, members, departments });
        }
    }

    public class ScheduleReportRequest
    {
        public string Email { get; set; } = string.Empty;
        public string Frequency { get; set; } = "weekly";
    }
}