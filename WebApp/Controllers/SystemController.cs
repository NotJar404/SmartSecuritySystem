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

            // Pass current system config so toggles render with real state
            lock (_configLock)
            {
                ViewBag.Config = new {
                    ArmSystem = _systemConfig.ArmSystem,
                    AutoMaintenance = _systemConfig.AutoMaintenance,
                    MotionSensitivity = _systemConfig.MotionSensitivity,
                    FaceAccuracy = _systemConfig.FaceAccuracy,
                    EmailReports = _systemConfig.EmailReports,
                    HardwareSiren = _systemConfig.HardwareSiren,
                    GateHoldOpen = _systemConfig.GateHoldOpen,
                    BiometricLock = _systemConfig.BiometricLock
                };
            }
            
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
        // SAVE GLOBAL SETTINGS (REAL PERSISTENCE — ALL CARDS)
        // =========================

        // Static config that Python polls (in-memory, survives requests)
        private static SystemSettingsRequest _systemConfig = new SystemSettingsRequest
        {
            ArmSystem = true,
            AutoMaintenance = true,
            MotionSensitivity = 2,
            FaceAccuracy = 80,
            EmailReports = true,
            HardwareSiren = true,
            GateHoldOpen = 5,
            BiometricLock = true
        };
        private static readonly object _configLock = new object();

        [HttpPost]
        public async Task<IActionResult> SaveSettings([FromBody] SystemSettingsRequest request)
        {
            if (request == null)
                return BadRequest();

            // Persist to in-memory config (Python polls this)
            lock (_configLock)
            {
                _systemConfig = request;
            }

            // If Master Arm is OFF → disable all alarm protocols in DB
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
        // SYSTEM CONFIG API (FOR PYTHON IOT CONTROLLER)
        // Python polls this to get ALL system settings
        // =========================
        [HttpGet]
        [AllowAnonymous]
        [Route("/api/system/config")]
        public IActionResult GetSystemConfig()
        {
            lock (_configLock)
            {
                return Json(new
                {
                    armSystem = _systemConfig.ArmSystem,
                    autoMaintenance = _systemConfig.AutoMaintenance,
                    motionSensitivity = _systemConfig.MotionSensitivity,
                    faceAccuracy = _systemConfig.FaceAccuracy,
                    emailReports = _systemConfig.EmailReports,
                    hardwareSiren = _systemConfig.HardwareSiren,
                    gateHoldOpen = _systemConfig.GateHoldOpen,
                    biometricLock = _systemConfig.BiometricLock
                });
            }
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

        // =========================
        // OPTIMIZE DATABASE (real VACUUM)
        // =========================
        [HttpPost]
        public async Task<IActionResult> OptimizeDatabase()
        {
            try
            {
                await _context.Database.ExecuteSqlRawAsync("VACUUM ANALYZE;");
                return Json(new { success = true, message = "Database optimized successfully (VACUUM ANALYZE)." });
            }
            catch (System.Exception ex)
            {
                return Json(new { success = false, message = $"Optimization failed: {ex.Message}" });
            }
        }

        // =========================
        // PI HEALTH (real disk usage from Pi Flask endpoint)
        // =========================
        [HttpGet]
        [Route("/api/system/pi-health")]
        public async Task<IActionResult> GetPiHealth()
        {
            try
            {
                // Try to reach the Pi's Flask /health endpoint
                using var client = new System.Net.Http.HttpClient();
                client.Timeout = System.TimeSpan.FromSeconds(3);

                // Use the first active camera's stream_url to find the Pi's IP
                var cam = _context.CameraDevices.FirstOrDefault(c => c.Status == "active");
                if (cam?.StreamUrl != null)
                {
                    var uri = new System.Uri(cam.StreamUrl);
                    var healthUrl = $"http://{uri.Host}:5050/health";
                    var resp = await client.GetStringAsync(healthUrl);
                    return Content(resp, "application/json");
                }

                return Json(new { diskUsedPercent = -1, diskTotalGb = 0, diskFreeGb = 0 });
            }
            catch
            {
                return Json(new { diskUsedPercent = -1, diskTotalGb = 0, diskFreeGb = 0 });
            }
        }

        // =========================
        // ARCHIVE RECORDINGS (sends command to Pi)
        // =========================
        [HttpPost]
        public async Task<IActionResult> ArchiveRecordings()
        {
            try
            {
                using var client = new System.Net.Http.HttpClient();
                client.Timeout = System.TimeSpan.FromSeconds(10);

                var cam = _context.CameraDevices.FirstOrDefault(c => c.Status == "active");
                if (cam?.StreamUrl != null)
                {
                    var uri = new System.Uri(cam.StreamUrl);
                    var archiveUrl = $"http://{uri.Host}:5050/archive";
                    var resp = await client.PostAsync(archiveUrl, null);
                    var body = await resp.Content.ReadAsStringAsync();
                    return Content(body, "application/json");
                }

                return Json(new { success = false, message = "No active Pi found." });
            }
            catch (System.Exception ex)
            {
                return Json(new { success = false, message = $"Archive failed: {ex.Message}" });
            }
        }
        // =========================
        // ALARM STATUS RECEIVE (FROM PYTHON IoT CONTROLLER)
        // Pi pushes active alarm state here for real-time UI display
        // =========================
        private static AlarmStatusPayload? _activeAlarm = null;
        private static readonly object _alarmLock = new object();

        [HttpPost]
        [AllowAnonymous]
        [Route("/api/system/alarm-status")]
        public IActionResult ReceiveAlarmStatus([FromBody] AlarmStatusPayload payload)
        {
            if (payload == null)
                return BadRequest();

            lock (_alarmLock)
            {
                _activeAlarm = payload.IsActive ? payload : null;
            }

            return Ok(new { success = true });
        }

        [HttpGet]
        [AllowAnonymous]
        [Route("/api/system/alarm-status")]
        public IActionResult GetAlarmStatus()
        {
            lock (_alarmLock)
            {
                if (_activeAlarm != null)
                {
                    return Json(new
                    {
                        active = true,
                        type = _activeAlarm.Type,
                        description = _activeAlarm.Description,
                        roomId = _activeAlarm.RoomId,
                        timestamp = _activeAlarm.Timestamp
                    });
                }
            }

            return Json(new { active = false });
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
        // Global Settings
        public bool ArmSystem { get; set; } = true;
        public bool EyeStrainProtection { get; set; }
        public bool AutoMaintenance { get; set; } = true;

        // AI Intelligence
        public int MotionSensitivity { get; set; } = 2;
        public int FaceAccuracy { get; set; } = 80;

        // Alert Protocols
        public bool EmailReports { get; set; } = true;
        public bool HardwareSiren { get; set; } = true;

        // Access Control
        public int GateHoldOpen { get; set; } = 5;
        public bool BiometricLock { get; set; } = true;
    }

    public class AlarmStatusPayload
    {
        public string Type { get; set; } = string.Empty;
        public bool IsActive { get; set; }
        public string SessionId { get; set; } = string.Empty;
        public string Description { get; set; } = string.Empty;
        public int RoomId { get; set; }
        public string Timestamp { get; set; } = string.Empty;
    }
}