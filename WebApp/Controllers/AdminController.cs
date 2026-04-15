using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using SmartSecuritySystem.Models;
using WebApp.Models;
using System;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")]
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
            var model = await BuildDashboardModel();
            return View(model);
        }

        // =========================
        // ANALYTICS
        // =========================
        public async Task<IActionResult> Analytics()
        {
            var model = await BuildDashboardModel();
            return View(model);
        }

        // =========================
        // CORE DASHBOARD BUILDER (SAFE - NO PARALLEL EF)
        // =========================
        private async Task<AdminDashboardViewModel> BuildDashboardModel()
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
            var alertDates = await _context.Alerts
                .Select(a => a.Timestamp)
                .ToListAsync();

            var accessDates = await _context.AccessLogs
                .Select(a => a.Timestamp)
                .ToListAsync();

            var motionDates = await _context.DetectionLogs
                .Select(d => d.Timestamp)
                .ToListAsync();

            var occupancy = await SafeLoadRoomOccupancy();

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
        public async Task<IActionResult> Personnel(string? search)
        {
            var query = _context.Users.AsQueryable();

            if (!string.IsNullOrWhiteSpace(search))
            {
                search = search.Trim();

                query = query.Where(u =>
                    u.Username.Contains(search) ||
                    u.Email.Contains(search) ||
                    u.FullName.Contains(search));
            }

            return View(await query.AsNoTracking().ToListAsync());
        }

        // =========================
        // ADD USER
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
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

        public IActionResult System()
        {
            return View(systemStatus);
        }

        [HttpPost]
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