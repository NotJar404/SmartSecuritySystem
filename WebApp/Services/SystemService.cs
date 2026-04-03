using WebApp.Models;

namespace WebApp.Services
{
    public class SystemService
    {
        private SystemStatus _status;

        // 🔹 FOR DATABASE INTEGRATION: 
        //    - Inject IRepository<CameraDevice>, IRepository<EmergencyAlarm> via constructor
        //    - Replace hardcoded initialization with: _status = LoadFromDatabase()
        //    - Create async methods: GetSystemStatusAsync(), UpdateCameraAsync(), etc.

        public SystemService()
        {
            // 🔹 INITIAL DATA (Remove when connecting to database)
            // TODO: Replace this with database queries when backend is ready
            _status = new SystemStatus
            {
                Cameras = new List<CameraDevice>
                {
                    new CameraDevice { Id = 1, Name = "Front Gate", Location = "Entrance", IpAddress = "192.168.1.10" },
                    new CameraDevice { Id = 2, Name = "Lobby", Location = "Reception", IpAddress = "192.168.1.11" },
                    new CameraDevice { Id = 3, Name = "Parking Lot", Location = "Outdoor", IpAddress = "192.168.1.12" }
                },
                EmergencyAlarms = new List<EmergencyAlarm>
                {
                    new EmergencyAlarm { Id = 1, Name = "Intruder Alert", Description = "Triggered when an intruder is detected", IconType = "intruder", IsEnabled = false },
                    new EmergencyAlarm { Id = 2, Name = "Fire Alarm", Description = "Triggered when smoke/fire detected", IconType = "fire", IsEnabled = false },
                    new EmergencyAlarm { Id = 3, Name = "Earthquake Drill", Description = "For earthquake simulation drills", IconType = "earthquake", IsEnabled = false },
                    new EmergencyAlarm { Id = 4, Name = "Emergency Drill", Description = "General emergency drill simulation", IconType = "ambulance", IsEnabled = false }
                }
            };
        }

        /// <summary>
        /// Gets the current system status with all cameras and alarms
        /// 🔹 DATABASE INTEGRATION: Convert to async method GetSystemStatusAsync()
        /// </summary>
        public SystemStatus GetSystemStatus()
        {
            return _status;
        }

        /// <summary>
        /// Updates system-wide settings (Notifications, Recording, AI Detection)
        /// 🔹 DATABASE INTEGRATION: Store settings in database table: SystemSettings
        /// </summary>
        public void UpdateSetting(string setting, bool value)
        {
            if (setting == "Notifications") _status.NotificationsEnabled = value;
            if (setting == "Recording") _status.RecordingEnabled = value;
            if (setting == "AI") _status.AiDetectionEnabled = value;

            // 🔹 TODO: Save to database
            // await _settingsRepository.UpdateAsync(setting, value);
        }

        /// <summary>
        /// Updates a specific camera configuration
        /// 🔹 DATABASE INTEGRATION: Update CameraDevices table where Id = id
        /// </summary>
        public void UpdateCamera(int id, CameraDevice updated)
        {
            var cam = _status.Cameras.FirstOrDefault(c => c.Id == id);
            if (cam != null)
            {
                cam.Name = updated.Name;
                cam.Location = updated.Location;
                cam.IpAddress = updated.IpAddress;
            }

            // 🔹 TODO: Persist to database
            // await _cameraRepository.UpdateAsync(id, updated);
        }

        /// <summary>
        /// Toggles an emergency alarm (only one can be enabled at a time)
        /// 🔹 DATABASE INTEGRATION: Update EmergencyAlarms table
        /// </summary>
        public void ToggleEmergencyAlarm(int id, bool isEnabled)
        {
            foreach (var alarm in _status.EmergencyAlarms)
                alarm.IsEnabled = (alarm.Id == id) ? isEnabled : false;

            // 🔹 TODO: Persist to database
            // await _alarmRepository.ToggleAsync(id, isEnabled);
        }
    }
}