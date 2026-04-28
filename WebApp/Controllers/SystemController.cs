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
        // TOGGLE SYSTEM FEATURE
        // =========================
        [HttpPost]
        public IActionResult ToggleFeature([FromBody] FeatureToggleRequest request)
        {
            if (request == null)
                return BadRequest();

            return Json(new
            {
                success = true,
                message = $"{request.Feature} set to {(request.State ? "ON" : "OFF")}"
            });
        }

        // =========================
        // SAVE GLOBAL SETTINGS
        // =========================
        [HttpPost]
        public IActionResult SaveSettings([FromBody] SystemSettingsRequest request)
        {
            if (request == null)
                return BadRequest();

            // Logic for pushing to Raspberry Pi via SQL bridge goes here
            return Json(new
            {
                success = true,
                message = "Settings deployed successfully to hardware engine."
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