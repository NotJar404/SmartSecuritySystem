using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")]
    public class SystemController : Controller
    {
        private readonly AppDbContext _context;

        public SystemController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // SYSTEM PAGE (NO SERVICE, NO VIEWMODEL)
        // =========================
        public async Task<IActionResult> Index()
        {
            var cameras = await _context.CameraDevices
                .Include(c => c.Room)
                .ToListAsync();

            // Temporary alarms (since no DB table yet)
            var alarms = new List<EmergencyAlarm>
            {
                new EmergencyAlarm { Id = 1, Name = "Intruder Alert", Description = "Triggered when an intruder is detected", IconType = "intruder", IsEnabled = false },
                new EmergencyAlarm { Id = 2, Name = "Fire Alarm", Description = "Triggered when smoke/fire detected", IconType = "fire", IsEnabled = false },
                new EmergencyAlarm { Id = 3, Name = "Earthquake Drill", Description = "Simulation mode", IconType = "earthquake", IsEnabled = false },
                new EmergencyAlarm { Id = 4, Name = "Emergency Drill", Description = "General emergency drill", IconType = "ambulance", IsEnabled = false }
            };

            // Send directly to View using dynamic container
            ViewBag.Cameras = cameras;
            ViewBag.Alarms = alarms;

            return View();
        }

        // =========================
        // UPDATE CAMERA
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> UpdateCamera(int id, string name, string location, string ipAddress)
        {
            var camera = await _context.CameraDevices
                .FirstOrDefaultAsync(c => c.Id == id);

            if (camera == null)
                return Json(new { success = false, message = "Camera not found" });

            camera.Name = name;
            camera.Location = location;

            await _context.SaveChangesAsync();

            return Json(new { success = true, message = "Camera updated successfully" });
        }

        // =========================
        // TOGGLE ALARM (TEMP ONLY)
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult ToggleAlarm(int alarmId, bool isEnabled)
        {
            // No DB yet
            return Json(new { success = true });
        }

        // =========================
        // SETTINGS (PLACEHOLDER)
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            return Json(new { success = true });
        }
    }
}