using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;

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

        // =========================
        // DASHBOARD HOME
        // =========================
        public async Task<IActionResult> Index()
        {
            var now = DateTime.UtcNow;

            // =========================
            // RECENT ACCESS LOGS
            // =========================
            var recentAccessLogs = await _context.AccessLogs
                .OrderByDescending(a => a.Timestamp)
                .Take(5)
                .ToListAsync();

            foreach (var log in recentAccessLogs)
            {
                log.FullName = log.FullName ?? "Unknown User";
                log.PersonnelId = log.PersonnelId ?? "N/A";
                log.Department = log.Department ?? "-";
                log.Room = log.Room ?? "Unknown Room";
                log.Location = log.Location ?? "Unknown Location";
                log.ImageUrl = log.ImageUrl ?? "/images/default-user.png";
            }

            // =========================
            // HYBRID OCCUPANCY (PI + LOCAL AI)
            // =========================
            var latestOccupancy = await _context.RoomOccupancy
                .OrderByDescending(o => o.Timestamp)
                .GroupBy(o => o.CameraId)
                .Select(g => new
                {
                    CameraId = g.Key,
                    PeopleCount = g.First().PeopleCount,
                    Timestamp = g.First().Timestamp
                })
                .ToListAsync();

            var occupancyMap = latestOccupancy
                .ToDictionary(x => x.CameraId, x => x.PeopleCount);

            // =========================
            // BUILD DASHBOARD MODEL
            // =========================
            var model = new DashboardViewModel
            {
                // =========================
                // CAMERA METRICS
                // =========================
                ActiveCameraCount = await _context.CameraDevices
                    .CountAsync(c => c.Status == "active"),

                TotalCameraCount = await _context.CameraDevices.CountAsync(),

                // =========================
                // DETECTIONS (AI / FACE / MOTION)
                // =========================
                TodayDetectionCount = await _context.DetectionLogs
                    .CountAsync(d => d.Timestamp.Date == now.Date),

                // =========================
                // ALERTS (HYBRID STATUS)
                // =========================
                ActiveAlertCount = await _context.Alerts
                    .CountAsync(a =>
                        a.Status == AlertStatus.New ||
                        a.Status == AlertStatus.Acknowledged),

                // =========================
                // ACCESS CONTROL
                // =========================
                PendingAccessCount = await _context.AccessLogs
                    .CountAsync(a => a.AccessResult == "denied"),

                // =========================
                // RECENT AI EVENTS
                // =========================
                RecentEvents = await _context.DetectionLogs
                    .Include(d => d.Camera!)
                        .ThenInclude(c => c!.Room)
                    .OrderByDescending(d => d.Timestamp)
                    .Take(5)
                    .ToListAsync(),

                // =========================
                // CAMERA LIST (LIVE FEED)
                // =========================
                Cameras = await _context.CameraDevices
                    .Include(c => c.Room)
                    .Take(6)
                    .ToListAsync(),

                // =========================
                // DASHBOARD LOGS
                // =========================
                RecentAccessLogs = recentAccessLogs,

                RecentAlerts = await _context.Alerts
                    .OrderByDescending(a => a.Timestamp)
                    .Take(6)
                    .ToListAsync()
            };

            // =========================
            // PASS HYBRID DATA TO VIEW
            // =========================
            ViewBag.OccupancyMap = occupancyMap;

            return View(model);
        }

        // =========================
        // SYSTEM PAGE
        // =========================
        public IActionResult System()
        {
            return View();
        }
    }
}