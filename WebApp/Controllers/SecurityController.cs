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
    [Authorize]
    public class DashboardController : Controller
    {
        private readonly AppDbContext _context;

        public DashboardController(AppDbContext context)
        {
            _context = context;
        }

        public async Task<IActionResult> Index()
        {
            var now = DateTime.UtcNow;

            // =========================
            // FETCH RECENT ACCESS LOGS
            // =========================
            var recentAccessLogs = await _context.AccessLogs
                .OrderByDescending(a => a.Timestamp)
                .Take(5)
                .ToListAsync();

            // ✅ Populate UI-safe values (same as AccessController)
            foreach (var log in recentAccessLogs)
            {
                log.FullName = log.FullName ?? "Unknown User";
                log.StudentId = log.StudentId ?? "N/A";
                log.Department = log.Department ?? "-";
                log.Room = log.Room ?? "Unknown Room";
                log.Location = log.Location ?? "Unknown Location";
                log.ImageUrl = log.ImageUrl ?? "/images/default-user.png";
            }

            var model = new DashboardViewModel
            {
                // =========================
                // CAMERAS
                // =========================
                ActiveCameraCount = await _context.CameraDevices
                    .Where(c => c.Status == "active")
                    .CountAsync(),

                TotalCameraCount = await _context.CameraDevices.CountAsync(),

                // =========================
                // DETECTIONS
                // =========================
                TodayDetectionCount = await _context.DetectionLogs
                    .Where(d => d.Timestamp.Date == now.Date)
                    .CountAsync(),

                // =========================
                // ALERTS
                // =========================
                ActiveAlertCount = await _context.Alerts
                    .Where(a => a.Status == AlertStatus.New ||
                                a.Status == AlertStatus.Acknowledged)
                    .CountAsync(),

                // =========================
                // ACCESS REQUESTS
                // =========================
                PendingAccessCount = await _context.AccessLogs
                    .Where(a => a.AccessResult == "denied")
                    .CountAsync(),

                // =========================
                // RECENT EVENTS
                // =========================
                RecentEvents = await _context.DetectionLogs
                    .Include(d => d.Camera)
                        .ThenInclude(c => c.Room)
                    .OrderByDescending(d => d.Timestamp)
                    .Take(5)
                    .ToListAsync(),

                // =========================
                // CAMERAS LIST
                // =========================
                Cameras = await _context.CameraDevices
                    .Include(c => c.Room)
                    .Take(5)
                    .ToListAsync(),

                // ✅ NEW: ACCESS LOGS FOR DASHBOARD
                RecentAccessLogs = recentAccessLogs
            };

            return View(model);
        }

        public IActionResult System()
        {
            return View();
        }
    }
}