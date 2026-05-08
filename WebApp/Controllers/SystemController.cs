using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System.Collections.Generic;
using System.Linq;
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
        // SYSTEM PAGE (LOAD REAL TOGGLES)
        // =========================
        public async Task<IActionResult> Index()
        {
            // Pulling from the alarm_settings table (IDs 1-4 now that duplicates are gone)
            var settings = await _context.AlarmSettings
                .OrderBy(s => s.SettingId)
                .ToListAsync();

            // This ViewBag name MUST match the 'var alarms = ViewBag.Alarms' in your Index.cshtml
            ViewBag.Alarms = settings; 
            
            return View(); 
        }

        // ==========================================
        // TOGGLE ALARM (CALLED BY JS confirmToggle)
        // ==========================================
        [HttpPost]
        public async Task<IActionResult> UpdateAlarmStatus(int id, bool isEnabled)
        {
            // Finding the specific alarm protocol (Intrusion, Fire, etc.)
            var setting = await _context.AlarmSettings
                .FirstOrDefaultAsync(s => s.SettingId == id);

            if (setting == null)
            {
                return NotFound(new { success = false, message = "Alarm protocol not found in database." });
            }

            // Updating the record
            setting.IsEnabled = isEnabled;
            await _context.SaveChangesAsync();

            return Json(new
            {
                success = true,
                message = $"Protocol {setting.Name} has been {(isEnabled ? "Armed" : "Disarmed")}."
            });
        }

        // =========================
        // TOGGLE SYSTEM FEATURE (REAL DB PERSISTENCE)
        // =========================
        [HttpPost]
        public async Task<IActionResult> ToggleFeature([FromBody] FeatureToggleRequest request)
        {
            if (request == null)
                return BadRequest();

            // Check if this feature maps to an alarm_setting
            var setting = await _context.AlarmSettings
                .FirstOrDefaultAsync(s => s.Name.ToLower() == request.Feature.ToLower()
                                       || s.Type.ToLower() == request.Feature.ToLower());

            if (setting != null)
            {
                setting.IsEnabled = request.State;
                await _context.SaveChangesAsync();
            }

            return Json(new
            {
                success = true,
                message = $"{request.Feature} set to {(request.State ? "ON" : "OFF")}",
                persisted = setting != null
            });
        }

        // =========================
        // SAVE GLOBAL SETTINGS (REAL PERSISTENCE)
        // =========================
        [HttpPost]
        public async Task<IActionResult> SaveSettings([FromBody] SystemSettingsRequest request)
        {
            if (request == null)
                return BadRequest();

            // Update all alarm settings based on ArmSystem flag
            if (!request.ArmSystem)
            {
                var allSettings = await _context.AlarmSettings.ToListAsync();
                foreach (var s in allSettings)
                {
                    s.IsEnabled = false;
                }
                await _context.SaveChangesAsync();
            }

            return Json(new
            {
                success = true,
                message = "Settings deployed successfully to hardware engine."
            });
        }

        // =========================
        // ALARM SETTINGS API (FOR PYTHON IOT CONTROLLER)
        // Python polls this endpoint to check which alarms are armed/disarmed
        // =========================
        [HttpGet]
        [AllowAnonymous]  // Pi controller needs access without browser auth
        [Route("/api/system/alarm-settings")]
        public async Task<IActionResult> GetAlarmSettings()
        {
            var settings = await _context.AlarmSettings.ToListAsync();
            return Json(settings.Select(s => new
            {
                settingId = s.SettingId,
                name = s.Name,
                type = s.Type,
                isEnabled = s.IsEnabled
            }));
        }

        // =========================
        // PI HEARTBEAT (for system.cshtml to check Pi status)
        // =========================
        [HttpGet]
        [Route("/api/system/pi-status")]
        public IActionResult GetPiStatus()
        {
            // Check if we received any camera/detection data recently
            var lastDetection = _context.DetectionLogs
                .OrderByDescending(d => d.Timestamp)
                .FirstOrDefault();

            var lastOccupancy = _context.RoomOccupancy
                .OrderByDescending(o => o.Timestamp)
                .FirstOrDefault();

            var latestTimestamp = new[] {
                lastDetection?.Timestamp,
                lastOccupancy?.Timestamp
            }.Where(t => t != null).Max();

            bool isOnline = latestTimestamp.HasValue &&
                           (System.DateTime.UtcNow - latestTimestamp.Value).TotalMinutes < 5;

            return Json(new
            {
                online = isOnline,
                lastSeen = latestTimestamp?.ToString("o"),
                activeCameras = _context.CameraDevices.Count(c => c.Status == "active")
            });
        }
    }

    // =========================
    // REQUEST MODELS
    // =========================

    public class FeatureToggleRequest
    {
        public string Feature { get; set; } = string.Empty;
        public bool State { get; set; }
    }

    public class SystemSettingsRequest
    {
        public bool ArmSystem { get; set; }
        public bool EyeStrainProtection { get; set; }
        public bool AutoMaintenance { get; set; }
        public int MotionSensitivity { get; set; }
        public int FaceAccuracy { get; set; }
    }
}