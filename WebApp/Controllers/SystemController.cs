using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Services;
using WebApp.Models;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")]
    public class SystemController : Controller
    {
        private readonly SystemService _systemService;

        // 🔹 FOR DATABASE INTEGRATION:
        //    - Inject ILogger<SystemController> for error handling
        //    - Inject IMapper for DTO conversions if needed
        //    - All action results should return DTO objects (not domain models directly)
        //    - Add try-catch blocks around service calls for exception handling

        public SystemController(SystemService systemService)
        {
            _systemService = systemService ?? throw new ArgumentNullException(nameof(systemService));
        }

        /// <summary>
        /// Displays the system settings page with current camera and alarm configurations
        /// 🔹 DATABASE: Currently loads from in-memory service
        /// 🔹 TODO: Call async method GetSystemStatusAsync() when database is ready
        /// </summary>
        public IActionResult Index()
        {
            var status = _systemService.GetSystemStatus();
            status.Cameras ??= new List<CameraDevice>();
            status.EmergencyAlarms ??= new List<EmergencyAlarm>();
            return View(status);
        }

        /// <summary>
        /// Updates system settings (Notifications, Recording, AI Detection)
        /// 🔹 DATABASE: Persist changes to SystemSettings table
        /// 🔹 TODO: Add logging and error handling after database integration
        /// </summary>
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            try
            {
                _systemService.UpdateSetting(setting, value);
                // 🔹 TODO: Log the change for audit trail
                return Json(new { success = true, message = $"{setting} updated successfully" });
            }
            catch (Exception ex)
            {
                // 🔹 TODO: Log exception properly
                return Json(new { success = false, message = ex.Message });
            }
        }

        /// <summary>
        /// Updates camera configuration (Name, Location, IP Address)
        /// 🔹 DATABASE: Update CameraDevices table, validate IP format
        /// 🔹 TODO: Add IP validation, test connection to camera endpoint
        /// </summary>
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult UpdateCamera(int id, string name, string location, string ipAddress)
        {
            try
            {
                // 🔹 TODO: Add validation for IP address format
                // if (!IsValidIPAddress(ipAddress)) return Json(new { success = false, message = "Invalid IP address" });

                var cam = new CameraDevice
                {
                    Id = id,
                    Name = name ?? "",
                    Location = location ?? "",
                    IpAddress = ipAddress ?? ""
                };

                _systemService.UpdateCamera(id, cam);
                // 🔹 TODO: Test connection to the camera at the new IP
                return Json(new { success = true, message = "Camera updated successfully" });
            }
            catch (Exception ex)
            {
                return Json(new { success = false, message = ex.Message });
            }
        }

        /// <summary>
        /// Toggles emergency alarm on/off (only one alarm can be active at a time)
        /// 🔹 DATABASE: Update EmergencyAlarms table, trigger notifications if enabled
        /// 🔹 TODO: Send alerts to connected devices when alarm is activated
        /// 🔹 TODO: Add audit log for alarm state changes
        /// </summary>
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult ToggleAlarm(int alarmId, bool isEnabled)
        {
            try
            {
                _systemService.ToggleEmergencyAlarm(alarmId, isEnabled);
                
                // 🔹 TODO: If enabled, trigger alarm system and send notifications
                // if (isEnabled)
                // {
                //     await _notificationService.SendAlertAsync($"Alarm {alarmId} has been activated");
                //     await _iotController.TriggerAlarmAsync(alarmId);
                // }

                return Json(new { success = true, message = "Alarm state updated" });
            }
            catch (Exception ex)
            {
                return Json(new { success = false, message = ex.Message });
            }
        }
    }
}