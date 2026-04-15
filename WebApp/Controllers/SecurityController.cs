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
                // ACCESS REQUESTS (FIXED)
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
                    .ToListAsync()
            };

            return View(model);
        }

        public IActionResult System()
        {
            return View();
        }
    }
}